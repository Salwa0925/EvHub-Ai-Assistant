import logging
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin


class BaseCrawler:
    """A small reusable base crawler.

    Responsibilities:
    - perform HTTP GET requests with basic error handling
    - parse HTML into BeautifulSoup objects
    - normalize URLs
    - simple CSS selector helpers
    - rate limiting via `delay`
    """

    def __init__(self, base_url: Optional[str] = None, delay: float = 1.0, headers: dict = None, timeout: int = 10):
        self.base_url = base_url
        self.delay = delay
        self.timeout = timeout
        self.session = requests.Session()
        self.headers = headers or {"User-Agent": "evhub-crawler/1.0 (+https://github.com/)"}
        self.logger = logging.getLogger(self.__class__.__name__)
        self.visited = set()

    def get(self, url: str, params: dict = None) -> Optional[str]:
        """Fetch URL and return text or None on failure."""
        try:
            self.logger.debug("GET %s", url)
            r = self.session.get(url, params=params, headers=self.headers, timeout=self.timeout)
            r.raise_for_status()
            # rate limit
            time.sleep(self.delay)
            return r.text
        except requests.RequestException as exc:
            self.logger.warning("Request failed for %s: %s", url, exc)
            return None

    def parse(self, html: Optional[str]) -> Optional[BeautifulSoup]:
        """Create a BeautifulSoup object, or return None for empty input."""
        if not html:
            return None
        return BeautifulSoup(html, "html.parser")

    def get_soup(self, url: str) -> Optional[BeautifulSoup]:
        html = self.get(url)
        return self.parse(html)

    def normalize_url(self, href: Optional[str], current_url: Optional[str] = None) -> Optional[str]:
        """Turn relative href into absolute URL using current_url or base_url."""
        if not href:
            return None
        base = current_url or self.base_url or ""
        try:
            return urljoin(base, href)
        except Exception:
            return None

    def select(self, soup: Optional[BeautifulSoup], selector: Optional[str]):
        if not soup or not selector:
            return []
        try:
            return soup.select(selector)
        except Exception as exc:
            self.logger.warning("CSS selector failed (%s): %s", selector, exc)
            return []

    def select_one(self, soup: Optional[BeautifulSoup], selector: Optional[str]):
        if not soup or not selector:
            return None
        try:
            return soup.select_one(selector)
        except Exception as exc:
            self.logger.warning("CSS selector failed (%s): %s", selector, exc)
            return None
