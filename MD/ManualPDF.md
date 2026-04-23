# EV Workshop Manual AI Pipeline
## Living Project Document — First Workplan

> **Last updated:** April 2026  
> **Status:** Phase 1 complete (extraction → classification → chunking)  
> **Test file:** 2011 Nissan Leaf Workshop Manual (iFixit, 121 pages)  
> **Real data:** Hard drive of EV workshop manuals — not yet received

---

## 1. What We Are Building

A pipeline that converts EV workshop manual PDFs into a structured JSON
knowledge base. The JSON is consumed by an LLM agent that helps car mechanics
troubleshoot and repair electric vehicles.

**How the agent works:**
A mechanic enters make, model, year, and an error code or symptom. The agent
asks checkup questions to narrow down the problem, then delivers the exact
procedure, torque specs, voltage ranges, and safety warnings from the manual.

**Why accuracy is critical:**
These are high-voltage vehicles (300–400V systems). A wrong procedure or a
missing safety warning is a direct safety risk to the mechanic.

---

## 2. Architecture Overview

```
PDF
 │
 ├─ extractor.py ──────────────────────────────────────── raw/
 │   pymupdf:  images (raster + vector), footer page refs   ├─ 1_5.json
 │   Docling:  text elements, tables                        ├─ 6_10.json
 │                                                          ├─ images/
 │                                                          └─ ...
 ├─ classifier.py ─────────────────────────────────── classified/
 │   Filter noise, tag elements, merge warnings,            ├─ 1_5.json
 │   repair broken table hierarchies                        ├─ 6_10.json
 │                                                          └─ ...
 ├─ chunker.py ──────────────────────────────────── chunks.json
 │   Merge all batches into one stream,
 │   split into semantic procedure chunks
 │
 ├─ assembler.py ────────────────────────────────── final.json  ⬜ TODO
 │   Validate, cross-reference, produce
 │   final JSON for LLM agent team
 │
 └─ Vision AI ───────────────────────── image descriptions     ⬜ TODO
     Read PNG + bbox per image,
     generate text description for agent retrieval
```

---

## 3. Module Status

| Module | Status | Input | Output |
| :--- | :--- | :--- | :--- |
| `extractor.py` | ✅ Complete | PDF | `raw/*.json` + `raw/images/` |
| `classifier.py` | ✅ Complete | `raw/*.json` | `classified/*.json` |
| `chunker.py` | ✅ Complete | `classified/*.json` | `chunks.json` |
| `assembler.py` | ⬜ Not started | `chunks.json` | `final.json` |
| Vision AI | ⬜ Not started | `images/*.png` + bbox | descriptions in `final.json` |

---

## 4. Module Summaries

### 4.1 `extractor.py`
Reads the PDF in configurable page batches. Uses pymupdf and Docling together —
each tool does what it is best at.

**pymupdf** (runs first, per page):
- Reads footer for manual page reference (e.g. EVC-11, GI-7)
- Extracts raster images via `get_images()`
- Extracts vector diagrams via `get_text("dict")` + `get_pixmap(clip=bbox)`

**Docling** (two-pass, per batch):
- Pass 1: always — fast text + layout, TableFormer OFF, OCR OFF
- Pass 2: conditional — TableFormer ON if 4+ column table detected
- Pass 2: conditional — OCR ON if page has < 50 characters (scanned page)
- Three converters built once at startup, reused across all batches

**Output per element:**
```json
{
  "text":         "WARNING: Do not touch HV terminals.",
  "page_pdf":     83,
  "page_manual":  "EVC-11",
  "section_code": "EVC",
  "label":        "section_header",
  "bbox":         [72.0, 735.8, 126.0, 726.5]
}
```

---

### 4.2 `classifier.py`
Three sequential jobs — noise filter → tag/merge → table repair.

**Job 1 — Noise filter:**
Removes page-edge tab letters (B, C, D... in right margin) and inline
bullet symbols (•, ·) that are layout artifacts not content.

**Job 2 — Tag and merge:**
Tags each element with `type` (warning / section_header / procedure_step /
spec_value / general_text) and `safety_level` (HIGH_VOLTAGE / WARNING /
CAUTION / NONE). Merges split WARNING: + body pairs into single elements.

**Job 3 — Table repair:**
Forward-fills empty left columns in nested spec tables and TOC index tables
to restore hierarchy lost from PDF merged cells. Keeps original in `data_raw`.

---

### 4.3 `chunker.py`
Loads all classified batch files sorted by page number and merges into one
continuous stream — procedures that cross batch boundaries stay intact.

Splits into chunks at every `section_header`. Each chunk contains:
- All text, tables, and images belonging to that procedure
- `safety_level` = highest level found among any element
- `prerequisites` = sentences with before/ensure/verify (for agent checkup questions)

**Output chunk:**
```json
{
  "chunk_id":      "EVC_pdf83_chunk2",
  "page_pdf":      83,
  "page_manual":   "EVC-11",
  "section_code":  "EVC",
  "heading":       "HV BATTERY REMOVAL",
  "safety_level":  "HIGH_VOLTAGE",
  "prerequisites": ["Disconnect 12V battery before starting"],
  "text_blocks":   [...],
  "tables":        [...],
  "images":        [...]
}
```

