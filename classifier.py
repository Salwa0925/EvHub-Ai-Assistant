"""
classifier.py — element tagging and table repair
Input:  raw/*.json
Output: classified/*.json

Four jobs:
  1. Filter noise (page-edge tabs, symbols, INFOID codes, breadcrumbs, variant tags)
  2. Merge split WARNING/CAUTION elements and tag every text element
  3. Fix broken tables (forward-fill empty left columns)
"""

from __future__ import annotations
import json, logging, re
from pathlib import Path

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S", level=logging.INFO)
log = logging.getLogger("classifier")

# ── Patterns ──────────────────────────────────────────────────────────────────

_SAFETY_TRIGGERS = {
    "HIGH_VOLTAGE": {
        "high voltage", "high-voltage", "hv ", "electric shock",
        "electrocution", "400v", "300v", "lithium", "battery pack",
        "do not touch", "insulated gloves",
    },
    "CAUTION": {"caution", "hot surface", "burn", "pressure"},
    "WARNING": {"warning", "danger", "death", "injury", "fire", "explosion"},
}

_STEP_RE      = re.compile(r"^\s*(\d+\.|[a-z]\)|\-|\•)\s+", re.IGNORECASE)
_SPEC_RE      = re.compile(r"\d+\s*(v|a|nm|rpm|°c|°f|kpa|psi|mm|in|kg|lb)\b", re.IGNORECASE)
_WARNING_KEYS = {"warning:", "caution:", "danger:"}
_HEADER_KEYS  = {"note:", "important:", "precaution"}

# Noise: single capital nav tabs on right margin
_TAB_LETTERS  = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
# Noise: inline wiring symbols
_TINY_SYMBOLS = {"•", "·", "○", "●", "◆", "■", "□", "–", "—"}
# Noise: INFOID reference codes e.g. INFOID:0000000010640902
_INFOID_RE    = re.compile(r"^INFOID:\d+$")
# Noise: variant tags e.g. [WITH HEAT PUMP SYSTEM], [WITHOUT HEAT PUMP SYSTEM]
_VARIANT_RE   = re.compile(r"^\[.{5,60}\]$")
# Noise: breadcrumb tags e.g. < REMOVAL AND INSTALLATION >, < PRECAUTION >
_BREADCRUMB_RE = re.compile(r"^<\s*.+\s*>$")


# ── Noise filters ─────────────────────────────────────────────────────────────

def _is_tab_letter(el: dict) -> bool:
    text = el["text"].strip()
    if text not in _TAB_LETTERS:
        return False
    bbox = el.get("bbox")
    return bbox is not None and bbox[0] > 560


def _is_noise(el: dict) -> bool:
    """Return True if this element should be discarded entirely."""
    text = el["text"].strip()
    if not text:
        return True
    if text in _TINY_SYMBOLS:
        return True
    if _INFOID_RE.match(text):
        return True
    if _VARIANT_RE.match(text):
        return True
    if _BREADCRUMB_RE.match(text):
        return True
    if _is_tab_letter(el):
        return True
    return False


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safety_level(text: str) -> str:
    low = text.lower()
    for level, keywords in _SAFETY_TRIGGERS.items():
        if any(k in low for k in keywords):
            return level
    return "NONE"


def _classify_text(el: dict) -> dict:
    text  = el["text"].strip()
    label = el.get("label", "")
    low   = text.lower()

    if any(low.startswith(k) for k in _WARNING_KEYS):
        t = "warning_header"
    elif any(k in low for k in _HEADER_KEYS) or label == "section_header":
        t = "section_header"
    elif _STEP_RE.match(text) or label == "list_item":
        t = "procedure_step"
    elif _SPEC_RE.search(text):
        t = "spec_value"
    else:
        t = "general_text"

    return {**el, "type": t, "safety_level": _safety_level(text)}


# ── Job 2: classify and merge warnings ───────────────────────────────────────

