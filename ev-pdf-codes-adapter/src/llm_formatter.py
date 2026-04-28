"""
llm_formatter.py
================
Post-ETL transform: schema v4 → lean LLM-friendly representation.

Converts each DTC record into a clean, token-efficient structure by:
  - Dropping raw_text (29 % of tokens — fully duplicated in sections + tables)
  - Dropping raw_rows when semantic_parse is ok/partial (9 % of tokens)
  - Stripping noise from section text (page labels, revision lines, year-model)
  - Truncating dtc_logic section text before the table echo
  - Flattening DTC logic into a simple {detecting_condition, possible_causes, codes[]}
  - Slimming images to {image_id, path, page_ref}

No LLM/AI calls — deterministic transforms only.
Original v4 record is never modified.

Usage (standalone):
    py src/llm_formatter.py data/EVB/EVB.json
    → writes data/EVB/EVB_llm.json

Usage (as module):
    from llm_formatter import format_document
    llm_doc = format_document(v4_doc)
"""

import re
import json
import sys
from pathlib import Path

# ── Noise-line patterns ────────────────────────────────────────────────────────

# Printed page labels: EVB-88, TM-44, EVC-109 — appear as standalone lines
_PAGE_LABEL_RE = re.compile(r'^\s*[A-Z]{2,4}-\d+\s*$')

# Revision lines: "Revision: October 2013"
_REVISION_RE = re.compile(r'^\s*Revision:', re.IGNORECASE)

# Year-model lines at end of pages: "2013 LEAF", "2011 LEAF"
# Pattern: 4-digit year, space, then all-caps word(s) only — short line
_YEAR_MODEL_RE = re.compile(r'^\s*\d{4}\s+[A-Z][A-Z\s]+$')

# INFOID internal reference numbers — should be stripped by content_extractor
# already, but kept here as a defence-in-depth fallback
_INFOID_RE = re.compile(r'\bINFOID:\d+\b')

# Lines that mark the start of the DTC table echo inside dtc_logic section text.
# When fitz dumps the table as flat text below the procedure steps, the first
# table column header appears as a standalone line.  Everything from that line
# onward is already captured in semantic_parse — no value repeating it here.
_DTC_ECHO_HEADERS = frozenset({
    'dtc',
    'trouble diagnosis name',
    'dtc detecting condition',
    'possible causes',
    'possible cause',
})


# ── Text cleaning helpers ──────────────────────────────────────────────────────

def _clean_text(text: str) -> str:
    """
    Strip noise lines and inline INFOID references from section text.

    Noise removed:
      - standalone page-label lines  (EVB-88, TM-44)
      - Revision: lines
      - year-model suffix lines       (2013 LEAF)
      - INFOID:xxxxxxxx strings
    Blank-line runs of 3+ are collapsed to 2.
    """
    if not text:
        return ""
    text = _INFOID_RE.sub("", text)
    lines = text.splitlines()
    cleaned = []
    for line in lines:
        if _PAGE_LABEL_RE.match(line):
            continue
        if _REVISION_RE.match(line):
            continue
        if _YEAR_MODEL_RE.match(line):
            continue
        cleaned.append(line)
    result = re.sub(r'\n{3,}', '\n\n', '\n'.join(cleaned))
    return result.strip()


def _truncate_at_table_echo(text: str) -> str:
    """
    For dtc_logic section text only: cut off the table echo.

    When fitz extracts a page it concatenates the table header text below the
    procedure steps, producing a flat dump of the column names and cell values.
    That content is already captured — structured — in semantic_parse.  Strip
    it by finding the first line that exactly matches a known column-header name.

    If no such line is found, returns text unchanged.
    """
    if not text:
        return ""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip().lower() in _DTC_ECHO_HEADERS:
            return '\n'.join(lines[:i]).rstrip()
    return text


# ── Section / table builders ───────────────────────────────────────────────────

def _build_dtc_logic(sections: list, tables: list) -> dict | None:
    """
    Build a flat dtc_logic block from section text + semantic_parse.

    Output keys (all optional — only present when data exists):
      confirmation_procedure  — cleaned DTC confirmation procedure steps
      detecting_condition     — shared fault-detection description
      possible_causes         — shared causes string
      codes                   — list of {code, name} per DTC in this record
    """
    # ── Confirmation procedure text ──
    proc_text = None
    for s in sections:
        if s.get('role') == 'dtc_logic':
            raw = s.get('text') or ''
            cleaned = _clean_text(raw)
            truncated = _truncate_at_table_echo(cleaned)
            if truncated:
                proc_text = truncated
            break  # only one dtc_logic section expected

    # ── Structured DTC data from the best available table ──
    sp = None
    for t in tables:
        if t.get('role') == 'dtc_logic':
            candidate = t.get('semantic_parse', {})
            if candidate.get('status') in ('ok', 'partial'):
                sp = candidate
                break

    if proc_text is None and sp is None:
        return None

    result: dict = {}

    if proc_text:
        result['confirmation_procedure'] = proc_text

    if sp:
        table_type = sp.get('table_type')

        if table_type == 'shared_fields':
            shared = sp.get('shared', {})

            # detecting_condition — try both slugified key variants
            dc = (shared.get('dtc_detecting_condition')
                  or shared.get('detecting_condition'))
            if dc:
                result['detecting_condition'] = dc['value']

            # possible_causes — try both singular and plural
            pc = (shared.get('possible_causes')
                  or shared.get('possible_cause'))
            if pc:
                result['possible_causes'] = pc['value']

            # per-code names
            # For multi-code records: trouble_diagnosis_name lives in individual[].
            # For single-code records: it lands in shared (confidence 1.0).
            # Fall back to shared value so the name is never blank.
            shared_name = (shared.get('trouble_diagnosis_name', {}) or {}).get('value', '')
            individual = sp.get('individual', [])
            if individual:
                result['codes'] = [
                    {
                        'code': row.get('dtc', ''),
                        'name': row.get('trouble_diagnosis_name') or shared_name,
                    }
                    for row in individual
                ]

        elif table_type == 'flat':
            # Unusual for dtc_logic — include rows as-is
            rows = sp.get('rows')
            if rows:
                result['table'] = rows

    return result or None


