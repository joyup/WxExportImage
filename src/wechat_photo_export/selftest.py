"""发行包自检：人工图片和短生命周期子进程，不读取微信或个人数据。"""
import io
import multiprocessing
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from PIL import Image

from .core.errors import error_code
from .platforms.windows import protect
from .services.accounts import account_at
from .services.jobs import build_plan, export
from .services.state import State


def child_probe():
    return "worker-ok"


def main():
    report = {"qt": False, "export": False, "resume": False, "dpapi": False, "worker": False}
    try:
        from PySide6.QtWidgets import QApplication, QLabel
        app = QApplication.instance() or QApplication([])
        widget = QLabel("发行自检")
        widget.show()
        app.processEvents()
        widget.close()
        report["qt"] = True
        entropy = b"synthetic-account"
        protected = protect(b"test-secret", entropy)
        report["dpapi"] = protect(protected, entropy, decrypt=True) == b"test-secret"
        with tempfile.TemporaryDirectory(prefix="wechat-photo-selftest-") as temporary:
            root = Path(temporary)
            full_hash, fid, xor = "a"*32, "b"*32, 0x6a
            attach = root/"account"/"msg"/"attach"/full_hash
            attach.mkdir(parents=True)
            buffer = io.BytesIO()
            Image.new("RGB", (8, 8), "green").save(buffer, "PNG")
            (attach/(fid+"_W.dat")).write_bytes(bytes(b ^ xor for b in buffer.getvalue()))
            account = account_at(root/"account")
            with State(account, root/"private") as state:
                plan = build_plan(account, state, [full_hash], root/"photos")
                report["export"] = export(plan, state, (b"0"*16, xor)).completed == 1
                plan = build_plan(account, state, [full_hash], root/"photos")
                report["resume"] = export(plan, state, (b"0"*16, xor)).skipped == 1
            with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"),
                                     max_tasks_per_child=1) as pool:
                report["worker"] = pool.submit(child_probe).result(timeout=30) == "worker-ok"
    except Exception as exc:
        report["error"] = error_code(exc)
    if sys_stdout := __import__("sys").stdout:
        print(__import__("json").dumps(report))
    # windowed EXE 没有 stdout；以退出码表达结果。
    return 0 if all(report[key] for key in ("qt", "export", "resume", "dpapi", "worker")) else 1
