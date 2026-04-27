"""
extractor.py
============
Extraction logic for one manual PDF.
Called by pipeline.py.
"""

import re
import hashlib
from pathlib import Path

from pdf_profile import profile_pdf
from index_builder import build_index
from content_extractor import extract_content
from vehicle_info import extract_vehicle_info


def _common_title_prefix(titles: list[str]) -> str:
    """
    Return the longest common word-level prefix shared by all titles.
    E.g. ["CELL OVER DISCHARGE MODULE25", "CELL OVER DISCHARGE MODULE26"]
         -> "CELL OVER DISCHARGE"
    """
    if not titles:
        return ""
    split = [t.split() for t in titles]
    min_len = min(len(s) for s in split)
    common = []
    for i in range(min_len):
        word = split[0][i]
        if all(s[i] == word for s in split):
            common.append(word)
        else:
            break
    return " ".join(common)


def _normalize_title(codes: list, code_titles: dict) -> str | None:
    """
    Build a compact title for a DTC record.
    Single code  -> "P0A0D HV SYSTEM INTERLOCK ERROR"
    Multiple codes -> "P3031-P303C CELL CONT"  (code range + common title prefix)
    Sidebar letters (e.g. 'E CELL CONT ASIC4') are stripped before comparison.
    """
    raw_titles = [code_titles.get(c, "") for c in codes if code_titles.get(c)]
    if not raw_titles:
        return None
    # Strip inline sidebar prefix: a single uppercase letter at the start
    # e.g. "E CELL CONT ASIC4" -> "CELL CONT ASIC4"
    # Only strips a single leading letter — won't touch "DLC DIAGNOSIS VCM"
    _leading = re.compile(r'^[A-Z] ')
    titles = [_leading.sub("", t).strip() for t in raw_titles]
    titles = [t for t in titles if t]
    if not titles:
        return None

    if len(codes) == 1:
        return f"{codes[0]} {titles[0]}".strip()

    sorted_codes = sorted(codes)
    first_code   = sorted_codes[0]
    last_code    = sorted_codes[-1]
    common       = _common_title_prefix(titles)
    if common:
        return f"{first_code}-{last_code} {common}"
    return f"{first_code}-{last_code}"


def _merge_continued_tables(tables: list, notes: list) -> list:
    """
    Merge tables that continue across pages within the same section.
    Two consecutive tables are considered a continuation when they share
    the same section_id and identical first rows (header).
    The duplicate header row is dropped from the second table onward.
    A note is appended to `notes` for each merge.
    """
    if not tables:
        return tables

    merged = []
    skip   = set()

    for i, tbl in enumerate(tables):
        if i in skip:
            continue

        combined     = dict(tbl)
        combined["rows"] = list(tbl["rows"])
        pages_merged = [tbl["page_ref"] or str(tbl["page"])]

        for j in range(i + 1, len(tables)):
            if j in skip:
                continue
            nxt = tables[j]
            if (nxt["section_id"] == tbl["section_id"]
                    and nxt["rows"] and tbl["rows"]
                    and nxt["rows"][0] == tbl["rows"][0]):
                combined["rows"].extend(nxt["rows"][1:])
                pages_merged.append(nxt["page_ref"] or str(nxt["page"]))
                skip.add(j)
            else:
                break   # only merge consecutive tables in the same section

        if len(pages_merged) > 1:
            notes.append(
                f"table {tbl['table_id']} continued across pages: {', '.join(pages_merged)}"
            )

        merged.append(combined)

    return merged


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
        # Full ordered list of footer labels seen across all pages of this block.
        page_refs = content["page_refs"]

        # ── DTC title ─────────────────────────────────────────────────────────
        dtc_title = _normalize_title(codes, code_titles)

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
        notes   = []
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

        # Merge tables that continue across pages (same section, same header row)
        tables = _merge_continued_tables(tables, notes)

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
            "notes":    notes,

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
