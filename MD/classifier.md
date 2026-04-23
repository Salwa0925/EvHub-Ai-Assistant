# Module Status: `classifier.py` ✅ Complete

## 1. Core Functionality
Reads every batch JSON from `raw/` and transforms raw extracted elements into
tagged, repaired, noise-free data that `chunker.py` can work with reliably.

### Input / Output
- **Reads:** `raw/*.json`
- **Writes:** `classified/*.json` (same filenames, schema version bumped to `1.1`)

---

## 2. Three Jobs in Order

### Job 1 — Filter Noise
Two types of junk are removed before any tagging runs:

**Page-edge tab letters** — Single capital letters (`B, C, D...`) printed on
the right margin of every physical manual page for navigation. Detected by
combining two conditions: the text is a single capital letter AND `bbox[0] > 560`
(far right margin of a ~612pt wide page).

**Inline symbols** — Bullet characters (`•`, `·`, `○` etc.) that appear between
wiring diagram legend items. These are layout artifacts, not content.

---

### Job 2 — Tag and Merge

**Pass 1 — classify every element** into one of five types:

| Type | Detection |
| :--- | :--- |
| `warning_header` | Text starts with `WARNING:`, `CAUTION:`, `DANGER:` |
| `section_header` | Docling label = `section_header`, or contains `NOTE:`, `< `, `PRECAUTION` |
| `procedure_step` | Docling label = `list_item`, or matches numbered/bulleted step pattern |
| `spec_value` | Contains a number followed by a unit (V, A, Nm, rpm, °C, mm...) |
| `general_text` | Everything else |

**Pass 2 — merge split warning pairs:**

Split warnings arrive from the extractor as two separate elements:
```json
{"text": "WARNING:",              "label": "section_header"}
{"text": "Do not touch the HV battery.", "label": "text"}
```
The classifier detects `warning_header` followed by the next element and
collapses them into one:
```json
{
  "text":         "WARNING: Do not touch the HV battery.",
  "type":         "warning",
  "safety_level": "HIGH_VOLTAGE"
}
```

**Safety levels assigned to warnings:**

| Level | Keywords |
| :--- | :--- |
| `HIGH_VOLTAGE` | high voltage, electric shock, 400V, battery pack, insulated gloves... |
| `CAUTION` | hot surface, burn, pressure |
| `WARNING` | danger, death, injury, fire, explosion |
| `NONE` | no safety keywords detected |

---

### Job 3 — Fix Broken Tables

Two table patterns identified in the Nissan Leaf manual are repaired with the
same forward-fill algorithm.

**Detection:**

| table_type | Detection heuristic |
| :--- | :--- |
| `index_table` | First column contains only short values (≤3 chars) — section letter codes |
| `spec_table` | >30% of left column cells are empty — merged cell hierarchy lost |
| `general` | Neither pattern — passed through unchanged |

**Forward-fill algorithm:**
Only applied to columns where >40% of cells are empty (label columns, not
value columns). Fills each empty cell with the last non-empty value above it.

Before:
```
["Camber", "Minimum", "-1° 10'"]
["",       "Nominal", "-0° 25'"]   <- parent lost
["",       "Maximum", "0° 20'"]    <- parent lost
```
After:
```
["Camber", "Minimum", "-1° 10'"]
["Camber", "Nominal", "-0° 25'"]
["Camber", "Maximum", "0° 20'"]
```

`data_raw` preserves the original unrepaired grid for debugging.

---

## 3. Output Schema Changes vs `raw/`

Every text element gains two new fields:
```json
{
  "text":         "WARNING: Do not touch the HV battery.",
  "type":         "warning",
  "safety_level": "HIGH_VOLTAGE",
  ...all existing fields preserved...
}
```

Every table gains three new fields:
```json
{
  "table_type": "spec_table",
  "data":       [...repaired grid...],
  "data_raw":   [...original grid...],
  ...all existing fields preserved...
}
```

---

## 4. Logging per Batch
```
16_20.json  text=84  warnings=3  hv=1  tables=2  fixed=1
```
Shows elements after noise filtering, warning count, high-voltage count,
total tables, and how many tables were repaired.

---
