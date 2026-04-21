import re
import fitz
from pathlib import Path
from patterns import INFOID_RE, SIDEBAR_RE


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
    with fitz.open(str(pdf_path)) as pdf:
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

    return {
        "text": full_text.strip(),
        "has_images": has_images,
        "images": image_filenames,   # ← NEW: list of saved image filenames
    }