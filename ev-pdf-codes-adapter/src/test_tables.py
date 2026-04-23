import fitz
import json
from content_extractor import extract_tables_from_rect, _find_heading_y

from pathlib import Path
MANUALS = Path(__file__).parent.parent / "manuals"
pdf = fitz.open(str(MANUALS / "2011 Nissan Leaf Workshop Manual for EVB.pdf"))

# Check pages 73 and 74 (index 72 and 73)
for page_idx in [72, 73]:
    page = pdf[page_idx]
    print(f"\n=== Page {page_idx + 1} ===")
    print("  dtc_logic y:          ", _find_heading_y(page, "dtc logic"))
    print("  diagnosis procedure y:", _find_heading_y(page, "diagnosis procedure"))
    print("  First lines of each block:")
    for block in page.get_text("blocks"):
        first_line = block[4].strip().split("\n")[0].strip()
        if first_line:
            print(f"    y={block[1]:.1f}  {repr(first_line[:60])}")
