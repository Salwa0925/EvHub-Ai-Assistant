from crawler.utils import clean_text, unique_preserve_order, normalize_url


def test_clean_text():
    assert clean_text("  Hello \n  World ") == "Hello World"


def test_unique_preserve_order():
    assert unique_preserve_order([1, 2, 1, 3]) == [1, 2, 3]


def test_normalize_url():
    assert normalize_url("/a", "https://example.com/base/") == "https://example.com/a"
