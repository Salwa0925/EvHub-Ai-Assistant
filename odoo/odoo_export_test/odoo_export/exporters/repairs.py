import base64
import logging
from .base import BaseExporter
from ..utils import safe_filename, write_json

log = logging.getLogger(__name__)

class RepairOrderExporter(BaseExporter):
    """
    Exports repair orders, their chatter messages, and file attachments.
    """

    def __init__(self, client, adapter, export_dir: str = "odoo_repairs_export", limit: int = 3):
        super().__init__(client, adapter, export_dir)
        self.limit = limit

    def fetch(self) -> None:
        self.export_dir.mkdir(exist_ok=True)
        log.info("Fetching Repair Orders...")

        kwargs = {
            "domain": [],
            "fields": ["id", "name"],
        }
        if self.limit:
            kwargs["limit"] = self.limit

        records = self.client.execute("repair.order", "search_read", **kwargs)
        if not records:
            log.info("No repair orders found.")
            return

        repair_ids = [r["id"] for r in records]
        log.info(f"Found {len(repair_ids)} repair orders. Reading all fields...")

        fields_info = self.client.execute("repair.order", "fields_get", attributes=["string"])
        all_fields = list(fields_info.keys())
        repairs = self.client.execute("repair.order", "read", ids=repair_ids, fields=all_fields)

        for repair in repairs:
            self._export_record(repair)

        log.info(f"Repair export complete → {self.export_dir}")

    def _export_record(self, repair: dict) -> None:
        repair_id = repair["id"]
        repair_name = repair.get("name", f"Repair_{repair_id}")
        case_dir = self.export_dir / safe_filename(repair_name)
        case_dir.mkdir(exist_ok=True)

        log.info(f"  Processing {repair_name} (ID: {repair_id})")

        # Attachments
        att_data = self.client.execute(
            "ir.attachment", "search_read",
            domain=[("res_model", "=", "repair.order"), ("res_id", "=", repair_id)],
            fields=["id", "name", "mimetype", "file_size"],
        )

        attachment_meta = []
        if att_data:
            att_ids = [a["id"] for a in att_data]
            attachments = self.client.execute(
                "ir.attachment", "read",
                ids=att_ids,
                fields=["name", "datas", "mimetype", "file_size"],
            )
            for att in attachments:
                file_name = safe_filename(att["name"])
                attachment_meta.append({
                    "name": file_name,
                    "mimetype": att.get("mimetype"),
                    "size": att.get("file_size"),
                })
                raw = att.get("datas")
                if raw:
                    try:
                        (case_dir / file_name).write_bytes(base64.b64decode(raw))
                        log.info(f"    -> Saved attachment: {file_name}")
                    except Exception as e:
                        log.warning(f"    -> Could not save {file_name}: {e}")

        # Chatter messages
        messages = self.client.execute(
            "mail.message", "search_read",
            domain=[("model", "=", "repair.order"), ("res_id", "=", repair_id)],
            fields=["author_id", "date", "body", "message_type",
                    "subtype_id", "is_internal", "email_from"],
        )
        if messages:
            # Clean chatter messages
            clean_messages = [self.adapter.adapt_record(m) for m in messages]
            write_json(case_dir / "chatter.json", clean_messages)
            log.info(f"    -> Saved {len(messages)} messages to chatter.json")

        # Metadata
        repair["_attachments"] = attachment_meta
        clean_repair = self.adapter.adapt_record(repair)
        write_json(case_dir / "metadata.json", clean_repair)
        log.info(f"    -> Saved metadata.json")
