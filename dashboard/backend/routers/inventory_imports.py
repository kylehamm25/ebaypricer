"""Photo imports for the unlisted inventory pile.

A scan is stored here while it waits for a person - or, for the clear cases, for the
scan page to confirm it immediately. The inventory row is only created by `confirm`,
through the same write path as a hand-added row. Recognition itself never prices a
card and never calls eBay; the page triggers the existing capped valuation batch after
the card is in the pile.
"""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from psycopg.errors import UndefinedTable
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from dashboard.backend.auth import get_current_user_id
from dashboard.backend.database import get_db
from dashboard.backend.services import card_scan, inventory_store, photo_storage
from dashboard.backend.services.upsert_rules import existing_columns
from ebaypricer.cards import card_identity, find_catalog_card

router = APIRouter(prefix="/api/v1/inventory/imports", tags=["inventory-imports"])

MIGRATION_HINT = "Card scanning needs db/migrations/0021_inventory_imports.sql to be run first"
BACK_MIGRATION_HINT = "Back photos need db/migrations/0022_inventory_import_back.sql to be run first"

_SCAN_SLOTS = threading.BoundedSemaphore(2)

_BASE_SELECT = """
    id, image_url, source_filename, status, auto_added, confidence, score,
    card_detected, ocr_text, detected_name, detected_number, candidates,
    chosen_card_query, inventory_id, error, created_at, updated_at
"""


def _select_for(db) -> str:
    if "back_image_url" in existing_columns(db, "inventory_imports"):
        return f"{_BASE_SELECT}, back_image_url"
    return _BASE_SELECT


class ConfirmRequest(BaseModel):
    card_query: str | None = Field(None, max_length=200)
    name: str = Field(..., min_length=1, max_length=200)
    condition: str | None = Field(None, max_length=40)
    quantity: int = Field(1, ge=1, le=100000)
    location: str | None = Field(None, max_length=120)
    sku: str | None = Field(None, max_length=40)
    auto: bool = False


def _candidates(value) -> list[dict]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    return value if isinstance(value, list) else []


def _row(row: dict) -> dict:
    item = dict(row)
    item["score"] = round(float(item["score"]), 3) if item.get("score") is not None else None
    item["candidates"] = _candidates(item.get("candidates"))
    item["created_at"] = item["created_at"].isoformat() if item.get("created_at") else None
    item["updated_at"] = item["updated_at"].isoformat() if item.get("updated_at") else None
    item["auto_add_eligible"] = bool(
        item.get("status") == "pending"
        and item.get("confidence") == "high"
        and item.get("candidates")
    )
    return item


def _get_import(db, import_id: int, user_id: UUID, for_update: bool = False) -> dict | None:
    suffix = " FOR UPDATE" if for_update else ""
    row = db.execute(
        f"SELECT {_select_for(db)} FROM inventory_imports WHERE id = %s AND user_id = %s{suffix}",
        [import_id, user_id],
    ).fetchone()
    return dict(row) if row else None


def _clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def _photos(row: dict) -> str:
    return "|".join(url for url in (row.get("image_url"), row.get("back_image_url")) if url)


def _insert_scan(
    user_id: UUID,
    image_url: str,
    back_url: str | None,
    filename: str | None,
    *,
    result=None,
    error: str | None = None,
) -> dict:
    """Write the finished scan row in one statement.

    The old flow inserted an empty row before recognition and updated it after,
    which cost a second round trip and forced the upload to finish before OCR could
    start. Recognition now happens first, so the row is written once, complete.
    """
    columns = ["user_id", "image_url", "source_filename"]
    values = ["%s", "%s", "%s"]
    params = [user_id, image_url, filename or None]
    if back_url:
        columns.append("back_image_url")
        values.append("%s")
        params.append(back_url)
    if error:
        columns.extend(("status", "error"))
        values.extend(("%s", "%s"))
        params.extend(("failed", error[:2000]))
    if result is not None:
        columns.extend((
            "confidence", "score", "card_detected", "ocr_text",
            "detected_name", "detected_number", "candidates",
        ))
        values.extend(["%s"] * 7)
        params.extend([
            result.confidence,
            result.score,
            result.card_detected,
            result.ocr_text or None,
            result.detected_name,
            result.detected_number,
            Jsonb(result.as_candidates()),
        ])

    with get_db(read_only=False) as db:
        row = db.execute(
            f"INSERT INTO inventory_imports ({', '.join(columns)}) "
            f"VALUES ({', '.join(values)}) RETURNING {_select_for(db)}",
            params,
        ).fetchone()
    return _row(dict(row))


