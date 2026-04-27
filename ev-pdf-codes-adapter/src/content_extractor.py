import re
import hashlib
import fitz
from pathlib import Path
from patterns import INFOID_RE, SIDEBAR_RE
from text_parser import KNOWN_HEADINGS

# Matches printed page labels like EVB-88, EVC-109, TM-44, TMS-12
# Pattern: 2–4 uppercase letters, dash, one or more digits
_PAGE_REF_RE = re.compile(r'\b([A-Z]{2,4}-\d+)\b')


def read_page_ref(page: fitz.Page) -> str | None:
    """
    Extract the printed page label from the page footer (e.g. 'EVB-88').
    Clips the bottom 10% of the page where the footer label lives.
    Returns None if no label is found.
    """
    rect = page.rect
    footer_rect = fitz.Rect(0, rect.height * 0.88, rect.width, rect.height)
    footer_text = page.get_text("text", clip=footer_rect)
    match = _PAGE_REF_RE.search(footer_text)
    return match.group(1) if match else None


def clean_text(raw: str) -> str:
    """Remove sidebar letters and internal reference IDs."""
    text = INFOID_RE.sub("", raw)
    text = SIDEBAR_RE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def page_belongs_to_codes(page: fitz.Page, codes: list) -> bool:
    """
    Check if a page header contains any of the given codes.
    We only check the first 300 characters — the header area.
    """
    top_text = page.get_text("text")[:300].upper()
    return any(code.upper() in top_text for code in codes)


def _find_heading_y(page: fitz.Page, heading: str) -> float | None:
    """
    Find the bottom y-coordinate of a heading line on a page.
    Searches every line in every block (case-insensitive exact match).
    Returns None if not found.
    """
    heading_lower = heading.lower()
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:   # text blocks only
            continue
        for line in block.get("lines", []):
            line_text = " ".join(
                span["text"] for span in line.get("spans", [])
            ).strip().lower()
            if line_text == heading_lower:
                return line["bbox"][3]  # y1 — bottom edge of this line
    return None


def extract_tables_from_rect(page: fitz.Page, rect: fitz.Rect) -> list:
    """
    Extract tables whose bounding box overlaps rect by at least 50%.

    Returns list of tables.
    Each table  = list of rows.
    Each row    = list of strings (None → "", whitespace stripped).
    Tables with fewer than 2 rows or 2 columns are skipped (likely noise).
    """
    if rect is None or rect.is_empty:
        return []

    finder = page.find_tables()
    result = []

    for table in finder.tables:
        tbbox      = fitz.Rect(table.bbox)
        overlap    = rect & tbbox
        if overlap.is_empty:
            continue

        table_area = tbbox.width * tbbox.height
        if table_area == 0:
            continue

        overlap_ratio = (overlap.width * overlap.height) / table_area
        if overlap_ratio < 0.5:
            continue

        rows = table.extract()

        # Skip noise: must have at least 2 rows and 2 columns
        if not rows or len(rows) < 2:
            continue
        if not rows[0] or len(rows[0]) < 2:
            continue

        # Normalise cells: None → "", strip whitespace
        clean_rows = [
            [str(cell).strip() if cell is not None else "" for cell in row]
            for row in rows
        ]
        result.append(clean_rows)

    return result


def _clean_zone_text(page: fitz.Page, rect: fitz.Rect) -> str:
    """Extract and clean text from a specific zone rect on a page."""
    raw = page.get_text("text", clip=rect)
    return clean_text(raw)


def _finalize_section(section: dict) -> dict:
    """
    Convert the internal section builder into the final section dict.
    Joins text collected across multiple pages into one string.
    """
    return {
        "heading":    section["heading"],
        "role":       section["role"],
        # join text collected from multiple pages — None if nothing was collected
        "text":       "\n\n".join(section["text_parts"]).strip() or None,
        "tables":     section["tables"],   # list of {page, page_ref, rows}
        "page_start": section["page_start"],
        "page_end":   section["page_end"],
    }


