# -*- coding: utf-8 -*-
"""Shared helpers for n8n WeChat image bridge."""
from __future__ import annotations

import base64
import json
import logging
import mimetypes
import uuid
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def setup_logging(name: str = "bridge") -> logging.Logger:
    log_dir = ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    fh = logging.FileHandler(log_dir / f"{name}.log", encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


def group_allowed(cfg: dict[str, Any], group_name: str) -> bool:
    allow = cfg.get("group_allowlist") or []
    if not allow:
        return True
    return group_name in allow


def sender_allowed(cfg: dict[str, Any], sender_name: str) -> bool:
    allow = cfg.get("sender_allowlist") or []
    if not allow:
        return True
    return sender_name in allow


def file_to_payload(
    cfg: dict[str, Any],
    image_path: Path,
    *,
    group_name: str = "",
    group_id: str = "",
    sender_name: str = "",
    sender_id: str = "",
    text: str = "",
    msgid: str | None = None,
) -> dict[str, Any]:
    data = image_path.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    mime, _ = mimetypes.guess_type(str(image_path))
    if not mime:
        mime = "application/octet-stream"
    gname = group_name or cfg.get("default_group_name") or ""
    sname = sender_name or cfg.get("default_sender_name") or "unknown"
    return {
        "source": cfg.get("source", "wechat"),
        "chatType": cfg.get("chat_type", "group"),
        "groupName": gname,
        "groupId": group_id or "",
        "senderName": sname,
        "senderId": sender_id or "",
        "msgType": "image",
        "text": text or "",
        "imageBase64": b64,
        "imageMime": mime,
        "imageFileName": image_path.name,
        "msgid": msgid or f"local-{uuid.uuid4().hex}",
        "localPath": str(image_path),
    }


def post_image_payload(
    cfg: dict[str, Any],
    payload: dict[str, Any],
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    url = cfg["webhook_url"]
    timeout = int(cfg.get("request_timeout_seconds") or 60)
    log = logger or setup_logging()
    log.info(
        "POST %s msgid=%s group=%s sender=%s",
        url,
        payload.get("msgid"),
        payload.get("groupName"),
        payload.get("senderName"),
    )
    resp = requests.post(url, json=payload, timeout=timeout)
    body_text = resp.text
    log.info("HTTP %s body=%s", resp.status_code, body_text[:500])
    try:
        body = resp.json()
    except Exception:
        body = {"raw": body_text}
    if resp.status_code >= 400:
        raise RuntimeError(f"webhook HTTP {resp.status_code}: {body_text[:300]}")
    return body if isinstance(body, dict) else {"result": body}


def post_image_file(
    cfg: dict[str, Any],
    image_path: Path,
    *,
    group_name: str = "",
    sender_name: str = "",
    text: str = "",
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    g = group_name or cfg.get("default_group_name") or ""
    s = sender_name or cfg.get("default_sender_name") or ""
    if not group_allowed(cfg, g):
        raise PermissionError(f"group not allowed: {g}")
    if not sender_allowed(cfg, s):
        raise PermissionError(f"sender not allowed: {s}")
    payload = file_to_payload(
        cfg,
        image_path,
        group_name=group_name,
        sender_name=sender_name,
        text=text,
    )
    return post_image_payload(cfg, payload, logger=logger)