@router.post("/scan")
def scan_card(
    file: UploadFile = File(...),
    back: UploadFile | None = File(None),
    user_id: UUID = Depends(get_current_user_id),
):
    """Upload a card's front (and optional back), recognize it, and queue it for review."""
    if not photo_storage.configured():
        raise HTTPException(503, "Photo hosting needs SUPABASE_URL and SUPABASE_SERVICE_KEY")
    if not card_scan.available():
        raise HTTPException(503, "Card scanning needs onnxruntime and rapidocr to be installed")

    if back is not None:
        with get_db() as db:
            columns = existing_columns(db, "inventory_imports")
        if columns and "back_image_url" not in columns:
            raise HTTPException(503, BACK_MIGRATION_HINT)

    data = file.file.read()
    if not data:
        raise HTTPException(422, "That file is empty")
    if len(data) > photo_storage.MAX_UPLOAD_BYTES:
        raise HTTPException(
            413,
            f"That image is larger than {photo_storage.MAX_UPLOAD_BYTES // (1024 * 1024)}MB",
        )

    back_data = None
    if back is not None:
        back_data = back.file.read()
        if not back_data:
            raise HTTPException(422, "The back photo is empty")
        if len(back_data) > photo_storage.MAX_UPLOAD_BYTES:
            raise HTTPException(
                413,
                f"The back photo is larger than {photo_storage.MAX_UPLOAD_BYTES // (1024 * 1024)}MB",
            )

    try:
        stored, ocr_image = photo_storage.process_scan(
            data, ocr_edge=card_scan.MAX_OCR_EDGE,
        )
    except photo_storage.PhotoStorageError as exc:
        raise HTTPException(422, str(exc)) from exc

    back_stored = None
    if back_data is not None:
        try:
            back_stored = photo_storage.process(back_data)
        except photo_storage.PhotoStorageError as exc:
            raise HTTPException(422, f"Back photo: {exc}") from exc

    key = uuid4().hex
    back_key = uuid4().hex if back_stored is not None else None

    # The photo upload and the recognizer are independent and slow for different
    # reasons (network vs CPU), so run them together and write the row once both
    # are done. Uploading first and then OCRing - the old order - paid both costs
    # back to back.
    with ThreadPoolExecutor(max_workers=2) as uploads:
        front_upload = uploads.submit(photo_storage.upload_import, user_id, key, stored)
        back_upload = (
            uploads.submit(photo_storage.upload_import, user_id, back_key, back_stored)
            if back_stored is not None else None
        )

        result = None
        error = None
        busy = False
        if not _SCAN_SLOTS.acquire(timeout=30):
            busy = True
            error = "The scanner is busy; dismiss this photo and try again"
        else:
            try:
                result = card_scan.analyze_image(ocr_image)
            except Exception as exc:
                error = str(exc)
            finally:
                _SCAN_SLOTS.release()

    try:
        image_url = front_upload.result()
    except photo_storage.PhotoStorageError as exc:
        raise HTTPException(503, str(exc)) from exc

    back_url = None
    if back_upload is not None:
        try:
            back_url = back_upload.result()
        except photo_storage.PhotoStorageError as exc:
            photo_storage.delete(image_url)
            raise HTTPException(503, f"Back photo: {exc}") from exc

    try:
        row = _insert_scan(
            user_id, image_url, back_url, file.filename,
            result=result, error=error,
        )
    except UndefinedTable:
        photo_storage.delete(image_url)
        if back_url:
            photo_storage.delete(back_url)
        raise HTTPException(503, MIGRATION_HINT)
    except Exception:
        photo_storage.delete(image_url)
        if back_url:
            photo_storage.delete(back_url)
        raise

    if busy:
        raise HTTPException(429, error)
    return row


