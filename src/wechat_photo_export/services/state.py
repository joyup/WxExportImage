"""每个账号独立的 SQLite 元数据。这里不保存明文密钥。"""
import hashlib
import json
import re
import sqlite3
from pathlib import Path

from ..core.errors import AppError
from ..core.files import no_links
from ..core.identity import DIRTY, session_metadata
from .accounts import state_home


class State:
    def __init__(self, account, home=None):
        self.directory = no_links((Path(home) if home else state_home())/"accounts"/account.uid)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = no_links(self.directory/"state.sqlite3")
        self.connection = sqlite3.connect(self.path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS names(hash TEXT, source TEXT, record TEXT,
                PRIMARY KEY(hash, source));
            CREATE TABLE IF NOT EXISTS exports(output TEXT, item TEXT, target TEXT, digest TEXT,
                status TEXT, code TEXT, PRIMARY KEY(output, item));
        """)

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def names(self):
        result = {}
        records = self.connection.execute("SELECT hash,source,record FROM names ORDER BY source")
        for full_hash, source, raw in records:
            try:
                record = json.loads(raw)
                self.validate_name(full_hash, source, record)
                record.update(hash=full_hash, source=source, verified=True)
                previous = result.get(full_hash[:16], {})
                if previous.get("hash", full_hash) != full_hash:
                    raise ValueError("hash_prefix_collision")
                record["aliases"] = sorted(set(record.get("aliases", [])+previous.get("aliases", [])+
                    ([previous["name"]] if previous.get("name") else [])))
                result[full_hash[:16]] = record
            except (ValueError, TypeError, KeyError, AttributeError):
                raise AppError("cache_invalid") from None
        return result

    @staticmethod
    def validate_name(full_hash, source, record):
        if not re.fullmatch(r"[0-9a-f]{32}", full_hash) or source not in ("db", "user"):
            raise ValueError("identity")
        if record.get("hash", full_hash) != full_hash:
            raise ValueError("identity")
        name = record.get("name")
        if not isinstance(name, str) or not name.strip() or DIRTY.search(name):
            raise ValueError("name")
        sid = record.get("id", "")
        if source == "db" and (not sid or record.get("verified") is not True):
            raise ValueError("database_identity")
        if sid and hashlib.md5(sid.encode()).hexdigest() != full_hash:
            raise ValueError("identity")
        if any(not isinstance(v, str) or DIRTY.search(v) for v in record.get("aliases", [])):
            raise ValueError("alias")

    def replace_database_names(self, catalog):
        for full_hash, record in catalog.items():
            self.validate_name(full_hash, "db", record)
        with self.connection:
            self.connection.execute("DELETE FROM names WHERE source='db'")
            self.connection.executemany("INSERT INTO names VALUES (?, 'db', ?)",
                [(h, json.dumps(v, ensure_ascii=False)) for h, v in catalog.items()])

    def confirm_name(self, full_hash, name):
        old = self.names().get(full_hash[:16], {})
        session_metadata(full_hash, {full_hash[:16]: old})
        record = dict(old, hash=full_hash, name=name.strip(), source="user", verified=True)
        self.validate_name(full_hash, "user", record)
        with self.connection:
            self.connection.execute("INSERT OR REPLACE INTO names VALUES (?, 'user', ?)",
                                    (full_hash, json.dumps(record, ensure_ascii=False)))

    def exported(self, output, item):
        return self.connection.execute("SELECT target,digest,status,code FROM exports WHERE output=? AND item=?",
                                      (str(output), item)).fetchone()

    def record(self, output, item, target, digest, status, code=""):
        with self.connection:
            self.connection.execute("INSERT OR REPLACE INTO exports VALUES (?,?,?,?,?,?)",
                (str(output), item, target, digest, status, code))
