"""
extractor.py
============
Extraction logic for one manual PDF.
Called by pipeline.py.
"""

import hashlib
from pathlib import Path

from pdf_profile import profile_pdf
from index_builder import build_index
from content_extractor import extract_content
from vehicle_info import extract_vehicle_info


def _make_record_id(document_id: str, start_pdf_page: int) -> str:
    """
    Generate a unique, deterministic ID for a DTC record.
    SHA256 of (document_id + start_pdf_page) — same PDF + same page = same ID.
    Truncated to 16 hex chars for readability.
    """
    raw = f"{document_id}{start_pdf_page}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def extract_records(pdf_path: Path, output_dir: Path) -> dict:
    """
    Main function called by pipeline.py.
    Returns one document-level JSON object for this PDF.
    output_dir is where image files will be saved.
    """
    source = pdf_path.name

    # SHA256 of the raw PDF bytes — same file different name = same ID
    document_id = hashlib.sha256(pdf_path.read_bytes()).hexdigest()

    # ── Profile the PDF ───────────────────────────────────────────────────────
    metadata, pdf_profile = profile_pdf(pdf_path)

    # ── Extract vehicle info ──────────────────────────────────────────────────
    vehicle = extract_vehicle_info(pdf_path, metadata)

    # ── Build DTC index ───────────────────────────────────────────────────────
    index = build_index(pdf_path)

    if not index:
        print("No codes found.")
        return {}

    # Flatten index into page_to_codes and code_titles
    page_to_codes: dict[int, list] = {}
    code_titles:   dict[str, str]  = {}
    page_to_ref:   dict[int, str]  = {}

    for code, info in index.items():
        code_titles[code] = info["title"]
        for i, page_num in enumerate(info["pages"]):
            page_to_codes.setdefault(page_num, []).append(code)
            # first code to claim the page sets the printed ref
            if page_num not in page_to_ref and info["page_refs"][i]:
                page_to_ref[page_num] = info["page_refs"][i]

    print(f"\nExtracting content for {len(index)} codes across {len(page_to_codes)} pages...")

    records     = []
    seen_xrefs  = set()
    seen_hashes = {}

    for record_num, (page_num, codes) in enumerate(sorted(page_to_codes.items()), start=1):
        print(f"  Page {page_num} -> {codes}")

        page_ref_base = f"{pdf_path.stem}-{page_num}"

        content = extract_content(
            pdf_path, page_num, codes, output_dir,
            page_ref_base, seen_xrefs, seen_hashes
        )

        # ── Cross-check: index ref vs footer ref ──────────────────────────────
        index_ref  = page_to_ref.get(page_num)
        footer_ref = content["start_page_ref_footer"]
        warnings   = []
        if index_ref and footer_ref and index_ref != footer_ref:
            msg = f"page_ref mismatch on PDF page {page_num}: index={index_ref}, footer={footer_ref}"
            print(f"  [WARN] {msg}")
            warnings.append(msg)

        # ── page_refs list ────────────────────────────────────────────────────
        # Build a list of unique page refs spanning this DTC block (start to end).
        start_ref = page_to_ref.get(page_num) or content["start_page_ref_footer"]
        end_ref   = content["end_page_ref"]
        if start_ref == end_ref or end_ref is None:
            page_refs = [start_ref] if start_ref else []
        else:
            page_refs = [r for r in [start_ref, end_ref] if r]

        # ── DTC title ─────────────────────────────────────────────────────────
        titles    = list(dict.fromkeys([code_titles.get(c, "") for c in codes if code_titles.get(c)]))
        dtc_title = " / ".join(titles) if titles else None

        # ── Sections — assign section_id to each ─────────────────────────────
        sections = []
        for s_idx, sec in enumerate(content["sections"]):
            sections.append({
                "section_id": f"r{record_num}_s{s_idx + 1}",
                "heading":    sec["heading"],
                "role":       sec["role"],
                "text":       sec["text"],
                "page_start": sec["page_start"],
                "page_end":   sec["page_end"],
            })

        # ── Tables — flat list, each linked to its section via section_id ─────
        tables  = []
        t_count = 1
        for s_idx, sec in enumerate(content["sections"]):
            section_id = f"r{record_num}_s{s_idx + 1}"
            for tbl in sec["tables"]:
                tables.append({
                    "table_id":       f"r{record_num}_t{t_count}",
                    "section_id":     section_id,
                    "heading_nearby": sec["heading"],
                    "role":           sec["role"],
                    "page":           tbl["page"],
                    "page_ref":       tbl["page_ref"],
                    "rows":           tbl["rows"],
                })
                t_count += 1

        # ── Images — enriched with metadata ──────────────────────────────────
        images = []
        for i_idx, img in enumerate(content["image_list"]):
            images.append({
                "image_id":   f"r{record_num}_i{i_idx + 1}",
                "section_id": None,          # not yet assigned to a specific section
                "pdf_page":   img["pdf_page"],
                "page_ref":   img["page_ref"],
                "image_path": f"images/{img['filename']}",
                "caption":    None,
                "role":       "unknown",
            })

        records.append({
            "record_id":   _make_record_id(document_id, page_num),
            "record_type": "dtc_block",

            "codes": codes,
            "title": dtc_title,

            "location": {
                "start_pdf_page": page_num,
                "end_pdf_page":   content["end_pdf_page"],
                "page_refs":      page_refs,
            },

            "sections": sections,
            "tables":   tables,
            "images":   images,
            "notes":    [],     # reserved for WARNING/CAUTION blocks — extraction not yet implemented

            "raw_text": content["raw_text"],

            "extraction": {
                "status":   "success",
                "ocr_used": False,
                "warnings": warnings,
            },
        })

    return {
        "schema_version": 3,
        "document_id":    document_id,
        "source_file":    source,
        "metadata":       metadata,
        "pdf_profile":    pdf_profile,
        "vehicle":        vehicle,
        "records":        records,
    }
