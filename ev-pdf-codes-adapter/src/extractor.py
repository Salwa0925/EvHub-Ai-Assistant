"""
extractor.py
============
Extraction logic for one manual PDF.
Called by pipeline.py.
"""

import hashlib #for fingerprinting
from pathlib import Path

from pdf_profile import profile_pdf
from index_builder import build_index
from content_extractor import extract_content


def extract_records(pdf_path: Path, output_dir: Path) -> dict:
    """
    Main function called by pipeline.py.
    Returns one document-level JSON object for this PDF.
    output_dir is where image files will be saved.
    """
    source = pdf_path.name

    # ── Generate document_id ──────────────────────────────────────────────
    #SHA265 reads the raw bytes of the PDF file and produces a unique fingerprint
    #same file with a different name = same ID. Different file = different ID
    document_id = hashlib.sha256(pdf_path.read_bytes()).hexdigest()

    # ── Profile the PDF ───────────────────────────────────────────────────
    # quick pre-check before any heavy extraction starts
    metadata, pdf_profile = profile_pdf(pdf_path)

    index = build_index(pdf_path)

    if not index:
        print("No codes found.")
        return {}
    
    #group codes by page number
    #multiple codes can share the same page - we extract the page once
    # index now returns { "U1000": [181, 195], ... }
    # flatten into page_to_codes: { 181: ["U1000"], 195: ["U1000"], ... }
    page_to_codes: dict[int, list] = {}
    for code, pages in index.items():
        for page_num in pages:
            page_to_codes.setdefault(page_num, []).append(code)

    print(f"\nExtracting content for {len(index)} codes across {len(page_to_codes)} pages...")
    records = []
    seen_xrefs = set()   # shared across all pages — same image is never saved twice
    seen_hashes = {}  # hash → filename — points duplicates to the already-saved file

    for page_num, codes in sorted(page_to_codes.items()):
        print(f"  Page {page_num} -> {codes}")

        page_ref_base = f"{pdf_path.stem}-{page_num}"

        content = extract_content(pdf_path, page_num, codes, output_dir, page_ref_base, seen_xrefs, seen_hashes)


        #One record per page - codes got into dtc_mentions list, not seperate records
        records.append({
            "schema_version": 2,                    # version of this JSON shape
            "document_id": document_id,             # SHA256 fingerprint of the PDF file
            "source_file": source,                  # original PDF filename
            "pdf_page": page_num,                   # physical page number in the PDF (1-indexed, always unique)
            "page_ref": page_ref_base,              # logical label printed on the page (e.g. "EVC-78") — constructed for now, read from footer in future
            "text": content["text"],                # all extracted text from this page
            "ocr_used": False,                      # True when Tesseract OCR was used (Phase 2)
            "ocr_confidence": None,                 # OCR confidence score (later)
            "dtc_mentions": codes,                  # list of DTC codes found on this page
            "has_images": content["has_images"],    # True if any images were saved
            "images": content["images"],            # list of saved image filenames
            "extraction_status": "ok"               # "ok" or "error" — for the processing report
        })

    return {
    "schema_version":  2,
    "document_id":     document_id,
    "source_file":     source,
    "metadata":        metadata,
    "pdf_profile":     pdf_profile,
    "pages":           records
}

        

