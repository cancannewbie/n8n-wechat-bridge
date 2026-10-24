# -*- coding: utf-8 -*-
"""Ensure decrypted WeChat blobs are standard JPEG/PNG/GIF/WEBP for LLM APIs.

Aligned with PROMPT_完整规范.md format pipeline:
- Trust magic bytes only
- Convert wxgf / HEVC / BMP / unknown via ffmpeg to JPEG
- Re-verify magic after conversion
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Tuple

from dat_decrypt import detect_image_format
from common import subprocess_no_window_kwargs

MIME = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
}

STANDARD = frozenset({"jpg", "png", "gif", "webp"})

DEFAULT_FFMPEG = (
    r"C:\Users\Administrator\AppData\Local\Microsoft\WinGet\Packages"
    r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
    r"\ffmpeg-8.1.1-full_build\bin\ffmpeg.exe"
)


def resolve_ffmpeg(configured: Optional[str] = None) -> Optional[str]:
    candidates = []
    if configured:
        candidates.append(configured)
    which = shutil.which("ffmpeg")
    if which:
        candidates.append(which)
    candidates.append(DEFAULT_FFMPEG)
    for c in candidates:
        if c and Path(c).is_file():
            return str(Path(c))
    return None


def looks_like_hevc(blob: bytes, fmt: str = "") -> bool:
    if fmt in ("hevc", "wxgf"):
        return True
    if not blob:
        return False
    if blob[:4] == b"wxgf":
        return True
    # Annex-B NAL start codes
    if blob[:4] == b"\x00\x00\x00\x01" or blob[:3] == b"\x00\x00\x01":
        return True
    # Sometimes length-prefixed HEVC with NAL type in low bits — heuristic only
    if len(blob) > 8 and blob[4:8] == b"\x00\x00\x00\x01":
        return True
    return False


def _run_ffmpeg(cmd: list, dst: Path, timeout: int = 60) -> Tuple[bool, str]:
    if dst.exists():
        try:
            dst.unlink()
        except OSError:
            pass
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
            **subprocess_no_window_kwargs(),
        )
    except Exception as e:
        return False, str(e)
    if proc.returncode == 0 and dst.exists() and dst.stat().st_size > 100:
        out = dst.read_bytes()
        if detect_image_format(out[:16]) == "jpg":
            return True, ""
        return False, "ffmpeg wrote non-JPEG magic=" + detect_image_format(out[:16])
    err = (proc.stderr or b"").decode("utf-8", errors="replace")[:300]
    return False, err or f"exit={proc.returncode}"


def ensure_standard_image(
    blob: bytes,
    fmt_hint: str = "",
    ffmpeg_path: Optional[str] = None,
    work_dir: Optional[Path] = None,
) -> Tuple[bytes, str, str]:
    """Return (bytes, fmt, mime). Convert wxgf/hevc/bmp/unknown via ffmpeg when needed.

    Raises ValueError with a clear Chinese message if conversion is impossible.
    """
    if not blob or len(blob) < 16:
        raise ValueError("FMT_INVALID: 图片数据过短或为空，无法识别格式")

    fmt = detect_image_format(blob[:32])
    if fmt_hint in ("hevc", "wxgf") and fmt == "bin":
        fmt = "hevc"

    if fmt in STANDARD:
        return blob, fmt, MIME[fmt]

    # BMP → always convert to JPEG for model compatibility
    need_convert = fmt in ("bmp", "hevc", "bin") or looks_like_hevc(blob, fmt)
    if not need_convert:
        raise ValueError(
            f"FMT_INVALID: 不支持的图片魔数（检测为 {fmt}，字节={len(blob)}）。"
            "禁止把未知二进制当作 PNG/JPEG 送给模型。"
        )

    ffmpeg = resolve_ffmpeg(ffmpeg_path)
    if not ffmpeg:
        raise ValueError(
            "FMT_NO_FFMPEG: 图片为微信 wxgf/HEVC/BMP 等非标准格式，但未找到 ffmpeg，"
            "无法转换为 JPEG。请安装 ffmpeg 或在 config.json 配置 ffmpeg_path。"
        )

    work = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="wximg_"))
    work.mkdir(parents=True, exist_ok=True)
    is_hevc = looks_like_hevc(blob, fmt)
    src_name = "src.hevc" if is_hevc else ("src.bmp" if fmt == "bmp" else "src.bin")
    src = work / src_name
    dst = work / "out.jpg"
    src.write_bytes(blob)

    attempts: list[list[str]] = [
        [ffmpeg, "-y", "-v", "error", "-i", str(src), "-frames:v", "1", "-q:v", "2", str(dst)],
    ]
    if is_hevc:
        attempts.append(
            [ffmpeg, "-y", "-v", "error", "-f", "hevc", "-i", str(src), "-frames:v", "1", "-q:v", "2", str(dst)]
        )
    if blob[:4] == b"wxgf":
        for skip in (4, 16, 32, 38, 64, 80, 96):
            if skip >= len(blob):
                break
            stripped = work / f"strip_{skip}.bin"
            stripped.write_bytes(blob[skip:])
            attempts.append(
                [ffmpeg, "-y", "-v", "error", "-i", str(stripped), "-frames:v", "1", "-q:v", "2", str(dst)]
            )
            attempts.append(
                [
                    ffmpeg,
                    "-y",
                    "-v",
                    "error",
                    "-f",
                    "hevc",
                    "-i",
                    str(stripped),
                    "-frames:v",
                    "1",
                    "-q:v",
                    "2",
                    str(dst),
                ]
            )

    last_err = ""
    for cmd in attempts:
        ok, err = _run_ffmpeg(cmd, dst)
        if ok:
            out = dst.read_bytes()
            # Final magic gate
            if detect_image_format(out[:16]) != "jpg":
                last_err = "post-check magic failed"
                continue
            return out, "jpg", MIME["jpg"]
        last_err = err

    raise ValueError(
        "FMT_INVALID: 微信图片疑似 wxgf/HEVC，ffmpeg 转 JPEG 失败："
        + (last_err or "unknown")
        + "。请重发图片或检查 ffmpeg；监控不会把假 PNG 送给模型。"
    )
