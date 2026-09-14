"""Card photos, hosted where eBay can fetch them.

Every route out of this app - the draft CSV, the File Exchange CSV, eBay's prefill
template - carries photos as **public https URLs ending in a file extension**, because
that is the only form eBay accepts. `card_image_url` elsewhere in the app cannot serve:
that is catalog art of the printing, not a photo of the card in hand, it shows no
condition, and eBay's terms make the seller warrant rights to every URL supplied.

So the photos are uploaded to the project's own Supabase Storage bucket, which is
already paid for and already configured (`SUPABASE_URL`, `SUPABASE_SERVICE_KEY`). The
public object URL it hands back is exactly the shape eBay wants:

    https://<ref>.supabase.co/storage/v1/object/public/card-photos/<uid>/<item>/<id>.jpg

Chosen over eBay Picture Services for one reason: EPS URLs expire in about 30 days if
they are never attached to a listing, and a pile gets re-exported over weeks. These do
not expire.

Images are re-encoded on the way in rather than stored as they arrive. A phone photo is
3-6MB and 4000px wide; eBay's own guidance is 1200px on the long side, so storing the
original would spend twenty times the quota to give eBay something it downscales
anyway. The re-encode also applies the EXIF orientation - phone photos are almost always
rotated by a flag rather than by their pixels, and eBay reads the pixels.
"""

import io
import uuid

import requests
from PIL import Image, ImageOps

from dashboard.backend import config

# iPhones shoot HEIC by default, and Pillow cannot open it unaided. Registering the
# plugin teaches `Image.open` the format, so nothing below has to special-case it.
#
# Optional on purpose: if the wheel is missing (an older deployment, a platform with no
# build for it) the import fails quietly and a HEIC upload is rejected as "not a
# readable image" - which is true, and far better than the whole photo feature failing
# to import.
try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass

# eBay's optimal long edge. Not a minimum: their floor is 500px and zoom needs 800px,
# so this leaves room while keeping a photo a few hundred KB.
MAX_EDGE = 1200
JPEG_QUALITY = 85

# What a browser may hand us per file, before re-encoding. Generous enough for any
# phone camera and small enough that a stray upload can't tie up a worker.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

# No content-type allowlist. Browsers send `application/octet-stream` for a .HEIC off
# an iPhone - the type header simply is not reliable enough to gate on, and an
# allowlist rejected real photos over a header the browser guessed. What a file IS gets
# decided by trying to decode it, in `_process`, which is the only test that can
# actually be wrong in the safe direction.

BUCKET = config._env("SUPABASE_PHOTO_BUCKET", "card-photos")

TIMEOUT = 30


class PhotoStorageError(RuntimeError):
    """Anything that stopped a photo reaching the bucket. Carries a message meant for
    the person who pressed upload, not a stack trace."""


def configured() -> bool:
    """Whether uploads can work at all. Checked before the UI offers the control, so a
    project without Supabase credentials says so instead of failing per file."""
    return bool(config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY)


def _headers() -> dict:
    # The service key, not the user's JWT: the bucket is written server-side only, and
    # the rows that reference it are already scoped by user_id.
    return {
        "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
        "apikey": config.SUPABASE_SERVICE_KEY,
    }


# Set once the bucket is known to exist. Single-instance deployment is assumed
# elsewhere too (see price_research.reconcile_stale_job_runs), and the cost of being
# wrong is one wasted round trip, not a wrong result.
_bucket_ready = False


def ensure_bucket() -> None:
    """Create the bucket if it isn't there, public-read.

    Public is the whole point - eBay's servers fetch these anonymously, so a signed or
    time-limited URL would break the moment the signature aged out. Nothing private
    goes in here; it is photographs of cards about to be advertised publicly.

    Existence is checked with a GET first rather than inferred from the POST's status,
    because Supabase reports "already exists" as **HTTP 400** with a 409 buried in the
    JSON body - so a plain `status_code in (200, 201, 409)` test fails every call after
    the very first one, which is every call that matters.
    """
    global _bucket_ready
    if _bucket_ready:
        return

    existing = requests.get(
        f"{config.SUPABASE_URL}/storage/v1/bucket/{BUCKET}", headers=_headers(), timeout=TIMEOUT,
    )
    if existing.status_code == 200:
        _bucket_ready = True
        return

    resp = requests.post(
        f"{config.SUPABASE_URL}/storage/v1/bucket",
        headers={**_headers(), "Content-Type": "application/json"},
        json={"id": BUCKET, "name": BUCKET, "public": True},
        timeout=TIMEOUT,
    )
    # The duplicate case is still tolerated here: two uploads can race between the GET
    # above and this POST, and losing that race is not an error.
    if resp.status_code in (200, 201) or "AlreadyExists" in resp.text:
        _bucket_ready = True
        return
    raise PhotoStorageError(f"Couldn't create the {BUCKET} bucket: {resp.status_code} {resp.text[:200]}")


