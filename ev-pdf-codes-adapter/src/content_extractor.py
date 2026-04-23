import re
import hashlib
import fitz
from pathlib import Path
from patterns import INFOID_RE, SIDEBAR_RE

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
    Uses overlap ratio to assign tables to the correct zone when they
    straddle a boundary.

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
        overlap    = rect & tbbox          # intersection rect
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
    Saves images to output_dir and extracts tables per zone.

    Returns:
        text                     — full merged text across all pages
        has_images               — True if any images were saved
        images                   — list of saved image filenames
        start_page_ref_footer    — footer label on first page (cross-check)
        end_page_ref             — footer label on last page
        end_pdf_page             — physical PDF page of last page (1-indexed)
        dtc_logic_tables         — tables found in the DTC Logic zone
        diagnosis_procedure_tables — tables found in the Diagnosis Procedure zone
    """
    with fitz.open(str(pdf_path)) as pdf:
        total_pages = len(pdf)

        full_text             = ""
        has_images            = False
        image_filenames       = []
        img_counter           = 1
        start_page_ref_footer = None
        end_page_ref          = None

        # ── Table extraction state ────────────────────────────────────────────
        in_dtc_logic            = False   # currently inside DTC Logic zone
        in_diagnosis            = False   # currently inside Diagnosis Procedure zone
        dtc_logic_tables        = []
        diagnosis_procedure_tables = []

        for page_num in range(start_page, total_pages + 1):
            page = pdf[page_num - 1]

            if page_num > start_page and not page_belongs_to_codes(page, codes):
                break

            # ── Footer page label ─────────────────────────────────────────────
            ref = read_page_ref(page)
            if page_num == start_page:
                start_page_ref_footer = ref
            end_page_ref = ref

            # ── Text ──────────────────────────────────────────────────────────
            raw_text   = page.get_text("text")
            full_text += clean_text(raw_text) + "\n\n"

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

                image_filenames.append(seen_hashes[img_hash])
                img_counter += 1
                has_images = True

            # ── Tables per zone ───────────────────────────────────────────────
            pw = page.rect.width
            ph = page.rect.height

            dtc_logic_y = _find_heading_y(page, "dtc logic")
            diagnosis_y = _find_heading_y(page, "diagnosis procedure")

            # Zone 1 — DTC Logic
            if dtc_logic_y is not None:
                # Heading found on this page — enter dtc_logic zone
                in_dtc_logic = True
                in_diagnosis = False
                bottom = diagnosis_y if diagnosis_y is not None else ph
                dtc_logic_tables.extend(
                    extract_tables_from_rect(page, fitz.Rect(0, dtc_logic_y, pw, bottom))
                )
            elif in_dtc_logic:
                # Continuation page in dtc_logic zone
                bottom = diagnosis_y if diagnosis_y is not None else ph
                dtc_logic_tables.extend(
                    extract_tables_from_rect(page, fitz.Rect(0, 0, pw, bottom))
                )

            # Zone 2 — Diagnosis Procedure
            if diagnosis_y is not None:
                # Heading found on this page — enter diagnosis zone
                in_diagnosis = True
                in_dtc_logic = False
                diagnosis_procedure_tables.extend(
                    extract_tables_from_rect(page, fitz.Rect(0, diagnosis_y, pw, ph))
                )
            elif in_diagnosis:
                # Continuation page in diagnosis zone
                diagnosis_procedure_tables.extend(
                    extract_tables_from_rect(page, fitz.Rect(0, 0, pw, ph))
                )

    return {
        "text":                        full_text.strip(),
        "has_images":                  has_images,
        "images":                      image_filenames,
        "start_page_ref_footer":       start_page_ref_footer,
        "end_page_ref":                end_page_ref,
        "end_pdf_page":                page_num - 1,
        "dtc_logic_tables":            dtc_logic_tables,
        "diagnosis_procedure_tables":  diagnosis_procedure_tables,
    }
