import re
from datetime import datetime

class RecordAdapter:
    """
    Cleans and standardizes Odoo JSON records.
    """
    
    INTERNAL_FIELDS = {
        "__last_update", 
        "message_follower_ids", 
        "message_ids", 
        "message_main_attachment_id",
        "access_token",
        "write_uid",
        "create_uid",
    }

    def adapt_record(self, record: dict) -> dict:
        """
        Process a single Odoo record.
        """
        if not isinstance(record, dict):
            return record

        clean_record = {}
        for key, value in record.items():
            if key in self.INTERNAL_FIELDS:
                continue
            
            # 1. Format Relational Fields [ID, "Name"]
            if isinstance(value, (list, tuple)) and len(value) == 2 and isinstance(value[0], int) and isinstance(value[1], str):
                clean_record[key] = {"id": value[0], "name": value[1]}
            
            # 2. Standardize Dates
            elif isinstance(value, str):
                clean_record[key] = self._standardize_date(value)
            
            # 3. Recursive cleanup for lists of records (e.g. one2many fields)
            elif isinstance(value, list):
                clean_record[key] = [self.adapt_record(item) if isinstance(item, dict) else item for item in value]
            
            else:
                clean_record[key] = value
                
        return clean_record

    def _standardize_date(self, value: str) -> str:
        """
        Convert Odoo date strings to ISO 8601.
        """
        # Match Odoo datetime: YYYY-MM-DD HH:MM:SS
        if re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", value):
            try:
                dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
                return dt.isoformat() + "Z"
            except ValueError:
                pass
        
        # Match Odoo date: YYYY-MM-DD
        if re.match(r"^\d{4}-\d{2}-\d{2}$", value):
            try:
                dt = datetime.strptime(value, "%Y-%m-%d")
                return dt.date().isoformat()
            except ValueError:
                pass
                
        return value
