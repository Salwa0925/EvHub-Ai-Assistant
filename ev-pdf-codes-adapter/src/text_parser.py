"""
text_parser.py
==============
Splits a DTC block's raw text into two high-level sections.

Sections:
  dtc_logic_block          — from "DTC Logic" to "Diagnosis Procedure" (exclusive)
  diagnosis_procedure_block — from "Diagnosis Procedure" to end of text

Called per DTC record — does not call any external API.
"""

import re

# ── Noise patterns — lines to ignore completely ───────────────────────────────
# These appear on every page but carry no useful content
NOISE_PATTERNS = [
    re.compile(r"^Revision:\s+", re.IGNORECASE),   # e.g. "Revision: 2014 June"
    re.compile(r"^<\s*DTC/CIRCUIT DIAGNOSIS\s*>$", re.IGNORECASE),
    re.compile(r"^\d{4}\s+LEAF$", re.IGNORECASE),  # e.g. "2011 LEAF"
    re.compile(r"^LEAF$", re.IGNORECASE),
]

# ── Two top-level section anchors ─────────────────────────────────────────────
# "DTC Logic" opens the logic block.
# "Diagnosis Procedure" opens the procedure block.
# Everything else (DTC DETECTION LOGIC, DTC CONFIRMATION PROCEDURE,
# WARNING, CAUTION, DANGER, Component Inspection) stays inside its parent block.
SECTION_ANCHORS = [
    ("DTC Logic",           "dtc_logic_block"),
    ("Diagnosis Procedure", "diagnosis_procedure_block"),
]


def is_noise(line: str) -> bool:
    """Return True if this line should be discarded."""
    for pattern in NOISE_PATTERNS:
        if pattern.match(line.strip()):
            return True
    return False


def match_anchor(line: str) -> str | None:
    """
    Return the section field name if this line starts a top-level section,
    or None if it is ordinary content.
    Uses startswith (case-insensitive) so minor suffix variations still match.
    """
    stripped = line.strip()
    for anchor_text, field_name in SECTION_ANCHORS:
        if stripped.lower().startswith(anchor_text.lower()):
            return field_name
    return None


def parse_text(text: str) -> dict:
    """
    Split a DTC block's raw text into two structured sections.

    Returns:
        {
            "dtc_logic_block":           str | None,
            "diagnosis_procedure_block": str | None,
        }
    Both values are stripped strings, or None if the section was not found.
    """
    result = {
        "dtc_logic_block":           None,
        "diagnosis_procedure_block": None,
    }

    current_field = None   # which section we are currently collecting lines into
    current_lines = []     # lines collected so far for the current section

    for line in text.splitlines():
        if is_noise(line):
            continue

        field = match_anchor(line)

        if field:
            # Save the section we were collecting before this anchor
            if current_field and current_lines:
                result[current_field] = "\n".join(current_lines).strip()

            # Start the new section — include the heading line itself
            current_field = field
            current_lines = [line]

        else:
            current_lines.append(line)

    # Save whatever was being collected when text ran out
    if current_field and current_lines:
        result[current_field] = "\n".join(current_lines).strip()

    return result
