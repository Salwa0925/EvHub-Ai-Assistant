import re
import fitz
from pathlib import Path
from patterns import CODE_RE
from patterns import REF_RE


def find_dtc_heading_y(page) -> float:
    """
    Look for a standalone 'DTC Index' heading on a page.
    Returns the bottom y-coordinate of the heading block, or None if not found.
    The heading block always has 'DTC Index' as first line AND contains 'INFOID:'
    """
    blocks = page.get_text("blocks")

    for block in blocks:
        block_text = block[4].strip()
        first_line = block_text.split("\n")[0].strip().lower()

        if first_line == "dtc index" and "infoid:" in block_text.lower():
            return block[3]

    return None


def find_index_table(page, heading_y: float):
    """
    Find the first table that starts below the DTC Index heading.
    """
    tables = page.find_tables()

    for table in tables.tables:
        if table.bbox[1] >= heading_y:
            return table

    return None


def detect_format(header_row: list) -> str:
    """
    Detect which table format this index uses.
    Format A: has a dedicated 'DTC' column
    Format B: no DTC column — codes are embedded in brackets like [U1000]
    """
    for cell in header_row:
        if cell and "dtc" in str(cell).lower():
            return "A"

    return "B"


def extract_codes_with_y(page, fmt: str) -> list:
    """
    Extract DTC codes, their y-positions, and titles from a page.
    Title = all words on the same y-level as the code, to the right of it.
    Returns a list of (code, y, title) tuples.
    """
    words = page.get_text("words")  # each word: (x0, y0, x1, y1, text, ...)
    results = []

    for i, word in enumerate(words):
        word_text = word[4]
        y_pos = word[1]   # y0 = top edge of this word

        if fmt == "A":
            clean = re.sub(r"[^A-Z0-9]", "", word_text.upper())
            if CODE_RE.match(clean):
                # collect all words on the same y-level (within 3px) that come after this word
                # those words form the title — e.g. "HV SYSTEM INTERLOCK ERROR"
                title_words = []
                for w in words:
                    if abs(w[1] - y_pos) >= 3:      # different y-level — skip
                        continue
                    if w[0] <= word[2]:             # to the left of or at the code — skip
                        continue
                    cell = w[4].strip()
                    # stop at × (warning flag), pure digits (trip count), page refs, or another code
                    if re.match(r"^[×—x]$", cell, re.IGNORECASE):
                        break
                    if re.match(r"^\d+$", cell):
                        break
                    if REF_RE.match(cell):
                        break
                    if CODE_RE.match(re.sub(r"[^A-Z0-9]", "", cell.upper())):
                        break
                    title_words.append(cell)

                title = " ".join(title_words).strip()
                results.append((clean, y_pos, title))

        else:
            m = re.match(r"\[([PBCU][0-9A-F]{4})\]", word_text, re.IGNORECASE)
            if m:
                results.append((m.group(1).upper(), y_pos, ""))   # Format B has no title column

    return results


def match_codes_to_links(codes_with_y: list, links: list) -> dict:
    """
    Match each DTC code to its nearest internal link by y-distance.
    Returns: { "U1000": {"page": 181, "title": "HV SYSTEM INTERLOCK ERROR"}, ... }
    """
    results = {}

    if not links:
        return results

    for code, code_y, title in codes_with_y:
        nearest = min(links, key=lambda l: abs(l["from"].y0 - code_y))
        target_page = nearest["page"] + 1
        results[code] = {"page": target_page, "title": title, "page_ref": nearest.get("ref_text")}

    return results



def build_index(pdf_path: Path) -> dict:
    """
    Scan all pages for DTC index tables.
    Returns: { "U1000": [181], "C1101": [1560, 1595], ... }
    One code can map to multiple pages.
    """
    with fitz.open(str(pdf_path)) as pdf:
        results = {}
        seen_pages = set()

        print(f"Step 1 — scanning {len(pdf)} pages for DTC index...")

        page_num = 0
        while page_num < len(pdf):
            page = pdf[page_num]

            if "dtc index" not in page.get_text("text").lower():
                page_num += 1
                continue

            heading_y = find_dtc_heading_y(page)
            if heading_y is None:
                page_num += 1
                continue

            table = find_index_table(page, heading_y)
            table_page_num = page_num

            if table is None and page_num + 1 < len(pdf):
                next_page = pdf[page_num + 1]
                tables = next_page.find_tables()
                if tables.tables:
                    table = tables.tables[0]
                    table_page_num = page_num + 1

            if table is None:
                page_num += 1
                continue

            if table_page_num in seen_pages:
                page_num += 1
                continue

            print(f"  Found index on page {table_page_num + 1}")

            rows = table.extract()
            if not rows:
                page_num += 1
                continue

            fmt = detect_format(rows[0])

            current_num = table_page_num
            while current_num < len(pdf):
                if current_num in seen_pages:
                    break

                current_page = pdf[current_num]

                if current_num > table_page_num:
                    if find_dtc_heading_y(current_page) is not None:
                        break

                    codes_check = extract_codes_with_y(current_page, fmt)
                    if not codes_check:
                        break

                # For each internal link, extract the visible text (e.g. "EVB-94") from its bounding box.
                # That text IS the printed page ref — same source, no word-scanning needed.
                links = []
                for l in current_page.get_links():
                    if l["kind"] != 4:
                        continue
                    raw = current_page.get_text("text", clip=l["from"]).strip()
                    m = REF_RE.search(raw)
                    l["ref_text"] = m.group(0) if m else None
                    links.append(l)
                codes_with_y = extract_codes_with_y(current_page, fmt)
                page_results = match_codes_to_links(codes_with_y, links)

                for code, info in page_results.items():
                    if code not in results:
                        results[code] = {"pages": [], "page_refs": [], "title": info["title"]}
                    results[code]["pages"].append(info["page"])
                    results[code]["page_refs"].append(info["page_ref"])  # parallel to pages, may be None


                seen_pages.add(current_num)
                current_num += 1

            page_num += 1

        print(f"  Found {len(results)} codes")
        return results