"""Read one card image the way the scan endpoint does, and print what it found.

Hand-run calibration tool, not part of the hourly/scheduled pipeline. It makes no eBay
calls and writes no database rows. It does fetch catalog art for the top candidates to
compare visual hashes, so the first run for a printing is slower; those hashes are
cached under `data/card_image_hashes/` and unsuccessful image URLs are remembered in
`data/card_image_misses.json` for a week.

Usage:
    python scripts/check_card_scan.py --image path/to/photo.jpg
    python scripts/check_card_scan.py --image path/to/photo.jpg --json
"""

import argparse
import json
import sys
from pathlib import Path

# Running `python scripts/...` puts scripts/ on sys.path, not the repo root, and
# `dashboard` is a namespace package rather than an installed one.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard.backend.services import card_scan, photo_storage


def main() -> int:
    # Windows consoles default to cp1252; card OCR commonly contains symbols the
    # font cannot encode, and a PrintError should not hide a successful result.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    parser = argparse.ArgumentParser(description="Run local card recognition on one image.")
    parser.add_argument("--image", required=True, help="path to a JPEG/PNG/WebP/HEIC photo")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    args = parser.parse_args()

    path = Path(args.image)
    if not path.is_file():
        print(f"No such image: {path}")
        return 2
    data = path.read_bytes()
    if len(data) > photo_storage.MAX_UPLOAD_BYTES:
        print(f"That image is larger than {photo_storage.MAX_UPLOAD_BYTES // (1024 * 1024)}MB")
        return 2
    if not card_scan.available():
        print("Recognition dependencies are missing; install requirements-dashboard.txt.")
        return 2

    try:
        jpeg = photo_storage.process(data, max_edge=card_scan.MAX_OCR_EDGE)
        result = card_scan.analyze_image(jpeg)
    except Exception as exc:
        print(f"Recognition failed: {exc}")
        return 1

    payload = {
        "image": str(path),
        "confidence": result.confidence,
        "score": result.score,
        "auto_add_eligible": result.auto_add_eligible,
        "card_detected": result.card_detected,
        "card_like": result.card_like,
        "detected_name": result.detected_name,
        "detected_number": result.detected_number,
        "ocr_text": result.ocr_text,
        "candidates": result.as_candidates(),
    }
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    print(f"image:     {path}")
    print(f"confidence: {result.confidence}  score: {result.score}")
    print(f"detected:  {result.detected_name or '-'} #{result.detected_number or '-'}")
    print(f"card found: {result.card_detected}  card-shaped: {result.card_like}")
    if not result.candidates:
        print("candidates: none")
    else:
        print("candidates:")
        for index, candidate in enumerate(result.candidates, 1):
            visual = "n/a" if candidate.visual_score is None else f"{candidate.visual_score:.3f}"
            print(
                f"  {index}. {candidate.name} #{candidate.number} - {candidate.set_name} "
                f"[{candidate.rarity}] score={candidate.score:.3f} "
                f"name={candidate.name_score:.3f} number={candidate.number_match} visual={visual}"
            )
            print(f"     {candidate.card_query}")
    if result.ocr_text:
        print("OCR:")
        print(result.ocr_text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
