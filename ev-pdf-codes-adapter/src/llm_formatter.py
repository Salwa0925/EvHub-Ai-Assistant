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

# Bare vehicle-name lines: "LEAF" printed alone at the top/bottom of a page.
# Exact match only — does not touch DTC titles like "P0A0B LEAF SOMETHING".
_BARE_MODEL_RE = re.compile(r'^\s*LEAF\s*$')

# Section-banner lines injected by the manual layout: "< DTC/CIRCUIT DIAGNOSIS >"
# These are structural dividers, not diagnostic content.
_SECTION_BANNER_RE = re.compile(r'^\s*<\s*DTC/CIRCUIT DIAGNOSIS\s*>\s*$', re.IGNORECASE)

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

    Noise removed (standalone lines only — never mid-line edits):
      - standalone page-label lines  (EVB-88, TM-44)
      - Revision: lines
      - year-model suffix lines       (2013 LEAF)
      - bare vehicle-name lines       (LEAF)
      - section-banner lines          (< DTC/CIRCUIT DIAGNOSIS >)
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
        if _BARE_MODEL_RE.match(line):
            continue
        if _SECTION_BANNER_RE.match(line):
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

def _build_dtc_logic(sections: list, tables: list, table_groups: list) -> dict | None:
    """
    Build a flat dtc_logic block from section text + semantic_parse.

    Table source priority:
      1. table_groups with role='dtc_logic'  (complete merged rows)
      2. raw tables with role='dtc_logic'    (single-page fallback)

    Always returns the same three keys (null when data is absent):
      confirmation_procedure  — cleaned DTC confirmation procedure steps
      detecting_condition     — shared fault-detection description
      possible_causes         — shared causes string
    Returns None only when the record has no dtc_logic section and no
    dtc_logic table at all (i.e. the block has no meaning for this record).
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

    # ── Best available table source: group first, raw table fallback ──
    best_table = None
    for g in table_groups:
        if g.get('role') == 'dtc_logic':
            best_table = g
            break
    if best_table is None:
        for t in tables:
            if t.get('role') == 'dtc_logic':
                best_table = t
                break

    sp = None
    if best_table is not None:
        candidate = best_table.get('semantic_parse', {})
        if candidate.get('status') in ('ok', 'partial'):
            sp = candidate

    if proc_text is None and best_table is None:
        return None

    detecting_condition = None
    possible_causes     = None

    if sp and sp.get('table_type') == 'shared_fields':
        shared = sp.get('shared', {})

        dc = (shared.get('dtc_detecting_condition')
              or shared.get('detecting_condition'))
        if dc:
            detecting_condition = dc['value']

        pc = (shared.get('possible_causes')
              or shared.get('possible_cause'))
        if pc:
            possible_causes = pc['value']

    return {
        'confirmation_procedure': proc_text,
        'detecting_condition':    detecting_condition,
        'possible_causes':        possible_causes,
        'raw_rows':               best_table.get('raw_rows') if best_table else None,
    }


def _build_diagnosis_procedure(sections: list, tables: list, table_groups: list) -> dict | None:
    """
    Build a clean diagnosis_procedure block.

    text        — section text with noise stripped (page labels, revision lines)
    tables      — raw single-page tables not absorbed into any group
    table_groups — merged multi-page tables (shown instead of their raw fragments)

    Raw tables absorbed into a group are omitted from output.
    Traceability to raw tables is preserved via group.source_table_ids.
    """
    proc_text = None
    for s in sections:
        if s.get('role') == 'diagnosis_procedure':
            raw = s.get('text') or ''
            cleaned = _clean_text(raw)
            if cleaned:
                proc_text = cleaned
            break  # only one diagnosis_procedure section expected

    # Build set of raw table_ids absorbed into a group — skip them in raw output
    absorbed = {
        tid
        for g in table_groups
        for tid in g.get('source_table_ids', [])
    }

    proc_tables = []

    # ── Raw standalone tables (not in any group) ──
    for t in tables:
        if t.get('role') != 'diagnosis_procedure':
            continue
        if t['table_id'] in absorbed:
            continue

        entry: dict = {
            'table_id':       t['table_id'],
            'start_pdf_page': t.get('start_pdf_page'),
            'end_pdf_page':   t.get('end_pdf_page'),
            'page_refs':      t.get('page_refs', []),
            'raw_rows':       t.get('raw_rows'),
        }
        sp = t.get('semantic_parse', {})
        if sp.get('status') in ('ok', 'partial'):
            entry['table_type'] = sp.get('table_type')
            for key, val in sp.items():
                if key not in ('status', 'table_type'):
                    entry[key] = val
        proc_tables.append(entry)

    # ── Table groups (merged multi-page tables) ──
    for g in table_groups:
        if g.get('role') != 'diagnosis_procedure':
            continue

        entry: dict = {
            'group_id':         g['group_id'],
            'source_table_ids': g.get('source_table_ids', []),
            'start_pdf_page':   g.get('start_pdf_page'),
            'end_pdf_page':     g.get('end_pdf_page'),
            'page_refs':        g.get('page_refs', []),
            'raw_rows':         g.get('raw_rows'),
        }
        sp = g.get('semantic_parse', {})
        if sp.get('status') in ('ok', 'partial'):
            entry['table_type'] = sp.get('table_type')
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

def format_record(record: dict) -> dict:
    """
    Convert one schema v4 DTC record into a lean LLM-friendly dict.

    Parameters
    ----------
    record  : one element from ``v4_doc['records']``

    Returns
    -------
    New dict.  The original record is not modified.
    """
    sections     = record.get('sections', [])
    tables       = record.get('tables', [])
    table_groups = record.get('table_groups', [])
    images       = record.get('images', [])

    out: dict = {
        'schema_version': '4-llm',
        'record_id':      record['record_id'],
        'codes':          record['codes'],
        'title':          record.get('title'),
        'location':       record.get('location', {}),
    }

    dtc_block = _build_dtc_logic(sections, tables, table_groups)
    if dtc_block:
        out['dtc_logic'] = dtc_block

    diag_block = _build_diagnosis_procedure(sections, tables, table_groups)
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
    records = [format_record(r) for r in doc.get('records', [])]

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
