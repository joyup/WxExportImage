# -*- coding: utf-8 -*-
"""读取本机联系人库的独立模块。密钥仅留在内存，不打印或持久化。

SQLCipher 4 / SQLite WAL 格式：
https://www.zetetic.net/sqlcipher/design/
https://www.sqlite.org/fileformat2.html#wal_file_format
Config.Cipher 对象布局参考 wechatauto-replica 的公开实现（仅使用格式信息）：
https://github.com/fanyuantaier/wechatauto-replica/blob/d6e61bea7f9c75906faa8b71d37ef3572fba2454/wechatauto/db.py
布局可能随微信版本变化；所有候选必须通过目标数据库页的 HMAC 验证。
"""
import hashlib
import hmac
import re
import sqlite3
import struct
from pathlib import Path

PAGE_SIZE = 4096
RESERVED = 80
CIPHER_NAME = b"com.Tencent.WCDB.Config.Cipher"
CIPHER_MASK = bytes.fromhex("d2c7442458020000004889442450488b450048844c2448488944254048584c24")
HEX_KEY = re.compile(rb"[xX]'([0-9a-fA-F]{64,192})'")


def mac_key(key, salt):
    return hashlib.pbkdf2_hmac("sha512", key, bytes(b ^ 0x3a for b in salt), 2, 32)


def verify_page(page, number, signing_key):
    if len(page) != PAGE_SIZE:
        return False
    start = 16 if number == 1 else 0
    digest = hmac.new(signing_key, page[start:PAGE_SIZE-64] + struct.pack("<I", number),
                      hashlib.sha512).digest()
    return hmac.compare_digest(digest, page[-64:])


def verify_key(key, page):
    return len(key) == 32 and verify_page(page, 1, mac_key(key, page[:16]))


def read_snapshot(path):
    """数据库与 WAL 均复制进内存，采集期间发生变化则重试。"""
    path = Path(path)
    wal = Path(str(path) + "-wal")
    def stamp(p):
        try:
            st = p.stat()
            return st.st_size, st.st_mtime_ns
        except FileNotFoundError:
            return None
    for _ in range(3):
        before = stamp(path), stamp(wal)
        raw = path.read_bytes()
        log = wal.read_bytes() if before[1] else b""
        if before == (stamp(path), stamp(wal)):
            return raw, log
    raise RuntimeError("联系人库正在持续写入，未取得稳定快照，请稍后重试")


def wal_checksum(blob, state, endian):
    s1, s2 = state
    for x, y in struct.iter_unpack(endian+"II", blob):
        s1 = (s1+x+s2) & 0xffffffff
        s2 = (s2+y+s1) & 0xffffffff
    return s1, s2


def committed_wal_pages(wal):
    """只采用校验通过、salt 匹配并已提交的 WAL 帧。尾部旧帧不参与。"""
    if not wal:
        return {}, None
    if len(wal) < 32:
        raise ValueError("WAL 文件头不完整")
    magic, version, size = struct.unpack_from(">III", wal)
    if magic not in (0x377f0682, 0x377f0683) or version != 3007000 or size != PAGE_SIZE:
        raise ValueError("不支持的 WAL 格式")
    endian = "<" if magic == 0x377f0682 else ">"
    state = wal_checksum(wal[:24], (0, 0), endian)
    if state != struct.unpack_from(">II", wal, 24):
        raise ValueError("WAL 文件头校验失败")
    frames, committed, count = [], 0, None
    step = PAGE_SIZE+24
    for off in range(32, len(wal)-step+1, step):
        header, page = wal[off:off+24], wal[off+24:off+step]
        if header[8:16] != wal[16:24]:
            break
        state = wal_checksum(header[:8] + page, state, endian)
        if state != struct.unpack_from(">II", header, 16):
            break
        number, db_size = struct.unpack_from(">II", header)
        if number == 0:
            break
        frames.append((number, page))
        if db_size:
            committed, count = len(frames), db_size
    return dict(frames[:committed]), count


def decrypt_snapshot(raw, wal, key, destination):
    """校验每个有效页，生成独立 SQLite 副本；不写微信源数据库。"""
    from Crypto.Cipher import AES
    if len(raw) % PAGE_SIZE or not verify_key(key, raw[:PAGE_SIZE]):
        raise ValueError("联系人库密钥或文件格式验证失败")
    replacements, size = committed_wal_pages(wal)
    size = size or len(raw)//PAGE_SIZE
    signing_key = mac_key(key, raw[:16])
    from contextlib import nullcontext
    with (nullcontext(destination) if hasattr(destination, "write") else open(destination, "wb")) as out:
        for number in range(1, size+1):
            page = replacements.get(number, raw[(number-1)*PAGE_SIZE:number*PAGE_SIZE])
            if not verify_page(page, number, signing_key):
                raise ValueError("联系人库第 %s 页校验失败" % number)
            start = 16 if number == 1 else 0
            iv = page[-RESERVED:-64]
            plain = AES.new(key, AES.MODE_CBC, iv).decrypt(page[start:-RESERVED])
            if number == 1:
                plain = b"SQLite format 3\0" + plain
                plain = plain[:18] + b"\1\1" + plain[20:]
            out.write(plain + b"\0"*RESERVED)
    return len(replacements)


def read_contacts(path):
    """从已验证的只读 SQLite 副本读取联系人，先执行数据库完整性检查。"""
    uri = Path(path).resolve().as_uri()+"?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    try:
        if connection.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise ValueError("联系人库完整性检查失败")
        columns = {r[1] for r in connection.execute("PRAGMA table_info(contact)")}
        if not {"username", "nick_name", "remark"} <= columns:
            raise ValueError("联系人表缺少 username/nick_name/remark 字段")
        rows = connection.execute("SELECT username, nick_name, remark FROM contact").fetchall()
        return [dict(zip(("username", "nick_name", "remark"), row)) for row in rows]
    finally:
        connection.close()


def contact_catalog(rows, hashes):
    catalog = {}
    seen = {}
    for row in rows:
        sid = row.get("username")
        if not isinstance(sid, str) or not sid:
            continue
        full_hash = hashlib.md5(sid.encode()).hexdigest()
        if full_hash in seen and seen[full_hash] != row:
            raise ValueError("duplicate_contact")
        seen[full_hash] = row
        name = row.get("remark") or row.get("nick_name") or ""
        if full_hash in hashes and isinstance(name, str) and name.strip():
            catalog[full_hash] = {"hash": full_hash, "id": sid, "name": name.strip(),
                "source": "db", "verified": True, "is_chatroom": sid.endswith("@chatroom"),
                "aliases": [v for v in (row.get("remark"), row.get("nick_name")) if isinstance(v, str) and v]}
    return catalog


def extract_contacts_memory(database, key):
    """解密副本仅在内存中，避免向系统临时目录写入明文联系人库。"""
    import io
    raw, wal = read_snapshot(database)
    target = io.BytesIO()
    decrypt_snapshot(raw, wal, key, target)
    connection = sqlite3.connect(":memory:")
    try:
        connection.deserialize(target.getvalue())
        connection.execute("PRAGMA query_only=ON")
        if connection.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise ValueError("database_integrity")
        columns = {r[1] for r in connection.execute("PRAGMA table_info(contact)")}
        if not {"username", "nick_name", "remark"} <= columns:
            raise ValueError("contact_schema")
        rows = connection.execute("SELECT username, nick_name, remark FROM contact").fetchall()
        return [dict(zip(("username", "nick_name", "remark"), row)) for row in rows]
    finally:
        connection.close()
