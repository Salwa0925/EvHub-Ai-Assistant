"""
extractor.py — raw PDF extraction (text, tables, images)
Output: raw/<start>_<end>.json  +  raw/images/*.png
Next:   classifier.py reads these files

Image strategy:
  pymupdf handles ALL image extraction directly — both raster and vector.
  For raster images: extracted directly from the PDF as-is.
  For vector graphics: the containing region is rendered to PNG via clip rect.
  Docling is NOT used for image detection — it misses vector graphics entirely.

Page numbering:
  Each page footer contains the manual page reference (e.g. EVC-11, GI-7).
  pymupdf reads the footer in the same pass as image extraction.
  Both pdf_page and manual_page are stamped on every element in the JSON.

Table strategy:
  TableFormer always runs — no conditional logic.
  OCR only triggers on scanned pages (char count below threshold).
"""

from __future__ import annotations
import gc, json, logging, re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz  # pymupdf — pip install pymupdf
from docling.datamodel.base_models import InputFormat
from docling.datamodel.document import TableItem, TextItem
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from pypdf import PdfReader

try:
    from docling.backend.docling_parse_v2 import DoclingParseV2DocumentBackend  # type: ignore[import-untyped]
    _BACKEND: Any = DoclingParseV2DocumentBackend
except ImportError:
    _BACKEND = None

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S", level=logging.INFO)
log = logging.getLogger("extractor")

_MANUAL_PAGE_RE = re.compile(r"\b([A-Z]{1,5}-\d{1,4})\b")


@dataclass
class Config:
    batch_size:      int   = 5
    img_scale:       float = 1.0
    page_render_dpi: int   = 150
    min_img_size:    int   = 50
    ocr_threshold:   int   = 50
    footer_height_pct: float = 0.08


def _converter(*, ocr: bool, cfg: Config) -> DocumentConverter:
    opts = PdfPipelineOptions()
    opts.do_ocr                  = ocr
    opts.do_table_structure      = True   # always on
    opts.images_scale            = cfg.img_scale
    opts.generate_page_images    = False
    opts.generate_picture_images = False
    kw: dict[str, Any] = {"pipeline_options": opts}
    if _BACKEND:
        kw["backend"] = _BACKEND
    return DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(**kw)})


def _read_footer(page: fitz.Page, footer_height_pct: float) -> tuple[str | None, str | None, str | None]:
    h      = page.rect.height
    footer = fitz.Rect(0, h * (1 - footer_height_pct), page.rect.width, h)
    text   = page.get_text("text", clip=footer).strip()
    match  = _MANUAL_PAGE_RE.search(text)
    if match:
        ref  = match.group(1)
        code = ref.split("-")[0]
        return ref, code, text
    return None, None, None


def _extract_page_pymupdf(pdf_path: Path, page_no: int,
                           image_dir: Path, cfg: Config) -> tuple[list[dict], str | None, str | None, str | None]:
    image_dir.mkdir(parents=True, exist_ok=True)
    images: list[dict] = []
    seen_rects: list[fitz.Rect] = []

    doc  = fitz.open(str(pdf_path))
    page = doc[page_no - 1]
    zoom = cfg.page_render_dpi / 72
    mat  = fitz.Matrix(zoom, zoom)

    manual_page, section_code, footer_text = _read_footer(page, cfg.footer_height_pct)

    for img_index, img in enumerate(page.get_images(full=True)):
        xref = img[0]
        try:
            extracted = doc.extract_image(xref)
        except Exception:
            continue

        w, h = extracted["width"], extracted["height"]
        if w < cfg.min_img_size or h < cfg.min_img_size:
            continue

        ext   = extracted["ext"]
        fname = f"page_{page_no}_raster_{img_index + 1}.{ext}"
        fpath = image_dir / fname
        if not fpath.exists():
            fpath.write_bytes(extracted["image"])

        bbox = None
        for item in page.get_image_info(xrefs=True):
            if item.get("xref") == xref:
                r    = fitz.Rect(item["bbox"])
                bbox = [r.x0, r.y0, r.x1, r.y1]
                seen_rects.append(r)
                break

        images.append({
            "file":         f"images/{fname}",
            "page_pdf":     page_no,
            "page_manual":  manual_page,
            "section_code": section_code,
            "bbox":         bbox,
            "caption":      "",
            "type":         "raster",
        })

    blocks    = page.get_text("dict", flags=fitz.TEXT_PRESERVE_IMAGES).get("blocks", [])
    vec_index = 0
    for block in blocks:
        if block.get("type") != 1:
            continue
        r = fitz.Rect(block["bbox"])
        if r.width < cfg.min_img_size or r.height < cfg.min_img_size:
            continue
        if any(r.intersects(seen) for seen in seen_rects):
            continue

        vec_index += 1
        fname = f"page_{page_no}_vector_{vec_index}.png"
        fpath = image_dir / fname
        if not fpath.exists():
            page.get_pixmap(matrix=mat, clip=fitz.Rect(block["bbox"])).save(str(fpath))

        images.append({
            "file":         f"images/{fname}",
            "page_pdf":     page_no,
            "page_manual":  manual_page,
            "section_code": section_code,
            "bbox":         [r.x0, r.y0, r.x1, r.y1],
            "caption":      "",
            "type":         "vector",
        })

    doc.close()
    return images, manual_page, section_code, footer_text


