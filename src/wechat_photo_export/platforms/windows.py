"""Windows x64 适配：进程只读、系统保护密钥、本机组件路径。"""
import ctypes
import json
import os
import re
import struct
import time
from collections import Counter
from ctypes import wintypes as wt
from pathlib import Path

from ..core.errors import AppError
from ..core.files import atomic_write, no_links
from ..core.images import V2_MAGIC, sniff


def require_windows():
    if os.name != "nt" or struct.calcsize("P") != 8:
        raise AppError("platform_unsupported")


def process_paths():
    require_windows()
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    class Entry(ctypes.Structure):
        _fields_ = [("size", wt.DWORD), ("usage", wt.DWORD), ("pid", wt.DWORD),
            ("heap", ctypes.c_size_t), ("module", wt.DWORD), ("threads", wt.DWORD),
            ("parent", wt.DWORD), ("priority", wt.LONG), ("flags", wt.DWORD),
            ("exe", wt.WCHAR*260)]
    api.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
    api.CreateToolhelp32Snapshot.restype = wt.HANDLE
    api.Process32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(Entry)]
    api.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(Entry)]
    api.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    api.OpenProcess.restype = wt.HANDLE
    api.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
    api.CloseHandle.argtypes = [wt.HANDLE]
    snapshot = api.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        return {}
    found = {}
    entry = Entry()
    entry.size = ctypes.sizeof(entry)
    try:
        more = api.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            if entry.exe.casefold() == "weixin.exe":
                handle = api.OpenProcess(0x1000, False, entry.pid)
                if handle:
                    try:
                        buf, size = ctypes.create_unicode_buffer(32768), wt.DWORD(32768)
                        if api.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                            found[entry.pid] = Path(buf.value)
                    finally:
                        api.CloseHandle(handle)
            more = api.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        api.CloseHandle(snapshot)
    return found


def wechat_version():
    paths = process_paths()
    if not paths:
        return "未运行"
    try:
        path = str(next(iter(paths.values())))
        api = ctypes.WinDLL("version", use_last_error=True)
        api.GetFileVersionInfoSizeW.argtypes = [wt.LPCWSTR, ctypes.POINTER(wt.DWORD)]
        api.GetFileVersionInfoW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p]
        api.VerQueryValueW.argtypes = [ctypes.c_void_p, wt.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wt.UINT)]
        size = api.GetFileVersionInfoSizeW(path, None)
        buf = ctypes.create_string_buffer(size)
        if not size or not api.GetFileVersionInfoW(path, 0, size, buf):
            return "未知"
        pointer, length = ctypes.c_void_p(), wt.UINT()
        if not api.VerQueryValueW(buf, "\\", ctypes.byref(pointer), ctypes.byref(length)):
            return "未知"
        numbers = ctypes.cast(pointer, ctypes.POINTER(wt.DWORD))
        return ".".join(map(str, (numbers[2] >> 16, numbers[2] & 65535, numbers[3] >> 16, numbers[3] & 65535)))
    except (OSError, ValueError):
        return "未知"


def protect(data, entropy, *, decrypt=False):
    require_windows()
    class Blob(ctypes.Structure):
        _fields_ = [("size", wt.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]
    def blob(value):
        buffer = ctypes.create_string_buffer(value)
        return Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer
    source, source_buffer = blob(data)
    extra, extra_buffer = blob(entropy)
    destination = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.LocalFree.argtypes = [ctypes.c_void_p]
    api.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        call = crypt.CryptUnprotectData
        call.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob),
                         ctypes.c_void_p, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(Blob)]
        success = call(ctypes.byref(source), None, ctypes.byref(extra), None, None, 1, ctypes.byref(destination))
    else:
        call = crypt.CryptProtectData
        call.argtypes = [ctypes.POINTER(Blob), wt.LPCWSTR, ctypes.POINTER(Blob),
                         ctypes.c_void_p, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(Blob)]
        success = call(ctypes.byref(source), "WeChatPhotoExport", ctypes.byref(extra), None, None, 1,
                       ctypes.byref(destination))
    if not success:
        raise AppError("cache_invalid")
    try:
        return ctypes.string_at(destination.data, destination.size)
    finally:
        api.LocalFree(destination.data)


