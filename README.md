# EvHub AI Crawler

This repository contains a modular Python web crawler project and a site-specific crawler for `evclinic.eu`.

**Status (2026-04-15)**

- Project was scaffolded and implemented with a modular layout under `ev-site-crawler/`.
- Implemented components:
  - `crawler/` — `BaseCrawler` and utilities for fetching and parsing pages.
  - `sites/evclinic/` — site-specific `EvClinicCrawler` driven by `config.json` selectors.
  - `adapters/adapter.py` — `adapt_article()` to normalize raw article objects to a consistent JSON schema (title, content, summary, images, categories, tags, fault_codes, part_numbers, comments, published_date, source).
  - CLI runner: `main.py` to run crawlers and write adapted JSON to `sites/<site>/data.json`.
  - Unit tests with `pytest` under `tests/` (currently passing).

**Parsing & Extraction Improvements**

- Image extraction: prefer `data-src`/`data-lazy-src`/`srcset` over placeholder `src` attributes and normalize relative URLs.
- Fault & part extraction: stricter regexes and contextual detection to reduce false positives.
- Categories/tags extraction: gather from multiple selectors and filter noisy categories.
- Deduplication: articles deduplicated by normalized title.

**Repository layout**

- `ev-site-crawler/` — the runnable project directory (code, tests, venv when created locally).
  - `main.py` — CLI entrypoint (run from inside `ev-site-crawler/`).
  - `requirements.txt` — Python dependencies.

Note: the project files live under `ev-site-crawler/` in the repo; running commands from the repo root will fail unless you `cd ev-site-crawler` first or install the package.

**How to run (recommended)**

1. From the repository root:

```bash
cd ev-site-crawler
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q  # run tests
python main.py --site evclinic --max-articles 10 --delay 1.0 --log-level INFO
```

2. The crawler writes adapted JSON to `sites/evclinic/data.json` (this file is ignored by `.gitignore` by default).

**Data / Git guidance**

- `sites/*/data.json` and the local `.venv/` are ignored by `.gitignore` to avoid committing large or generated artifacts.
- If the team needs shared access to scraped datasets, prefer a private object store (S3/GCS), a separate private data repo, or DVC/Git LFS rather than committing the JSON into the code repo.

**Tests & Validation**

- Unit tests validate parsing and adapter behavior. Run `python -m pytest -q` inside `ev-site-crawler/` to execute them.

**Next steps / TODOs**

- (Optional) Make the project installable (`pip install -e .`) so you can run it from repo root without `cd`.
- (Optional) Add CI to run tests and optionally publish dataset artifacts.

If you want, I can: create a small root-level wrapper so you can run the CLI from the repo root, or convert the project into an installable package. Which would you prefer?
