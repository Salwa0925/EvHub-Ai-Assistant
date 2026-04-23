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
from text_parser import parse_text
from vehicle_info import extract_vehicle_info



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

    # ── Extract vehicle info ───────────────────────────────────────────────
    vehicle = extract_vehicle_info(pdf_path, metadata)

    index = build_index(pdf_path)

    if not index:
        print("No codes found.")
        return {}
    
    #group codes by page number
    #multiple codes can share the same page - we extract the page once
    # index now returns { "U1000": [181, 195], ... }
    # flatten into page_to_codes: { 181: ["U1000"], 195: ["U1000"], ... }
    page_to_codes: dict[int, list] = {}
    code_titles: dict[str, str] = {}   # stores title for each code from the index table
    page_to_ref:  dict[int, str] = {}  # physical page → printed label e.g. {835: "EVB-88"}

    for code, info in index.items():
        code_titles[code] = info["title"]   # save title for later
        for i, page_num in enumerate(info["pages"]):
            page_to_codes.setdefault(page_num, []).append(code)
            # store the printed ref for this page — first code to claim the page wins
            if page_num not in page_to_ref and info["page_refs"][i]:
                page_to_ref[page_num] = info["page_refs"][i]


    print(f"\nExtracting content for {len(index)} codes across {len(page_to_codes)} pages...")
    records = []
    seen_xrefs = set()   # shared across all pages — same image is never saved twice
    seen_hashes = {}  # hash → filename — points duplicates to the already-saved file

    for page_num, codes in sorted(page_to_codes.items()):
        print(f"  Page {page_num} -> {codes}")

        page_ref_base = f"{pdf_path.stem}-{page_num}"

        content = extract_content(pdf_path, page_num, codes, output_dir, page_ref_base, seen_xrefs, seen_hashes)

        # ── Cross-check: index ref vs footer ref ──────────────────────────────
        index_ref  = page_to_ref.get(page_num)
        footer_ref = content["start_page_ref_footer"]
        if index_ref and footer_ref and index_ref != footer_ref:
            print(f"  [WARN] page_ref mismatch on PDF page {page_num}: index={index_ref}, footer={footer_ref}")

        # parse the merged text into structured sections
        parsed = parse_text(content["text"])

        # get titles for all codes in this block — join if multiple
        titles = list(dict.fromkeys([code_titles.get(c, "") for c in codes if code_titles.get(c)]))
        dtc_title = " / ".join(titles) if titles else None

        # one record per DTC block — may span multiple pages
        records.append({
            "document_id":    document_id,             # SHA256 fingerprint of the PDF file
            "source_file":    source,                  # original PDF filename
            "dtc_codes":      codes,                   # list of DTC codes in this block (e.g. ["P3031", "P303C"])
            "dtc_title":      dtc_title,               # title from index table (e.g. "HV SYSTEM INTERLOCK ERROR")
            "start_pdf_page":  page_num,                     # physical PDF page — first page of block
            "end_pdf_page":    content["end_pdf_page"],     # physical PDF page — last page of block
            "start_page_ref":  page_to_ref.get(page_num) or content["start_page_ref_footer"],  # index first, footer as fallback
            "end_page_ref":    content["end_page_ref"],     # printed label from footer e.g. "EVB-91"
            "has_images":     content["has_images"],   # True if any images were saved
            "images":         content["images"],       # list of saved image filenames
            # ── two high-level text blocks from text parser ──────────────────
            "dtc_logic_block":             parsed["dtc_logic_block"],
            "diagnosis_procedure_block":   parsed["diagnosis_procedure_block"],
            # ── tables extracted per zone (raw cell strings) ─────────────────
            "dtc_logic_tables":            content["dtc_logic_tables"],
            "diagnosis_procedure_tables":  content["diagnosis_procedure_tables"],
        })


    return {
    "schema_version":  2,
    "document_id":     document_id,
    "source_file":     source,
    "metadata":        metadata,
    "pdf_profile":     pdf_profile,
    "vehicle":         vehicle,
    "pages":           records
}

        