@router.get("")
def list_imports(user_id: UUID = Depends(get_current_user_id)):
    """Pending work plus recently auto-added rows that can still be undone."""
    try:
        with get_db() as db:
            select = _select_for(db)
            pending = [
                dict(r) for r in db.execute(
                    f"SELECT {select} FROM inventory_imports "
                    "WHERE user_id = %s AND status IN ('pending', 'failed') "
                    "ORDER BY created_at ASC LIMIT 100",
                    [user_id],
                ).fetchall()
            ]
            recent = [
                dict(r) for r in db.execute(
                    f"SELECT {select} FROM inventory_imports "
                    "WHERE user_id = %s AND status = 'confirmed' AND auto_added "
                    "AND created_at > now() - interval '24 hours' "
                    "ORDER BY created_at DESC LIMIT 20",
                    [user_id],
                ).fetchall()
            ]
    except UndefinedTable:
        return {
            "pending": [],
            "recent": [],
            "imports_enabled": False,
            "photo_hosting_enabled": photo_storage.configured(),
            "recognition_enabled": card_scan.available(),
        }

    return {
        "pending": [_row(r) for r in pending],
        "recent": [_row(r) for r in recent],
        "imports_enabled": True,
        "photo_hosting_enabled": photo_storage.configured(),
        "recognition_enabled": card_scan.available(),
    }


@router.post("/{import_id}/rescan")
def rescan_import(import_id: int, user_id: UUID = Depends(get_current_user_id)):
    """Try recognition again on the photo already stored for a pending scan."""
    if not card_scan.available():
        raise HTTPException(503, "Card scanning needs onnxruntime and rapidocr to be installed")

    with get_db() as db:
        row = _get_import(db, import_id, user_id)
        if row is None:
            raise HTTPException(404, "No such scan")
        if row["status"] not in ("pending", "failed"):
            raise HTTPException(409, "That scan has already been reviewed")
        image_url = row["image_url"]

    # Only the 1200px listing copy is kept, so this is a best-effort second read.
    try:
        data = photo_storage.download(image_url)
    except photo_storage.PhotoStorageError as exc:
        raise HTTPException(503, str(exc)) from exc

    if not _SCAN_SLOTS.acquire(timeout=30):
        raise HTTPException(429, "The scanner is busy; try again")
    try:
        result = card_scan.analyze_image(data)
    except Exception as exc:
        raise HTTPException(422, f"Could not read that photo again: {exc}") from exc
    finally:
        _SCAN_SLOTS.release()

    with get_db(read_only=False) as db:
        updated = db.execute(
            "UPDATE inventory_imports SET confidence = %s, score = %s, card_detected = %s, "
            "ocr_text = %s, detected_name = %s, detected_number = %s, candidates = %s, "
            "status = 'pending', error = NULL, updated_at = now() "
            "WHERE id = %s AND user_id = %s AND status IN ('pending', 'failed') "
            f"RETURNING {_select_for(db)}",
            [
                result.confidence,
                result.score,
                result.card_detected,
                result.ocr_text or None,
                result.detected_name,
                result.detected_number,
                Jsonb(result.as_candidates()),
                import_id,
                user_id,
            ],
        ).fetchone()
    if updated is None:
        raise HTTPException(409, "That scan has already been reviewed")
    return _row(dict(updated))


