# -*- coding: utf-8 -*-
"""统一解析导出范围：全部会话、精确群名或会话编号。"""
import argparse
import difflib
import hashlib
import re
import unicodedata
from pathlib import Path

from .identity import session_metadata, trusted_name


def add_selection_args(parser):
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--all", action="store_true", help="导出全部会话（默认）")
    mode.add_argument("--group", action="append", metavar="群名",
                      help="按完整群名精确选择；可重复指定多个群")
    mode.add_argument("--session", action="append", metavar="会话编号",
                      help="按 hash16/hash32 或真实会话 ID 选择，可重复指定")
    parser.add_argument("--list-groups", action="store_true", help="列出本地已识别群后退出")


def positive_int(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("必须是正整数")
    return number


def source_sessions(attach):
    if not attach or not Path(attach).is_dir():
        raise ValueError("未找到微信图片目录")
    sessions = sorted(p.name for p in Path(attach).iterdir()
                      if p.is_dir() and re.fullmatch(r"[0-9a-f]{32}", p.name))
    if len({h[:16] for h in sessions}) != len(sessions):
        raise ValueError("源会话 hash 前缀冲突，禁止合并")
    return sessions


def normalize(name):
    return unicodedata.normalize("NFC", name.strip())


def group_names(info):
    """名称与别名只能来自可信记录；聊天类型不明的会话不能猜为群聊。"""
    if not trusted_name(info) or info.get("is_chatroom") is not True:
        return set()
    return {normalize(n) for n in [info["name"], *info.get("aliases", [])]
            if isinstance(n, str) and n.strip()}


def select_sessions(sessions, names, groups=None, identifiers=None):
    """先验证全部选择；缺失或重名时不返回任何部分结果。"""
    selected = set()
    labels = {}
    for full_hash in sessions:
        info = names.get(full_hash[:16], {})
        session_metadata(full_hash, names)
        for label in group_names(info):
            labels.setdefault(label, set()).add(full_hash)
    for group in groups or []:
        label = normalize(group)
        matches = labels.get(label, set())
        if not matches:
            similar = difflib.get_close_matches(label, sorted(labels), n=3, cutoff=0.5)
            hint = "；相近群名："+"、".join(similar) if similar else ""
            raise ValueError("未找到已识别群名「%s」%s。请先刷新会话名称，"
                             "或按会话编号选择。" % (group, hint))
        if len(matches) > 1:
            choices = "\n".join("  --session "+h[:16] for h in sorted(matches))
            raise ValueError("群名「%s」对应多个会话，请按编号选择：\n%s" % (group, choices))
        selected.update(matches)
    for identifier in identifiers or []:
        value = identifier.strip()
        if re.fullmatch(r"[0-9a-fA-F]{16}|[0-9a-fA-F]{32}", value):
            matches = [h for h in sessions if h.startswith(value.lower())]
        else:
            full_hash = hashlib.md5(value.encode("utf-8")).hexdigest()
            matches = [h for h in sessions if h == full_hash]
        if len(matches) != 1:
            raise ValueError("未找到唯一的本地会话：" + identifier)
        selected.update(matches)
    return sorted(selected) if groups or identifiers else list(sessions)
