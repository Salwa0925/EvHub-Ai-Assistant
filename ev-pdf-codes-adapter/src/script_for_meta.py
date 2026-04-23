import fitz
import json
from pathlib import Path


base_dir = Path(__file__).resolve().parent
project_root = base_dir.parent
pdf_path = project_root / "manuals" / "PWO.pdf"
out_path = project_root / "data" /"PWO_metadata.json"

with fitz.open(pdf_path) as pdf:
    metadata = pdf.metadata

with open(out_path, "w", encoding="utf-8") as f:
    json.dump(metadata, f, indent=2, ensure_ascii=False)
print(f"Saved to {out_path}")