@router.post("/{import_id}/confirm")
def confirm_import(
    import_id: int,
    body: ConfirmRequest,
    user_id: UUID = Depends(get_current_user_id),
):
    """Create the inventory row and mark this import confirmed in one transaction."""
    with get_db(read_only=False) as db:
        row = _get_import(db, import_id, user_id, for_update=True)
        if row is None:
            raise HTTPException(404, "No such scan")
        if row["status"] == "confirmed":
            return {"status": "ok", "id": import_id, "inventory_id": row["inventory_id"]}
        if row["status"] != "pending":
            raise HTTPException(409, "That scan is no longer waiting for confirmation")

        name = body.name.strip()
        if not name:
            raise HTTPException(422, "A card name is required")
        card_query = _clean(body.card_query)
        resolved = find_catalog_card(card_query) if card_query else None
        ident = card_identity(card_query) if card_query else None
        set_name = (
            (resolved or {}).get("set_name")
            or (ident or {}).get("set_name")
            or None
        )
        number = (
            str((resolved or {}).get("number") or (ident or {}).get("number") or "")
            or None
        )

        params = {
            "uid": user_id,
            "name": name,
            "card_query": card_query,
            "set_name": _clean(set_name),
            "number": _clean(number),
            "condition": _clean(body.condition),
            "quantity": body.quantity,
            "location": _clean(body.location),
            "sku": _clean(body.sku),
            "cost": None,
            "manual_value": None,
            "photo_urls": _photos(row),
            "notes": None,
        }
        try:
            created = inventory_store.write(db, params)
        except inventory_store.InventoryWriteError as exc:
            raise HTTPException(exc.status, str(exc)) from exc

        db.execute(
            "UPDATE inventory_imports SET status = 'confirmed', auto_added = %s, "
            "chosen_card_query = %s, inventory_id = %s, error = NULL, updated_at = now() "
            "WHERE id = %s AND user_id = %s",
            [body.auto, card_query, created["id"], import_id, user_id],
        )
    return {"status": "ok", "id": import_id, "inventory_id": created["id"]}


@router.post("/{import_id}/dismiss")
def dismiss_import(import_id: int, user_id: UUID = Depends(get_current_user_id)):
    with get_db(read_only=False) as db:
        row = _get_import(db, import_id, user_id, for_update=True)
        if row is None:
            raise HTTPException(404, "No such scan")
        if row["status"] not in ("pending", "failed"):
            raise HTTPException(409, "Only a scan waiting for review can be dismissed")
        db.execute(
            "UPDATE inventory_imports SET status = 'dismissed', updated_at = now() "
            "WHERE id = %s AND user_id = %s",
            [import_id, user_id],
        )
    photo_storage.delete(row["image_url"])
    if row.get("back_image_url"):
        photo_storage.delete(row["back_image_url"])
    return {"status": "ok", "id": import_id}


@router.post("/{import_id}/undo")
def undo_import(import_id: int, user_id: UUID = Depends(get_current_user_id)):
    """Reverse an auto-added card: remove the row and its photos."""
    with get_db(read_only=False) as db:
        row = _get_import(db, import_id, user_id, for_update=True)
        if row is None:
            raise HTTPException(404, "No such scan")
        if row["status"] != "confirmed" or not row["auto_added"]:
            raise HTTPException(409, "Only an auto-added scan can be undone")
        if row["inventory_id"]:
            db.execute(
                "DELETE FROM inventory WHERE id = %s AND user_id = %s",
                [row["inventory_id"], user_id],
            )
        db.execute(
            "UPDATE inventory_imports SET status = 'dismissed', inventory_id = NULL, "
            "updated_at = now() WHERE id = %s AND user_id = %s",
            [import_id, user_id],
        )
    photo_storage.delete(row["image_url"])
    if row.get("back_image_url"):
        photo_storage.delete(row["back_image_url"])
    return {"status": "ok", "id": import_id}
