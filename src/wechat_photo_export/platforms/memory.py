"""Windows 只读进程访问与已认证数据库取钥；不使用写权限。"""
import os
import re
import struct
import time
from ..core.contacts import CIPHER_NAME, CIPHER_MASK, HEX_KEY, verify_key

class ProcessMemory:
    """仅请求查询和读取权限；不注入、不写入微信进程。"""
    def __init__(self, pid, deadline, cancelled=lambda: False):
        import ctypes
        from ctypes import wintypes as wt
        self.c = ctypes
        self.deadline = deadline
        self.cancelled = cancelled
        class MBI(ctypes.Structure):
            _fields_ = [("base", ctypes.c_void_p), ("allocation", ctypes.c_void_p),
                        ("allocation_protect", wt.DWORD), ("partition", wt.WORD),
                        ("size", ctypes.c_size_t), ("state", wt.DWORD),
                        ("protect", wt.DWORD), ("kind", wt.DWORD)]
        self.MBI = MBI
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
        self.api.OpenProcess.restype = wt.HANDLE
        self.api.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                               ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
        self.api.VirtualQueryEx.argtypes = [wt.HANDLE, ctypes.c_void_p,
                                            ctypes.POINTER(MBI), ctypes.c_size_t]
        self.api.VirtualQueryEx.restype = ctypes.c_size_t
        self.api.CloseHandle.argtypes = [wt.HANDLE]
        self.handle = self.api.OpenProcess(0x0410, False, pid)
        if not self.handle:
            raise OSError("无法读取微信进程 %s" % pid)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.api.CloseHandle(self.handle)

    def read(self, address, size):
        if not 0x10000 <= address < 0x800000000000 or not 0 < size <= 4*1024*1024:
            return b""
        buf = self.c.create_string_buffer(size)
        received = self.c.c_size_t()
        self.api.ReadProcessMemory(self.handle, address, buf, size, self.c.byref(received))
        return buf.raw[:received.value]

    def chunks(self, rw_only=False):
        addr, info = 0, self.MBI()
        while addr < 0x800000000000:
            if self.cancelled():
                raise InterruptedError("cancelled")
            if time.monotonic() >= self.deadline:
                raise TimeoutError("内存扫描超时")
            if not self.api.VirtualQueryEx(self.handle, addr, self.c.byref(info),
                                          self.c.sizeof(info)):
                break
            base, size = info.base or 0, info.size
            following = base + size
            if following <= addr:
                break
            addr = following
            if info.state != 0x1000 or info.protect & (0x01 | 0x100):
                continue
            if rw_only and info.protect not in (0x04, 0x08, 0x40, 0x80):
                continue
            for off in range(0, size, 4*1024*1024-256):
                if self.cancelled():
                    raise InterruptedError("cancelled")
                if time.monotonic() >= self.deadline:
                    raise TimeoutError("内存扫描超时")
                blob = self.read(base+off, min(4*1024*1024, size-off))
                if blob:
                    yield base+off, blob


def find_contact_key(page, pids, seconds=120, progress=lambda _: None, cancelled=lambda: False):
    """验证内存 SQL hex literal 和 Config.Cipher 中的库密钥。"""
    if os.name != "nt" or struct.calcsize("P") != 8:
        raise RuntimeError("提取联系人库密钥需要 Windows 64 位 Python")
    stats = {"processes": 0, "anchors": 0, "objects": 0, "candidates": 0}
    tested = set()
    deadline = time.monotonic() + seconds

    def candidates(blob):
        for match in HEX_KEY.finditer(blob):
            value = match.group(1)
            for offset in range(0, len(value)-63, 32):
                key = bytes.fromhex(value[offset:offset+64].decode("ascii"))
                if key in tested:
                    continue
                tested.add(key)
                stats["candidates"] += 1
                if verify_key(key, page):
                    return key
        return None

    for pid in pids:
        progress("扫描微信进程 %s 的联系人库密钥（只读）..." % pid)
        try:
            with ProcessMemory(pid, deadline, cancelled) as mem:
                stats["processes"] += 1
                anchors = set()
                for address, blob in mem.chunks():
                    key = candidates(blob)
                    if key:
                        return key, stats
                    start = 0
                    while True:
                        index = blob.find(CIPHER_NAME, start)
                        if index < 0:
                            break
                        anchors.add(address+index)
                        start = index+len(CIPHER_NAME)
                stats["anchors"] += len(anchors)
                if not anchors:
                    continue
                progress("发现 %s 个配置锚点，检查关联对象..." % len(anchors))
                pattern = re.compile(b"|".join(re.escape(struct.pack("<QQ", a, len(CIPHER_NAME)))
                                               for a in anchors))
                for address, blob in mem.chunks():
                    for match in pattern.finditer(blob):
                        node = mem.read(address+match.start()-16, 64)
                        if len(node) < 48:
                            continue
                        pointer = struct.unpack_from("<Q", node, 40)[0]
                        obj = mem.read(pointer+0x88, 40)
                        if len(obj) < 24:
                            continue
                        data_pointer, length = struct.unpack_from("<QQ", obj, 8)
                        if not 0 < length <= 1024:
                            continue
                        payload = mem.read(data_pointer, length)
                        if len(payload) != length:
                            continue
                        stats["objects"] += 1
                        decoded = bytes(b ^ CIPHER_MASK[i % len(CIPHER_MASK)]
                                        for i, b in enumerate(payload))
                        key = candidates(decoded)
                        if key:
                            return key, stats
        except (OSError, TimeoutError) as exc:
            progress(str(exc))
    return None, stats
