"""Main entry point to run site crawlers and save adapted JSON results.

This script provides a small CLI so you can configure the site, limits,
delay, output path, and logging without editing code.
"""

import argparse
import json
import logging
import os
import sys
from typing import Optional

from adapters.adapter import adapt_article
from sites.evclinic.crawler import EvClinicCrawler


def configure_logging(level: str = "INFO", logfile: Optional[str] = None):
    """Configure logging for console or file output.

    level: one of DEBUG, INFO, WARNING, ERROR, CRITICAL
    logfile: optional path to write logs to
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    fmt = "%(levelname)s:%(name)s:%(message)s"
    if logfile:
        handler = logging.FileHandler(logfile, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s " + fmt))
        root = logging.getLogger()
        root.setLevel(numeric_level)
        root.addHandler(handler)
    else:
        logging.basicConfig(level=numeric_level, format=fmt)


def parse_args():
    parser = argparse.ArgumentParser(description="Run site crawlers and save results")
    parser.add_argument("--site", default="evclinic", choices=["evclinic"], help="Site to crawl")
    parser.add_argument("--max-articles", type=int, default=100, help="Max articles to fetch")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay between requests (seconds)")
    parser.add_argument("--output", default=None, help="Output JSON path")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], help="Logging level")
    parser.add_argument("--log-file", default=None, help="Optional log file path")
    return parser.parse_args()


def run_site(site: str, max_articles: int, delay: float, output: Optional[str]):
    """Run the given site crawler and save adapted JSON results.

    Currently only `evclinic` is supported. Returns (output_path, count).
    """
    if site != "evclinic":
        raise ValueError(f"Unsupported site: {site}")

    crawler = EvClinicCrawler(delay=delay)
    raw = crawler.run(max_articles=max_articles)
    adapted = [adapt_article(a) for a in raw]

    out_path = output or os.path.join("sites", site, "data.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(adapted, fh, ensure_ascii=False, indent=2)

    logging.info("Saved %d articles to %s", len(adapted), out_path)
    return out_path, len(adapted)


def main():
    args = parse_args()
    configure_logging(args.log_level, args.log_file)
    try:
        out_path, count = run_site(args.site, args.max_articles, args.delay, args.output)
        print(f"Saved {count} articles to {out_path}")
    except Exception:
        logging.exception("Crawler failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
