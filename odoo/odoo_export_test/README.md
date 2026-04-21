# Odoo Export Tool

This tool exports data from Odoo using the JSON-2 API. Currently, it supports exporting:
- **Repair Orders:** Includes metadata, chatter messages, and file attachments.
- **Knowledge Base Articles:** Raw JSON export of published articles.

## Setup

1. **Clone the repository.**
2. **Create a virtual environment:**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows use: .venv\Scripts\activate
   ```
3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
4. **Configure environment variables:**
   Create a `.env` file in the root directory with the following:
   ```env
   ODOO_URL=https://your-odoo-instance.com
   ODOO_DB=your_database_name
   ODOO_API_KEY=your_api_key
   ```

## Usage

Run the main script to start the export:
```bash
python main.py
```

Exports will be saved to `odoo_repairs_export/` and `odoo_knowledge_export/` by default.
