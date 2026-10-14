"""会话身份和可移植目录名称。"""
import re

DIRTY = re.compile(r"[\x00-\x1f\x7f]")
_BAD = '\\/:*?"<>|\r\n\t'
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}

def sanitize(name: str, maxlen: int = 40) -> str:
    """移除控制字符、替换非法字符，并处理 Windows 保留名称。"""
    s = "".join("" if ord(c) < 0x20 or ord(c) == 0x7f else ("_" if c in _BAD else c)
                for c in (name or "").strip())
    s = s.strip(" .")                       # 首尾空格和点不合法
    s = s[:maxlen].strip(" .")
    if s.upper() in _RESERVED:
        s = "_" + s
    return s

def trusted_name(info):
    return bool(info and info.get("name") and
                (info.get("source") == "user" or
                 (info.get("source") == "db" and info.get("verified") is True)))


def session_metadata(full_hash, names):
    info = names.get(full_hash[:16], {})
    if info.get("hash") and info["hash"] != full_hash:
        raise ValueError("名字表与源目录的完整 hash 不一致")
    valid = trusted_name(info)
    return {"hash": full_hash, "id": info.get("id", ""),
            "name": info.get("name", "") if valid else "",
            "source": info.get("source", "none") if valid else "none",
            "is_chatroom": info.get("is_chatroom"), "named": valid, "confident": valid,
            "verified": valid, "candidates": info.get("candidates", [])}
