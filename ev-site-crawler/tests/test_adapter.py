from adapters.adapter import adapt_article


def test_adapt_article_empty():
    out = adapt_article({})
    assert out["title"] == ""
    assert out["content"] == ""
    assert out["summary"] == ""
    assert out["images"] == []
    assert out["categories"] == []
    assert out["fault_codes"] == []
    assert out["part_numbers"] == []
    assert out["comments"] == []
    assert out["published_date"] == ""
    assert out["source"] == ""


def test_adapt_article_full():
    raw = {
        "title": "  My Title ",
        "content": "x" * 300,
        "images": ["img1.jpg"],
        "categories": ["news", "ev"],
        "url": "https://evclinic.eu/article",
    }
    out = adapt_article(raw)
    assert out["title"] == "My Title"
    assert len(out["summary"]) == 200
    assert out["images"] == ["img1.jpg"]
    assert out["categories"] == ["news", "ev"]
    assert out["fault_codes"] == []
    assert out["part_numbers"] == []
    assert out["comments"] == []
    assert out["published_date"] == ""
    assert out["source"] == "https://evclinic.eu/article"
