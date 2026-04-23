# Module Status: `chunker.py` ✅ Complete

## 1. Core Functionality
Reads all classified batch files as one continuous ordered stream and groups
elements into semantic chunks — one chunk per complete procedure unit.
Outputs a single `chunks.json` for the LLM agent team.

### Input / Output
- **Reads:** `classified/*.json` (all 25 batches merged in page order)
- **Writes:** `chunks.json` (one file, all chunks across the entire manual)

---

## 2. Why One Stream Instead of File-by-File

Each batch file covers 5 pages. A procedure can start on page 5 (end of
`1_5.json`) and finish on page 6 (start of `6_10.json`). Processing files
separately would split that procedure into two incomplete chunks.

Loading all files sorted by start page and merging into one flat list before
chunking means cross-batch procedures stay intact automatically.

---

## 3. Chunk Boundaries

A new chunk starts at every `section_header` element. Everything that follows
belongs to that chunk until the next `section_header`:
- procedure steps
- warnings
- spec values
- general text
- tables on the same pages
- images on the same pages

The `section_header` element itself is included as the first element of the
new chunk — not the last element of the previous one.

The final chunk closes at end of file with no following header needed.
This handles `121_121.json` (last page of the manual) naturally.

---

## 4. What Each Chunk Contains

```json
{
  "chunk_id":      "EVC_pdf83_chunk2",
  "page_pdf":      83,
  "page_manual":   "EVC-11",
  "section_code":  "EVC",
  "heading":       "HV BATTERY REMOVAL",
  "safety_level":  "HIGH_VOLTAGE",
  "prerequisites": ["Disconnect 12V battery before starting procedure"],
  "text_blocks":   [...],
  "tables":        [...],
  "images":        [...]
}
```

### Safety level
Highest safety level found among any element in the chunk.
Order: HIGH_VOLTAGE > WARNING > CAUTION > NONE.
If one element in a chunk is HIGH_VOLTAGE, the whole chunk is HIGH_VOLTAGE.
The agent uses this to prepend safety reminders automatically.

### Prerequisites
Sentences containing `before / prior to / ensure / verify / confirm / must be`
found in the first 5 elements of the chunk. The LLM agent uses these to ask
checkup questions before delivering procedure steps to the mechanic.

### Tables and images
Grouped by `page_pdf` at load time for O(1) lookup during chunking.
Every table and image whose page falls within the chunk's page range
is attached to that chunk automatically.

---

## 5. Output File Structure

```json
{
  "schema_version": "1.0",
  "total_chunks":   312,
  "stats": {
    "high_voltage_chunks": 47,
    "chunks_with_tables":  89,
    "chunks_with_images":  201,
    "chunks_with_prereqs": 134
  },
  "chunks": [...]
}
```

Stats at the top give a quick sanity check — if `high_voltage_chunks` is 0
on an EV manual something is wrong with the classifier safety tagging.

---

## 6. Open Questions for Tuning

**Minimum chunk size** — currently no minimum. A section header with one
sentence becomes a chunk. May need a minimum element count before the agent
team tests retrieval quality.

**Maximum chunk size** — no maximum either. A very long procedure section
could produce a chunk too large for the agent's context window. May need
splitting on sub-headers if this becomes a problem.

**Warning chunks** — warnings currently stay attached to the procedure they
belong to. Debating whether HIGH_VOLTAGE warnings should also exist as their
own standalone chunks for direct safety queries.

These decisions depend on retrieval quality testing by the LLM agent team.

---

