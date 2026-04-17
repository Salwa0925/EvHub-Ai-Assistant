"""
extractor.py
============
Extraction logic for one manual PDF.
Called by pipeline.py.
"""

import re
import fitz
from pathlib import Path

# Matches DTC codes like P0A0D, B1234, C3456, U0100
CODE_RE = re.compile(r"^[PBCU][0-9A-F]{4}$", re.IGNORECASE)

# Matches EVB-123 style references
REF_RE = re.compile(r"[A-Z]{2,10}-(\d+)", re.IGNORECASE)

# Single letters on their own line — PDF sidebar nav tabs
SIDEBAR_RE = re.compile(r"^\s*[A-Z]{1,3}\s*$", re.MULTILINE)

# Internal Nissan reference IDs
INFOID_RE = re.compile(r"INFOID:\d+")


def build_index(pdf_path: Path) -> dict:
    """
    Scan first 60 pages for DTC index table.
    Returns: {"P0A0D": 88, "P33EB": 167, ...}
    """
    pdf = fitz.open(str(pdf_path))
    max_page = min(60, len(pdf))
    results = {}

    index_found = False
    dtc_col = None
    ref_col = None
    last_page_ref = None

    print(f"Step 1 — scanning pages 1-{max_page} for index ...")

    for page_num in range(1, max_page + 1):
        page = pdf[page_num - 1]
        tables = page.find_tables()

        for table in tables:
            rows = table.extract()
            if not rows:
                continue

            if not index_found:
                header = " ".join(str(c).lower() for c in rows[0] if c)
                if "dtc" not in header or "reference" not in header:
                    continue

                for i, cell in enumerate(rows[0]):
                    cell_text = str(cell).lower().strip() if cell else ""
                    if cell_text == "dtc":
                        dtc_col = i
                    if "reference" in cell_text:
                        ref_col = i

                if dtc_col is None or ref_col is None:
                    continue

                print(f"  Found index on page {page_num}")
                index_found = True
                data_rows = rows[1:]
            else:
                has_any_code = any(
                    CODE_RE.match(str(row[dtc_col]).strip())
                    for row in rows if row and len(row) > dtc_col
                )
                if not has_any_code:
                    pdf.close()
                    print(f"  Found {len(results)} codes")
                    return results
                data_rows = rows

            for row in data_rows:
                if not row or len(row) <= max(dtc_col, ref_col):
                    continue

                dtc_cell = str(row[dtc_col]).strip() if row[dtc_col] else ""
                ref_cell = str(row[ref_col]).strip() if row[ref_col] else ""

                m = REF_RE.search(ref_cell)
                if m:
                    last_page_ref = int(m.group(1))

                if not CODE_RE.match(dtc_cell):
                    continue

                if last_page_ref is not None:
                    results[dtc_cell.upper()] = last_page_ref

    pdf.close()
    print(f"  Found {len(results)} codes")
    return results


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


def extract_content(
    pdf_path: Path,
    start_page: int,
    codes: list,
    output_dir: Path,      # ← NEW: folder where image files will be saved
    page_ref_base: str,    # ← NEW: e.g. "EVB-167" — used as the image filename prefix
) -> dict:
    """
    Extract content starting from start_page, continuing while
    the page header still belongs to our codes.
    Also saves any images found to output_dir and returns their filenames.
    Returns: {"text": "...", "has_images": True/False, "images": ["EVB-167-img1.png", ...]}
    """
    pdf = fitz.open(str(pdf_path))
    total_pages = len(pdf)

    full_text = ""
    has_images = False
    image_filenames = []   # will hold the names of saved image files
    img_counter = 1        # counts up across ALL pages in this DTC section: img1, img2, img3...
    seen_xrefs = set()     # tracks which images we already saved (avoids saving the same image twice)

    for page_num in range(start_page, total_pages + 1):
        page = pdf[page_num - 1]

        if page_num > start_page and not page_belongs_to_codes(page, codes):
            break

        # ── Extract text ──────────────────────────────────────────────────────
        raw_text = page.get_text("text")
        full_text += clean_text(raw_text) + "\n\n"

        # ── Extract images ────────────────────────────────────────────────────
        # get_images() returns a list of image references on this page.
        # Each item is a tuple; the first element [0] is the xref — the image's unique ID in the PDF.
        page_images = page.get_images(full=True)

        for img_info in page_images:
            xref = img_info[0]  # unique ID of this image inside the PDF

            # Skip if we already saved this image (same image can appear on multiple pages)
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)

            # Pull the raw image bytes out of the PDF
            img_data = pdf.extract_image(xref)
            img_bytes = img_data["image"]   # the actual binary content of the image
            img_ext = img_data["ext"]       # file extension: "png", "jpeg", etc.

            # Build filename: EVB-167-img1.png, EVB-167-img2.png, ...
            img_filename = f"{page_ref_base}-img{img_counter}.{img_ext}"

            # Full path on disk where we will save the file
            img_path = output_dir / img_filename

            # Write the binary bytes to disk
            with open(img_path, "wb") as f:  # "wb" = write binary
                f.write(img_bytes)

            image_filenames.append(img_filename)  # remember the name for the JSON
            img_counter += 1
            has_images = True

    pdf.close()

    return {
        "text": full_text.strip(),
        "has_images": has_images,
        "images": image_filenames,   # ← NEW: list of saved image filenames
    }


def extract_records(pdf_path: Path, output_dir: Path) -> list:
    """
    Main function called by pipeline.py.
    Returns a list of records, one per DTC code.
    output_dir is where image files will be saved.
    """
    source = pdf_path.name

    # Step 1 — build index
    index = build_index(pdf_path)

    if not index:
        print("No codes found.")
        return []

    # Step 2 — group codes by page number
    page_to_codes: dict[int, list] = {}
    for code, page_num in index.items():
        page_to_codes.setdefault(page_num, []).append(code)

    print(f"\nStep 2 — extracting content for {len(index)} codes ...")

    records = []

    for page_num, codes in sorted(page_to_codes.items()):
        print(f"  Page {page_num} → {codes}")

        # Build the page_ref_base used for image filenames: "EVB-167"
        page_ref_base = f"{pdf_path.stem}-{page_num}"

        # Pass output_dir and page_ref_base to extract_content
        content = extract_content(pdf_path, page_num, codes, output_dir, page_ref_base)

        for code in codes:
            records.append({
                "dtc": code,
                "source": source,
                "page": page_num,
                "page_ref": f"{pdf_path.stem}-{page_num}",
                "content": content
            })

    return records
