"""原生转换在短生命周期子进程中执行；不写文件，不加载用户照片目录的 DLL。"""
import ctypes
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, TimeoutError

from ..core.errors import AppError


def decode_native(data, dll_path):
    from ..core.files import no_links
    path = no_links(dll_path).resolve()
    if path.name.casefold() != "voipengine.dll":
        raise ValueError("decoder_path")
    # 限定依赖搜索到系统和安装组件所在目录，不搜索当前目录。
    library = ctypes.CDLL(str(path), winmode=0x1100)
    call = library.wxam_dec_wxam2pic_5
    call.restype = ctypes.c_int64
    call.argtypes = [ctypes.c_int64, ctypes.c_int, ctypes.c_int64, ctypes.c_int64, ctypes.c_void_p]
    size = max(8*1024*1024, min(len(data)*24, 256*1024*1024))
    source = ctypes.create_string_buffer(data)
    output = ctypes.create_string_buffer(size)
    received, mode = ctypes.c_int64(size), ctypes.c_int64(0)
    code = call(ctypes.addressof(source), len(data), ctypes.addressof(output),
                ctypes.addressof(received), ctypes.byref(mode))
    if code or not 0 < received.value <= size:
        raise ValueError("decode_failed")
    return output.raw[:received.value]


class Decoder:
    def __init__(self, path):
        self.path = path
        self.pool = None

    def close(self):
        if self.pool:
            self.pool.shutdown(wait=True, cancel_futures=True)
            self.pool = None

    def decode(self, data, cancelled=lambda: False):
        if not self.path:
            raise AppError("decoder_unavailable")
        if not self.pool:
            self.pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"),
                                            max_tasks_per_child=10)
        future = self.pool.submit(decode_native, data, str(self.path))
        deadline = __import__("time").monotonic()+30
        try:
            while True:
                if cancelled():
                    raise AppError("cancelled")
                try:
                    return future.result(timeout=0.1)
                except TimeoutError:
                    if __import__("time").monotonic() >= deadline:
                        raise AppError("decode_failed")
        except Exception:
            # 只终止本工具创建的转换进程。Python 3.13 无公共 terminate_workers 接口。
            for process in (getattr(self.pool, "_processes", None) or {}).values():
                process.terminate()
            self.close()
            raise