def _build_diagnosis_procedure(sections: list, tables: list) -> dict | None:
    """
    Build a clean diagnosis_procedure block.

    text   — section text with noise stripped (page labels, revision lines)
    tables — one entry per diagnosis table:
               {table_id, page_ref, table_type, ...semantic fields...}
             raw_rows are excluded (they duplicate semantic_parse)
    """
    proc_text = None
    for s in sections:
        if s.get('role') == 'diagnosis_procedure':
            raw = s.get('text') or ''
            cleaned = _clean_text(raw)
            if cleaned:
                proc_text = cleaned
            break  # only one diagnosis_procedure section expected

    proc_tables = []
    for t in tables:
        if t.get('role') != 'diagnosis_procedure':
            continue
        sp = t.get('semantic_parse', {})
        if sp.get('status') not in ('ok', 'partial'):
            continue

        # Include all semantic_parse fields except 'status' (ETL metadata,
        # not useful for reasoning) and flatten together with table location.
        entry: dict = {
            'table_id':   t['table_id'],
            'page_ref':   t.get('page_ref'),
            'table_type': sp.get('table_type'),
        }
        for key, val in sp.items():
            if key not in ('status', 'table_type'):
                entry[key] = val
        proc_tables.append(entry)

    if proc_text is None and not proc_tables:
        return None

    result: dict = {}
    if proc_text:
        result['text'] = proc_text
    if proc_tables:
        result['tables'] = proc_tables
    return result


# ── Public API ─────────────────────────────────────────────────────────────────

def format_record(record: dict, vehicle: dict | None = None) -> dict:
    """
    Convert one schema v4 DTC record into a lean LLM-friendly dict.

    Parameters
    ----------
    record  : one element from ``v4_doc['records']``
    vehicle : document-level ``vehicle`` block (optional — adds context)

    Returns
    -------
    New dict.  The original record is not modified.
    """
    sections = record.get('sections', [])
    tables   = record.get('tables', [])
    images   = record.get('images', [])

    out: dict = {
        'schema_version': '4-llm',
        'record_id':      record['record_id'],
        'codes':          record['codes'],
        'title':          record.get('title'),
        'page_refs':      record.get('location', {}).get('page_refs', []),
    }

    # Vehicle context from the document level — helps the LLM stay oriented
    if vehicle:
        v = {k: vehicle[k] for k in ('year', 'make', 'model', 'variant')
             if vehicle.get(k)}
        if v:
            out['vehicle'] = v

    dtc_block = _build_dtc_logic(sections, tables)
    if dtc_block:
        out['dtc_logic'] = dtc_block

    diag_block = _build_diagnosis_procedure(sections, tables)
    if diag_block:
        out['diagnosis_procedure'] = diag_block

    # Slim image records — keep only what a RAG/LLM consumer needs
    if images:
        out['images'] = [
            {
                'image_id': img['image_id'],
                'path':     img['image_path'],
                'page_ref': img.get('page_ref'),
            }
            for img in images
        ]

    return out


def format_document(doc: dict) -> dict:
    """
    Convert a complete schema v4 JSON document into LLM-friendly format.

    Returns a new dict — original is not modified.
    Both the document wrapper and every record are transformed.
    """
    vehicle = doc.get('vehicle')
    records = [format_record(r, vehicle=vehicle) for r in doc.get('records', [])]

    return {
        'schema_version': '4-llm',
        'document_id':    doc['document_id'],
        'source_file':    doc.get('source_file'),
        'vehicle':        vehicle,
        'records':        records,
    }


# ── CLI entry point ────────────────────────────────────────────────────────────

def _cli():
    """
    Standalone usage:
        py src/llm_formatter.py data/EVB/EVB.json
        → writes data/EVB/EVB_llm.json
    """
    if len(sys.argv) < 2:
        print("Usage: py src/llm_formatter.py <path/to/file.json>")
        sys.exit(1)

    in_path = Path(sys.argv[1])
    if not in_path.exists():
        print(f"File not found: {in_path}")
        sys.exit(1)

    with open(in_path, encoding='utf-8') as f:
        doc = json.load(f)

    if doc.get('schema_version') != 4:
        print(f"Warning: expected schema_version 4, got {doc.get('schema_version')}")

    llm_doc = format_document(doc)

    out_path = in_path.with_stem(in_path.stem + '_llm')
    tmp_path = out_path.with_suffix('.json.tmp')

    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(llm_doc, f, indent=2, ensure_ascii=False)
    tmp_path.replace(out_path)

    # ── Size report ──
    in_size  = in_path.stat().st_size
    out_size = out_path.stat().st_size
    saved    = in_size - out_size
    pct      = saved / in_size * 100

    print(f"Written: {out_path}")
    print(f"  v4  : {in_size:,} bytes  (~{in_size // 4:,} tokens)")
    print(f"  llm : {out_size:,} bytes  (~{out_size // 4:,} tokens)")
    print(f"  saved: {saved:,} bytes  ({pct:.1f} %)")


if __name__ == '__main__':
    _cli()
