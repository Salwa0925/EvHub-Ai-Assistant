import logging
from config import setup_logging, load_config
from odoo_export.client import OdooClient
from odoo_export.adapter import RecordAdapter
from odoo_export.exporters.repairs import RepairOrderExporter
from odoo_export.exporters.knowledge import KnowledgeBaseExporter

log = logging.getLogger(__name__)

def main():
    setup_logging()
    
    try:
        config = load_config()
    except EnvironmentError as e:
        log.error(e)
        return

    # Initialize Client and Adapter
    client = OdooClient(config["url"], config["db"], config["api_key"])
    adapter = RecordAdapter()

    # Verify connection once
    try:
        client.verify_connection()
    except Exception as e:
        log.error(f"Failed to connect to Odoo: {e}")
        return

    # 1. Export Repair Orders
    try:
        repairs = RepairOrderExporter(client, adapter, limit=3)
        repairs.fetch()
    except Exception as e:
        log.error(f"Repair Orders export failed: {e}")

    # 2. Export Knowledge Base
    try:
        knowledge = KnowledgeBaseExporter(client, adapter, published_only=True)
        knowledge.fetch()
    except Exception as e:
        log.error(f"Knowledge Base export failed: {e}")

    log.info("All exports complete.")

if __name__ == "__main__":
    main()
