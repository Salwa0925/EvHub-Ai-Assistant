"""
main.py — pipeline entry point
Runs the full extraction pipeline in order:
  1. extractor.py   — raw text, tables, images from PDF
  2. classifier.py  — tag elements, filter noise, repair tables
  3. chunker.py     — group into semantic chunks
  4. validate.py    — sanity check on chunks.json

Usage:
    python main.py
"""

from __future__ import annotations
import logging
from pathlib import Path

from extractor  import run as extract,  Config as ExtractorConfig
from classifier import run as classify
from chunker    import run as chunk
from validation   import run as validate

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S", level=logging.INFO)
log = logging.getLogger("main")
 

# ── Configuration ─────────────────────────────────────────────────────────────
# Change these to match your setup

PDF_FILE   = "PDF/EVB.pdf"   # path to your PDF
RAW_DIR    = "raw"                      # extractor output
CLASSIFIED = "classified"               # classifier output
CHUNKS     = "chunks.json"             # chunker output

EXTRACTOR_CFG = ExtractorConfig(
    batch_size          = 5,      # lower to 3 if RAM is tight
    page_render_dpi     = 150,
    min_img_size        = 50,
    footer_height_pct   = 0.08,
)


# ── Pipeline ──────────────────────────────────────────────────────────────────

def main() -> None:

    log.info("═══════════════════════════════════════")
    log.info("  EV Manual Pipeline")
    log.info("  PDF: %s", PDF_FILE)
    log.info("═══════════════════════════════════════")

    # Step 1 — Extract
    log.info("Step 1/4 — Extraction")
    if not extract(pdf_path=PDF_FILE, output_dir=RAW_DIR, cfg=EXTRACTOR_CFG):
        log.error("Extraction failed — stopping pipeline")
        return

    # Step 2 — Classify
    log.info("Step 2/4 — Classification")
    if not classify(raw_dir=RAW_DIR, output_dir=CLASSIFIED):
        log.error("Classification failed — stopping pipeline")
        return

    # Step 3 — Chunk
    log.info("Step 3/4 — Chunking")
    if not chunk(classified_dir=CLASSIFIED, output_file=CHUNKS):
        log.error("Chunking failed — stopping pipeline")
        return

    # Step 4 — Validate
    log.info("Step 4/4 — Validation")
    validate(chunks_file=CHUNKS)

    log.info("═══════════════════════════════════════")
    log.info("  Pipeline complete")
    log.info("  Output: %s", CHUNKS)
    log.info("═══════════════════════════════════════")


if __name__ == "__main__":
    main()