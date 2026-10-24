# -*- coding: utf-8 -*-
"""Local Excel append API for n8n recognition results (销售单五列+嵌入图)."""
from __future__ import annotations

import base64
import io
import json
import logging
import re
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from openpyxl import Workbook, load_workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"
DEFAULT_XLSX = OUTPUT_DIR / "results.xlsx"
SALES_XLSX = OUTPUT_DIR / "results_销售单.xlsx"
IMG_DIR = OUTPUT_DIR / "sales_images"
HOST = "0.0.0.0"
PORT = 8787

LEGACY_HEADERS = [
    "time",
    "source",
    "group",
    "sender",
    "msgid",
    "status",
    "summary",
    "readable_text",
    "raw_file",
]

# business columns + embedded image column
SALES_HEADERS = [
    "商品编号",
    "商品名称",
    "数量",
    "备注",
    "摘要",
    "图片",
]

# row height / col width for embedded thumbs
IMG_COL_WIDTH = 18
IMG_ROW_HEIGHT = 80
IMG_DISPLAY_MAX = 96  # px

log_dir = ROOT / "logs"
log_dir.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_dir / "append_api.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("append_api")


def _headers_for(path: Path) -> list[str]:
    name = path.name
    if "销售单" in name or "sales" in name.lower():
        return list(SALES_HEADERS)
    return list(LEGACY_HEADERS)


def _migrate_sales_rows(old_path: Path, headers: list[str]) -> list[list[Any]]:
    out: list[list[Any]] = []
    try:
        wb_old = load_workbook(old_path)
        ws_old = wb_old.active
        old_headers = [str(c.value or "") for c in next(ws_old.iter_rows(min_row=1, max_row=1))]
        for row in ws_old.iter_rows(min_row=2, values_only=True):
            old = dict(zip(old_headers, row))
            out.append([old.get(h, "") or "" for h in headers])
    except Exception:
        logger.exception("migrate sales rows failed from %s", old_path)
    return out


def ensure_workbook(path: Path, headers: list[str] | None = None) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    headers = headers or _headers_for(path)
    is_sales = "商品编号" in headers and "摘要" in headers and "图片" in headers

    if path.exists():
        try:
            wb = load_workbook(path)
            ws = wb.active
            current = [str(c.value or "") for c in next(ws.iter_rows(min_row=1, max_row=1))]
            if current == headers:
                return
            if is_sales or ("商品编号" in headers and "摘要" in headers):
                bak = path.with_name(
                    path.stem + ".bak_" + datetime.now().strftime("%Y%m%d_%H%M%S") + path.suffix
                )
                path.replace(bak)
                wb2 = Workbook()
                ws2 = wb2.active
                ws2.title = "results"
                ws2.append(headers)
                _style_sales_sheet(ws2, headers)
                for values in _migrate_sales_rows(bak, headers):
                    if any(str(v).strip() for v in values if v is not None):
                        ws2.append(values)
                wb2.save(path)
                logger.info("rebuilt sales workbook %s headers=%s (backup %s)", path, headers, bak)
                return
            return
        except Exception:
            logger.exception("ensure_workbook inspect failed for %s", path)
            return

    wb = Workbook()
    ws = wb.active
    ws.title = "results"
    ws.append(headers)
    if is_sales or headers == SALES_HEADERS:
        _style_sales_sheet(ws, headers)
    wb.save(path)
    logger.info("created workbook %s", path)


def _style_sales_sheet(ws, headers: list[str]) -> None:
    for i, h in enumerate(headers, start=1):
        letter = get_column_letter(i)
        if h == "图片":
            ws.column_dimensions[letter].width = IMG_COL_WIDTH
        elif h == "摘要":
            ws.column_dimensions[letter].width = 48
        elif h == "商品名称":
            ws.column_dimensions[letter].width = 22
        elif h == "备注":
            ws.column_dimensions[letter].width = 24
        else:
            ws.column_dimensions[letter].width = 12


def _row_values(headers: list[str], row: dict[str, Any]) -> list[Any]:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    out = []
    for h in headers:
        if h == "time":
            out.append(row.get("time") or now)
        elif h == "readable_text":
            out.append(row.get("readable_text") or row.get("readableText") or "")
        elif h == "raw_file":
            out.append(row.get("raw_file") or row.get("rawFile") or "")
        elif h == "图片":
            # cell text left empty; image anchored separately
            out.append("")
        else:
            out.append(row.get(h) if row.get(h) is not None else "")
    return out


