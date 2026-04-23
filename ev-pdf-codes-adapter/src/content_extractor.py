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
    Also saves any images found to output_dir and returns their filenames.
    Returns: {"text": "...", "has_images": True/False, "images": ["EVB-167-img1.png", ...]}
    """
    with fitz.open(str(pdf_path)) as pdf:
        total_pages = len(pdf)

        full_text = ""
        has_images = False
        image_filenames = []   # will hold the names of saved image files
        img_counter = 1        # counts up across ALL pages in this DTC section: img1, img2, img3...
        start_page_ref_footer = None  # footer label on the first page — used to cross-check the index
        end_page_ref          = None  # footer label on the last page
        for page_num in range(start_page, total_pages + 1):
            page = pdf[page_num - 1]

            if page_num > start_page and not page_belongs_to_codes(page, codes):
                break

            # ── Read printed page label from footer ───────────────────────────────
            ref = read_page_ref(page)
            if page_num == start_page:
                start_page_ref_footer = ref   # capture once — will be compared against index ref
            end_page_ref = ref                # updated each iteration — last value = end label

            # ── Extract text ──────────────────────────────────────────────────────
            raw_text = page.get_text("text")
            full_text += clean_text(raw_text) + "\n\n"

            # ── Extract images ────────────────────────────────────────────────────
            # get_images() returns a list of image references on this page.
            # Each item is a tuple; the first element [0] is the xref — the image's unique ID in the PDF.
            page_images = page.get_images(full=True)

            for img_info in page_images:
                xref = img_info[0]  # unique ID of this image inside the PDF

                # Skip if we already saved this xref anywhere in this document
                if xref in seen_xrefs:
                    continue
                seen_xrefs.add(xref)

                # Skip small decorative images (icons, warning signs, logos)
                # Real diagnostic diagrams are always larger than 100x100 pixels
                img_data = pdf.extract_image(xref)
                if img_data["width"] < 100 or img_data["height"] < 100:
                    continue

                img_bytes = img_data["image"]           # raw image bytes
                img_ext = img_data["ext"]               # "png", "jpeg", etc.
                img_hash = hashlib.md5(img_bytes).hexdigest()  # fingerprint of the image content

                img_filename = f"{page_ref_base}-img{img_counter}.{img_ext}"
                img_path = output_dir / img_filename

                if img_hash not in seen_hashes:
                    # New image — save to disk and remember its filename
                    with open(img_path, "wb") as f:
                        f.write(img_bytes)
                    seen_hashes[img_hash] = img_filename  # store hash → filename

                # Always reference the original saved file (even if this is a duplicate)
                image_filenames.append(seen_hashes[img_hash])
                img_counter += 1
                has_images = True

    return {
        "text":                  full_text.strip(),
        "has_images":            has_images,
        "images":                image_filenames,
        "start_page_ref_footer": start_page_ref_footer,  # footer label on first page — for cross-check
        "end_page_ref":          end_page_ref,            # footer label on last page
        "end_pdf_page":          page_num - 1,            # physical PDF page (1-indexed)
    }
