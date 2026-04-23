import json
from pathlib import Path
from collections import Counter

# ── Load the JSON file ────────────────────────────────────────────────────────
# Point this at whichever JSON output you want to analyse
json_path = Path("data/2011 Nissan Leaf Workshop Manual for EVB/2011 Nissan Leaf Workshop Manual for EVB.json")

with open(json_path, encoding="utf-8") as f:
    doc = json.load(f)

pages = doc["pages"]
print(f"Total pages: {len(pages)}")
print()

# ── Count how many pages each line appears on ─────────────────────────────────
# We use a Counter — it counts occurrences of each unique value
line_counts = Counter()

for record in pages:
    # Combine both text blocks for noise analysis
    text = " ".join(filter(None, [
        record.get("dtc_logic_block", ""),
        record.get("diagnosis_procedure_block", ""),
    ]))

    # Split text into individual lines, strip whitespace, skip empty lines
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    # Use a set — we only want to count each line ONCE per page
    # (not 5 times if it appears 5 times on the same page)
    unique_lines = set(lines)

    for line in unique_lines:
        line_counts[line] += 1   # this line appeared on one more page

# ── Print lines that appear on more than 50% of pages ────────────────────────
threshold = len(pages) * 0.5   # 50% of total pages

print(f"Lines appearing on more than 50% of pages ({threshold:.0f}+ pages):")
print()

for line, count in line_counts.most_common():
    if count < threshold:
        break   # most_common() is sorted — once we go below threshold, stop

    pct = (count / len(pages)) * 100
    print(f"  {count:4d} pages ({pct:.0f}%)  |  {line}")