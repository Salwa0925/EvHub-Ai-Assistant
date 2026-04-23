# Module Status: `extractor.py` ✅ Complete

## 1. Core Functionality
Handles raw ingestion of EV workshop manuals (PDF) using batch processing.
Outputs structured JSON per batch and extracted images to `raw/`.
Docling handles text and tables. pymupdf handles images and page number mapping.

### Output Structure
- **Batch JSON:** `raw/1_5.json`, `raw/6_10.json` etc.
- **Images:** `raw/images/page_<N>_raster_<N>.<ext>` and `raw/images/page_<N>_vector_<N>.png`

---

## 2. JSON Schema

### Text elements
```json
{
  "text":         "WARNING:",
  "page_pdf":     83,
  "page_manual":  "EVC-11",
  "section_code": "EVC",
  "label":        "section_header",
  "bbox":         [72.0, 735.8, 126.0, 726.5]
}
```

### Tables
```json
{
  "page_pdf":     4,
  "page_manual":  "GI-7",
  "section_code": "GI",
  "bbox":         [x0, y0, x1, y1],
  "num_rows":     5,
  "num_cols":     3,
  "data":         [["Header", "Min", "Max"], ["HV bus", "280V", "400V"]],
  "markdown":     "| Header | Min | Max |\n|---|---|---|\n| HV bus | 280V | 400V |",
  "tableformer":  true
}
```

### Images
```json
{
  "file":         "images/page_83_vector_1.png",
  "page_pdf":     83,
  "page_manual":  "EVC-11",
  "section_code": "EVC",
  "bbox":         [x0, y0, x1, y1],
  "caption":      "",
  "type":         "raster" | "vector"
}
```

### Extraction metadata (per batch)
```json
"extraction": {
  "source_file":      "manual.pdf",
  "vehicle":          "2015 Leaf NAM",
  "page_start":       1,
  "page_end":         5,
  "ocr_used":         false,
  "tableformer_used": false,
  "page_map":         {"83": ["EVC-11", "EVC"], "84": ["EVC-12", "EVC"]}
}
```

---

## 3. Pipeline Logic

### Page number mapping — pymupdf (runs first)
Every page footer contains the manual page reference (e.g. `EVC-11`, `GI-7`).
`_read_footer()` clips to the bottom 8% of the page and scans for the pattern
`[A-Z]{1,5}-\d{1,4}` using regex. Returns `(manual_page, section_code)`.

Both values are stamped on every text element, table, and image so the LLM
agent can reference the correct manual page when answering mechanic questions.

If no footer match is found (image-only page or different layout), `null` is
stored and a warning is logged. `classifier.py` can interpolate from
neighbouring pages if needed.

### Images — pymupdf (same pass as footer reading)
Two-step extraction per page:

**Step 1 — Raster images:** `get_images()` pulls embedded bitmaps directly
from the PDF bytes. Saved in original format. Fast and exact.

**Step 2 — Vector graphics:** `get_text("dict")` finds image-type blocks not
captured in step 1. Each region is cropped and rendered to PNG using a clip
rectangle at the configured DPI. Captures wiring diagrams and technical
illustrations that Docling cannot detect.

> This approach was necessary because workshop manuals store diagrams as
> vector graphics. Docling's PictureItem detection returned zero results.
> pymupdf with both steps confirmed working. ✅

### Text & Tables — Docling (two-pass)

**Pass 1 — Fast scan:** TableFormer `OFF`, OCR `OFF`. ~2s per batch.

**Pass 2 — Conditional:**

| Condition | Action |
| :--- | :--- |
| Complex table (≥4 cols) | Re-run with TableFormer `ON`, OCR `OFF` |
| Scanned page (chars < 50) | Re-run with TableFormer `ON`, OCR `ON` |
| Simple tables / text only | Keep Pass 1 result — no Pass 2 |

---

## 4. Known Issues → flagged for `classifier.py`

### WARNING / CAUTION split
Safety warnings arrive as two consecutive elements:
```json
{"text": "WARNING:",                      "label": "section_header"}
{"text": "To prevent electric shock...",  "label": "text"}
```
`classifier.py` must detect this pattern and merge them into one tagged
warning element with an appropriate `safety_level`.

### Index / TOC tables
Section letters (D, E, F...) span multiple rows via merged cells.
TableFormer flattens these — orphaned rows lose their parent section context.
`classifier.py` must re-attach parent labels to orphaned rows.

### Nested spec tables (e.g. Front Wheel Alignment, torque specs)
Three levels of hierarchy with merged left columns. Empty cells appear where
the merge was — parent labels (Camber, Caster, Toe-in) disappear from child
rows. `classifier.py` must forward-fill empty left columns to restore
hierarchy. Critical for accuracy — wrong parent = wrong spec value returned
to mechanic.

---

## 5. Configuration

| Parameter | Default | Effect |
| :--- | :--- | :--- |
| `batch_size` | 5 | Pages per batch. Lower to 3 if RAM is tight |
| `page_render_dpi` | 150 | Crop render quality for vector regions |
| `min_img_size` | 50 | Min px — filters decorative/tiny images |
| `complex_table_cols` | 4 | Min columns to trigger TableFormer |
| `ocr_threshold` | 50 | Chars below this = scanned page, run OCR |
| `footer_height_pct` | 0.08 | Bottom % of page scanned for manual page ref |

---

