"""测试加密页认证、SQLite WAL 提交边界与 ID→名称绑定，不使用真实联系人。"""
import hashlib
import hmac
import sqlite3
import struct
import tempfile
import unittest
from pathlib import Path

from Crypto.Cipher import AES
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"src"))
from wechat_photo_export.core import contacts as db


class TestContactDB(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.key = bytes(range(32))
        self.salt = bytes(range(16))

    def encrypted(self, content, number):
        start = 16 if number == 1 else 0
        iv = b"test fixture iv!"
        cipher = AES.new(self.key, AES.MODE_CBC, iv).encrypt(content[start:4016])
        signed = cipher+iv
        key = hashlib.pbkdf2_hmac("sha512", self.key,
                                  bytes(v ^ 0x3a for v in self.salt), 2, 32)
        digest = hmac.digest(key, signed+struct.pack("<I", number), "sha512")
        return (self.salt if number == 1 else b"")+signed+digest

    def test_authentication_rejects_wrong_key_tampering_and_wrong_page_number(self):
        page = self.encrypted(b"\0"*4096, 1)
        self.assertTrue(db.verify_key(self.key, page))
        self.assertFalse(db.verify_key(b"x"*32, page))
        bad = bytearray(page)
        bad[100] ^= 1
        self.assertFalse(db.verify_key(self.key, bytes(bad)))
        page2 = self.encrypted(b"\0"*4096, 2)
        self.assertFalse(db.verify_page(page2, 3, db.mac_key(self.key, self.salt)))

    def test_decryption_checks_every_page_and_restores_header(self):
        plain1 = b"SQLite format 3\0"+b"a"*4000+b"\0"*80
        plain2 = bytes(range(256))*15+b"b"*176+b"\0"*80
        raw = self.encrypted(plain1, 1)+self.encrypted(plain2, 2)
        target = self.root/"plain.db"
        self.assertEqual(db.decrypt_snapshot(raw, b"", self.key, target), 0)
        expected = plain1[:18]+b"\1\1"+plain1[20:]+plain2
        self.assertEqual(target.read_bytes(), expected)
        bad = bytearray(raw)
        bad[5000] ^= 1
        with self.assertRaises(ValueError):
            db.decrypt_snapshot(bytes(bad), b"", self.key, target)

    def sqlite_wal(self):
        path = self.root/"test.db"
        con = sqlite3.connect(path)
        self.addCleanup(con.close)
        con.execute("PRAGMA page_size=4096")
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA wal_autocheckpoint=0")
        con.execute("CREATE TABLE sample(value TEXT)")
        con.execute("INSERT INTO sample VALUES ('committed')")
        con.commit()
        return Path(str(path)+"-wal").read_bytes()

    def test_real_sqlite_wal_checksums_and_committed_pages(self):
        wal = self.sqlite_wal()
        pages, size = db.committed_wal_pages(wal)
        self.assertEqual(size, 2)
        self.assertIn(1, pages)
        self.assertIn(b"committed", pages[2])
        self.assertEqual(db.committed_wal_pages(wal+b"partial frame"), (pages, size))
        bad = bytearray(wal)
        bad[24] ^= 1
        with self.assertRaises(ValueError):
            db.committed_wal_pages(bad)

    def test_uncommitted_and_stale_wal_tail_ignored(self):
        wal = self.sqlite_wal()
        pages, size = db.committed_wal_pages(wal)
        last_header = len(wal)-4096-24
        state = struct.unpack_from(">II", wal, last_header+16)
        prefix = struct.pack(">II", 2, 0)
        content = b"x"*4096
        endian = "<" if struct.unpack_from(">I", wal)[0] == 0x377f0682 else ">"
        checksum = db.wal_checksum(prefix+content, state, endian)
        tail = prefix+wal[16:24]+struct.pack(">II", *checksum)+content
        self.assertEqual(db.committed_wal_pages(wal+tail), (pages, size))
        stale = bytearray(tail)
        stale[8] ^= 1
        self.assertEqual(db.committed_wal_pages(wal+stale), (pages, size))

    def test_wal_committed_encrypted_page_overrides_main_database(self):
        # 使用 SQLite 产生的合法 WAL 文件头，接入已认证的加密数据页。
        header = self.sqlite_wal()[:32]
        original = self.encrypted(b"\0"*4096, 1)
        replacement = self.encrypted(b"\1"*4096, 1)
        prefix = struct.pack(">II", 1, 1)
        endian = "<" if struct.unpack_from(">I", header)[0] == 0x377f0682 else ">"
        state = struct.unpack_from(">II", header, 24)
        checksum = db.wal_checksum(prefix+replacement, state, endian)
        wal = header+prefix+header[16:24]+struct.pack(">II", *checksum)+replacement
        target = self.root/"merged.db"
        self.assertEqual(db.decrypt_snapshot(original, wal, self.key, target), 1)
        self.assertEqual(target.read_bytes()[100:200], b"\1"*100)

    def test_contact_schema_and_remark_preference(self):
        path = self.root/"contacts.db"
        with sqlite3.connect(path) as con:
            con.execute("CREATE TABLE contact(username TEXT, nick_name TEXT, remark TEXT)")
            con.execute("INSERT INTO contact VALUES ('wxid_sample', '昵称', '备注')")
        con.close()
        rows = db.read_contacts(path)
        full_hash = hashlib.md5(b"wxid_sample").hexdigest()
        catalog = db.contact_catalog(rows, {full_hash})
        self.assertEqual(catalog[full_hash]["name"], "备注")
        self.assertEqual(catalog[full_hash]["id"], "wxid_sample")
        self.assertTrue(catalog[full_hash]["verified"])


if __name__ == "__main__":
    unittest.main()
