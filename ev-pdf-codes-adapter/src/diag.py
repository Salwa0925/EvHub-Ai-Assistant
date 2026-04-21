import fitz

path = "manuals/2011 Nissan Leaf Workshop Manual.pdf"
doc = fitz.open(path)

print(f"Total pages: {len(doc)}")
print("Scanning all pages for DTC Index sections...")
print()

for i in range(len(doc)):
    page = doc[i]

    # quick filter — must have "DTC Index" text on this page
    if "dtc index" not in page.get_text("text").lower():
        continue

    # get all text blocks on the page
    blocks = page.get_text("blocks")  # each block: (x0, y0, x1, y1, text, ...)
    dtc_index_y = None

    for block in blocks:
        block_text = block[4].strip()
        # first line must be exactly "DTC Index" AND block must have INFOID
        if block_text.split("\n")[0].strip().lower() == "dtc index" and "infoid:" in block_text.lower():
            dtc_index_y = block[3]  # y1 = bottom edge of the heading block
            break

    # no standalone "DTC Index" heading found on this page — skip
    if dtc_index_y is None:
        continue

    # find tables below the heading
    tables = page.find_tables()
    for table in tables.tables:
        rows = table.extract()
        if not rows:
            continue

        # only accept tables that start below the "DTC Index" heading
        if table.bbox[1] < dtc_index_y:
            continue

        if len(rows) - 1 > 2:
            header = " | ".join(str(c).strip() if c else "" for c in rows[0])
            print(f"Page {i + 1}: {header}  ({len(rows) - 1} data rows)")

            # check for internal hyperlinks on this page (kind == 4)
            links = page.get_links()
            internal_links = [l for l in links if l["kind"] == 4]
            print(f"  Internal links: {len(internal_links)}")
