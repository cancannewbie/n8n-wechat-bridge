# -*- coding: utf-8 -*-
"""Poll decrypted WeChat DBs for new group images -> decrypt -> POST n8n webhook.

READ-ONLY towards WeChat: no send, no inject for outbound.
"""
from __future__ import annotations

import atexit
import base64
import json
import mimetypes
import os
import sys
import time
from pathlib import Path

import requests

from capture_image_key import load_keys
from common import load_config, parse_int_maybe_hex, setup_logging
from dat_decrypt import decrypt_dat_bytes, detect_image_format
from image_convert import ensure_standard_image
from extract_db_keys import run_extract
from message_scanner import MessageScanner


def _pid_path(cfg: dict) -> Path:
    return Path(cfg["state_dir"]) / "monitor.pid"


def write_pid(cfg: dict) -> None:
    p = _pid_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(str(os.getpid()), encoding="utf-8")


def clear_pid(cfg: dict) -> None:
    p = _pid_path(cfg)
    try:
        if p.exists() and p.read_text(encoding="utf-8").strip() == str(os.getpid()):
            p.unlink()
    except OSError:
        pass


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"last_ctime": 0, "processed": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"last_ctime": 0, "processed": []}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # keep processed list bounded
    processed = state.get("processed") or []
    if len(processed) > 5000:
        processed = processed[-3000:]
        state["processed"] = processed
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def build_payload(cfg: dict, msg, image_bytes: bytes, image_name: str, mime: str) -> dict:
    return {
        "source": cfg.get("source", "wechat"),
        "chatType": cfg.get("chat_type", "group"),
        "groupName": msg.group_name or "",
        "groupId": msg.group_id or "",
        "senderName": msg.sender_name or "",
        "senderId": msg.sender_id or "",
        "msgType": "image",
        "text": "",
        "imageBase64": base64.b64encode(image_bytes).decode("ascii"),
        "imageMime": mime,
        "imageFileName": image_name,
        "msgid": msg.msgid,
        "createTime": msg.create_time,
        "localDatPath": str(msg.dat_path) if msg.dat_path else "",
    }


def post_webhook(cfg: dict, payload: dict, log) -> dict:
    url = cfg["webhook_url"]
    timeout = int(cfg.get("request_timeout_seconds") or 60)
    log.info("POST %s msgid=%s group=%s sender=%s", url, payload.get("msgid"), payload.get("groupName"), payload.get("senderName"))
    resp = requests.post(url, json=payload, timeout=timeout)
    text = resp.text
    log.info("HTTP %s body=%s", resp.status_code, text[:500])
    try:
        body = resp.json()
    except Exception:
        body = {"raw": text}
    if resp.status_code >= 400:
        raise RuntimeError(f"webhook HTTP {resp.status_code}: {text[:300]}")
    return body if isinstance(body, dict) else {"result": body}


def refresh_dbs(cfg: dict, log) -> None:
    if not cfg.get("decrypt_db_on_start", True):
        return
    log.info("Refreshing DB keys + decrypt snapshot...")
    code = run_extract(decrypt=True)
    if code != 0:
        log.warning("extract/decrypt returned %s (will use existing decrypted files if present)", code)