def _process_texts(elements: list[dict]) -> list[dict]:
    """
    Pass 1 — classify every element.
    Pass 2 — merge warning_header + next element ONLY if next is not a
             procedure_step. Fixes inline step warnings (EVB-200 pattern)
             where a WARNING sits between numbered steps — merging would
             incorrectly absorb the step into the warning body.
    """
    classified = [_classify_text(el) for el in elements]

    merged = []
    i = 0
    while i < len(classified):
        el = classified[i]
        if el["type"] == "warning_header" and i + 1 < len(classified):
            nxt = classified[i + 1]
            # Only merge if the next element is NOT a procedure step
            if nxt["type"] != "procedure_step":
                combined = f"{el['text'].strip()} {nxt['text'].strip()}"
                merged.append({
                    **el,
                    "text":         combined,
                    "type":         "warning",
                    "safety_level": _safety_level(combined),
                })
                i += 2
                continue
            else:
                # Keep the warning_header as a standalone warning
                merged.append({
                    **el,
                    "type":         "warning",
                    "safety_level": _safety_level(el["text"]),
                })
                i += 1
        else:
            merged.append(el)
            i += 1

    return merged


# ── Job 3: fix broken tables ──────────────────────────────────────────────────

def _forward_fill(grid: list[list[str]]) -> list[list[str]]:
    if not grid:
        return grid
    filled  = [row[:] for row in grid]
    n_cols  = len(filled[0])
    for col in range(n_cols - 1):
        empty_count = sum(1 for row in filled if not row[col].strip())
        if empty_count / len(filled) > 0.4:
            last_val = ""
            for row in filled:
                if row[col].strip():
                    last_val = row[col]
                else:
                    row[col] = last_val
    return filled


def _process_tables(tables: list[dict]) -> list[dict]:
    result = []
    for table in tables:
        grid = table.get("data", [])
        if not grid:
            result.append({**table, "table_type": "empty"})
            continue

        first_col = [row[0].strip() for row in grid if row]
        is_index  = all(len(v) <= 3 or v == "" for v in first_col)

        n_empty = sum(1 for row in grid for cell in row[:2] if not cell.strip())
        n_total = len(grid) * min(2, len(grid[0]))
        is_spec = n_total > 0 and (n_empty / n_total) > 0.3

        if is_index or is_spec:
            table_type = "index_table" if is_index else "spec_table"
            fixed_grid = _forward_fill(grid)
        else:
            table_type = "general"
            fixed_grid = grid

        result.append({
            **table,
            "table_type": table_type,
            "data":       fixed_grid,
            "data_raw":   grid,
            "markdown":   table.get("markdown", ""),
        })
    return result


# ── Main ──────────────────────────────────────────────────────────────────────

def classify_batch(raw_path: Path, out_dir: Path) -> bool:
    try:
        raw = json.loads(raw_path.read_text(encoding="utf-8"))

        # Job 1: filter all noise in one pass
        elements = [
            el for el in raw.get("text_elements", [])
            if not _is_noise(el)
        ]

        classified = {
            **raw,
            "schema_version": "1.1",
            "text_elements":  _process_texts(elements),
            "tables":         _process_tables(raw.get("tables", [])),
            "images":         raw.get("images", []),
        }

        (out_dir / raw_path.name).write_text(
            json.dumps(classified, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        texts = classified["text_elements"]
        warns = sum(1 for t in texts if t["type"] == "warning")
        hv    = sum(1 for t in texts if t["safety_level"] == "HIGH_VOLTAGE")
        fixed = sum(1 for t in classified["tables"]
                    if t.get("table_type") in ("spec_table", "index_table"))

        log.info("%s  text=%d  warnings=%d  hv=%d  tables=%d  fixed=%d",
                 raw_path.name, len(texts), warns, hv, len(classified["tables"]), fixed)
        return True

    except Exception:
        log.exception("Failed: %s", raw_path.name)
        return False


def run(raw_dir: str | Path = "raw", output_dir: str | Path = "classified") -> bool:
    raw_dir = Path(raw_dir)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    batches = sorted(raw_dir.glob("*.json"))
    if not batches:
        log.error("No JSON files found in %s", raw_dir)
        return False

    pending = [f for f in batches if not (out_dir / f.name).exists()]
    if len(pending) < len(batches):
        log.info("Resuming - skipping %d already classified", len(batches) - len(pending))

    log.info("Classifying %d batches", len(pending))
    return all(classify_batch(f, out_dir) for f in pending)


if __name__ == "__main__":
    run(raw_dir="raw", output_dir="classified")