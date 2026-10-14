"""预览与执行使用同一计划；单文件验证、原子落盘、清单提交。"""
import hashlib
import io
import re
import time
import warnings
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from ..core.errors import AppError, error_code
from ..core.files import atomic_write, child, no_links, output_lock, read_json, write_json
from ..core.identity import sanitize, session_metadata
from ..core.images import EXT, decrypt_any, pick_best, sniff
from ..core.selection import source_sessions
from .catalog import dat_files

MARKER = "_导出信息.json"
MAX_INPUT = 128*1024*1024


@dataclass(frozen=True)
class Item:
    session: str
    fid: str
    rank: int
    source: Path
    size: int
    mtime_ns: int
    directory: str

    @property
    def key(self):
        return self.session+":"+self.fid+":"+str(self.rank)

    @property
    def stem(self):
        date = time.strftime("%Y%m%d_%H%M%S", time.localtime(self.mtime_ns/1e9))
        return f"{date}_{self.fid}_{'h' if self.rank == 3 else 'W'}"


@dataclass(frozen=True)
class Plan:
    account_uid: str
    source_root: Path
    output: Path
    items: tuple
    metadata: dict
    directories: dict

    @property
    def source_bytes(self):
        return sum(item.size for item in self.items)


@dataclass
class Result:
    total: int
    completed: int = 0
    skipped: int = 0
    failed: int = 0
    pending_conversion: int = 0
    cancelled: bool = False
    errors: dict = field(default_factory=dict)


def output_metadata(output, account_uid):
    metadata = read_json(child(output, MARKER))
    if metadata:
        if metadata.get("schema") != 1 or metadata.get("account") != account_uid:
            raise AppError("output_owned")
        directories = metadata.get("sessions")
        if not isinstance(directories, dict):
            raise AppError("cache_invalid")
        owners = set()
        for full_hash, info in directories.items():
            if not re.fullmatch(r"[0-9a-f]{32}", full_hash):
                raise AppError("cache_invalid")
            name = info.get("dir", "")
            if not name or len(Path(name).parts) != 1:
                raise AppError("unsafe_path")
            child(output, name)
            if name.casefold() in owners:
                raise AppError("output_owned")
            owners.add(name.casefold())
        return metadata
    if output.exists() and any(output.iterdir()):
        raise AppError("output_owned")
    return {"schema": 1, "account": account_uid, "sessions": {}}


def build_plan(account, state, selected, output, cancelled=lambda: False, progress=lambda _: None):
    if not selected:
        raise ValueError("请勾选会话，或明确选择全部导出。")
    output = no_links(output).resolve()
    source = no_links(account.root).resolve()
    private = state.directory.resolve()
    if any(output.is_relative_to(p) or p.is_relative_to(output) for p in (source, private)):
        raise AppError("unsafe_path")
    if output.exists() and not output.is_dir():
        raise AppError("unsafe_path")
    metadata = output_metadata(output, account.uid)
    known = set(source_sessions(account.attach))
    if not set(selected) <= known:
        raise AppError("source_changed")
    names = state.names()
    items, directories = [], {}
    for index, full_hash in enumerate(sorted(set(selected))):
        if cancelled():
            raise AppError("cancelled")
        progress(f"扫描会话 {index+1}/{len(set(selected))}")
        info = session_metadata(full_hash, names)
        dirname = metadata["sessions"].get(full_hash, {}).get("dir")
        if not dirname:
            dirname = (sanitize(info["name"]) or "会话")+"__"+full_hash[:16]
            if child(output, dirname).exists():
                raise AppError("target_conflict")
        child(output, dirname)
        directories[full_hash] = dict(info, dir=dirname)
        files = dat_files(child(account.attach, full_hash), cancelled)
        for path, fid, rank in sorted(pick_best(files), key=lambda row: row[1]):
            if not re.fullmatch(r"[0-9a-fA-F]{32}", fid):
                # 非标准名称不能被带入输出路径，也不能截断为短 ID。
                continue
            stat = path.stat()
            items.append(Item(full_hash, fid.lower(), rank, path, stat.st_size, stat.st_mtime_ns, dirname))
    return Plan(account.uid, source, output, tuple(items), metadata, directories)


