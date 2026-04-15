You are a Python developer building a modular web crawling system.

---

# 🎯 Goal

Build a scalable Python project that crawls EV-related websites, extracts structured data, and stores it in consistent JSON format.

---

# 🧱 Project Structure

Create the following structure:

project/
│
├── crawler/
│ ├── base_crawler.py
│ ├── utils.py
│ └── **init**.py
│
├── adapters/
│ ├── adapter.py
│ └── **init**.py
│
├── sites/
│ ├── evclinic/
│ │ ├── crawler.py
│ │ ├── config.json
│ │ ├── description.txt
│ │ └── data.json
│
├── main.py
└── requirements.txt

---

# ⚙️ Core Requirements

## 1. Base Crawler (crawler/base_crawler.py)

- Handles:
  - HTTP requests using `requests`
  - HTML parsing using `BeautifulSoup`
  - Error handling
  - Rate limiting (time.sleep)

- Should be reusable across all sites

---

## 2. Site-Specific Crawler (sites/evclinic/crawler.py)

- Inherit from BaseCrawler
- Read scraping rules from `config.json`
- Extract:
  - title
  - content
  - images
  - categories (if available)
  - url

---

## 3. Config-Driven Scraping (IMPORTANT)

Use `config.json` to define selectors like:

{
"base_url": "https://evclinic.eu",
"article_selector": "h3.entry-title a",
"title_selector": "h1",
"content_selector": "div.entry-content",
"image_selector": "div.entry-content img",
"category_selector": "span.categories-links a"
}

The crawler MUST read this file and dynamically apply selectors.

---

## 4. Adapter Layer (adapters/adapter.py)

Create a function:

adapt_article(raw_data)

It must transform raw scraped data into this schema:

{
"title": "",
"content": "",
"summary": "",
"images": [],
"categories": [],
"source": ""
}

Rules:

- summary = first 200 characters of content
- Always return consistent keys
- Handle missing values safely

---

## 5. JSON Storage

- Save results in:
  sites/evclinic/data.json
- Store a list of articles
- Use clean formatting (indent=2)

---

## 6. Main Entry Point (main.py)

- Run the evclinic crawler
- Collect raw data
- Pass through adapter
- Save final JSON

---

# 📄 description.txt

- Store human-readable notes about the website
- DO NOT use this file in code logic

---

# ⚠️ Important Rules

- Do NOT hardcode selectors inside crawler logic
- Always use config.json
- Handle missing HTML elements safely
- Avoid duplicate URLs
- Add delay between requests
- Keep code modular and clean

---

# 🧠 Required Skills

The agent must demonstrate the following skills:

### 🐍 Python Fundamentals

- Write clean, readable Python code
- Use functions, classes, and modules correctly

### 🌐 Web Scraping

- Use `requests` and `BeautifulSoup`
- Work with HTML tags, attributes, and selectors
- Handle missing or inconsistent HTML safely

### 🧩 Data Extraction & Structuring

- Extract structured data from unstructured HTML
- Clean and normalize text
- Handle lists (categories, images)

### ⚙️ Config-Driven Development

- Read and use `config.json`
- Dynamically apply selectors
- Avoid hardcoding

### 🧱 Software Architecture

- Separate concerns (crawler, site logic, adapter)
- Use base class + inheritance
- Keep code modular and scalable

### 🔄 Data Transformation (Adapter)

- Convert raw data into consistent schema
- Handle missing values
- Generate summaries

### 💾 JSON Handling

- Read/write JSON files
- Maintain valid structure and formatting

### 🛡️ Error Handling

- Use try/except
- Handle network and parsing errors

### ⏱️ Responsible Crawling

- Add delays between requests
- Avoid duplicates
- Prevent unnecessary requests

### 🔗 URL Handling

- Handle relative and absolute URLs correctly

### 🧪 Debugging & Logging

- Log progress clearly
- Print useful debug information

### 🧠 Code Readability

- Write beginner-friendly code
- Use clear variable names
- Add helpful comments

---

# 🚫 What to Avoid

- Hardcoding selectors
- Mixing scraping and data formatting
- Writing monolithic scripts
- Ignoring error handling
- Producing inconsistent JSON

---

# 🎯 Expected Output

The system should:

- Crawl multiple articles from the website
- Extract structured data (title, content, images, categories, url)
- Adapt data into a consistent JSON schema
- Save results in a clean JSON file
- Be modular and reusable for additional websites

---

# 🚀 Bonus (Optional)

- Normalize image URLs (handle relative paths)
- Avoid duplicate articles
- Provide clear console logs of progress

---

Write clean, readable, beginner-friendly Python code.
Explain key parts with comments.
