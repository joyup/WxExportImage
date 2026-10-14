"""账号发现不自动选择第一项；自定义目录只在用户指定时访问。"""
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from ..core.errors import AppError
from ..core.files import no_links


@dataclass(frozen=True)
class Account:
    root: Path
    uid: str

    @property
    def attach(self):
        return self.root/"msg"/"attach"

    @property
    def label(self):
        return self.root.name


def account_at(path):
    root = no_links(path).resolve()
    if root.name == "attach" and root.parent.name == "msg":
        root = root.parent.parent
    if not no_links(root/"msg"/"attach").is_dir():
        raise AppError("account_invalid")
    uid = hashlib.sha256(os.path.normcase(str(root)).encode()).hexdigest()
    return Account(root, uid)


def discover_accounts(extra=(), *, defaults=True):
    home = Path.home()
    bases = [home, home/"Documents"]
    if os.name == "nt":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
                bases.append(Path(os.path.expandvars(winreg.QueryValueEx(key, "Personal")[0])))
        except OSError:
            pass
        import ctypes
        from ctypes import wintypes
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
        mask = api.GetLogicalDrives()
        # 不探测断开的网络盘、光驱或不存在的盘符，避免启动长时间卡住。
        bases += [Path(f"{chr(65+i)}:/") for i in range(26) if mask & (1 << i)
                  and api.GetDriveTypeW(f"{chr(65+i)}:\\") == 3]
    roots = [base/name for base in bases for name in ("xwechat_files", "WeChat Files")] if defaults else []
    roots += [Path(value) for value in extra]
    found = {}
    for root in roots:
        try:
            candidates = [root] if (root/"msg"/"attach").is_dir() else list(root.iterdir())
            for candidate in candidates:
                try:
                    account = account_at(candidate)
                    found[account.uid] = account
                except (AppError, OSError):
                    continue
        except (OSError, AppError):
            continue
    return sorted(found.values(), key=lambda account: str(account.root).casefold())


def state_home():
    base = Path(os.environ.get("LOCALAPPDATA", Path.home()/".local"/"share"))
    return no_links(base/"WeChatPhotoExport")


def default_output(account):
    return Path.home()/"Pictures"/"微信照片导出"/account.uid[:12]
