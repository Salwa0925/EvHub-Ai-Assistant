"""Adapter to transform raw scraped data into a consistent schema."""

from typing import Dict, Any


def adapt_article(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Adapt a raw article dict into the required schema.

    Ensures consistent keys and safe defaults. Generates a 200-char summary
    from content.
    """

    title = (raw.get("title") or "").strip()
    content = (raw.get("content") or "").strip()
    images = raw.get("images") or []
    categories = raw.get("categories") or []
    source = raw.get("url") or raw.get("source") or ""

    fault_codes = raw.get("fault_codes") or []
    part_numbers = raw.get("part_numbers") or []
    comments = raw.get("comments") or []
    published_date = raw.get("published_date") or ""
    tags = raw.get("tags") or []

    if not isinstance(images, list):
        images = [images]
    if not isinstance(categories, list):
        categories = [categories]
    if not isinstance(fault_codes, list):
        fault_codes = [fault_codes]
    if not isinstance(part_numbers, list):
        part_numbers = [part_numbers]
    if not isinstance(comments, list):
        comments = [comments]
    if not isinstance(tags, list):
        tags = [tags]

    summary = content[:200]

    return {
        "title": title,
        "content": content,
        "summary": summary,
        "images": images,
        "categories": categories,
        "tags": tags,
        "fault_codes": fault_codes,
        "part_numbers": part_numbers,
        "comments": comments,
        "published_date": published_date,
        "source": source,
    }
