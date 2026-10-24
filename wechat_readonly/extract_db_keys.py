# -*- coding: utf-8 -*-
"""Extract + decrypt WeChat SQLCipher DBs via vendor wcdb_key_tool_windows.py (read-only)."""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
from common import load_config, setup_logging, subprocess_no_window_kwargs

ROOT = Path(__file__).resolve().parent
VENDOR = ROOT / "vendor" / "wcdb_key_tool_windows.py"

def run_extract(decrypt: bool = True) -> int:
    cfg = load_config()
    log = setup_logging("extract_db_keys")
    py = cfg.get("python_exe") or sys.executable
    keys = Path(cfg["keys_file"])
    keys.parent.mkdir(parents=True, exist_ok=True)
    cmd = [py, str(VENDOR), "extract", "--db-dir", cfg["db_storage_dir"], "--output", str(keys)]
    log.info("Running: %s", " ".join(cmd))
    r = subprocess.run(cmd, cwd=str(ROOT), **subprocess_no_window_kwargs())
    if r.returncode != 0:
        return r.returncode
    if decrypt:
        out = Path(cfg["decrypted_dir"])
        out.mkdir(parents=True, exist_ok=True)
        cmd2 = [py, str(VENDOR), "decrypt", "--db-dir", cfg["db_storage_dir"], "--keys", str(keys), "--output", str(out)]
        log.info("Running: %s", " ".join(cmd2))
        r2 = subprocess.run(cmd2, cwd=str(ROOT), **subprocess_no_window_kwargs())
        return r2.returncode
    return 0

if __name__ == "__main__":
    raise SystemExit(run_extract(decrypt="--no-decrypt" not in sys.argv))