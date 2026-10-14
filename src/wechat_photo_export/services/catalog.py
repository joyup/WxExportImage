"""后台会话扫描、可信名称刷新；目录遍历拒绝链接。"""
import os
from dataclasses import dataclass

from ..core.contacts import contact_catalog, extract_contacts_memory
from ..core.errors import AppError
from ..core.files import child, is_link, no_links
from ..core.identity import session_metadata
from ..core.selection import source_sessions


@dataclass(frozen=True)
class Session:
    full_hash: str
    name: str
    kind: str
    source: str
    aliases: tuple = ()


def dat_files(root, cancelled=lambda: False):
    root = no_links(root)
    for directory, dirs, files in os.walk(root, followlinks=False):
        if cancelled():
            raise AppError("cancelled")
        dirs[:] = sorted(d for d in dirs if not is_link(child(root, os.path.relpath(os.path.join(directory, d), root))))
        for filename in sorted(files):
            if filename.lower().endswith(".dat"):
                path = child(root, os.path.relpath(os.path.join(directory, filename), root))
                if not is_link(path):
                    yield path


def sessions(account, state):
    names = state.names()
    result = []
    for full_hash in source_sessions(account.attach):
        child(account.attach, full_hash)
        info = session_metadata(full_hash, names)
        kind = {True: "群聊", False: "单聊", None: "待识别"}[info["is_chatroom"]]
        result.append(Session(full_hash, info["name"] or "未命名会话", kind, info["source"],
                              tuple(names.get(full_hash[:16], {}).get("aliases", []))))
    return sorted(result, key=lambda row: (row.name.casefold(), row.full_hash))


def refresh_names(account, state, cancelled=lambda: False, progress=lambda _: None):
    from ..platforms.memory import find_contact_key
    from ..platforms.windows import process_paths
    database = child(account.root, "db_storage/contact/contact.db")
    if not database.is_file():
        raise AppError("contact_key_unavailable")
    pids = process_paths()
    if not pids:
        raise AppError("wechat_not_running")
    with database.open("rb") as stream:
        page = stream.read(4096)
    progress("正在验证会话名称（只读）")
    key, _ = find_contact_key(page, pids, cancelled=cancelled, progress=lambda _: None)
    if key is None:
        raise AppError("contact_key_unavailable")
    if cancelled():
        raise AppError("cancelled")
    rows = extract_contacts_memory(database, key)
    catalog = contact_catalog(rows, set(source_sessions(account.attach)))
    if cancelled():
        raise AppError("cancelled")
    state.replace_database_names(catalog)
    return sessions(account, state)
