"""
pipeline.py
===========
Entry point — scans the manuals/ folder and processes every pdf found

Usage:
    python src/pipeline.py 
"""

import json
import sys
from pathlib import Path

from extractor import extract_records


def main():
    # ── Get the manuals directory ────────────────────────────────────────
    # Path("manuals") points to the manuals/ folder relative to where you run the script
    # this replaces the old command-line argument - no need to type a filename anymore

    manuals_dir = Path("manuals")

    if not manuals_dir.exists():
        print(f"Manuals folders not found: {manuals_dir}")
        sys.exit(1)

    # ── Find all PDFs ───────────────────────────────────────────────────

    pdf_files = sorted(manuals_dir.glob("*.pdf"))
    if not pdf_files:
        print("No PDF files found in manuals/")
        sys.exit(1)

    print(f"Found {len(pdf_files)} PDF(s) to process")


    # ── Set up base output directory ───────────────────────────────────────────────
    # All output (JSON + images) goes into the data/ - each PDF gets its own subfolder inside it
    # We define it here so we can pass it to extract_records,
    # which will use it to save image files to disk.
    base_dir = Path("data")
    base_dir.mkdir(exist_ok=True)  # create the data/ folder if it doesn't exist yet

    # ── Process each PDF ───────────────────────────────────────────────────
    # we loop through every pdf file found in manuals/
    # each iteration, pdf_path points to the next file in the list
    for pdf_path in pdf_files:
        print(f"\nProcessing: {pdf_path.name}")

        # Create a subfolder named after the PDF — e.g. data/EVB/
        # Each PDF gets its own folder so files never overwrite each other
        out_dir = base_dir / pdf_path.stem
        out_dir.mkdir(exist_ok=True)

        # ── Skip already processed PDFs ───────────────────────────────────────
        # Check if the JSON already exists inside the subfolder
        out_path = out_dir / f"{pdf_path.stem}.json"
        if out_path.exists():
            print(f"  Already processed - skipping.")
            continue
        records = extract_records(pdf_path, output_dir=out_dir)


        if not records:
            print("No records extracted - skipping.")
            continue

        # ── Save JSON output ──────────────────────────────────────────────────────
        # each pdf gets its own json file in data/, named after the pdf but with .json extension
        
        with open(out_path, 'w', encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)
        print(f" Saved {len(records)} records to {out_path}")

        # ── Quality report ────────────────────────────────────────────────────────
        missing_text = [r for r in records if not r["content"]["text"].strip()]
        all_images = set()
        for r in records:
            all_images.update(r["content"]["images"])
        total_images = len(all_images)

        print(f"  Quality report:")
        print(f"   Total records  : {len(records)}")
        print(f"   Missing content: {len(missing_text)}")
        print(f"   Images saved   : {total_images}")

        if missing_text:
            for r in missing_text[:5]:  # show up to 5 records with missing text
                print(f"   {r['dtc']} -> page {r['page']} has no content")


if __name__ == "__main__":
    main()
