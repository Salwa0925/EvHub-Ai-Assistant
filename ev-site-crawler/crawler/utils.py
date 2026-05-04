from urllib.parse import urljoin
from typing import Iterable, List, Optional
import re


def normalize_url(href: Optional[str], base: str) -> Optional[str]:
    """Normalize a possibly-relative URL against a base URL."""
    if not href:
        return None
    return urljoin(base or "", href)


def clean_text(text: Optional[str]) -> str:
    """Simple whitespace-normalizing text cleaner."""
    if not text:
        return ""
    return " ".join(text.split())


def unique_preserve_order(items: Iterable) -> List:
    """Return a list with duplicates removed while preserving order."""
    seen = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def is_english(text: Optional[str]) -> bool:
    """A lightweight heuristic to detect English text.

    Looks for common English words or a high ratio of ASCII letters.
    This is intentionally simple to avoid extra dependencies.
    """
    if not text:
        return False
    text = str(text)
    # common English words
    if re.search(r"\b(the|and|is|are|in|on|for|with|that|this|it)\b", text, re.I):
        return True

    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    ascii_letters = sum(1 for c in letters if ord(c) < 128)
    return (ascii_letters / len(letters)) > 0.8