---

### 4.4 `assembler.py` ⬜ TODO
Reads `chunks.json` and produces the final JSON the LLM agent team uses.

Planned jobs:
- Build full manual index (section_code → page range mapping)
- Detect cross-references between chunks ("see also EVC-15")
- Validation pass — flag HIGH_VOLTAGE chunks missing prerequisites
- Add `source_manual` metadata (make, model, year) per chunk
- Output format agreed with LLM agent team

---

### 4.5 Vision AI ⬜ TODO
Every image in `chunks.json` has a file path and bbox but no description.
The agent cannot reason about diagram content without this step.

Planned approach:
- Read each `images[].file` PNG path from chunks
- Send to vision model (model TBD — GPT-4o / Claude / Gemini)
- Store returned description back into the image entry:
```json
{
  "file":        "images/page_83_vector_1.png",
  "page_manual": "EVC-11",
  "bbox":        [...],
  "description": "Wiring diagram showing HV battery connector J4.
                  Positive terminal red, negative black. Three pins."
}
```

---

## 5. Known Issues and Resolutions

| Issue | Root Cause | Status |
| :--- | :--- | :--- |
| 33 sec/page speed | TableFormer on every page | ✅ Fixed — selective Pass 2 |
| Zero images from Docling | Manual uses vector graphics | ✅ Fixed — pymupdf two-step |
| PDF page ≠ manual page | Different numbering systems | ✅ Fixed — footer regex scan |
| Procedures split across batches | File-by-file processing | ✅ Fixed — single stream in chunker |
| WARNING separated from body | Docling splits on punctuation | ✅ Fixed — classifier merge |
| Nested table hierarchy lost | TableFormer flattens merged cells | ✅ Fixed — forward-fill |
| RAM issues on long runs | Converters rebuilt per batch | ✅ Fixed — build once, reuse |
| Page-edge tab letters in output | Docling captures nav tabs | ✅ Fixed — bbox position filter |

---

## 6. Open Questions

**For the pipeline team:**
- [ ] What is the minimum chunk size? A chunk with only a heading and one line
      will be too small for meaningful retrieval
- [ ] Should warnings always be their own chunk, or stay attached to the
      procedure they belong to?
- [ ] How should the assembler handle duplicate content — some procedures
      appear in multiple sections of the manual

**For the LLM agent team:**
- [ ] What exact JSON format does the agent expect? (field names, nesting)
- [ ] Does the agent need the full `text_blocks` array or just concatenated text?
- [ ] How should image descriptions be formatted for embedding?
- [ ] What metadata does the agent use for keyword search?
      (section_code, safety_level, page_manual, heading?)

**For both teams:**
- [ ] Which vision model for image descriptions?
- [ ] How do we handle manuals where the footer layout is different?
- [ ] What is the plan for keeping the knowledge base updated when new
      manual revisions are released?

---

## 7. Configuration Reference

### `extractor.py`
| Parameter | Default | Notes |
| :--- | :--- | :--- |
| `batch_size` | 5 | Lower to 3 if RAM is tight |
| `page_render_dpi` | 150 | PNG quality for vector crops |
| `min_img_size` | 50 | Filters tiny decorative images (px) |
| `complex_table_cols` | 4 | Columns threshold for TableFormer |
| `ocr_threshold` | 50 | Chars below this = scanned page |
| `footer_height_pct` | 0.08 | Bottom % scanned for page ref |

### `classifier.py`
| Parameter | Default | Notes |
| :--- | :--- | :--- |
| `_TAB_LETTERS` | A-Z | Page-edge nav tab filter |
| `_TINY_SYMBOLS` | •·○●... | Inline symbol filter |
| `bbox[0] > 560` | hardcoded | Right margin threshold |

---

## 8. How to Run

```bash
# Step 1 — Extract
python extractor.py

# Step 2 — Classify
python classifier.py

# Step 3 — Chunk
python chunker.py

# Each step is resumable — already processed files are skipped automatically
# If a step crashes, just re-run it
```

---

## 9. For the LLM Agent Team

Your input is `chunks.json`. Each chunk is one complete procedure unit with:

- `chunk_id` — unique identifier for retrieval
- `page_manual` — the manual page reference a mechanic would cite
- `section_code` — system category (EVC = Electric Vehicle Control, GI = General Info, HA = HVAC, BR = Brakes...)
- `heading` — the procedure title
- `safety_level` — HIGH_VOLTAGE / WARNING / CAUTION / NONE
- `prerequisites` — conditions to check before starting (use for checkup questions)
- `text_blocks` — all text elements with their `type` tags
- `tables` — structured data with repaired hierarchy
- `images` — file path + bbox per diagram (descriptions added by Vision AI step)

**Recommended retrieval strategy:**
Keyword search on `section_code`, `heading`, `page_manual` for fast initial
filtering. Semantic similarity on `text_blocks` content for ranking. Always
surface `safety_level` and `prerequisites` to the mechanic before procedure steps.