def extract_content(
    pdf_path: Path,
    start_page: int,
    codes: list,
    output_dir: Path,      # folder where image files will be saved
    page_ref_base: str,    # e.g. "EVB-167" — used as the image filename prefix
    seen_xrefs: set,       # shared across all sections — prevents saving same xref twice
    seen_hashes: dict,     # hash → filename — points duplicates to the already-saved file
) -> dict:
    """
    Extract content starting from start_page, continuing while
    the page header still belongs to our codes.

    Returns:
        raw_text                 — full unprocessed text across all pages
        sections                 — list of section dicts with text, tables, page range
        has_images               — True if any images were saved
        image_list               — list of image metadata dicts (filename, pdf_page, page_ref)
        start_page_ref_footer    — footer label on first page (cross-check)
        end_page_ref             — footer label on last page
        end_pdf_page             — physical PDF page of last page (1-indexed)
    """
    with fitz.open(str(pdf_path)) as pdf:
        total_pages = len(pdf)

        raw_text_parts        = []   # one raw string per page — joined at end
        has_images            = False
        image_list            = []   # image metadata, IDs assigned later in extractor.py
        img_counter           = 1
        start_page_ref_footer = None
        end_page_ref          = None
        last_processed        = start_page

        # ── Section tracking ──────────────────────────────────────────────────
        # active_section holds the section currently being built.
        # When a new heading is found, we close active_section and open a new one.
        active_section = None
        all_sections   = []

        for page_num in range(start_page, total_pages + 1):
            page = pdf[page_num - 1]

            if page_num > start_page and not page_belongs_to_codes(page, codes):
                break

            last_processed = page_num

            # ── Footer page label ─────────────────────────────────────────────
            ref = read_page_ref(page)
            if page_num == start_page:
                start_page_ref_footer = ref
            end_page_ref = ref

            pw = page.rect.width
            ph = page.rect.height

            # ── Raw text (unprocessed) ────────────────────────────────────────
            raw_text_parts.append(page.get_text("text"))

            # ── Images ────────────────────────────────────────────────────────
            for img_info in page.get_images(full=True):
                xref = img_info[0]
                if xref in seen_xrefs:
                    continue
                seen_xrefs.add(xref)

                img_data = pdf.extract_image(xref)
                if img_data["width"] < 100 or img_data["height"] < 100:
                    continue

                img_bytes    = img_data["image"]
                img_ext      = img_data["ext"]
                img_hash     = hashlib.md5(img_bytes).hexdigest()
                img_filename = f"{page_ref_base}-img{img_counter}.{img_ext}"
                img_path     = output_dir / img_filename

                if img_hash not in seen_hashes:
                    with open(img_path, "wb") as f:
                        f.write(img_bytes)
                    seen_hashes[img_hash] = img_filename

                # Store metadata — image_id is assigned later in extractor.py
                image_list.append({
                    "filename": seen_hashes[img_hash],
                    "pdf_page": page_num,
                    "page_ref": ref,
                })
                img_counter += 1
                has_images = True

            # ── Section detection ─────────────────────────────────────────────
            # Find all known headings on this page and sort them top-to-bottom by y.
            breaks = []   # (y_bottom_of_heading, display_name, role)
            for display_name, role in KNOWN_HEADINGS:
                y = _find_heading_y(page, display_name)
                if y is not None:
                    breaks.append((y, display_name, role))
            breaks.sort(key=lambda x: x[0])

            if not breaks:
                # No headings on this page — entire page continues active section
                if active_section is not None:
                    text = _clean_zone_text(page, fitz.Rect(0, 0, pw, ph))
                    if text:
                        active_section["text_parts"].append(text)
                    for rows in extract_tables_from_rect(page, fitz.Rect(0, 0, pw, ph)):
                        active_section["tables"].append({"page": page_num, "page_ref": ref, "rows": rows})
                    active_section["page_end"] = page_num

            else:
                # ── Content before the first heading ─────────────────────────
                # Belongs to the active section (it's a continuation from a previous page).
                first_y = breaks[0][0]
                if first_y > 0 and active_section is not None:
                    pre_rect = fitz.Rect(0, 0, pw, first_y)
                    pre_text = _clean_zone_text(page, pre_rect)
                    if pre_text:
                        active_section["text_parts"].append(pre_text)
                    for rows in extract_tables_from_rect(page, pre_rect):
                        active_section["tables"].append({"page": page_num, "page_ref": ref, "rows": rows})
                    active_section["page_end"] = page_num

                # ── Process each heading zone ─────────────────────────────────
                for i, (y, display_name, role) in enumerate(breaks):
                    # Close the section that was active before this heading
                    if active_section is not None:
                        all_sections.append(_finalize_section(active_section))

                    # Zone runs from this heading's y to the next heading's y (or page bottom)
                    y_end     = breaks[i + 1][0] if i + 1 < len(breaks) else ph
                    zone_rect = fitz.Rect(0, y, pw, y_end)

                    zone_text   = _clean_zone_text(page, zone_rect)
                    zone_tables = [
                        {"page": page_num, "page_ref": ref, "rows": rows}
                        for rows in extract_tables_from_rect(page, zone_rect)
                    ]

                    # Open new section
                    active_section = {
                        "heading":    display_name,
                        "role":       role,
                        "text_parts": [zone_text] if zone_text else [],
                        "tables":     zone_tables,
                        "page_start": page_num,
                        "page_end":   page_num,
                    }

        # Close the last open section after the page loop ends
        if active_section is not None:
            all_sections.append(_finalize_section(active_section))

    return {
        "raw_text":               "\n\n".join(raw_text_parts).strip(),
        "sections":               all_sections,
        "has_images":             has_images,
        "image_list":             image_list,
        "start_page_ref_footer":  start_page_ref_footer,
        "end_page_ref":           end_page_ref,
        "end_pdf_page":           last_processed,
    }
