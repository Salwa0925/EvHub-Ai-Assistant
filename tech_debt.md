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

## Item 4 — No skip logic for already-processed PDFs:
No skip logic — pipeline re-processes files it already ran
- File: src/pipeline.py
- Problem: running the pipeline twice on the same PDF overwrites the JSON
  and re-saves all images. Wastes time and could cause duplicate records later
  when we add the database importer.
- Fix: check if output JSON already exists before processing. Skip if found.
- Priority: High — needed before we run this on the full manuals folder.

## Item 5 — No error handling around image extraction:
Image extraction has no error handling
- File: src/extractor.py — extract_content(), image loop
- Problem: if pdf.extract_image(xref) fails (corrupt image, unsupported format),
  the whole run crashes and no output is saved.
- Fix: wrap in try/except, log the failure, and continue.
- Priority: Medium — will hit this eventually with real-world messy PDFs.

## Item 6 — print() used instead of proper logging:
print() used throughout instead of Python logging
- File: src/extractor.py, src/pipeline.py
- Problem: print() output cannot be saved to a file, filtered by severity,
  or turned off easily. At scale you want a log file per run.
- Fix: replace with Python's built-in logging module.
- Priority: Low — fine for now, needed before production.

## Item 7 — Table data stored as raw text instead of structured fields
Table data is stored as raw text instead of structured fields
- File: `src/extractor.py`
- Problem: table content is flattened into `content.text`, so row/column relationships are lost. Shared table values, such as one detecting condition applying to multiple DTC rows, are only implied by the page text.
- - Why it matters: this makes semantic search and LLM answering less reliable, because the model has to infer table structure instead of reading explicit field mappings. It can also increase duplication and make output less efficient as more manuals are processed.
- Fix: store one structured JSON record per DTC with explicit fields for diagnosis name, detecting condition, and possible causes. Keep raw page text as fallback context.
- Priority: High — needed for accurate retrieval and structured downstream use.


---
Items are not blockers unless marked High.
