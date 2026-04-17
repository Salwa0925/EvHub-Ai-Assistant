"""
pipeline.py
===========
Entry point — processes one manual PDF end to end.

Usage:
    python src/pipeline.py manuals/EVB.pdf
"""

import json
import sys
from pathlib import Path

from extractor import extract_records


def main():
    # ── Get PDF path from command line ────────────────────────────────────────
    if len(sys.argv) < 2:
        print("Usage: python src/pipeline.py manuals/EVB.pdf")
        sys.exit(1)

    pdf_path = Path(sys.argv[1])

    if not pdf_path.exists():
        print(f"PDF not found: {pdf_path}")
        sys.exit(1)

    print(f"Processing: {pdf_path.name}")

    # ── Set up output directory ───────────────────────────────────────────────
    # All output (JSON + images) goes into the data/ folder.
    # We define it here so we can pass it to extract_records,
    # which will use it to save image files to disk.
    out_dir = Path("data")
    out_dir.mkdir(exist_ok=True)  # create the data/ folder if it doesn't exist yet

    # ── Extract records ───────────────────────────────────────────────────────
    # We now pass out_dir so the extractor knows where to save images
    records = extract_records(pdf_path, output_dir=out_dir)

    if not records:
        print("No records extracted — check the PDF.")
        sys.exit(1)

    # ── Save JSON output ──────────────────────────────────────────────────────
    out_path = out_dir / f"{pdf_path.stem}.json"

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

    print(f"Saved {len(records)} records to {out_path}")

    # ── Quality report ────────────────────────────────────────────────────────
    missing_text = [r for r in records if not r["content"]["text"].strip()]
    # collect all inuque image filenames across all records(avoid counting  shared imageds twice)
    all_images = set() # to store unique image filenames
    for r in records:
        all_images.update(r["content"]["images"]) # add image filenames from this record to the set
    total_images = len(all_images) 

    print(f"\nQuality report:")
    print(f"  Total records  : {len(records)}")
    print(f"  Missing content: {len(missing_text)}")
    print(f"  Images saved   : {total_images}")  # ← NEW: show how many images were extracted

    if missing_text:
        for r in missing_text[:5]:
            print(f"  {r['dtc']} → page {r['page']} has no content")


if __name__ == "__main__":
    main()
