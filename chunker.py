"""
chunker.py — semantic chunking
Reads:  classified/*.json  (all batches processed as one continuous stream)
Writes: chunks.json

One chunk = one complete procedure unit.
chunk_type values:
  precaution  — safety briefing pages, no numbered steps
  procedure   — numbered steps with optional warnings
  description — system description, component parts, no steps
  spec        — service data and specifications tables only
"""

from __future__ import annotations
import json, logging, re
from pathlib import Path

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S", level=logging.INFO)
log = logging.getLogger("chunker")

_PREREQ_RE    = re.compile(r"\b(before|prior to|ensure|verify|confirm|check that|must be)\b", re.IGNORECASE)
_SAFETY_ORDER = {"HIGH_VOLTAGE": 3, "WARNING": 2, "CAUTION": 1, "NONE": 0}
_VARIANT_RE   = re.compile(r"(\d{4}\s+leaf\s*\w*)", re.IGNORECASE)  # "2015 LEAF", "2015 Leaf NAM"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _highest_safety(elements: list[dict]) -> str:
    best = "NONE"
    for el in elements:
        level = el.get("safety_level") or "NONE"
        if _SAFETY_ORDER.get(level, 0) > _SAFETY_ORDER.get(best, 0):
            best = level
    return best


def _detect_chunk_type(elements: list[dict]) -> str:
    """
    Determine what kind of chunk this is based on its content.

    precaution  — only warnings, no procedure steps
    procedure   — has at least one numbered procedure step
    spec        — only tables, minimal text (service data pages)
    description — everything else (system descriptions, component parts)
    """
    types = [el.get("type") for el in elements]
    has_steps    = "procedure_step" in types
    has_warnings = "warning" in types or "warning_header" in types
    has_text     = any(t in ("general_text", "spec_value") for t in types)

    if has_steps:
        return "procedure"
    if has_warnings and not has_steps and not has_text:
        return "precaution"
    return "description"


def _extract_prerequisites(elements: list[dict]) -> list[str]:
    """
    Two sources of prerequisites:
    1. Warning elements that appear BEFORE the first procedure_step —
       these are the DANGER/WARNING blocks Nissan puts at the top of
       every removal procedure (e.g. "Be sure to remove service plug...")
    2. Any element in the first 5 whose text contains prerequisite language
       (before/ensure/verify/confirm...)
    """
    prereqs = []
    first_step_idx = next(
        (i for i, el in enumerate(elements) if el.get("type") == "procedure_step"),
        len(elements)
    )

    # Warnings before first step are always prerequisites
    for el in elements[:first_step_idx]:
        if el.get("type") == "warning" and el["text"].strip() not in prereqs:
            prereqs.append(el["text"].strip())

    # Prerequisite language in first 5 elements
    for el in elements[:5]:
        text = el.get("text", "")
        if _PREREQ_RE.search(text) and text.strip() not in prereqs:
            prereqs.append(text.strip())

    return prereqs


def _extract_variant(page_map: dict) -> str | None:
    """
    Extract vehicle variant from page_map footer text.
    e.g. "2015 LEAF", "2015 Leaf NAM"
    """
    for val in page_map.values():
        if isinstance(val, list):
            for v in val:
                if v and _VARIANT_RE.search(str(v)):
                    return str(v).strip()
    return None


def _chunk_id(section_code: str | None, page_pdf: int | None, index: int) -> str:
    return f"{section_code or 'UNK'}_pdf{page_pdf or 0}_chunk{index}"


# ── Load all batches as one ordered stream ────────────────────────────────────

def _load_all(classified_dir: Path) -> tuple[list[dict], list[dict], list[dict], str | None]:
    files = sorted(
        classified_dir.glob("*.json"),
        key=lambda p: int(p.stem.split("_")[0])
    )
    if not files:
        log.error("No classified JSON files found in %s", classified_dir)
        return [], [], [], None

    texts, tables, images = [], [], []
    variant = None

    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        texts.extend(data.get("text_elements", []))
        tables.extend(data.get("tables", []))
        images.extend(data.get("images", []))
        if not variant:
            pm = data.get("extraction", {}).get("page_map", {})
            variant = _extract_variant(pm)

    log.info("Loaded %d elements  %d tables  %d images  from %d batches  variant=%s",
             len(texts), len(tables), len(images), len(files), variant)
    return texts, tables, images, variant