def _bbox(prov) -> list | None:
    b = getattr(prov[0], "bbox", None) if prov else None
    return [b.l, b.t, b.r, b.b] if b else None


def _page(prov) -> int | None:
    return getattr(prov[0], "page_no", None) if prov else None


def _extract_text_tables(result, page_map: dict[int, tuple]) -> tuple[list, list]:
    texts, tables = [], []
    for item, _ in result.document.iterate_items():
        prov   = getattr(item, "prov", [])
        pg     = _page(prov)
        manual, code, footer_text = page_map.get(pg, (None, None, None))

        if isinstance(item, TextItem):
            texts.append({
                "text":         item.text,
                "page_pdf":     pg,
                "page_manual":  manual,
                "section_code": code,
                "label":        item.label.value if item.label else None,
                "bbox":         _bbox(prov),
            })

        elif isinstance(item, TableItem):
            grid = [[c.text if c else "" for c in row]
                    for row in (item.data.grid if item.data else [])]
            tables.append({
                "page_pdf":     pg,
                "page_manual":  manual,
                "section_code": code,
                "bbox":         _bbox(prov),
                "num_rows":     len(grid),
                "num_cols":     len(grid[0]) if grid else 0,
                "data":         grid,
                "markdown":     item.export_to_markdown() if grid else "",
                "tableformer":  item.data is not None and len(grid) > 0,
            })

    return texts, tables


def _is_scanned(texts: list, threshold: int) -> bool:
    return sum(len(t["text"]) for t in texts) < threshold


def _process_batch(pdf: Path, s: int, e: int, out: Path, convs: dict, cfg: Config) -> bool:
    try:
        # ── pymupdf pass: images + footer reading ──────────────────────────────
        image_dir = out / "images"
        images:   list[dict]       = []
        page_map: dict[int, tuple] = {}

        for page_no in range(s, e + 1):
            page_imgs, manual, code, footer_text = _extract_page_pymupdf(pdf, page_no, image_dir, cfg)
            images.extend(page_imgs)
            page_map[page_no] = (manual, code, footer_text)
            if manual:
                log.info("  page %d -> %s", page_no, manual)
            else:
                log.warning("  page %d -> manual page ref not found in footer", page_no)

        # ── Docling: TableFormer always ON ─────────────────────────────────────
        log.info("Extracting pages %d-%d (TableFormer ON)", s, e)
        res = convs["tables_only"].convert(str(pdf), page_range=(s, e))
        texts, tables = _extract_text_tables(res, page_map)
        ran_ocr = False

        # ── OCR fallback for scanned pages ─────────────────────────────────────
        if _is_scanned(texts, cfg.ocr_threshold):
            log.info("  -> scanned pages detected, re-running with OCR")
            res = convs["ocr_tables"].convert(str(pdf), page_range=(s, e))
            texts, tables = _extract_text_tables(res, page_map)
            ran_ocr = True

        gc.collect()

        (out / f"{s}_{e}.json").write_text(
            json.dumps({
                "schema_version": "1.0",
                "extraction": {
                    "source_file":      pdf.name,
                    "vehicle":          next((v[2] for v in page_map.values() if len(v) > 2 and v[2]), None),
                    "page_start":       s,
                    "page_end":         e,
                    "ocr_used":         ran_ocr,
                    "tableformer_used": True,
                    "page_map":         {str(k): list(v) for k, v in page_map.items()},
                },
                "text_elements": texts,
                "tables":        tables,
                "images":        images,
            }, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        log.info("  -> text=%d tables=%d images=%d  ocr=%s",
                 len(texts), len(tables), len(images), ran_ocr)
        gc.collect()
        return True

    except Exception:
        log.exception("Failed pages %d-%d", s, e)
        return False


def run(pdf_path: str | Path, output_dir: str | Path = "raw", cfg: Config | None = None) -> bool:
    cfg = cfg or Config()
    pdf = Path(pdf_path)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    total = len(PdfReader(str(pdf)).pages)
    log.info("%s  -  %d pages", pdf.name, total)

    # Two converters — TableFormer always on, OCR optional
    convs = {
        "tables_only": _converter(ocr=False, cfg=cfg),
        "ocr_tables":  _converter(ocr=True,  cfg=cfg),
    }

    batches = [(s, min(s + cfg.batch_size - 1, total))
               for s in range(1, total + 1, cfg.batch_size)]

    pending = [(s, e) for s, e in batches if not (out / f"{s}_{e}.json").exists()]
    if len(pending) < len(batches):
        log.info("Resuming - skipping %d completed batches", len(batches) - len(pending))

    return all(_process_batch(pdf, s, e, out, convs, cfg) for s, e in pending) 