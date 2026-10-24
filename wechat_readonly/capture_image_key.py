# -*- coding: utf-8 -*-
"""Capture V2 image AES key from Weixin.exe memory (READ-ONLY).

IMPORTANT: While this script runs, open 2-3 chat images full-size in WeChat.
The AES key is only briefly present in memory when images are viewed.
XOR key is derived from JPEG EOI (usually 0xA6 on this account).

Based on public patterns from ZedeX/weixin-decrypte-script and ylytdeng/wechat-decrypt.
"""
from __future__ import annotations

import ctypes
import re
import struct
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

from Crypto.Cipher import AES
from Crypto.Util import Padding

from common import load_config, parse_int_maybe_hex, setup_logging
from dat_decrypt import V2_MAGIC, detect_image_format, decrypt_dat_file

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
MEM_COMMIT = 0x1000

class MBI(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
    ]

kernel32 = ctypes.windll.kernel32
RE16 = re.compile(rb"(?<![0-9A-Za-z])[0-9A-Za-z]{16}(?![0-9A-Za-z])")
RE32 = re.compile(rb"(?<![0-9A-Za-z])[0-9A-Za-z]{32}(?![0-9A-Za-z])")
MAGICS = [
    bytes([0xFF, 0xD8, 0xFF]),
    bytes([0x89, 0x50, 0x4E, 0x47]),
    b"GIF8",
    b"RIFF",
    b"BM",
    b"wxgf",
]


def weixin_pids() -> list[int]:
    r = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq Weixin.exe", "/FO", "CSV", "/NH"],
        capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    pids = []
    for line in r.stdout.strip().splitlines():
        if not line.strip():
            continue
        parts = line.strip('"').split('","')
        if len(parts) >= 2:
            pids.append(int(parts[1]))
    return pids


def derive_xor_key(attach_dir: Path) -> int:
    from collections import Counter
    c: Counter = Counter()
    files = sorted(attach_dir.rglob("*_t.dat"), key=lambda p: p.stat().st_mtime, reverse=True)[:40]
    for p in files:
        try:
            data = p.read_bytes()
        except OSError:
            continue
        if data[:6] != V2_MAGIC or len(data) < 2:
            continue
        x = data[-2] ^ 0xFF
        y = data[-1] ^ 0xD9
        if x == y:
            c[x] += 1
    if c:
        return c.most_common(1)[0][0]
    return 0xA6


def pick_ciphertext(attach_dir: Path) -> tuple[bytes, Path] | tuple[None, None]:
    # Prefer recent thumbnails (usually JPEG) then _h
    cands = sorted(attach_dir.rglob("*_t.dat"), key=lambda p: p.stat().st_mtime, reverse=True)[:80]
    cands += sorted(attach_dir.rglob("*_h.dat"), key=lambda p: p.stat().st_mtime, reverse=True)[:40]
    for p in cands:
        try:
            data = p.read_bytes()
        except OSError:
            continue
        if data[:6] == V2_MAGIC and len(data) >= 31:
            return data[15:31], p
    return None, None


def try_key(key: bytes, ciphertext: bytes) -> bool:
    try:
        pt = AES.new(key, AES.MODE_ECB).decrypt(ciphertext)
    except Exception:
        return False
    return any(pt.startswith(m[:3]) for m in MAGICS) or pt[:4] == b"wxgf"


def scan_pid(pid: int, ciphertext: bytes) -> str | None:
    h = kernel32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
    if not h:
        return None
    try:
        addr = 0
        mbi = MBI()
        while addr < 0x7FFFFFFFFFFF:
            if kernel32.VirtualQueryEx(h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)) == 0:
                break
            prot = mbi.Protect
            if (
                mbi.State == MEM_COMMIT
                and prot in (0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80)
                and mbi.RegionSize
                and mbi.RegionSize < 120 * 1024 * 1024
            ):
                buf = ctypes.create_string_buffer(mbi.RegionSize)
                n = ctypes.c_size_t(0)
                if kernel32.ReadProcessMemory(h, ctypes.c_void_p(mbi.BaseAddress), buf, mbi.RegionSize, ctypes.byref(n)):
                    mem = buf.raw[: n.value]
                    for rx in (RE16, RE32):
                        for m in rx.finditer(mem):
                            raw = m.group()
                            keys = [raw[:16]] if len(raw) == 16 else [raw[:16], raw[16:32]]
                            for key in keys:
                                if try_key(key, ciphertext):
                                    return key.decode("ascii")
            nxt = (mbi.BaseAddress or 0) + (mbi.RegionSize or 0)
            if nxt <= addr:
                break
            addr = nxt
    finally:
        kernel32.CloseHandle(h)
    return None


def save_keys(path: Path, aes_key: str, xor_key: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"aes_key={aes_key}\nxor_key=0x{xor_key:02x}\n", encoding="utf-8")


def load_keys(path: Path) -> tuple[str | None, int | None]:
    if not path.exists():
        return None, None
    aes = None
    xor = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("aes_key="):
            aes = line.split("=", 1)[1].strip()
        if line.startswith("xor_key="):
            xor = int(line.split("=", 1)[1].strip(), 0)
    return aes, xor


def main() -> int:
    cfg = load_config()
    log = setup_logging("capture_image_key")
    attach = Path(cfg["attach_dir"])
    out_keys = Path(cfg["image_keys_file"])
    xor_key = derive_xor_key(attach)
    log.info("Derived XOR key: 0x%02x", xor_key)

    ciphertext, sample = pick_ciphertext(attach)
    if ciphertext is None:
        log.error("No V2 .dat files found under %s", attach)
        return 1
    log.info("Using ciphertext from %s (%s)", sample, ciphertext.hex())

    existing_aes, existing_xor = load_keys(out_keys)
    if existing_aes and try_key(existing_aes.encode("ascii")[:16], ciphertext):
        log.info("Existing image key still valid: %s", existing_aes)
        if existing_xor is None:
            existing_xor = xor_key
        save_keys(out_keys, existing_aes, existing_xor)
        # decrypt sample
        dec = decrypt_dat_file(sample, Path(cfg["temp_image_dir"]) / f"keycheck_{sample.stem}", existing_aes, existing_xor)
        log.info("Sample decrypt: %s", dec)
        return 0

    print("=" * 60)
    print(" 请在微信中打开 2-3 张聊天图片（点开大图），保持本窗口运行")
    print(" Please open 2-3 full-size chat images in WeChat now")
    print("=" * 60)
    log.info("Monitoring Weixin.exe memory for V2 AES key... Ctrl+C to stop")

    scan_n = 0
    try:
        while True:
            scan_n += 1
            pids = weixin_pids()
            if not pids:
                log.warning("Weixin.exe not running")
                time.sleep(3)
                continue
            for pid in pids:
                aes = scan_pid(pid, ciphertext)
                if aes:
                    save_keys(out_keys, aes, xor_key)
                    log.info("FOUND aes_key=%s xor_key=0x%02x -> %s", aes, xor_key, out_keys)
                    dec = decrypt_dat_file(
                        sample,
                        Path(cfg["temp_image_dir"]) / f"captured_{sample.stem}",
                        aes,
                        xor_key,
                    )
                    log.info("Decrypted sample: %s", dec)
                    print(f"\n成功 / SUCCESS: aes_key={aes} xor_key=0x{xor_key:02x}")
                    print(f"已写入 {out_keys}")
                    return 0
            print(f"  scan #{scan_n} not found yet — open images in WeChat...", end="\r", flush=True)
            time.sleep(2)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())