def _process(data: bytes) -> bytes:
    """Re-encode to a JPEG no larger than MAX_EDGE, oriented the way it was taken."""
    try:
        img = Image.open(io.BytesIO(data))
        # Bakes the EXIF orientation flag into the pixels. Without it a photo taken in
        # portrait arrives sideways on eBay, which looks like a damaged listing rather
        # than a metadata problem.
        img = ImageOps.exif_transpose(img)
        # JPEG has no alpha channel, and a PNG screenshot with one would otherwise
        # raise on save. Flattened onto white rather than black: a card photo on black
        # reads as a bad scan.
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            flat = Image.new("RGB", img.size, (255, 255, 255))
            flat.paste(img, mask=img.split()[-1])
            img = flat
        elif img.mode != "RGB":
            img = img.convert("RGB")
        # thumbnail() only ever shrinks, so a small photo is left at its own size
        # rather than being upscaled into blur.
        img.thumbnail((MAX_EDGE, MAX_EDGE), Image.LANCZOS)
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        return out.getvalue()
    except PhotoStorageError:
        raise
    except Exception as exc:
        raise PhotoStorageError(
            "That file isn't an image this server can read. JPEG, PNG, WebP and HEIC "
            f"all work ({exc})",
        ) from exc


def upload(user_id, item_id: int, data: bytes, content_type: str = "") -> str:
    """Store one photo and return its public URL.

    The object path is `<user>/<item>/<random>.jpg`. Random rather than sequential so
    re-uploading never silently overwrites an earlier photo that a live listing is
    still pointing at, and scoped by user and row so deleting a row's photos is a
    prefix, not a search.

    `content_type` is accepted for the caller's convenience and deliberately not
    trusted - whether this is an image is settled by decoding it.
    """
    if not configured():
        raise PhotoStorageError(
            "Photo hosting needs SUPABASE_URL and SUPABASE_SERVICE_KEY to be set",
        )
    if len(data) > MAX_UPLOAD_BYTES:
        raise PhotoStorageError(f"That image is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)}MB")

    jpeg = _process(data)
    # .jpg, always: eBay requires the URL to END in an image extension, so the stored
    # name has to carry it whatever the file was called when it arrived.
    path = f"{user_id}/{item_id}/{uuid.uuid4().hex}.jpg"

    ensure_bucket()
    resp = requests.post(
        f"{config.SUPABASE_URL}/storage/v1/object/{BUCKET}/{path}",
        headers={**_headers(), "Content-Type": "image/jpeg", "x-upsert": "false"},
        data=jpeg,
        timeout=TIMEOUT,
    )
    if resp.status_code not in (200, 201):
        raise PhotoStorageError(f"Upload failed: {resp.status_code} {resp.text[:200]}")

    return f"{config.SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{path}"


def delete(url: str) -> None:
    """Remove a photo we host. A URL from anywhere else is left alone.

    Best effort on purpose: the row's `photo_urls` is the thing that matters, and a
    failed delete should not stop a photo being removed from a listing. The orphan
    costs a few hundred KB.
    """
    prefix = f"{config.SUPABASE_URL}/storage/v1/object/public/{BUCKET}/"
    if not url.startswith(prefix):
        return
    try:
        requests.delete(
            f"{config.SUPABASE_URL}/storage/v1/object/{BUCKET}/{url[len(prefix):]}",
            headers=_headers(),
            timeout=TIMEOUT,
        )
    except requests.RequestException:
        pass
