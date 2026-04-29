import json

with open("data/2011 Nissan Leaf Workshop Manual for EVB/2011 Nissan Leaf Workshop Manual for EVB.json", encoding="utf-8") as f:
    data = json.load(f)

for record in data["records"]:
    for table in record.get("tables", []):
        sp = table.get("semantic_parse", {})
        if sp.get("status") == "partial":
            assert "quality_flags" in sp
            assert "raw_rows_preferred" in sp

    for group in record.get("table_groups", []):
        sp = group.get("semantic_parse", {})
        if sp.get("status") == "partial":
            assert "quality_flags" in sp
            assert "raw_rows_preferred" in sp

print("Validation passed")