def _decode_image_bytes(row: dict[str, Any]) -> tuple[bytes | None, str]:
    """Return (bytes, ext) from row fields imageBase64 / image_base64 / imageDataUrl."""
    raw = (
        row.get("imageBase64")
        or row.get("image_base64")
        or row.get("image")
        or row.get("图片")
        or ""
    )
    mime = str(row.get("imageMime") or row.get("mimeType") or "").lower()
    if isinstance(raw, dict):
        raw = raw.get("data") or raw.get("base64") or ""
    s = str(raw).strip()
    if not s:
        return None, "jpg"
    if s.startswith("data:"):
        m = re.match(r"^data:([^;]+);base64,(.+)$", s, re.S)
        if m:
            mime = m.group(1).lower()
            s = m.group(2)
    # strip whitespace/newlines
    s = re.sub(r"\s+", "", s)
    try:
        data = base64.b64decode(s, validate=False)
    except Exception:
        logger.exception("base64 decode failed")
        return None, "jpg"
    if not data or len(data) < 32:
        return None, "jpg"
    ext = "jpg"
    if "png" in mime or data[:4] == b"\x89PNG":
        ext = "png"
    elif "gif" in mime or data[:3] == b"GIF":
        ext = "gif"
    elif "webp" in mime:
        ext = "webp"
    elif data[:3] == b"\xff\xd8\xff":
        ext = "jpg"
    return data, ext


def _embed_image(ws, row_idx: int, col_idx: int, data: bytes, ext: str, tag: str) -> str | None:
    """Embed image at cell (row_idx, col_idx). Returns saved path or None."""
    try:
        IMG_DIR.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^\w\-]+", "_", tag)[:40] or "img"
        fname = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe}_{row_idx}.{ext}"
        fpath = IMG_DIR / fname
        fpath.write_bytes(data)

        # Prefer Pillow resize via openpyxl Image
        img = XLImage(io.BytesIO(data))
        # scale to fit thumb
        try:
            w, h = float(img.width or 1), float(img.height or 1)
            scale = min(IMG_DISPLAY_MAX / w, IMG_DISPLAY_MAX / h, 1.0)
            img.width = max(1, int(w * scale))
            img.height = max(1, int(h * scale))
        except Exception:
            img.width = IMG_DISPLAY_MAX
            img.height = IMG_DISPLAY_MAX

        # anchor to cell (openpyxl uses 1-based row/col in anchor string like 'F2')
        cell_ref = f"{get_column_letter(col_idx)}{row_idx}"
        img.anchor = cell_ref
        ws.add_image(img)
        ws.row_dimensions[row_idx].height = IMG_ROW_HEIGHT
        return str(fpath)
    except Exception:
        logger.exception("embed image failed row=%s", row_idx)
        return None


