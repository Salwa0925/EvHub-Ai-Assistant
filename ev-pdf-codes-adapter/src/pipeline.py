"""
pipeline.py
===========
Entry point — scans the manuals/ folder and processes every pdf found

Usage:
    python src/pipeline.py 
"""

import json
import sys
import hashlib
from datetime import datetime
from pathlib import Path

from extractor import extract_records
from pdf_profile import profile_pdf
from llm_formatter import format_document


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

        # ── Processing report ─────────────────────────────────────────────────
    # collects one entry per PDF — printed at the end and saved to data/
    report = []

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

        # ── Profile the PDF ───────────────────────────────────────────────────
        # quick check before any heavy extraction — tells us what type of PDF this is
        metadata, pdf_profile = profile_pdf(pdf_path)
        pdf_type = pdf_profile["pdf_type"]
        print(f"  PDF type: {pdf_type}")

        # ── Handle scanned PDFs ───────────────────────────────────────────────
        # scanned PDFs have no text layer — OCR not yet built, so we skip extraction
        # we still write a stub JSON so the file appears in the output with a clear reason
        if pdf_type == "scanned":
            document_id = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
            stub = {
                "schema_version": 3,
                "document_id":    document_id,
                "source_file":    pdf_path.name,
                "metadata":       metadata,
                "pdf_profile":    pdf_profile,
                "status":         "skipped",
                "reason":         "scanned PDF — OCR not yet supported",
                "records":        []
            }
            tmp_path = out_path.with_suffix(".json.tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(stub, f, indent=2, ensure_ascii=False)
            tmp_path.rename(out_path)
            print(f"  Skipped — stub JSON written to {out_path}")
            report.append({"file": pdf_path.name, "pdf_type": pdf_type, "status": "skipped", "reason": "scanned PDF — OCR not yet supported"})
            continue


        # ── Try to process — skip and log if anything goes wrong ─────────────
        # try/except means: attempt the code inside try — if ANY error occurs,
        # jump to except instead of crashing the whole program.
        # This way one bad PDF never kills the rest of the run.
        try:
            result = extract_records(pdf_path, output_dir=out_dir)

            if not result or not result["records"]:
                print("  No records extracted — writing stub JSON.")
                stub = {
                    "schema_version": 3,
                    "document_id":    hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
                    "source_file":    pdf_path.name,
                    "metadata":       result.get("metadata", {}),
                    "pdf_profile":    result.get("pdf_profile", {}),
                    "status":         "skipped",
                    "reason":         "no DTC codes found",
                    "records":        []
                }
                tmp_path = out_path.with_suffix(".json.tmp")
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(stub, f, indent=2, ensure_ascii=False)
                tmp_path.rename(out_path)
                report.append({"file": pdf_path.name, "pdf_type": pdf_type, "status": "skipped", "reason": "no DTC codes found"})
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

            # ── LLM-friendly output ───────────────────────────────────────────
            # Derived representation — raw v4 file above is the source of truth.
            # This strips raw_text, raw_rows, and noise so consumers don't pay
            # for duplicate tokens.  Written atomically like the v4 file.
            llm_path = out_dir / f"{pdf_path.stem}_llm.json"
            llm_tmp  = llm_path.with_suffix(".json.tmp")
            with open(llm_tmp, 'w', encoding='utf-8') as f:
                json.dump(format_document(result), f, indent=2, ensure_ascii=False)
            llm_tmp.replace(llm_path)

            print(f"  Saved {len(result['records'])} records to {out_path}")
            report.append({"file": pdf_path.name, "pdf_type": pdf_type, "status": "extracted", "records": len(result["records"])})


            # ── Quality report ────────────────────────────────────────────────
            records_list = result["records"]

            # Records with no sections extracted (no text found)
            missing_text = [r for r in records_list if not r.get("sections")]

            # Count unique images across all records
            all_images = set()
            for r in records_list:
                for img in r.get("images", []):
                    all_images.add(img["image_path"])
            total_images = len(all_images)

        except Exception as e:
            # Something went wrong with this PDF — print the error and move on.
            # The .json file was never written (atomic write), so next run will retry.
            print(f"  ERROR processing {pdf_path.name}: {e}")
            report.append({"file": pdf_path.name, "pdf_type": pdf_type, "status": "error", "reason": str(e)})


    # ── Processing report ─────────────────────────────────────────────────
    # print summary to terminal and save to data/processing_report.json
    print(f"\n{'-' * 50}")
    print(f"Processing report -- {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'-' * 50}")
    for entry in report:
        status = entry["status"].upper()
        pages  = f"  {entry.get('records', 0)} records" if entry["status"] == "extracted" else f"  {entry.get('reason', '')}"
        print(f"  {status:10} {entry['file']}{pages}")

    report_path = base_dir / "processing_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({"run_date": datetime.now().isoformat(), "results": report}, f, indent=2, ensure_ascii=False)
    print(f"\nReport saved to {report_path}")


if __name__ == "__main__":
    main()
