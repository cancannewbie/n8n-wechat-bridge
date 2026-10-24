# -*- coding: utf-8 -*-
"""Read decrypted WeChat message DBs for new group image messages (read-only)."""
from __future__ import annotations

import hashlib
import re
import sqlite3
import zstandard
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Optional

@dataclass
class ImageMessage:
    msgid: str
    talker: str
    group_name: str
    group_id: str
    sender_id: str
    sender_name: str
    create_time: int
    local_id: int
    server_id: int
    md5: str
    aeskey_cdn: str
    dat_path: Optional[Path]
    db_index: int
    table: str


def md5_hex(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def decompress_content(raw) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    data = bytes(raw)
    if data[:4] == b"\x28\xb5\x2f\xfd":
        data = zstandard.ZstdDecompressor().decompress(data, max_output_size=50 * 1024 * 1024)
    return data.decode("utf-8", errors="replace")


def parse_image_xml(content: str) -> tuple[str, str, str]:
    """Return (sender_prefix, md5, cdn_aeskey)."""
    sender = ""
    idx = content.find("<?xml")
    if idx > 0:
        sender = content[:idx].strip().rstrip(":").strip()
        content = content[idx:]
    md5 = ""
    m = re.search(r'\bmd5="([0-9a-fA-F]{32})"', content)
    if m:
        md5 = m.group(1).lower()
    aes = ""
    m = re.search(r'aeskey="([0-9a-fA-F]{32})"', content)
    if m:
        aes = m.group(1).lower()
    return sender, md5, aes


def fname_from_packed(packed: Optional[bytes]) -> str:
    if not packed:
        return ""
    m = re.search(rb"([0-9a-f]{32})", packed)
    return m.group(1).decode() if m else ""


class MessageScanner:
    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.decrypted = Path(cfg["decrypted_dir"])
        self.attach = Path(cfg["attach_dir"])
        self.contacts: dict[str, dict[str, str]] = {}
        self.dirmap: dict[int, str] = {}
        self._load_contacts()
        self._load_dirmap()

    def _load_contacts(self) -> None:
        db = self.decrypted / "contact" / "contact.db"
        if not db.exists():
            return
        conn = sqlite3.connect(str(db))
        try:
            for u, nick, remark in conn.execute("SELECT username, nick_name, remark FROM contact"):
                self.contacts[u] = {
                    "nick": nick or "",
                    "remark": remark or "",
                    "display": (remark or nick or u or ""),
                }
        finally:
            conn.close()

    def _load_dirmap(self) -> None:
        db = self.decrypted / "hardlink" / "hardlink.db"
        if not db.exists():
            return
        conn = sqlite3.connect(str(db))
        try:
            self.dirmap = {rid: name for rid, name in conn.execute("SELECT rowid, username FROM dir2id")}
        finally:
            conn.close()

    def resolve_dat_path(self, content_md5: str, packed_fname: str, talker_md5: str) -> Optional[Path]:
        # 1) hardlink by content md5
        db = self.decrypted / "hardlink" / "hardlink.db"
        if db.exists() and content_md5:
            conn = sqlite3.connect(str(db))
            try:
                rows = conn.execute(
                    "SELECT file_name, dir1, dir2 FROM image_hardlink_info_v4 WHERE md5=? ORDER BY rowid DESC LIMIT 8",
                    (content_md5,),
                ).fetchall()
            finally:
                conn.close()
            ranked = sorted(rows, key=lambda r: (0 if str(r[0]).endswith("_h.dat") else 1 if "_t" not in str(r[0]) else 2))
            for fn, d1, d2 in ranked:
                folder = self.dirmap.get(d1, "")
                month = self.dirmap.get(d2, "")
                # hardlink dirs sometimes swapped relative to path layout
                for a, b in ((folder, month), (month, folder)):
                    if not a or not b:
                        continue
                    cand = self.attach / a / b / "Img" / fn
                    if cand.exists():
                        return cand
                    # some layouts omit Img
                    cand2 = self.attach / a / b / fn
                    if cand2.exists():
                        return cand2
        # 2) by packed filename under talker folder
        names = []
        if packed_fname:
            names.extend([f"{packed_fname}_h.dat", f"{packed_fname}.dat", f"{packed_fname}_t.dat"])
        if content_md5:
            names.extend([f"{content_md5}_h.dat", f"{content_md5}.dat", f"{content_md5}_t.dat"])
        base = self.attach / talker_md5
        if base.exists():
            for n in names:
                hits = list(base.rglob(n))
                if hits:
                    hits.sort(key=lambda p: (0 if p.name.endswith("_h.dat") else 1 if "_t" not in p.name else 2, -p.stat().st_size))
                    return hits[0]
        # 3) global search by packed fname
        if packed_fname:
            hits = list(self.attach.rglob(f"{packed_fname}_h.dat")) or list(self.attach.rglob(f"{packed_fname}.dat")) or list(self.attach.rglob(f"{packed_fname}_t.dat"))
            if hits:
                hits.sort(key=lambda p: -p.stat().st_size)
                return hits[0]
        return None

    def iter_image_messages(self, since_ctime: int = 0) -> Iterator[ImageMessage]:
        groups_only = bool(self.cfg.get("groups_only", True))
        allow_names = set(self.cfg.get("group_allowlist") or [])
        allow_ids = set(self.cfg.get("group_allowlist_ids") or [])

        for mid in range(10):
            dbp = self.decrypted / "message" / f"message_{mid}.db"
            if not dbp.exists():
                continue
            conn = sqlite3.connect(str(dbp))
            try:
                n2 = {rid: uname for uname, rid in conn.execute("SELECT user_name, rowid FROM Name2Id")}
                # reverse md5 -> talker via n2 + contacts
                md5_to_user = {md5_hex(u): u for u in list(n2.values()) + list(self.contacts.keys())}
                tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'")]
                for table in tables:
                    talker_md5 = table[4:]
                    talker = md5_to_user.get(talker_md5, "")
                    is_group = talker.endswith("@chatroom") if talker else False
                    if groups_only and talker and not is_group:
                        continue
                    # if talker unknown, still try (may be group folder hash)
                    gname = self.contacts.get(talker, {}).get("display", "") if talker else ""
                    if allow_names or allow_ids:
                        ok = (gname in allow_names) or (talker in allow_ids) or (talker_md5 in allow_ids)
                        if not ok:
                            # if allowlist set and talker unknown, skip
                            continue
                    sql = (
                        f"SELECT local_id, server_id, real_sender_id, create_time, message_content, packed_info_data "
                        f"FROM {table} WHERE local_type=3 AND create_time>? ORDER BY create_time ASC"
                    )
                    for local_id, server_id, sid, ctime, mc, packed in conn.execute(sql, (since_ctime,)):
                        text = decompress_content(mc)
                        sender_prefix, content_md5, aes = parse_image_xml(text)
                        sender_id = n2.get(sid) or sender_prefix or str(sid)
                        sender_name = self.contacts.get(sender_id, {}).get("display", sender_id)
                        fname = fname_from_packed(packed if isinstance(packed, (bytes, bytearray)) else None)
                        dat_path = self.resolve_dat_path(content_md5, fname, talker_md5)
                        # If talker empty but path under attach/<hash>, treat hash as group folder
                        if not talker and dat_path is not None:
                            # parent chain: attach / hash / yyyy-mm / Img / file
                            try:
                                talker_md5 = dat_path.parts[-4]
                            except Exception:
                                pass
                        msgid = f"wximg-{mid}-{table}-{local_id}-{server_id}"
                        # infer is_group from talker or allow if groups_only and talker empty with @chatroom unknown
                        if groups_only and talker and not talker.endswith("@chatroom"):
                            continue
                        yield ImageMessage(
                            msgid=msgid,
                            talker=talker or talker_md5,
                            group_name=gname or talker or talker_md5,
                            group_id=talker or talker_md5,
                            sender_id=sender_id,
                            sender_name=sender_name,
                            create_time=int(ctime or 0),
                            local_id=int(local_id),
                            server_id=int(server_id or 0),
                            md5=content_md5,
                            aeskey_cdn=aes,
                            dat_path=dat_path,
                            db_index=mid,
                            table=table,
                        )
            finally:
                conn.close()