def validate_image(data):
    fmt = sniff(data)
    if fmt not in EXT or fmt == "wxgf":
        raise AppError("image_invalid")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.width <= 0 or image.height <= 0:
                    raise ValueError("size")
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                image.load()
    except Exception:
        raise AppError("image_invalid") from None
    return fmt


def publish(path, data):
    digest = hashlib.sha256(data).hexdigest()
    try:
        atomic_write(path, data, replace=False)
    except FileExistsError:
        if hashlib.sha256(no_links(path).read_bytes()).hexdigest() != digest:
            raise AppError("target_conflict") from None
    return digest


def verify_existing(record, output, item):
    if not record or record[2] != "done":
        return False
    target = child(output, record[0])
    if target.parent != child(output, item.directory) or target.stem != item.stem:
        raise AppError("cache_invalid")
    if not target.is_file():
        return False
    return hashlib.sha256(target.read_bytes()).hexdigest() == record[1]


def export(plan, state, keys, decoder=None, cancelled=lambda: False, progress=lambda _: None):
    if state.directory.name != plan.account_uid:
        raise AppError("output_owned")
    result = Result(len(plan.items))
    output = no_links(plan.output)
    # 重新检查预览后的路径和归属，避免在两个账号间复用旧计划。
    if output.is_relative_to(plan.source_root) or plan.source_root.is_relative_to(output):
        raise AppError("unsafe_path")
    current = output_metadata(output, plan.account_uid)
    if current != plan.metadata:
        raise AppError("output_owned")
    if cancelled():
        result.cancelled = True
        return result
    output.mkdir(parents=True, exist_ok=True)
    # 首次任务先声明归属，再拿进程锁；并发创建使用不可覆盖写入。
    marker = child(output, MARKER)
    if not marker.exists():
        try:
            write_json(marker, current, replace=False)
        except FileExistsError:
            current = output_metadata(output, plan.account_uid)
    with output_lock(output):
        current = output_metadata(output, plan.account_uid)
        current["sessions"].update(plan.directories)
        write_json(marker, current)
        for item in plan.items:
            if cancelled():
                result.cancelled = True
                break
            try:
                path = child(plan.source_root, item.source.relative_to(plan.source_root))
                stat = path.stat()
                if (stat.st_size, stat.st_mtime_ns) != (item.size, item.mtime_ns):
                    raise AppError("source_changed")
                old = state.exported(output, item.key)
                if verify_existing(old, output, item):
                    result.skipped += 1
                    progress(result)
                    continue
                if item.size > MAX_INPUT:
                    raise AppError("image_too_large")
                data, fmt = decrypt_any(path, *keys)
                stat = path.stat()
                if (stat.st_size, stat.st_mtime_ns) != (item.size, item.mtime_ns):
                    raise AppError("source_changed")
                if data is None:
                    raise AppError("image_invalid")
                destination = child(output, item.directory)
                destination.mkdir(exist_ok=True)
                if fmt == "wxgf":
                    raw_path = child(destination, item.stem+".wxgf")
                    publish(raw_path, data)
                    # 私有原文件留存；转换失败仍然可以重试，统计不会伪装为成功。
                    try:
                        if decoder is None:
                            raise AppError("decoder_unavailable")
                        data = decoder.decode(data, cancelled)
                        fmt = validate_image(data)
                    except Exception as exc:
                        if error_code(exc) == "cancelled":
                            raise AppError("cancelled") from None
                        code = error_code(exc) if isinstance(exc, AppError) else "decode_failed"
                        state.record(output, item.key, str(raw_path.relative_to(output)), "", "pending", code)
                        result.pending_conversion += 1
                        result.errors[code] = result.errors.get(code, 0)+1
                        progress(result)
                        continue
                else:
                    fmt = validate_image(data)
                target = child(destination, item.stem+EXT[fmt])
                if cancelled():
                    raise AppError("cancelled")
                digest = publish(target, data)
                state.record(output, item.key, str(target.relative_to(output)), digest, "done")
                result.completed += 1
            except Exception as exc:
                code = error_code(exc)
                if code == "cancelled":
                    result.cancelled = True
                    break
                state.record(output, item.key, "", "", "failed", code)
                result.failed += 1
                result.errors[code] = result.errors.get(code, 0)+1
                if code in ("disk_full", "permission_denied"):
                    progress(result)
                    break
            progress(result)
        from .index import build_index
        build_index(output, current)
    return result
