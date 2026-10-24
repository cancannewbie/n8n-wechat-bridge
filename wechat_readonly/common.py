# -*- coding: utf-8 -*-
from __future__ import annotations
import json, logging, subprocess, sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"

def subprocess_no_window_kwargs() -> dict[str, Any]:
    """Windows: hide console for child processes (ffmpeg/python/tasklist)."""
    if sys.platform != "win32":
        return {}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0  # SW_HIDE
    return {"creationflags": flags, "startupinfo": si}

def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8-sig") as f:
        return json.load(f)

def setup_logging(name: str = "wechat_readonly") -> logging.Logger:
    cfg = load_config()
    log_dir = Path(cfg.get("state_dir") or (ROOT / "state")) / ".." / "logs"
    log_dir = (ROOT / "logs")
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

def parse_int_maybe_hex(v, default=0xA6) -> int:
    if v is None:
        return default
    if isinstance(v, int):
        return v
    s = str(v).strip().lower()
    return int(s, 0) if s.startswith("0x") else int(s)