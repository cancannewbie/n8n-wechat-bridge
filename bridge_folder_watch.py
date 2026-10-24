# -*- coding: utf-8 -*-
"""Watch a local folder and POST new images to the n8n WeChat webhook.

Usage (WeChat 4.x / any version):
1. Keep this script running.
2. In WeChat group, open an image -> 另存为 / 保存 -> save into inbox\\
   Or drag/copy the screenshot into inbox\\.
3. Optional: name file as 群名__发送人__备注.png so metadata is filled.
   Example: 采购群__张三__订单.png
"""
from __future__ import annotations

import shutil
import time
from datetime import datetime
from pathlib import Path

from bridge_common import load_config, post_image_file, setup_logging

logger = setup_logging("folder_watch")


def parse_meta_from_name(path: Path) -> tuple[str, str, str]:
    """Parse group__sender__note from filename stem.
    Returns (group_name, sender_name, text).
    """
    stem = path.stem
    parts = stem.split("__")
    if len(parts) >= 2:
        group = parts[0].strip()
        sender = parts[1].strip()
        note = "__".join(parts[2:]).strip() if len(parts) > 2 else ""
        return group, sender, note
    return "", "", ""


def is_stable(path: Path, wait: float = 0.8) -> bool:
    try:
        s1 = path.stat().st_size
        time.sleep(wait)
        s2 = path.stat().st_size
        return s1 == s2 and s1 > 0
    except OSError:
        return False


def move_processed(src: Path, processed_dir: Path) -> Path:
    processed_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = processed_dir / f"{stamp}_{src.name}"
    if dest.exists():
        dest = processed_dir / f"{stamp}_{src.stem}_{int(time.time())}{src.suffix}"
    shutil.move(str(src), str(dest))
    return dest


def main() -> None:
    cfg = load_config()
    watch_dir = Path(cfg["watch_dir"])
    processed_dir = Path(cfg["processed_dir"])
    watch_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)
    exts = {e.lower() for e in (cfg.get("image_extensions") or [])}
    poll = float(cfg.get("poll_seconds") or 2)

    logger.info("folder watch started: %s -> %s", watch_dir, cfg["webhook_url"])
    logger.info("group_allowlist=%s (empty=all)", cfg.get("group_allowlist"))
    seen: set[str] = set()

    while True:
        try:
            for path in sorted(watch_dir.iterdir()):
                if not path.is_file():
                    continue
                if path.suffix.lower() not in exts:
                    continue
                key = str(path.resolve())
                if key in seen:
                    continue
                if not is_stable(path):
                    continue
                group, sender, note = parse_meta_from_name(path)
                try:
                    result = post_image_file(
                        cfg,
                        path,
                        group_name=group,
                        sender_name=sender,
                        text=note,
                        logger=logger,
                    )
                    logger.info("accepted result=%s", result)
                    dest = move_processed(path, processed_dir)
                    logger.info("moved to %s", dest)
                    seen.discard(key)
                except PermissionError as e:
                    logger.warning("skipped filter: %s", e)
                    dest = move_processed(path, processed_dir)
                    logger.info("filtered file moved to %s", dest)
                except Exception as e:
                    logger.exception("post failed for %s: %s", path.name, e)
                    # leave file in inbox for retry; mark seen temporarily to avoid tight loop
                    seen.add(key)
                    # allow retry later
                    time.sleep(5)
                    seen.discard(key)
        except Exception:
            logger.exception("watch loop error")
        time.sleep(poll)


if __name__ == "__main__":
    main()