def append_rows(path: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    headers = _headers_for(path)
    ensure_workbook(path, headers)
    wb = load_workbook(path)
    ws = wb.active
    current = [str(c.value or "") for c in next(ws.iter_rows(min_row=1, max_row=1))]
    if current != headers and headers == SALES_HEADERS:
        ensure_workbook(path, headers)
        wb = load_workbook(path)
        ws = wb.active
        current = [str(c.value or "") for c in next(ws.iter_rows(min_row=1, max_row=1))]
    use_headers = headers if headers == SALES_HEADERS else (current if current and any(current) else headers)
    if headers == SALES_HEADERS:
        _style_sales_sheet(ws, use_headers)

    img_col = None
    if "图片" in use_headers:
        img_col = use_headers.index("图片") + 1

    # shared image bytes for multi-line same order
    shared_bytes: bytes | None = None
    shared_ext = "jpg"
    for row in rows:
        b, e = _decode_image_bytes(row)
        if b:
            shared_bytes, shared_ext = b, e
            break

    start = ws.max_row
    embedded = 0
    saved_paths: list[str] = []
    for i, row in enumerate(rows):
        values = _row_values(use_headers, row)
        ws.append(values)
        row_idx = ws.max_row
        if img_col:
            b, e = _decode_image_bytes(row)
            if not b:
                b, e = shared_bytes, shared_ext
            if b:
                tag = str(row.get("商品编号") or row.get("msgid") or i)
                p = _embed_image(ws, row_idx, img_col, b, e, tag)
                if p:
                    embedded += 1
                    saved_paths.append(p)
                    # optional: put filename hint in cell (keeps column non-empty if image fails to show)
                    # leave blank so only picture shows

    saved_path = path
    try:
        tmp = path.with_suffix(path.suffix + ".tmp")
        wb.save(tmp)
        try:
            tmp.replace(path)
        except PermissionError:
            # Excel may lock the file; keep tmp as alternate writable copy
            alt = path.with_name(path.stem + "_写入中" + path.suffix)
            try:
                if alt.exists():
                    alt.unlink()
            except Exception:
                pass
            tmp.replace(alt)
            saved_path = alt
            logger.warning("target locked, wrote alternate %s", alt)
    except PermissionError:
        alt = path.with_name(path.stem + "_" + datetime.now().strftime("%H%M%S") + path.suffix)
        wb.save(alt)
        saved_path = alt
        logger.warning("save permission denied, wrote %s", alt)
    return {
        "ok": True,
        "path": str(saved_path),
        "row": ws.max_row,
        "rows_written": len(rows),
        "first_row": start + 1 if rows else start,
        "headers": use_headers,
        "images_embedded": embedded,
        "image_files": saved_paths[:5],
        "locked_fallback": str(saved_path) != str(path),
    }


def append_row(path: Path, row: dict[str, Any]) -> dict[str, Any]:
    return append_rows(path, [row])


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/health", "/"):
            self._send(
                200,
                {
                    "ok": True,
                    "service": "n8n-excel-append",
                    "xlsx": str(DEFAULT_XLSX),
                    "sales_xlsx": str(SALES_XLSX),
                    "sales_headers": SALES_HEADERS,
                },
            )
            return
        self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path != "/append":
            self._send(404, {"ok": False, "error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            body = json.loads(raw.decode("utf-8") or "{}")
            if not isinstance(body, dict):
                raise ValueError("body must be a JSON object")
            xlsx = Path(body.get("path") or DEFAULT_XLSX)
            if not str(xlsx).lower().startswith(str(ROOT).lower()):
                name = Path(str(body.get("path") or "")).name
                if name:
                    xlsx = OUTPUT_DIR / name
                else:
                    xlsx = DEFAULT_XLSX
            rows = body.get("rows")
            # top-level image applies to all rows if row lacks one
            top_img = {
                k: body[k]
                for k in ("imageBase64", "image_base64", "imageMime", "mimeType", "image")
                if k in body
            }
            if isinstance(rows, list) and rows:
                cleaned = []
                for r in rows:
                    if not isinstance(r, dict):
                        continue
                    merged = dict(r)
                    for k, v in top_img.items():
                        merged.setdefault(k, v)
                    cleaned.append(merged)
                result = append_rows(xlsx, cleaned)
            else:
                if "销售单" in xlsx.name or "sales" in xlsx.name.lower():
                    keep = {h: body.get(h, "") for h in SALES_HEADERS if h != "图片"}
                    keep.update(top_img)
                    # also allow imageBase64 on body
                    for k in ("imageBase64", "image_base64", "imageMime", "mimeType"):
                        if k in body:
                            keep[k] = body[k]
                    body = keep
                result = append_row(xlsx, body)
            logger.info(
                "appended path=%s rows=%s last=%s imgs=%s",
                result.get("path"),
                result.get("rows_written"),
                result.get("row"),
                result.get("images_embedded"),
            )
            self._send(200, result)
        except Exception as exc:  # noqa: BLE001
            logger.exception("append failed")
            self._send(500, {"ok": False, "error": str(exc)})

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.info("%s - %s", self.address_string(), fmt % args)


def main() -> None:
    ensure_workbook(DEFAULT_XLSX, LEGACY_HEADERS)
    ensure_workbook(SALES_XLSX, SALES_HEADERS)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    logger.info(
        "listening on http://%s:%s  xlsx=%s sales=%s headers=%s",
        HOST,
        PORT,
        DEFAULT_XLSX,
        SALES_XLSX,
        SALES_HEADERS,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
