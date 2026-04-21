import os
import re
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

def safe_filename(name: str, max_len: int = 60) -> str:
    """Sanitize a string for safe use as a filename."""
    # Replace slashes and backslashes with underscores before sanitizing
    name = name.replace("/", "_").replace("\\", "_")
    name = re.sub(r"[^\w\-\.]", "_", name)  # Replace remaining unsafe characters
    return name[:max_len]

def write_json(path: Path, data: any) -> None:
    """Write data to a JSON file with proper encoding and formatting."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
