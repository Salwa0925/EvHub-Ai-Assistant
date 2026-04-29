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


# Tuning constants for row/block-aware link matching
_ROW_Y_TOL  = 4    # pt — codes within this Y band are treated as one visual row
_LINK_Y_TOL = 20   # pt — a link's midY must be within this of a row's Y to match
_BLOCK_GAP  = 40   # pt — Y gap larger than this between rows starts a new block


def match_codes_to_links(codes_with_y: list, links: list) -> dict:
    """
    Match each DTC code row to its page-ref hyperlink using row/block-aware matching.

    The old implementation used an unconditional nearest-link search, which caused
    codes on different rows to incorrectly share a single link when only one link
    happened to be present on the index page.

    Algorithm
    ---------
    1. Sort codes by Y and group into rows (_ROW_Y_TOL): codes within 4 pt of each
       other in Y share the same visual row.  DTC ranges (P3031-P303C) that land on
       the same row naturally share one link this way.
    2. Group consecutive rows into blocks (_BLOCK_GAP): a Y gap larger than 40 pt
       between two adjacent rows signals a section break or heading, starting a new
       block.  Links from one block are never used to match codes in another block.
    3. For each block, collect candidate links whose midY falls within the block's
       Y span (padded by _LINK_Y_TOL).
    4. For each row, pick the nearest candidate link whose midY is within
       _LINK_Y_TOL of the row's Y.  If none qualifies, skip the row and emit a
       warning — better to drop the code than to assign a wrong page.
    5. All codes in the same row receive the same match result.

    Returns: { code: {"page": int, "title": str, "page_ref": str|None}, ... }
    """
    if not links or not codes_with_y:
        return {}

    def link_midy(lnk: dict) -> float:
        r = lnk["from"]
        return (r.y0 + r.y1) / 2

    # ── Step 1: group codes into rows ─────────────────────────────────────────
    rows: list[dict] = []
    for code, y, title in sorted(codes_with_y, key=lambda x: x[1]):
        if rows and abs(y - rows[-1]["y"]) <= _ROW_Y_TOL:
            rows[-1]["items"].append((code, y, title))
        else:
            rows.append({"y": y, "items": [(code, y, title)]})

    # ── Step 2: group rows into blocks ────────────────────────────────────────
    blocks: list[list[dict]] = [[rows[0]]]
    for row in rows[1:]:
        if row["y"] - blocks[-1][-1]["y"] > _BLOCK_GAP:
            blocks.append([])
        blocks[-1].append(row)

    # ── Steps 3-4: match rows to links ────────────────────────────────────────
    results: dict = {}

    for block in blocks:
        b_top    = block[0]["y"]  - _LINK_Y_TOL
        b_bottom = block[-1]["y"] + _LINK_Y_TOL
        block_links = [lnk for lnk in links
                       if b_top <= link_midy(lnk) <= b_bottom]

        for row in block:
            ry     = row["y"]
            nearby = [lnk for lnk in block_links
                      if abs(link_midy(lnk) - ry) <= _LINK_Y_TOL]

            if not nearby:
                codes_str = ", ".join(c[0] for c in row["items"])
                print(f"  [WARN index-match] no link for [{codes_str}] at Y={ry:.1f} "
                      f"(block Y {block[0]['y']:.0f}-{block[-1]['y']:.0f}, "
                      f"{len(block_links)} block links)")
                continue

            best        = min(nearby, key=lambda lnk: abs(link_midy(lnk) - ry))
            target_page = best["page"] + 1
            ref_text    = best.get("ref_text")

            for code, _y, title in row["items"]:
                results[code] = {
                    "page":     target_page,
                    "title":    title,
                    "page_ref": ref_text,
                }

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