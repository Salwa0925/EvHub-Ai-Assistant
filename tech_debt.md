# Tech Debt

Known shortcuts and limitations in the current codebase.
Each item notes where it lives, why it's a problem at scale, and when to fix it.

## Item 1 — PDF opened and closed for every code group:
PDF re-opened on every DTC group
- File: src/extractor.py — extract_content()
- Problem: fitz.open() is called once per DTC page group. A manual with 200 codes
  opens and closes the same PDF 100+ times. Slow at scale.
- Fix: open the PDF once in extract_records() and pass the document object down.
- Priority: Medium — not a problem with one manual, noticeable with hundreds.

## Item 2 — Index scan limited to 60 pages:
Index scan hardcoded to first 60 pages
- File: src/extractor.py — build_index(), line 31
- Problem: max_page = min(60, len(pdf)) assumes the DTC index is always
  in the first 60 pages. Other manufacturers may put it later.
- Fix: make this configurable, or scan the full document.
- Priority: Low — acceptable for now, revisit when adding new manuals.

## Item 3 — Hardcoded path in pdf_detector.py:
Hardcoded folder path in pdf_detector.py
- File: src/pdf_detector.py, line 4
- Problem: storage_folder = r"D:\EVHUB\Manuals" is tied to one machine.
  Anyone else running this code will need to change it manually.
- Fix: read the path from a config file or environment variable.
- Priority: Low — this file is a utility script, not part of the main pipeline.

## Item 4 — No skip logic for already-processed PDFs: ✅ RESOLVED
No skip logic — pipeline re-processes files it already ran
- File: src/pipeline.py
- Problem: running the pipeline twice on the same PDF overwrites the JSON
  and re-saves all images. Wastes time and could cause duplicate records later
  when we add the database importer.
- Fix: check if output JSON already exists before processing. Skip if found.
- Priority: High — DONE. Skip logic added to pipeline.py.

## Item 5 — No error handling around image extraction: ⚠️ PARTIALLY RESOLVED
Image extraction has no error handling
- File: src/extractor.py — extract_content(), image loop
- Problem: if pdf.extract_image(xref) fails (corrupt image, unsupported format),
  the whole run crashes and no output is saved.
- Fix applied: try/except added at pipeline level — one bad PDF no longer kills the run.
- Remaining: the image loop inside extract_content() still has no per-image try/except.
  One bad image inside a PDF can still crash that PDF's extraction.
- Fix remaining: wrap the image loop body in try/except, log and skip bad images.
- Priority: Medium — will hit this with real-world messy PDFs.

## Item 6 — print() used instead of proper logging:
print() used throughout instead of Python logging
- File: src/extractor.py, src/pipeline.py
- Problem: print() output cannot be saved to a file, filtered by severity,
  or turned off easily. At scale you want a log file per run.
- Fix: replace with Python's built-in logging module.
- Priority: Low — fine for now, needed before production.

## Item 7 — Table data stored as raw text instead of structured fields: 🔀 APPROACH CHANGED
Table data is stored as raw text instead of structured fields
- File: `src/extractor.py`
- Problem: table content is flattened into page text, so row/column relationships are lost.
- Approach update: structured field extraction (diagnosis name, detecting condition,
  possible causes) is now confirmed as the responsibility of the enrichment layer —
  not this ETL pipeline. AWS Bedrock (or equivalent LLM) will read the raw page text
  and extract structured fields in a separate downstream step.
- This pipeline's job is to deliver clean raw text. The LLM does the structuring.
- Priority: No longer a priority for this pipeline — tracked in enrichment layer.


---
Items are not blockers unless marked High.
