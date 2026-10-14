"""图片格式、解密和版本策略。没有平台或用户目录依赖。"""
import os
import struct

V2_MAGIC = b"\x07\x08V2\x08\x07"

def decrypt_v2(raw: bytes, aes_key: bytes, xor_key: int):
    """V2：AES-128-ECB 段、可选明文中段和 XOR 尾段。"""
    if len(raw) < 15 or raw[:6] != V2_MAGIC:
        return None
    aes_size = struct.unpack("<I", raw[6:10])[0]
    xor_size = struct.unpack("<I", raw[10:14])[0]
    data = raw[15:]
    total = len(data)
    blocks = (aes_size // 16 + 1) * 16        # ← 关键: +1 padding 块
    if blocks > total or xor_size > total-blocks:
        return None
    from Crypto.Cipher import AES
    head = AES.new(aes_key, AES.MODE_ECB).decrypt(data[:blocks])[:aes_size]
    # XOR 只作用于尾段，中间区域保持原样。
    # 忽略 xor_size 会破坏中间数据，却仍可能通过文件头检测。
    boundary = total-xor_size
    middle = data[blocks:boundary]
    tail = bytes(b ^ xor_key for b in data[boundary:])
    return head + middle + tail

def decrypt_any(path, aes_key, xor_key):
    """自动判定 V2 / 纯XOR, 返回 (bytes, fmt)"""
    try:
        with open(path, "rb") as stream:
            raw = stream.read(128*1024*1024+1)
        if len(raw) > 128*1024*1024:
            return None, "too_large"
    except Exception:
        return None, "unreadable"
    d = decrypt_v2(raw, aes_key, xor_key)
    if d is not None:
        return d, sniff(d)
    d = bytes(b ^ xor_key for b in raw)
    f = sniff(d)
    if not f.startswith("unknown"):
        return d, f
    return None, "unknown"

def sniff(d: bytes) -> str:
    for magic, name in ((b"\xff\xd8\xff", "jpg"), (b"\x89PNG", "png"), (b"wxgf", "wxgf"),
                        (b"GIF8", "gif"), (b"RIFF", "webp"), (b"BM", "bmp")):
        if d.startswith(magic):
            return name
    return "unknown:" + d[:4].hex()

def img_rank(fn: str) -> int:
    """图片版本优先级：高清 _h 为 3，大图 _W 为 2，普通版为 1，缩略图为 0。

    仅 _h / _W 允许导出；同一 fileId 优先保留 _h。
    """
    b = fn[:-4]
    if b.endswith("_t_W") or b.endswith("_t") or "_t_" in b:
        return 0
    if b.endswith("_h") or "_h_" in b:
        return 3
    if b.endswith("_W"):
        return 2
    return 1

def fid_of(fn: str) -> str:
    """取 fileId(剥掉 _t_W / _t / _h / _W 版本后缀)"""
    b = fn[:-4]
    for suf in ("_t_W", "_t", "_h", "_W"):
        if b.endswith(suf):
            return b[:-len(suf)]
    return b

def pick_best(files):
    """同一 fileId 只保留最高的 _h/_W 版本。普通版和缩略图均丢弃。"""
    g = {}
    for p in files:
        fn = os.path.basename(p)
        f = fid_of(fn)
        r = img_rank(fn)
        if not is_orig(fn):
            continue
        if f not in g or r > g[f][1]:
            g[f] = (p, r)
    return [(v[0], f, v[1]) for f, v in g.items()]

def is_orig(fn: str) -> bool:
    """允许导出的高清/大图版本: _h 或 _W, 不含普通版和缩略图。"""
    return img_rank(fn) >= 2

EXT = {"jpg": ".jpg", "png": ".png", "gif": ".gif", "bmp": ".bmp", "webp": ".webp", "wxgf": ".wxgf"}
