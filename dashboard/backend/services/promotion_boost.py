"""
Per-user promoted-listing ad-rate boosting (Phase 4).

Ports scripts/auto_boost_promotion.py into a per-user job using each user's
own eBay OAuth token (via ebay_oauth.get_access_token, not the legacy global
.env refresh token) and Postgres active_listings (already synced by
ebay_data.py's per-user sync) instead of a fresh Trading API call.

Every 10 days an item has been listed without selling, its promoted ad rate
is raised, up to a cap (see marketing_api.compute_target_bid). Requires the
user's eBay account to have the sell.marketing scope granted and to be
eligible for Promoted Listings (active Store subscription, Top Rated/Above
Standard seller level, accepted terms) - ineligibility is a normal per-user
outcome (status="not_eligible"), not a job failure, so it never aborts a
batch run across other users.
"""

import logging
import uuid
from datetime import datetime, timezone

from psycopg.types.json import Json

from ebaypricer.marketing_api import (
    MarketingApiError,
    bulk_update_bids,
    compute_target_bid,
    get_ads,
    get_campaigns,
)

from dashboard.backend.database import get_db
from dashboard.backend.services.ebay_oauth import (
    EbayOAuthError,
    NotConnectedError,
    get_access_token,
)

log = logging.getLogger(__name__)

JOB_NAME = "user_promotion_boost"
BATCH_SIZE = 500
DEFAULT_MAX_BID = 5.0
HIGH_PRICE_MAX_BID = 3.0
HIGH_PRICE_THRESHOLD = 50.0


def _record_job_run(user_id: uuid.UUID, started: datetime, status: str, detail: dict | None = None) -> None:
    try:
        with get_db(read_only=False) as conn:
            conn.execute(
                "INSERT INTO job_runs (job_name, user_id, status, started_at, finished_at, detail) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    JOB_NAME,
                    str(user_id),
                    status,
                    started,
                    datetime.now(timezone.utc),
                    Json(detail) if detail is not None else None,
                ),
            )
    except Exception as e:
        log.error("Failed to record job_runs row for user %s: %s", user_id, e)


def _user_active_listings(user_id: uuid.UUID) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT item_id, price, days_listed FROM active_listings WHERE user_id = %s",
            [str(user_id)],
        ).fetchall()
    return [dict(r) for r in rows]


def run_user_promotion_boost(user_id: uuid.UUID, campaign_id: str | None = None) -> dict:
    """Boost stale-inventory ad rates for one user's running Cost-Per-Sale campaign.

    Never raises - connection/eligibility problems are reported via the returned
    status ("not_eligible" / "error") so a caller looping over many users can
    keep going after one user's failure.
    """
    started = datetime.now(timezone.utc)
    try:
        token = get_access_token(user_id)
    except NotConnectedError:
        result = {"status": "not_eligible", "reason": "eBay account not connected"}
        _record_job_run(user_id, started, result["status"], result)
        return result
    except EbayOAuthError as e:
        result = {"status": "error", "error": str(e)[:300]}
        _record_job_run(user_id, started, result["status"], result)
        return result

    try:
        if campaign_id is None:
            campaigns = get_campaigns(token)
            if not campaigns:
                result = {"status": "ok", "boosted": 0, "reason": "no running campaigns"}
                _record_job_run(user_id, started, result["status"], result)
                return result
            campaign = campaigns[0]
            campaign_id = campaign["campaignId"]
            funding_model = campaign.get("fundingStrategy", {}).get("fundingModel")
            if funding_model and funding_model != "COST_PER_SALE":
                result = {
                    "status": "ok",
                    "boosted": 0,
                    "reason": f"campaign funding model is {funding_model}, not COST_PER_SALE",
                }
                _record_job_run(user_id, started, result["status"], result)
                return result

        listings = _user_active_listings(user_id)
        if not listings:
            result = {"status": "ok", "boosted": 0, "reason": "no active listings"}
            _record_job_run(user_id, started, result["status"], result)
            return result

        ads = get_ads(token, campaign_id)
        ads_by_listing = {ad["listingId"]: ad for ad in ads if ad.get("listingId")}

        to_update = []
        for item in listings:
            item_id = item.get("item_id") or ""
            ad = ads_by_listing.get(item_id)
            if ad is None:
                continue

            price = float(item.get("price") or 0)
            max_bid = HIGH_PRICE_MAX_BID if price > HIGH_PRICE_THRESHOLD else DEFAULT_MAX_BID
            current_bid = float(ad.get("bidPercentage") or 0)
            days = item.get("days_listed") or 0

            target = compute_target_bid(days, current_bid, max_bid)
            if target is None:
                continue
            to_update.append({"listingId": item_id, "bidPercentage": f"{target:.1f}"})

        if not to_update:
            result = {"status": "ok", "boosted": 0}
            _record_job_run(user_id, started, result["status"], result)
            return result

        sent = 0
        errors = []
        for i in range(0, len(to_update), BATCH_SIZE):
            batch = to_update[i : i + BATCH_SIZE]
            batch_result = bulk_update_bids(token, campaign_id, batch)
            sent += batch_result["sent"]
            errors.extend(batch_result.get("errors", []))

        result = {"status": "ok", "boosted": sent, "errors": errors[:10]}
        _record_job_run(user_id, started, result["status"], result)
        return result
    except MarketingApiError as e:
        status = "not_eligible" if e.status_code == 403 else "error"
        result = {"status": status, "error": str(e)[:300]}
        _record_job_run(user_id, started, status, result)
        return result
    except Exception as e:
        result = {"status": "error", "error": str(e)[:300]}
        log.error("Promotion boost failed for user %s: %s", user_id, e)
        _record_job_run(user_id, started, result["status"], result)
        return result


def run_all_users_promotion_boost() -> dict:
    """Run the boost job for every connected user. One user's failure doesn't stop the rest."""
    with get_db() as conn:
        user_ids = [r["user_id"] for r in conn.execute("SELECT user_id FROM ebay_connections").fetchall()]
    results = {}
    for uid in user_ids:
        results[str(uid)] = run_user_promotion_boost(uid)
    return results