def sample_keys(attach, cancelled=lambda: False):
    from ..services.catalog import dat_files
    votes, samples, pure = Counter(), [], []
    count = 0
    for path in dat_files(attach, cancelled):
        try:
            with path.open("rb") as stream:
                header = stream.read(31)
                if header.startswith(V2_MAGIC):
                    if len(header) >= 31 and struct.unpack_from("<I", header, 6)[0] >= 16:
                        if len(samples) < 8:
                            samples.append(header[15:31])
                    if path.name.endswith("_t.dat"):
                        stream.seek(-2, 2)
                        tail = stream.read(2)
                        first, second = tail[0] ^ 255, tail[1] ^ 217
                        if first == second:
                            votes[first] += 1
                elif path.name.endswith("_W.dat") and len(pure) < 8:
                    pure.append(header)
            count += 1
        except OSError:
            continue
        if count >= 3000 and samples and votes:
            break
    xor = votes.most_common(1)[0][0] if votes else None
    if xor is None:
        # 纯 XOR JPEG 的前三字节必须同时符合，不能只猜首字节。
        candidates = [value[0] ^ 255 for value in pure if value]
        for candidate in candidates:
            if sum(sniff(bytes(b ^ candidate for b in v)) == "jpg" for v in pure) >= 2:
                xor = candidate
                break
    return samples, xor


def valid_aes(key, samples):
    from Crypto.Cipher import AES
    if len(key) != 16 or len(samples) < 2:
        return False
    cipher = AES.new(key, AES.MODE_ECB)
    return sum(not sniff(cipher.decrypt(value)).startswith("unknown") for value in samples[:6]) >= 2


def image_keys(account, state, cancelled=lambda: False, progress=lambda _: None):
    require_windows()
    progress("正在验证图片密钥")
    samples, xor = sample_keys(account.attach, cancelled)
    cache = no_links(state.directory/"image-key.dpapi")
    if cache.exists() and xor is not None:
        try:
            record = json.loads(protect(cache.read_bytes(), account.uid.encode(), decrypt=True))
            key = bytes.fromhex(record["aes"])
            if record["xor"] == xor and valid_aes(key, samples):
                return key, xor
        except (AppError, ValueError, KeyError, TypeError):
            pass
    if not samples and xor is not None:
        return b"\0"*16, xor
    if xor is None or len(samples) < 2:
        raise AppError("image_key_unavailable")
    from .memory import ProcessMemory
    pids = process_paths()
    if not pids:
        raise AppError("wechat_not_running")
    deadline = time.monotonic()+120
    pattern = re.compile(rb"(?<![0-9A-Za-z])[0-9A-Za-z]{16}(?![0-9A-Za-z])|(?<![0-9A-Za-z])[0-9A-Za-z]{32}(?![0-9A-Za-z])")
    tested = set()
    progress("正在只读扫描微信图片密钥")
    for rw_only in (True, False):
        for pid in pids:
            try:
                with ProcessMemory(pid, deadline, cancelled) as memory:
                    for _, blob in memory.chunks(rw_only=rw_only):
                        for match in pattern.finditer(blob):
                            candidate = match.group()[:16]
                            if candidate in tested:
                                continue
                            tested.add(candidate)
                            if valid_aes(candidate, samples):
                                private = json.dumps({"aes": candidate.hex(), "xor": xor}).encode()
                                atomic_write(cache, protect(private, account.uid.encode()))
                                return candidate, xor
            except (OSError, TimeoutError):
                continue
    raise AppError("image_key_unavailable")


def decoder_path():
    require_windows()
    roots = [p.parent for p in process_paths().values()]
    roots += [Path(os.environ.get(variable, "C:/Program Files"))/"Tencent"/"Weixin"
              for variable in ("ProgramFiles", "ProgramFiles(x86)")]
    for root in roots:
        try:
            no_links(root)
            candidates = [root/"VoipEngine.dll", *sorted(root.glob("*/VoipEngine.dll"), reverse=True)]
            for path in candidates:
                if no_links(path).is_file():
                    return path.resolve()
        except (OSError, AppError):
            continue
    return None
