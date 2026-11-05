"""Recognize a Pokemon card from one photo, entirely on this machine.

The scanner answers one question: which catalog printing is in this picture? It does
not price anything and never talks to eBay. The result is a ranked shortlist plus a
conservative confidence label; the inventory row is created later, by the same
confirm endpoint a hand-picked card uses.

The useful signal is the collector number. Name OCR is good enough to narrow the
catalog, but the number is what separates the same Charizard art across printings.
Visual hashing is a tiebreaker for the candidates OCR produced, never a reason to add
a card on its own. Anything ambiguous stays pending for a person to review.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import requests
from rapidfuzz import fuzz
from rapidfuzz import process as fuzz_process

from ebaypricer import cards, paths

MAX_OCR_EDGE = 2400
WARP_WIDTH = 750
WARP_HEIGHT = 1050
MAX_CANDIDATES = 5
MAX_VISUAL_CANDIDATES = 6
IMAGE_TIMEOUT = 8
MISS_DAYS = 7

AUTO_NAME_SCORE = 0.92
AUTO_VISUAL_FLOOR = 0.45
MEDIUM_NAME_SCORE = 0.72
MEDIUM_VISUAL_FLOOR = 0.35
NAME_MATCH_CUTOFF = 65
VISUAL_BONUS_FLOOR = 0.88
VISUAL_BONUS = 0.18

SLASH_NUMBER_RE = re.compile(r"\b([A-Za-z]{0,3}\s*\d{1,4})\s*/\s*([A-Za-z]{0,3}\s*\d{1,4})\b")
PROMO_NUMBER_RE = re.compile(
    r"\b(SVP|MEP|SWSH|BW|SM|XY|DP|HGSS|POP|TG|GG|RC|SV|ME)\s*[-]?\s*(\d{1,4})\b",
    re.IGNORECASE,
)
BARE_NUMBER_RE = re.compile(r"\b(\d{1,4})\b")

NAME_NOISE = {
    "BASIC", "STAGE", "STAGE 1", "STAGE 2", "POKEMON", "POKéMON", "TRAINER",
    "ENERGY", "ITEM", "SUPPORTER", "STADIUM", "TOOL", "HP",
}
NAME_SUFFIXES = {"ex", "EX", "V", "VMAX", "VSTAR", "GX", "LV.X", "δ", "BREAK"}

_engine = None
_engine_init_lock = threading.Lock()
_ocr_lock = threading.Lock()
_name_list: list[str] | None = None
_name_list_lock = threading.Lock()

# Catalog art is fetched over the network, and one scan can ask for half a dozen
# hashes. Doing that one after another made the downloads the slowest part of a
# scan; they are independent, so they run together. The pool is shared (rather
# than per-scan) so a batch of cards cannot multiply the number of open sockets.
_hash_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="card-hash")
_hash_cache: dict[str, str] = {}
_hash_cache_lock = threading.Lock()
_miss_lock = threading.Lock()
_session = requests.Session()


class CardScanError(RuntimeError):
    """Recognition could not start or could not read the image at all."""


@dataclass
class OcrLine:
    text: str
    score: float
    x: int
    y: int
    w: int
    h: int


@dataclass
class Candidate:
    card_query: str
    name: str
    set_name: str
    number: str
    rarity: str
    image_url: str | None
    score: float
    name_score: float
    number_match: bool
    visual_score: float | None = None

    def as_dict(self) -> dict:
        return {
            "card_query": self.card_query,
            "name": self.name,
            "set_name": self.set_name,
            "number": self.number,
            "rarity": self.rarity,
            "image_url": self.image_url,
            "score": round(self.score, 3),
            "name_score": round(self.name_score, 3),
            "number_match": self.number_match,
            "visual_score": round(self.visual_score, 3) if self.visual_score is not None else None,
        }


@dataclass
class ScanResult:
    card_detected: bool = False
    card_like: bool = False
    ocr_text: str = ""
    detected_name: str | None = None
    detected_number: str | None = None
    candidates: list[Candidate] = field(default_factory=list)
    confidence: str = "none"
    score: float | None = None
    error: str | None = None

    @property
    def auto_add_eligible(self) -> bool:
        return self.confidence == "high" and bool(self.candidates)

    def as_candidates(self) -> list[dict]:
        return [c.as_dict() for c in self.candidates]


def available() -> bool:
    """Whether the optional OCR stack is installed, without loading its models."""
    return all(
        importlib.util.find_spec(name) is not None
        for name in ("cv2", "numpy", "onnxruntime", "rapidocr")
    )


def analyze_image(jpeg: bytes) -> ScanResult:
    """Read a JPEG and return the best catalog guesses. No DB or network writes."""
    if not available():
        raise CardScanError(
            "Card scanning needs opencv-python-headless, onnxruntime and rapidocr to be installed",
        )
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise CardScanError(f"Card scanning dependencies are unavailable: {exc}") from exc

    image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise CardScanError("That photo could not be read as an image")

    warped, detected, card_like = _warp_card(image, cv2, np)
    lines = _read_lines(warped, cv2, np)
    name_raw, name_sim = _extract_name(lines)
    number = _extract_number(lines)

    if not name_raw:
        name_lines = _read_crop(warped, (0.0, 0.0, 1.0, 0.32), cv2, np)
        lines.extend(name_lines)
        name_raw, name_sim = _extract_name(lines)
    if not number:
        number_lines = _read_crop(warped, (0.0, 0.65, 0.62, 1.0), cv2, np)
        lines.extend(number_lines)
        number = _extract_number(lines)

    candidates = _resolve_candidates(name_raw, name_sim, number, warped, cv2, np)
    confidence, score = _confidence(
        name_raw, name_sim, candidates, detected or card_like,
    )
    return ScanResult(
        card_detected=detected,
        card_like=card_like,
        ocr_text=" | ".join(line.text for line in lines)[:4000],
        detected_name=name_raw,
        detected_number=number,
        candidates=candidates[:MAX_CANDIDATES],
        confidence=confidence,
        score=score,
    )


def warm() -> None:
    """Load the OCR models and card catalog before the first scan asks for them."""
    if not available():
        return
    cards.get_db()
    _get_engine()


def _get_engine():
    global _engine
    if _engine is None:
        with _engine_init_lock:
            if _engine is None:
                try:
                    from rapidocr import RapidOCR
                except ImportError as exc:
                    raise CardScanError(
                        "Card scanning needs the rapidocr package to be installed",
                    ) from exc
                _engine = RapidOCR()
    return _engine


def _engine_read(image) -> list[tuple[list, str, float]]:
    engine = _get_engine()
    try:
        with _ocr_lock:
            output = engine(image)
    except Exception as exc:
        raise CardScanError(f"OCR failed: {exc}") from exc

    rows = []
    if hasattr(output, "txts"):
        boxes = getattr(output, "boxes", None)
        texts = getattr(output, "txts", None)
        scores = getattr(output, "scores", None)
        if boxes is None or texts is None:
            return rows
        if scores is None:
            scores = [0.0] * len(texts)
        for box, text, score in zip(boxes, texts, scores):
            rows.append((box, str(text), float(score)))
        return rows
    if isinstance(output, tuple):
        output = output[0]
    for item in output or []:
        if isinstance(item, (list, tuple)) and len(item) >= 3:
            rows.append((item[0], str(item[1]), float(item[2])))
    return rows


def _read_lines(image, cv2, np) -> list[OcrLine]:
    return _lines_from(_engine_read(image), 0, 0)


def _read_crop(image, box: tuple[float, float, float, float], cv2, np) -> list[OcrLine]:
    height, width = image.shape[:2]
    x1, y1, x2, y2 = box
    left, top = int(x1 * width), int(y1 * height)
    right, bottom = int(x2 * width), int(y2 * height)
    crop = image[top:bottom, left:right]
    if crop.size == 0:
        return []
    crop = cv2.resize(crop, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    return _lines_from(_engine_read(crop), left, top, scale=2.0)


def _lines_from(rows, offset_x: int, offset_y: int, scale: float = 1.0) -> list[OcrLine]:
    lines = []
    for box, text, score in rows:
        text = text.strip()
        if not text:
            continue
        xs = [float(p[0]) for p in box]
        ys = [float(p[1]) for p in box]
        lines.append(OcrLine(
            text=text,
            score=score,
            x=int(min(xs) / scale) + offset_x,
            y=int(min(ys) / scale) + offset_y,
            w=int((max(xs) - min(xs)) / scale),
            h=int((max(ys) - min(ys)) / scale),
        ))
    lines.sort(key=lambda line: (line.y, line.x))
    return lines


def _warp_card(image, cv2, np):
    height, width = image.shape[:2]
    scale = min(1.0, 1600.0 / max(height, width))
    small = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else image
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(gray, 50, 150)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    best = None
    best_area = 0.0
    image_area = small.shape[0] * small.shape[1]
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < image_area * 0.08:
            continue
        peri = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.02 * peri, True)
        if len(approx) != 4:
            continue
        points = approx.reshape(4, 2).astype("float32")
        rect = _order_points(points)
        top = np.linalg.norm(rect[1] - rect[0])
        side = np.linalg.norm(rect[2] - rect[1])
        if top <= 0 or side <= 0:
            continue
        ratio = min(top, side) / max(top, side)
        if not 0.55 <= ratio <= 0.88:
            continue
        if area > best_area:
            best_area = area
            best = rect

    if best is None:
        ratio = min(width, height) / max(width, height)
        card_like = 0.5 <= ratio <= 0.9
        resized = cv2.resize(image, (WARP_WIDTH, WARP_HEIGHT), interpolation=cv2.INTER_AREA)
        return resized, False, card_like

    dst = np.array([
        [0, 0],
        [WARP_WIDTH - 1, 0],
        [WARP_WIDTH - 1, WARP_HEIGHT - 1],
        [0, WARP_HEIGHT - 1],
    ], dtype="float32")
    matrix = cv2.getPerspectiveTransform(best, dst)
    return cv2.warpPerspective(image, matrix, (WARP_WIDTH, WARP_HEIGHT)), True, True


def _order_points(points):
    rect = points.reshape(4, 2)
    ordered = rect.copy()
    sums = rect.sum(axis=1)
    diffs = rect[:, 0] - rect[:, 1]
    ordered[0] = rect[sums.argmin()]
    ordered[2] = rect[sums.argmax()]
    ordered[1] = rect[diffs.argmin()]
    ordered[3] = rect[diffs.argmax()]
    return ordered


def _clean_name(text: str) -> str:
    text = re.sub(r"\bHP\s*\d+\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b\d{2,3}\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" -:|")
    words = [word for word in text.split() if word.upper() not in NAME_NOISE]
    return " ".join(words).strip()


def _extract_name(lines: list[OcrLine]) -> tuple[str | None, float]:
    if not lines:
        return None, 0.0
    height = max(line.y + line.h for line in lines)
    top_lines = [line for line in lines if line.y <= height * 0.35] or lines[:5]
    names = []
    for line in top_lines:
        cleaned = _clean_name(line.text)
        if cleaned and any(ch.isalpha() for ch in cleaned):
            names.append(cleaned)

    best_text = None
    best_sim = 0.0
    for i, text in enumerate(names[:6]):
        variants = [text]
        if i + 1 < len(names) and names[i + 1].strip(" .") in NAME_SUFFIXES:
            variants.append(f"{text} {names[i + 1].strip(' .')}")
        for variant in variants:
            best = _best_name(variant)
            if not best:
                continue
            match, score, _ = best
            if match and score / 100.0 > best_sim:
                best_text = match
                best_sim = score / 100.0
    return best_text, round(best_sim, 3)


def _best_name(value: str):
    global _name_list
    if _name_list is None:
        with _name_list_lock:
            if _name_list is None:
                _name_list = list(cards.get_db().name_to_cards.keys())
    if not _name_list:
        return None, 0.0, None
    return fuzz_process.extractOne(
        value, _name_list, scorer=fuzz.WRatio, score_cutoff=NAME_MATCH_CUTOFF,
    )


def _extract_number(lines: list[OcrLine]) -> str | None:
    if not lines:
        return None
    height = max(line.y + line.h for line in lines)
    texts = [" ".join(line.text for line in lines)]
    for text in texts:
        for match in SLASH_NUMBER_RE.finditer(text):
            return re.sub(r"\s+", "", match.group(1)).upper()
        for match in PROMO_NUMBER_RE.finditer(text):
            prefix = match.group(1).upper()
            digits = match.group(2)
            if prefix in {"SVP", "MEP"} and digits.isdigit():
                digits = str(int(digits))
            return f"{prefix}{digits}"

    # A bare number is only meaningful when it sits in the collector-number strip
    # at the very bottom. Attack damage and HP also look like digits to OCR.
    for line in reversed(lines):
        if line.y < height * 0.85:
            continue
        match = BARE_NUMBER_RE.fullmatch(line.text.strip())
        if match:
            return match.group(1)
    return None


def _resolve_candidates(
    name: str | None,
    name_sim: float,
    number: str | None,
    image,
    cv2,
    np,
) -> list[Candidate]:
    db = cards.get_db()
    queries: list[str] = []
    search_name = name or ""
    if name and number:
        queries.append(f"{search_name} {number}")
        queries.append(search_name)
    elif name:
        queries.append(search_name)
    elif number:
        queries.append(number)

    found: dict[str, dict] = {}
    for query in queries:
        for card in db.search_cards(query, limit=15):
            key = cards._fmt_card(card)
            if key:
                found[key] = card
        matched = db.match(query)
        if matched:
            key = cards._fmt_card(matched)
            if key:
                found[key] = matched

    ranked: list[Candidate] = []
    photo_hash = None
    for card_query, card in found.items():
        card_name = card.get("name") or ""
        this_name_score = fuzz.WRatio(name, card_name) / 100.0 if name else 0.0
        number_match = _number_matches(number, card)
        base = (0.62 * this_name_score + 0.38 * (1.0 if number_match else 0.0)) if number else 0.82 * this_name_score
        ranked.append(Candidate(
            card_query=card_query,
            name=card_name,
            set_name=card.get("set_name") or "",
            number=str(card.get("number") or ""),
            rarity=card.get("rarity") or "",
            image_url=cards.card_image_url(card),
            score=base,
            name_score=this_name_score,
            number_match=number_match,
        ))

    ranked.sort(key=lambda candidate: candidate.score, reverse=True)
    top = ranked[:MAX_VISUAL_CANDIDATES]
    if top:
        photo_hash = _phash(image, cv2, np)
        jobs = [
            (candidate, found[candidate.card_query])
            for candidate in top
            if candidate.card_query in found
        ]
        hashes = list(_hash_pool.map(
            lambda job: _catalog_hash(job[1], cv2, np), jobs,
        )) if jobs else []
        for (candidate, _card), catalog_hash in zip(jobs, hashes):
            if catalog_hash is None:
                continue
            candidate.visual_score = _hash_similarity(photo_hash, catalog_hash)
            candidate.score = 0.75 * candidate.score + 0.25 * candidate.visual_score
            if candidate.visual_score >= VISUAL_BONUS_FLOOR:
                candidate.score += VISUAL_BONUS
            candidate.score = min(1.0, candidate.score)

    ranked.sort(
        key=lambda candidate: (
            candidate.score,
            candidate.visual_score or 0.0,
            candidate.number_match,
        ),
        reverse=True,
    )
    return ranked[:MAX_CANDIDATES]


def _number_matches(detected: str | None, card: dict) -> bool:
    if not detected:
        return False
    want = re.sub(r"\s+", "", detected).lower()
    number = str(card.get("number") or "").lower()
    if not number:
        return False
    if want == number:
        return True
    prefix = cards._PROMO_SET_TO_PREFIX.get(card.get("set_id") or "")
    if prefix:
        formatted = f"{prefix}{number}".lower()
        if want in {formatted, f"{prefix}{int(number)}".lower() if number.isdigit() else formatted}:
            return True
    slash = SLASH_NUMBER_RE.fullmatch(detected)
    if slash:
        return re.sub(r"\s+", "", slash.group(1)).lower() == number
    return want.endswith(number) and any(ch.isdigit() for ch in want)


def _confidence(
    name: str | None,
    name_sim: float,
    candidates: list[Candidate],
    card_shape_ok: bool,
) -> tuple[str, float | None]:
    if not candidates:
        return "none", None
    best = candidates[0]
    score = round(best.score, 3)
    identity = [(c.name.lower(), c.number.lower()) for c in candidates]
    unique = identity.count((best.name.lower(), best.number.lower())) == 1
    visual_ok = best.visual_score is None or best.visual_score >= AUTO_VISUAL_FLOOR

    if (
        name
        and name_sim >= AUTO_NAME_SCORE
        and best.number_match
        and unique
        and card_shape_ok
        and visual_ok
    ):
        return "high", score

    if name and name_sim >= MEDIUM_NAME_SCORE and (
        best.number_match or best.name_score >= 0.9
    ) and (best.visual_score is None or best.visual_score >= MEDIUM_VISUAL_FLOOR):
        return "medium", score
    return "low", score


def _phash(image, cv2, np):
    if image.ndim == 3:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(image, (32, 32), interpolation=cv2.INTER_AREA)
    dct = cv2.dct(np.float32(gray))
    low = dct[:8, :8].flatten()
    median = np.median(low[1:])
    bits = (low > median).astype(np.uint8)
    return np.packbits(bits).tobytes().hex()


def _hash_similarity(left: str, right: str) -> float:
    import numpy as np

    a = np.unpackbits(np.frombuffer(bytes.fromhex(left), dtype=np.uint8))
    b = np.unpackbits(np.frombuffer(bytes.fromhex(right), dtype=np.uint8))
    return round(1.0 - float(np.count_nonzero(a != b)) / len(a), 3)


def _catalog_hash(card: dict, cv2, np):
    key = re.sub(r"[^a-zA-Z0-9_.-]", "_", f"{card.get('set_id', '')}_{card.get('number', '')}")
    if not key.strip("_"):
        return None
    with _hash_cache_lock:
        if key in _hash_cache:
            return _hash_cache[key]

    os.makedirs(paths.CARD_IMAGE_HASHES, exist_ok=True)
    cache_path = os.path.join(paths.CARD_IMAGE_HASHES, f"{key}.json")
    try:
        with open(cache_path, encoding="utf-8") as handle:
            cached = json.load(handle)
        if cached.get("hash"):
            with _hash_cache_lock:
                _hash_cache[key] = cached["hash"]
            return cached["hash"]
    except (OSError, ValueError):
        pass

    if _recent_miss(key):
        return None

    url = cards.card_image_url(card)
    if not url:
        _record_miss(key)
        return None
    try:
        response = _session.get(url, timeout=IMAGE_TIMEOUT, headers={"User-Agent": "EbayPrice/1.0"})
    except requests.RequestException:
        _record_miss(key)
        return None
    if response.status_code != 200 or len(response.content) < 1000:
        _record_miss(key)
        return None
    image = cv2.imdecode(np.frombuffer(response.content, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        _record_miss(key)
        return None
    value = _phash(image, cv2, np)
    with _hash_cache_lock:
        _hash_cache[key] = value
    try:
        tmp = f"{cache_path}.{uuid4().hex}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump({"hash": value, "fetched_at": datetime.now(timezone.utc).isoformat()}, handle)
        os.replace(tmp, cache_path)
    except OSError:
        pass
    return value


def _recent_miss(key: str) -> bool:
    try:
        with open(paths.CARD_IMAGE_MISSES, encoding="utf-8") as handle:
            misses = json.load(handle)
        seen = datetime.fromisoformat(misses.get(key, ""))
        return datetime.now(timezone.utc) - seen < timedelta(days=MISS_DAYS)
    except (OSError, ValueError, TypeError):
        return False


def _record_miss(key: str) -> None:
    # Parallel hash lookups for one card can record misses at the same time; the
    # read-modify-write below would otherwise drop each other's entries.
    with _miss_lock:
        try:
            os.makedirs(paths.DATA_DIR, exist_ok=True)
            try:
                with open(paths.CARD_IMAGE_MISSES, encoding="utf-8") as handle:
                    misses = json.load(handle)
            except (OSError, ValueError):
                misses = {}
            misses[key] = datetime.now(timezone.utc).isoformat()
            tmp = f"{paths.CARD_IMAGE_MISSES}.{uuid4().hex}.tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(misses, handle)
            os.replace(tmp, paths.CARD_IMAGE_MISSES)
        except OSError:
            pass
