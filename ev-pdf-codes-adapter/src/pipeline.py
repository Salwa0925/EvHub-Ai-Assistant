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

    # ── Extract records ───────────────────────────────────────────────────────
    records = extract_records(pdf_path)

    if not records:
        print("No records extracted — check the PDF.")
        sys.exit(1)

    # ── Save output ───────────────────────────────────────────────────────────
    out_path = Path("data") / f"{pdf_path.stem}.json"
    out_path.parent.mkdir(exist_ok=True)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

    print(f"Saved {len(records)} records to {out_path}")

    # ── Quality report ────────────────────────────────────────────────────────
    missing = [r for r in records if not r["content"]["text"].strip()]
    print(f"\nQuality report:")
    print(f"  Total records : {len(records)}")
    print(f"  Missing content: {len(missing)}")

    if missing:
        for r in missing[:5]:
            print(f"  {r['dtc']} → page {r['page']} has no content")


if __name__ == "__main__":
    main()