def _page_lookup(items: list[dict]) -> dict[int, list[dict]]:
    lookup: dict[int, list[dict]] = {}
    for item in items:
        pg = item.get("page_pdf")
        if pg is not None:
            lookup.setdefault(pg, []).append(item)
    return lookup


# ── Core chunker ──────────────────────────────────────────────────────────────

def _build_chunks(
    texts:        list[dict],
    table_lookup: dict[int, list[dict]],
    image_lookup: dict[int, list[dict]],
    variant:      str | None,
) -> list[dict]:
    chunks:        list[dict] = []
    idx:           int        = 0
    current_els:   list[dict] = []
    current_pages: set[int]   = set()

    heading      = "PREAMBLE"
    section_code = None
    page_pdf     = None
    page_manual  = None

    def _flush():
        nonlocal idx
        if not current_els and not current_pages:
            return

        chunk_tables = [t for pg in sorted(current_pages) for t in table_lookup.get(pg, [])]
        chunk_images = [i for pg in sorted(current_pages) for i in image_lookup.get(pg, [])]
        chunk_type   = _detect_chunk_type(current_els)

        chunks.append({
            "chunk_id":      _chunk_id(section_code, page_pdf, idx),
            "chunk_type":    chunk_type,
            "page_pdf":      page_pdf,
            "page_manual":   page_manual,
            "section_code":  section_code,
            "vehicle":       variant,
            "heading":       heading,
            "safety_level":  _highest_safety(current_els),
            "prerequisites": _extract_prerequisites(current_els),
            "text_blocks":   current_els[:],
            "tables":        chunk_tables,
            "images":        chunk_images,
        })

        idx += 1
        current_els.clear()
        current_pages.clear()

    for el in texts:
        pg = el.get("page_pdf")
        if el.get("type") == "section_header":
            _flush()
            heading      = el.get("text", "").strip()
            section_code = el.get("section_code")
            page_pdf     = pg
            page_manual  = el.get("page_manual")

        current_els.append(el)
        if pg is not None:
            current_pages.add(pg)

    _flush()
    return chunks


# ── Entry point ───────────────────────────────────────────────────────────────

def run(
    classified_dir: str | Path = "classified",
    output_file:    str | Path = "chunks.json",
) -> bool:
    classified_dir = Path(classified_dir)
    output_file    = Path(output_file)

    texts, tables, images, variant = _load_all(classified_dir)
    if not texts:
        return False

    chunks = _build_chunks(texts, _page_lookup(tables), _page_lookup(images), variant)

    hv         = sum(1 for c in chunks if c["safety_level"] == "HIGH_VOLTAGE")
    w_tables   = sum(1 for c in chunks if c["tables"])
    w_images   = sum(1 for c in chunks if c["images"])
    w_prereq   = sum(1 for c in chunks if c["prerequisites"])
    procedures = sum(1 for c in chunks if c["chunk_type"] == "procedure")
    precautions = sum(1 for c in chunks if c["chunk_type"] == "precaution")

    log.info(
        "chunks=%d  procedures=%d  precautions=%d  hv=%d  "
        "with_tables=%d  with_images=%d  with_prereqs=%d",
        len(chunks), procedures, precautions, hv, w_tables, w_images, w_prereq,
    )

    output_file.write_text(
        json.dumps({
            "schema_version": "1.0",
            "vehicle":        variant,
            "total_chunks":   len(chunks),
            "stats": {
                "high_voltage_chunks": hv,
                "procedure_chunks":    procedures,
                "precaution_chunks":   precautions,
                "chunks_with_tables":  w_tables,
                "chunks_with_images":  w_images,
                "chunks_with_prereqs": w_prereq,
            },
            "chunks": chunks,
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    log.info("Written -> %s", output_file)
    return True


if __name__ == "__main__":
    run(classified_dir="classified", output_file="chunks.json")