def process_once(cfg: dict, state: dict, log) -> int:
    keys_file = Path(cfg["image_keys_file"])
    aes_key, xor_from_file = load_keys(keys_file)
    xor_key = xor_from_file if xor_from_file is not None else parse_int_maybe_hex(cfg.get("xor_key"), 0xA6)
    if not aes_key:
        log.warning("No V2 image AES key yet. Run capture_image_key.py after opening images in WeChat.")

    scanner = MessageScanner(cfg)
    last_ctime = int(state.get("last_ctime") or 0)
    if last_ctime == 0:
        # first run: do not backfill unless lookback set
        lookback = int(cfg.get("lookback_seconds_on_first_run") or 0)
        if lookback > 0:
            last_ctime = int(time.time()) - lookback
        else:
            # set watermark to now so only future messages are processed
            # but still allow manual smoke via --smoke
            state["last_ctime"] = int(time.time())
            return 0

    processed = set(state.get("processed") or [])
    dry_run = bool(cfg.get("dry_run", True))
    temp_dir = Path(cfg["temp_image_dir"])
    temp_dir.mkdir(parents=True, exist_ok=True)
    n_ok = 0
    max_ctime = last_ctime

    for msg in scanner.iter_image_messages(since_ctime=last_ctime):
        max_ctime = max(max_ctime, msg.create_time)
        if msg.msgid in processed:
            continue
        if not msg.dat_path or not msg.dat_path.exists():
            log.info("SKIP no dat yet msgid=%s group=%s md5=%s", msg.msgid, msg.group_name, msg.md5)
            # do not mark processed — wait for download
            continue
        data = msg.dat_path.read_bytes()
        head = data[:6]
        need_aes = head in (b"\x07\x08V2\x08\x07",)
        if need_aes and not aes_key:
            log.warning("SKIP V2 needs AES key: %s", msg.dat_path)
            continue
        result = decrypt_dat_bytes(data, aes_key=aes_key, xor_key=xor_key)
        if not result:
            log.warning("Decrypt failed: %s", msg.dat_path)
            processed.add(msg.msgid)
            continue
        blob, fmt0 = result
        try:
            blob, fmt, mime = ensure_standard_image(
                blob,
                fmt_hint=fmt0,
                ffmpeg_path=cfg.get("ffmpeg_path"),
                work_dir=temp_dir / "_convert",
            )
        except ValueError as e:
            log.error("SKIP bad image format msgid=%s path=%s err=%s", msg.msgid, msg.dat_path, e)
            processed.add(msg.msgid)  # permanent FMT_*
            continue
        # Belt-and-suspenders: never POST non-standard magic
        magic = detect_image_format(blob[:16] if blob else b"")
        if magic not in ("jpg", "png", "gif", "webp"):
            log.error(
                "SKIP post-convert magic gate msgid=%s decrypted_fmt=%s final_magic=%s size=%s",
                msg.msgid, fmt0, magic, len(blob or b""),
            )
            processed.add(msg.msgid)
            continue
        out_name = f"{msg.create_time}_{msg.local_id}.{fmt}"
        out_path = temp_dir / out_name
        out_path.write_bytes(blob)
        log.info(
            "Format pipeline msgid=%s decrypted=%s final=%s mime=%s bytes=%s",
            msg.msgid, fmt0, fmt, mime, len(blob),
        )
        payload = build_payload(cfg, msg, blob, out_name, mime)
        payload["imageFormat"] = fmt
        payload["decryptedFormat"] = fmt0
        if dry_run:
            log.info(
                "DRY_RUN would POST group=%s sender=%s file=%s size=%s msgid=%s",
                msg.group_name, msg.sender_name, out_path, len(blob), msg.msgid,
            )
            # write meta sidecar
            (temp_dir / (out_name + ".json")).write_text(
                json.dumps({k: v for k, v in payload.items() if k != "imageBase64"}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            processed.add(msg.msgid)
            n_ok += 1
        else:
            try:
                body = post_webhook(cfg, payload, log)
                log.info("Webhook result: %s", body)
                processed.add(msg.msgid)
                n_ok += 1
            except Exception as e:
                # WEBHOOK_TRANSIENT: do not mark processed — retry next poll
                log.error(
                    "WEBHOOK_TRANSIENT msgid=%s will retry: %s",
                    msg.msgid, e,
                )

    state["last_ctime"] = max(max_ctime, last_ctime)
    state["processed"] = list(processed)
    return n_ok


def smoke_one(cfg: dict, log, force_post: bool = False) -> int:
    """Decrypt newest resolvable group image; optionally POST once."""
    keys_file = Path(cfg["image_keys_file"])
    aes_key, xor_from_file = load_keys(keys_file)
    xor_key = xor_from_file if xor_from_file is not None else parse_int_maybe_hex(cfg.get("xor_key"), 0xA6)
    scanner = MessageScanner(cfg)
    msgs = list(scanner.iter_image_messages(since_ctime=0))
    msgs.sort(key=lambda m: m.create_time, reverse=True)
    n_path = sum(1 for m in msgs if m.dat_path)
    n_v2 = 0
    for m in msgs[:200]:
        if m.dat_path and m.dat_path.exists() and m.dat_path.read_bytes()[:6] == b"\x07\x08V2\x08\x07":
            n_v2 += 1
    log.info("Smoke: %s image msgs, %s with dat path, ~%s V2 among first200-with-check; aes_key=%s", len(msgs), n_path, n_v2, bool(aes_key))

    for msg in msgs[:80]:
        if not msg.dat_path or not msg.dat_path.exists():
            continue
        data = msg.dat_path.read_bytes()
        if data[:6] == b"\x07\x08V2\x08\x07" and not aes_key:
            continue
        result = decrypt_dat_bytes(data, aes_key=aes_key, xor_key=xor_key)
        if not result:
            continue
        blob, fmt = result
        try:
            blob, fmt, mime = ensure_standard_image(
                blob,
                fmt_hint=fmt,
                ffmpeg_path=cfg.get("ffmpeg_path"),
                work_dir=Path(cfg["temp_image_dir"]) / "_convert",
            )
        except ValueError as e:
            log.warning("Smoke convert failed: %s", e)
            continue
        out = Path(cfg["temp_image_dir"]) / f"smoke_{msg.create_time}_{msg.local_id}.{fmt}"
        out.write_bytes(blob)
        log.info("Smoke decrypted OK: %s (%s bytes) group=%s sender=%s", out, len(blob), msg.group_name, msg.sender_name)
        payload = build_payload(cfg, msg, blob, out.name, mime)
        dry = bool(cfg.get("dry_run", True)) and not force_post
        if dry:
            log.info("Smoke DRY_RUN (set dry_run=false or pass --post to POST)")
            (out.with_suffix(out.suffix + ".json")).write_text(
                json.dumps({k: v for k, v in payload.items() if k != "imageBase64"}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return 0
        body = post_webhook(cfg, payload, log)
        log.info("Smoke POST result: %s", body)
        return 0

    # Fallback: old XOR .dat (pre-V2) to prove decrypt+webhook path while waiting for V2 key
    attach = Path(cfg["attach_dir"])
    xor_files = sorted([p for p in attach.rglob("*.dat") if p.read_bytes()[:4] not in (b"\x07\x08V2", b"\x07\x08V1")], key=lambda p: p.stat().st_mtime, reverse=True)[:20]
    meta = next((m for m in msgs if m.group_name), None)
    for xp in xor_files:
        result = decrypt_dat_bytes(xp.read_bytes(), xor_key=xor_key)
        if not result:
            continue
        blob, fmt = result
        out = Path(cfg["temp_image_dir"]) / f"smoke_xor_fallback.{fmt}"
        out.write_bytes(blob)
        log.warning("V2 AES key missing; XOR-fallback decrypted %s -> %s (%s bytes)", xp.name, out, len(blob))
        if meta is None:
            return 0
        payload = build_payload(cfg, meta, blob, out.name, mimetypes.guess_type(out.name)[0] or "application/octet-stream")
        payload["msgid"] = f"smoke-xor-{xp.stem}"
        payload["text"] = "[poc-xor-fallback] waiting for V2 image AES key via capture_image_key.py"
        dry = bool(cfg.get("dry_run", True)) and not force_post
        if dry:
            (out.with_suffix(out.suffix + ".json")).write_text(
                json.dumps({k: v for k, v in payload.items() if k != "imageBase64"}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            log.info("Smoke XOR-fallback DRY_RUN ok")
            return 0
        body = post_webhook(cfg, payload, log)
        log.info("Smoke XOR-fallback POST result: %s", body)
        return 0

    log.error("Smoke failed: need capture_image_key.py (open 2-3 images in WeChat)")
    return 1


def main(argv: list[str]) -> int:
    cfg = load_config()
    log = setup_logging("monitor")
    state_path = Path(cfg["state_dir"]) / "monitor_state.json"

    if "--extract-only" in argv:
        return run_extract(decrypt=True)

    if "--smoke" in argv:
        refresh_dbs(cfg, log)
        return smoke_one(cfg, log, force_post=("--post" in argv))

    write_pid(cfg)
    atexit.register(clear_pid, cfg)
    refresh_dbs(cfg, log)
    state = load_state(state_path)
    interval = float(cfg.get("poll_interval_seconds") or 5)
    log.info(
        "Monitor start dry_run=%s allowlist=%s interval=%ss webhook=%s",
        cfg.get("dry_run"), cfg.get("group_allowlist"), interval, cfg.get("webhook_url"),
    )
    # refresh decrypted DBs periodically
    last_refresh = time.time()
    try:
        while True:
            if time.time() - last_refresh > 60:
                try:
                    refresh_dbs(cfg, log)
                except Exception as e:
                    log.warning("refresh_dbs failed: %s", e)
                last_refresh = time.time()
            try:
                n = process_once(cfg, state, log)
                save_state(state_path, state)
                if n:
                    log.info("Processed %s image(s) this round", n)
            except Exception as e:
                log.exception("process_once crashed (will continue): %s", e)
                try:
                    save_state(state_path, state)
                except Exception:
                    pass
            time.sleep(interval)
    except KeyboardInterrupt:
        log.info("Stopped")
        save_state(state_path, state)
        return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))