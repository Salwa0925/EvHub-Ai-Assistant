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

        # ── Try to process — skip and log if anything goes wrong ─────────────
        # try/except means: attempt the code inside try — if ANY error occurs,
        # jump to except instead of crashing the whole program.
        # This way one bad PDF never kills the rest of the run.
        try:
            result = extract_records(pdf_path, output_dir=out_dir)

            if not result or not result["pages"]:
                print("  No records extracted - skipping.")
                continue

            # ── Atomic JSON write ─────────────────────────────────────────────
            # We write to a temporary file first (.json.tmp).
            # Only when the write is fully complete do we rename it to .json.
            # If the program crashes mid-write, the .tmp file is left behind
            # and .json is never created — so the next run will reprocess correctly.
            tmp_path = out_path.with_suffix(".json.tmp")   # e.g. data/EVB/EVB.json.tmp

            with open(tmp_path, 'w', encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)

            tmp_path.rename(out_path)   # instant rename — cannot be interrupted halfway

            print(f"  Saved {len(result['pages'])} pages to {out_path}")

            # ── Quality report ────────────────────────────────────────────────
            # Check for pages where no text was extracted
            pages = result["pages"]   # pull out the pages list for easy access

            missing_text = [r for r in pages if not r["text"].strip()]

            all_images = set()
            for r in pages:
                all_images.update(r["images"])
            total_images = len(all_images)

            print(f"  Quality report:")
            print(f"   Total pages    : {len(pages)}")
            print(f"   Missing text   : {len(missing_text)}")
            print(f"   Images saved   : {total_images}")

            if missing_text:
                for r in missing_text[:5]:
                    print(f"   page {r['pdf_page']} ({r['dtc_mentions']}) has no text")

        except Exception as e:
            # Something went wrong with this PDF — print the error and move on.
            # The .json file was never written (atomic write), so next run will retry.
            print(f"  ERROR processing {pdf_path.name}: {e}")


if __name__ == "__main__":
    main()
