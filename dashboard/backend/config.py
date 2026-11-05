import os
from ebaypricer.paths import PROJECT_ROOT, DATA_DIR


def _env(name: str, default: str = "") -> str:
    """Read an env var, stripping surrounding quotes (docker --env-file keeps them)."""
    value = os.environ.get(name, default)
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        value = value[1:-1]
    return value


DATABASE_URL = _env("DATABASE_URL")
SUPABASE_URL = _env("SUPABASE_URL")
SUPABASE_ANON_KEY = _env("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_KEY = _env("SUPABASE_SERVICE_KEY")
SUPABASE_JWT_SECRET = _env("SUPABASE_JWT_SECRET")
DEFAULT_USER_ID = _env("DEFAULT_USER_ID")
AUTH_REQUIRED = _env("AUTH_REQUIRED", "true").lower() in ("1", "true", "yes")

# eBay per-user OAuth (Phase 5)
EBAY_APP_ID = _env("EBAY_APP_ID")
EBAY_SECRET = _env("EBAY_SECRET")
EBAY_RUNAME = _env("RUNAME", "")
EBAY_TOKEN_ENCRYPTION_KEY = _env("EBAY_TOKEN_ENCRYPTION_KEY", "")
# Scopes the eBay app is approved for (space-separated). sell.finances.readonly
# requires additional approval in the developer portal - add once granted.
# sell.inventory (not .readonly) is required to revise a listing's price from the
# dashboard - a user who connected before this scope was added must disconnect and
# reconnect (Settings page) to grant it; their existing token won't gain it retroactively.
# sell.marketplace.insights.readonly (Item Sales sold comps) likewise needs a
# reconnect; see scripts/probe_item_sales.py for the validation probe.
EBAY_SCOPES = _env(
    "EBAY_SCOPES",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly "
    "https://api.ebay.com/oauth/api_scope/sell.inventory "
    "https://api.ebay.com/oauth/api_scope/sell.marketplace.insights.readonly",
)

# Per-user eBay sync (Phase 6)
EBAY_SYNC_DAYS = int(_env("EBAY_SYNC_DAYS", "120"))  # fetch window (overlap for fee updates)
EBAY_SYNC_INTERVAL_HOURS = float(_env("EBAY_SYNC_INTERVAL_HOURS", "6"))

# Shared marketplace price research (Phase 3): researches every card any connected
# user currently has listed and writes derived pricing columns onto each user's
# own active_listings rows.
EBAY_PRICE_RESEARCH_INTERVAL_HOURS = float(_env("EBAY_PRICE_RESEARCH_INTERVAL_HOURS", "6"))

LOG_PATH = os.path.join(PROJECT_ROOT, "logs", "main.log")
DATA_DIR_STR = str(DATA_DIR)
FRONTEND_DIST = _env("FRONTEND_DIST", os.path.join(PROJECT_ROOT, "dashboard", "frontend", "dist"))

ALLOWED_ORIGINS = [
    o.strip().strip('"').strip("'")
    for o in _env(
        "ALLOWED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if o.strip()
]
