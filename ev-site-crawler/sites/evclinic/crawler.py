import json
import logging
import os
import re
import html as _html
from typing import List, Optional, Dict

from crawler.base_crawler import BaseCrawler
from crawler.utils import normalize_url, clean_text, unique_preserve_order, is_english


class EvClinicCrawler(BaseCrawler):
    """Site-specific crawler for evclinic using selectors from config.json.

    This crawler reads selectors and an `index_pages` list from `config.json`.
    It extracts title, content, images, categories, fault codes, part numbers,
    comments, published_date and the source URL.
    """

    def __init__(self, config_path: Optional[str] = None, delay: float = 1.0):
        package_dir = os.path.dirname(__file__)
        if config_path is None:
            config_path = os.path.join(package_dir, "config.json")

        with open(config_path, "r", encoding="utf-8") as fh:
            self.config = json.load(fh)

        base_url = self.config.get("base_url")
        super().__init__(base_url=base_url, delay=delay)

        # selectors
        self.index_pages = self.config.get("index_pages") or [self.base_url]
        self.article_selector = self.config.get("article_selector")
        self.title_selector = self.config.get("title_selector")
        self.content_selector = self.config.get("content_selector")
        self.image_selector = self.config.get("image_selector")
        self.category_selector = self.config.get("category_selector")

        self.logger = logging.getLogger(self.__class__.__name__)

    def crawl_index(self, max_articles: Optional[int] = None) -> List[str]:
        """Crawl configured index pages and collect unique article URLs."""
        links: List[str] = []
        seen = set()
        for page in self.index_pages:
            soup = self.get_soup(page)
            if not soup:
                self.logger.warning("Failed to fetch index page: %s", page)
                continue

            items = self.select(soup, self.article_selector)
            for item in items:
                link_tag = item if getattr(item, "name", None) == "a" else item.find("a")
                if not link_tag:
                    continue
                href = link_tag.get("href")
                url = self.normalize_url(href, current_url=page)
                if not url or url in seen:
                    continue
                seen.add(url)
                links.append(url)
                if max_articles and len(links) >= max_articles:
                    return links

        return links

    def parse_article(self, url: str) -> Optional[Dict]:
        """Fetch and extract structured data from an article page."""
        html = self.get(url)
        if not html:
            return None
        soup = self.parse(html)
        if not soup:
            return None

        # Title
        title_elem = self.select_one(soup, self.title_selector)
        title = clean_text(title_elem.get_text()) if title_elem else ""

        # Published date
        pub_elem = self.select_one(soup, "div.content-date-comments .date-meta") or self.select_one(soup, ".date-meta")
        published_date = clean_text(pub_elem.get_text()) if pub_elem else ""

        # Content root
        content_root = self.select_one(soup, self.content_selector) or soup

        # Extract paragraph text
        paragraphs = [clean_text(p.get_text()) for p in content_root.select("p") if clean_text(p.get_text())]
        # prefer english paragraphs when available
        english_paras = [p for p in paragraphs if is_english(p)]
        content_text = "\n\n".join(english_paras if english_paras else paragraphs)

        # Images — pick best candidate (prefer real urls over placeholder SVGs)
        def pick_from_srcset(srcset_val: str) -> Optional[str]:
            if not srcset_val:
                return None
            # pick the largest width candidate (usually last)
            parts = [p.strip() for p in srcset_val.split(',') if p.strip()]
            if not parts:
                return None
            # each part like: 'URL 1024w' or just 'URL'
            best = parts[-1]
            url_part = best.split()[0]
            return url_part

        images = []
        for img in content_root.select(self.image_selector):
            # prefer data-src/data-lazy-src if available (lazy-loaded real image)
            cand = img.get("data-src") or img.get("data-lazy-src") or img.get("data-srcset")
            if not cand:
                # try srcset attributes
                cand = pick_from_srcset(img.get("srcset") or img.get("data-srcset") or "")
            if not cand:
                # fallback to src, but avoid data:image placeholders
                src_attr = img.get("src") or ""
                if src_attr and src_attr.startswith("data:image/svg+xml"):
                    cand = None
                else:
                    cand = src_attr or None

            if not cand:
                continue
            # unescape HTML entities and normalize relative URLs
            cand = _html.unescape(cand)
            img_url = normalize_url(cand, url)
            if img_url and not img_url.startswith("data:"):
                images.append(img_url)

        images = unique_preserve_order(images)

        # Categories and tags
        categories = []
        # common category containers
        for sel in ("div.cat-links a", "span.categories-links a", self.category_selector):
            if not sel:
                continue
            for cat in soup.select(sel):
                text = clean_text(cat.get_text())
                if text:
                    categories.append(text)
        # remove categories containing the word 'crap'
        categories = [c for c in unique_preserve_order(categories) if "crap" not in c.lower()]

        tags = []
        for tag in soup.select("div.tags-links a"):
            t = clean_text(tag.get_text())
            if t:
                tags.append(t)
        tags = unique_preserve_order(tags)

        # Fault codes and part numbers — tighter extraction to avoid false positives
        fault_codes = []
        part_numbers = []

        # patterns
        # OBD-style P-codes (e.g. P0123)
        fault_pat = re.compile(r"\b[Pp]\d{3,}\b")
        # manufacturer-style fault codes that often start with digits (e.g. 21F37E)
        manuf_fault_pat = re.compile(r"\b\d{2}[A-Za-z0-9]{3,}\b")
        # part numbers: require at least one digit, length >=5, allow hyphens
        part_pat = re.compile(r"\b(?=[0-9A-Za-z-]*\d)([0-9A-Za-z-]{5,})\b")

        for ul in content_root.find_all("ul"):
            ul_text = clean_text(ul.get_text(separator=" "))

            # attempt to find a short label immediately before the list
            prev_label = ""
            prev = None
            for el in ul.find_all_previous():
                if getattr(el, "name", None) in ("p", "h1", "h2", "h3", "strong", "b", "span"):
                    prev = el
                    break
            if prev:
                prev_label = clean_text(prev.get_text()).lower()

            is_fault_list = bool(re.search(r"\bfaults?\b|\berrors?\b|\bfault code\b|\berror code\b", prev_label))
            is_part_list = bool(re.search(r"part numbers?|part no\b|part#|part number", prev_label))

            # sniff for explicit P-codes first
            found_faults = fault_pat.findall(ul_text)
            # if the list is explicitly labeled as faults, also accept manufacturer codes
            if is_fault_list:
                found_faults += manuf_fault_pat.findall(ul_text)

            if found_faults and is_fault_list:
                for f in found_faults:
                    ff = f.strip().strip(",").upper()
                    if ff:
                        fault_codes.append(ff)
                continue

            # sniff part numbers when the list is labeled as parts or if no faults were found
            found_parts = part_pat.findall(ul_text)
            if found_parts and (is_part_list or not found_faults):
                for p in found_parts:
                    pp = p.strip().strip(",")
                    if pp:
                        part_numbers.append(pp)
                continue

            # otherwise ignore this UL (likely comments, share buttons, menus)

        fault_codes = unique_preserve_order(fault_codes)
        part_numbers = unique_preserve_order(part_numbers)

        # Comments
        comments = []
        for cb in soup.select(".comment-body"):
            author_elem = cb.select_one("cite.fn")
            author = clean_text(author_elem.get_text()) if author_elem else ""
            ptexts = [clean_text(p.get_text()) for p in cb.find_all("p")]
            text = "\n\n".join([pt for pt in ptexts if pt])
            date_elem = cb.select_one(".comment-meta a") or cb.select_one(".comment-meta")
            date = clean_text(date_elem.get_text()) if date_elem else ""
            comments.append({"author": author, "text": text, "date": date})

        return {
            "title": title,
            "content": content_text,
            "images": images,
            "categories": categories,
            "tags": tags,
            "fault_codes": fault_codes,
            "part_numbers": part_numbers,
            "comments": comments,
            "published_date": published_date,
            "url": url,
        }

    def run(self, max_articles: Optional[int] = None) -> List[Dict]:
        """Run the crawler, deduplicating articles by title.

        Deduplication is performed by normalized title (lowercased, stripped).
        """
        urls = self.crawl_index(max_articles=max_articles)
        results: List[Dict] = []
        seen_titles = set()
        for u in urls:
            self.logger.info("Fetching article %s", u)
            article = self.parse_article(u)
            if not article:
                continue
            tnorm = (article.get("title") or "").strip().lower()
            if tnorm and tnorm in seen_titles:
                self.logger.debug("Skipping duplicate article by title: %s", article.get("title"))
                continue
            if tnorm:
                seen_titles.add(tnorm)
            results.append(article)
        return results
