"""文件边界、原子写入和进程锁；图片写入从不覆盖已有文件。"""
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .errors import AppError


def is_link(path):
    path = Path(path)
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        return True
    try:
        return bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)
    except FileNotFoundError:
        return False


def no_links(path):
    path = Path(path).absolute()
    if any(is_link(p) for p in (path, *path.parents)):
        raise AppError("unsafe_path")
    return path


def child(root, relative):
    root = no_links(root).resolve()
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise AppError("unsafe_path")
    # 包括 NTFS alternate data streams 和 Windows DOS 设备名。
    reserved = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}
    if any(any(c in part for c in ':*?"<>|') or any(ord(c) < 32 for c in part) or
           part.split(".")[0].upper() in reserved for part in relative.parts):
        raise AppError("unsafe_path")
    result = no_links(root/relative)
    if not result.resolve().is_relative_to(root):
        raise AppError("unsafe_path")
    return result


def read_json(path, default=None):
    path = no_links(path)
    if not path.exists():
        return {} if default is None else default
    try:
        with path.open(encoding="utf-8") as stream:
            return json.load(stream)
    except (ValueError, TypeError):
        raise AppError("cache_invalid") from None


def atomic_write(path, data, *, replace=True):
    path = no_links(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".wechat-photo-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        no_links(path)
        if replace:
            os.replace(temp, path)
        elif os.name == "nt":
            # Windows rename 不覆盖已存在的目标；避免 exists + replace 的竞争窗口。
            os.rename(temp, path)
        else:
            os.link(temp, path)
            os.unlink(temp)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def write_json(path, value, *, replace=True):
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2).encode(), replace=replace)


@contextmanager
def output_lock(root):
    path = child(root, "_导出锁")
    with path.open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if not stream.tell():
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise AppError("output_busy") from None
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
