import re

# Matches DTC codes like P0A0D, B1234, C3456, U0100
CODE_RE = re.compile(r"^[PBCU][0-9A-F]{4}$", re.IGNORECASE)

# Matches EVB-123 style references
REF_RE = re.compile(r"[A-Z]{2,10}-(\d+)", re.IGNORECASE)

# Single letters on their own line — PDF sidebar nav tabs
SIDEBAR_RE = re.compile(r"^\s*[A-Z]{1,3}\s*$", re.MULTILINE)

# Internal Nissan reference IDs
INFOID_RE = re.compile(r"INFOID:\d+")