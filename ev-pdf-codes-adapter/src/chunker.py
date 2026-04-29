"""
chunker.py
==========
Convert a schema v4 JSON document into a flat list of retrieval chunks.

Each chunk:
  chunk_id      — "{record_id}_dtc_block"
  document_id   — from document wrapper
  source_file   — from document wrapper
  vehicle       — from document wrapper
  record_id     — from record
  codes         — list of DTC codes
  title         — record title
  location      — {start_pdf_page, end_pdf_page, page_refs}
  chunk_type    — "dtc_block"
  text          — title + codes + all section text, combined into one string
  tables        — list of table summaries (omitted when no tables exist)

Usage (standalone):
    py src/chunker.py data/EVB/EVB_llm.json
    -> writes data/EVB/EVB_chunks.json

Usage (as module):
    from chunker import chunk_document
    chunks = chunk_document(llm_doc)
"""

import json
import sys
from pathlib import Path


def _build_text(record: dict) -> str:
    """
    Build the searchable text for one LLM-schema DTC record.

    Format:
        <title>
        Codes: <code1>, <code2>, ...

        <dtc_logic.confirmation_procedure>

        <diagnosis_procedure.text>
    """
    parts = []

    title = record.get("title") or ""
    if title:
        parts.append(title)

    codes = record.get("codes") or []
    if codes:
        parts.append("Codes: " + ", ".join(codes))

    dtc_logic = record.get("dtc_logic") or {}
    confirmation = (dtc_logic.get("confirmation_procedure") or "").strip()
    if confirmation:
        parts.append(confirmation)

    diag = record.get("diagnosis_procedure") or {}
    diag_text = (diag.get("text") or "").strip()
    if diag_text:
        parts.append(diag_text)

    return "\n\n".join(parts)


def _build_tables(record: dict) -> list[dict]:
    """
    Build the tables list for one LLM-schema DTC record.

    Source: diagnosis_procedure.tables (table objects with inlined semantic_parse).

    Status is inferred from raw_rows_preferred because llm_formatter strips
    the original status field:
      - raw_rows_preferred == True  -> was "partial" -> use raw_rows + quality_flags
      - table_type present, no raw_rows_preferred -> was "ok" -> use structured rows

    Each entry always includes:
      table_id    — group_id or table_id (whichever is present)
      table_type  — e.g. "flat", "grouped_rows", "shared_fields"
      status      — "ok" or "partial" (reconstructed)
      page_refs   — list of printed page refs for this table

    Partial tables also include:
      raw_rows      — raw cell data from PDF
      quality_flags — list of structural anomaly flags
      uncertain     — True (signals downstream: do not trust structured rows)

    Ok tables also include:
      header        — column headers (flat / grouped_rows)
      rows / groups — structured row data
    """
    diag = record.get("diagnosis_procedure") or {}
    raw_tables = diag.get("tables") or []
    if not raw_tables:
        return []

    result = []
    for t in raw_tables:
        table_id   = t.get("group_id") or t.get("table_id")
        table_type = t.get("table_type")
        page_refs  = t.get("page_refs") or []

        if t.get("raw_rows_preferred"):
            # Partial: structured parse is unreliable — expose raw data
            entry = {
                "table_id":     table_id,
                "table_type":   table_type,
                "status":       "partial",
                "uncertain":    True,
                "page_refs":    page_refs,
                "raw_rows":     t.get("raw_rows"),
                "quality_flags": t.get("quality_flags") or [],
            }
        elif table_type:
            # Ok: structured parse is trustworthy — expose semantic rows
            entry = {
                "table_id":   table_id,
                "table_type": table_type,
                "status":     "ok",
                "page_refs":  page_refs,
            }
            # Include whichever structured-row key this table_type uses
            for key in ("header", "rows", "groups", "shared", "individual",
                        "primary_key", "primary_key_values", "key_column"):
                if key in t:
                    entry[key] = t[key]
        else:
            # No table_type — semantic parse failed entirely; skip
            continue

        result.append(entry)

    return result


def chunk_document(doc: dict) -> list[dict]:
    """
    Convert a schema v4 document into a list of dtc_block chunks.

    Parameters
    ----------
    doc : loaded schema v4 JSON document

    Returns
    -------
    List of chunk dicts, one per record.
    """
    document_id = doc["document_id"]
    source_file = doc.get("source_file")
    vehicle     = doc.get("vehicle")

    chunks = []
    for record in doc.get("records", []):
        record_id = record["record_id"]
        tables = _build_tables(record)
        chunk: dict = {
            "chunk_id":    f"{record_id}_dtc_block",
            "document_id": document_id,
            "source_file": source_file,
            "vehicle":     vehicle,
            "record_id":   record_id,
            "codes":       record.get("codes", []),
            "title":       record.get("title"),
            "location":    record.get("location", {}),
            "chunk_type":  "dtc_block",
            "text":        _build_text(record),
        }
        if tables:
            chunk["tables"] = tables
        chunks.append(chunk)

    return chunks


def _cli():
    if len(sys.argv) < 2:
        print("Usage: py src/chunker.py <path/to/file.json>")
        sys.exit(1)

    in_path = Path(sys.argv[1])
    if not in_path.exists():
        print(f"File not found: {in_path}")
        sys.exit(1)

    with open(in_path, encoding="utf-8") as f:
        doc = json.load(f)

    if doc.get("schema_version") != "4-llm":
        print(f"Warning: expected schema_version 4-llm, got {doc.get('schema_version')}")

    chunks = chunk_document(doc)

    # Strip _llm suffix before adding _chunks so EVB_llm.json -> EVB_chunks.json
    base_stem = in_path.stem
    if base_stem.endswith("_llm"):
        base_stem = base_stem[:-4]
    out_path = in_path.with_stem(base_stem + "_chunks")
    tmp_path = out_path.with_suffix(".json.tmp")

    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(chunks, f, indent=2, ensure_ascii=False)
    tmp_path.replace(out_path)

    print(f"Written: {out_path}")
    print(f"  records : {len(doc.get('records', []))}")
    print(f"  chunks  : {len(chunks)}")


if __name__ == "__main__":
    _cli()
