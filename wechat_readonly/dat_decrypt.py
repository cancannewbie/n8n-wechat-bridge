# -*- coding: utf-8 -*-
"""Decrypt WeChat .dat images (XOR / V1 / V2). Patterns from ZedeX/weixin-decrypte-script."""
from __future__ import annotations

import re
import struct
from pathlib import Path
from typing import Optional, Tuple

from Crypto.Cipher import AES
from Crypto.Util import Padding

V2_MAGIC = b"\x07\x08V2\x08\x07"
V1_MAGIC = b"\x07\x08V1\x08\x07"
IMAGE_MAGIC = {
    "png": bytes([0x89, 0x50, 0x4E, 0x47]),
    "gif": b"GIF8",
    "jpg": bytes([0xFF, 0xD8, 0xFF]),
    "bmp": b"BM",
    "webp": b"RIFF",
}


def detect_image_format(header: bytes) -> str:
    if header[:3] == IMAGE_MAGIC["jpg"]:
        return "jpg"
    if header[:4] == IMAGE_MAGIC["png"]:
        return "png"
    if header[:3] == b"GIF":
        return "gif"
    if header[:2] == b"BM":
        return "bmp"
    if header[:4] == b"RIFF" and len(header) >= 12 and header[8:12] == b"WEBP":
        return "webp"
    if header[:4] == b"wxgf":
        return "hevc"
    # Annex-B HEVC/H.265 bitstream
    if header[:4] == bytes([0, 0, 0, 1]) or header[:3] == bytes([0, 0, 1]):
        return "hevc"
    return "bin"


def detect_xor_key(data: bytes) -> Optional[int]:
    if len(data) < 4 or data[:4] == b"\x07\x08V2" or data[:4] == b"\x07\x08V1":
        return None
    for magic in IMAGE_MAGIC.values():
        key = data[0] ^ magic[0]
        if all((data[i] ^ key) == magic[i] for i in range(len(magic)) if i < len(data)):
            return key
    return None


def xor_decrypt(data: bytes, key: Optional[int] = None) -> Optional[bytes]:
    if key is None:
        key = detect_xor_key(data)
    if key is None:
        return None
    return bytes(b ^ key for b in data)


def normalize_aes_key(aes_key) -> Optional[bytes]:
    if aes_key is None:
        return None
    if isinstance(aes_key, bytes):
        return aes_key[:16] if len(aes_key) >= 16 else None
    s = str(aes_key).strip()
    if re.fullmatch(r"[0-9a-fA-F]{32}", s):
        return bytes.fromhex(s)
    if len(s) >= 16:
        return s.encode("ascii", errors="ignore")[:16]
    return None


def v2_decrypt(data: bytes, aes_key, xor_key: int = 0xA6) -> Optional[bytes]:
    if len(data) < 15:
        return None
    sig = data[:6]
    if sig not in (V2_MAGIC, V1_MAGIC):
        return None
    aes_size, xor_size = struct.unpack_from("<LL", data, 6)
    key = b"cfcd208495d565ef" if sig == V1_MAGIC else normalize_aes_key(aes_key)
    if key is None:
        return None
    aligned = aes_size - ~(~aes_size % 16)
    offset = 15
    if offset + aligned > len(data):
        return None
    aes_data = data[offset : offset + aligned]
    try:
        dec_aes = Padding.unpad(AES.new(key[:16], AES.MODE_ECB).decrypt(aes_data), AES.block_size)
    except (ValueError, KeyError):
        return None
    offset += aligned
    raw_end = len(data) - xor_size
    raw = data[offset:raw_end] if offset < raw_end else b""
    xor_data = data[raw_end:]
    return dec_aes + raw + bytes(b ^ xor_key for b in xor_data)


def decrypt_dat_bytes(data: bytes, aes_key=None, xor_key: int = 0xA6) -> Optional[Tuple[bytes, str]]:
    head = data[:6]
    if head in (V2_MAGIC, V1_MAGIC):
        out = v2_decrypt(data, aes_key, xor_key)
    else:
        out = xor_decrypt(data)
    if not out:
        return None
    return out, detect_image_format(out[:16])


def decrypt_dat_file(path: Path, out_path: Optional[Path] = None, aes_key=None, xor_key: int = 0xA6) -> Optional[Path]:
    data = Path(path).read_bytes()
    result = decrypt_dat_bytes(data, aes_key=aes_key, xor_key=xor_key)
    if not result:
        return None
    blob, fmt = result
    if out_path is None:
        out_path = Path(path).with_suffix("." + fmt)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(blob)
    return out_path
