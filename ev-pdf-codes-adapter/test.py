"""
test.py - debug first DTC record grouping for EVB manual.

Expected first record:
  codes         : ["P0A0D"]
  title         : something with P0A0D
  start page ref: EVB-73
  pdf page      : 73

Current wrong output:
  codes         : ["P33ED", "U1000", "P0A0D"]
  title         : "P0A0D-U1000"

Goal: trace which step in build_index assigns P33ED and U1000
to the same PDF page as P0A0D.

Run from the repo root:
    cd ev-pdf-codes-adapter
    python test.py
"""

import sys
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import fitz
from index_builder import (
    find_dtc_heading_y,
    find_index_table,
    detect_format,
    extract_codes_with_y,
    match_codes_to_links,
)
from patterns import REF_RE

PDF_PATH = Path(__file__).parent / "manuals" / "2011 Nissan Leaf Workshop Manual for EVB.pdf"

TARGET_CODES = {"P0A0D", "P33ED", "U1000"}


def sep(label=""):
    print(f"\n{'-' * 60}")
    if label:
        print(f"  {label}")
        print(f"{'-' * 60}")


# ── Step 1: run build_index and inspect raw index output ─────────────────────

sep("STEP 1 - raw index from build_index()")

from index_builder import build_index
index = build_index(PDF_PATH)

sep("Index entries for target codes")
for code in sorted(TARGET_CODES):
    info = index.get(code)
    if info:
        print(f"  {code}: pages={info['pages']}  page_refs={info['page_refs']}  title={info['title']!r}")
    else:
        print(f"  {code}: NOT FOUND in index")

# ── Step 2: show page_to_codes grouping ──────────────────────────────────────

sep("STEP 2 - page_to_codes grouping (codes that share a PDF page)")

page_to_codes: dict[int, list] = {}
for code, info in index.items():
    for page_num in info["pages"]:
        page_to_codes.setdefault(page_num, []).append(code)

# Find which pages contain any of our target codes
target_pages = {
    page_num
    for code in TARGET_CODES
    for info in [index.get(code)]
    if info
    for page_num in info["pages"]
}

print(f"\n  Pages that contain at least one target code: {sorted(target_pages)}")
for pg in sorted(target_pages):
    codes_on_page = page_to_codes[pg]
    flag = "  *** MIXED ***" if len(set(codes_on_page) & TARGET_CODES) > 1 else ""
    print(f"  PDF page {pg:4d}: {codes_on_page}{flag}")

# ── Step 3: re-run index scanning with verbose per-link tracing ──────────────

sep("STEP 3 - verbose re-scan: trace each link->code->page assignment")

with fitz.open(str(PDF_PATH)) as pdf:
    seen_pages: set[int] = set()

    for page_num in range(len(pdf)):
        page = pdf[page_num]

        if "dtc index" not in page.get_text("text").lower():
            continue

        heading_y = find_dtc_heading_y(page)
        if heading_y is None:
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
            continue

        if table_page_num in seen_pages:
            continue

        rows = table.extract()
        if not rows:
            continue

        fmt = detect_format(rows[0])
        print(f"\n  Index table found - starts on PDF page {table_page_num + 1}, format={fmt!r}")

        # Walk each index page
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

            # Collect links
            links = []
            for lnk in current_page.get_links():
                if lnk["kind"] != 4:
                    continue
                raw = current_page.get_text("text", clip=lnk["from"]).strip()
                m = REF_RE.search(raw)
                lnk["ref_text"] = m.group(0) if m else None
                links.append(lnk)

            codes_with_y = extract_codes_with_y(current_page, fmt)
            page_results = match_codes_to_links(codes_with_y, links)

            # Print only rows that involve target codes or land on a target page
            interesting_pages = {info["page"] for info in page_results.values() if info["page"] in target_pages}
            interesting_codes = {c for c in page_results if c in TARGET_CODES}

            if interesting_codes or interesting_pages:
                print(f"\n  [Index PDF page {current_num + 1}]")
                for code, info in page_results.items():
                    if code in TARGET_CODES or info["page"] in target_pages:
                        print(f"    code={code:8s}  -> target pdf_page={info['page']:4d}  "
                              f"page_ref={info.get('page_ref')!r:12}  title={info.get('title','')!r}")

                # Also print raw link list for full traceability
                print(f"    [raw links on this index page]")
                for lnk in links:
                    dest_page = lnk.get("page", -1) + 1
                    if dest_page in target_pages:
                        rect = lnk["from"]
                        link_text = current_page.get_text("text", clip=rect).strip()
                        print(f"      link text={link_text!r:20}  ref={lnk.get('ref_text')!r:12}  -> dest pdf_page={dest_page}")

            seen_pages.add(current_num)
            current_num += 1

        break  # only process the first index section found

# ── Step 4: what does the final first record look like? ──────────────────────

sep("STEP 4 - first record in page_to_codes (sorted by pdf page)")

first_page = sorted(page_to_codes.keys())[0]
first_codes = page_to_codes[first_page]
print(f"\n  First record: pdf_page={first_page}  codes={first_codes}")
for code in first_codes:
    info = index.get(code, {})
    print(f"    {code}: pages={info.get('pages')}  page_refs={info.get('page_refs')}")

print()
