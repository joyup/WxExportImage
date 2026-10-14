# 只收集 src 应用与依赖；不扫描 data、旧脚本、图片、微信 DLL 或 .git。
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH).parent
a = Analysis([str(root / "packaging" / "launcher.py")],
    pathex=[str(root / "src")], binaries=[], datas=[],
    hiddenimports=collect_submodules("wechat_photo_export"),
    excludes=["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml",
              "PySide6.QtQuick", "tkinter", "numpy", "matplotlib", "pytest"],
    noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="WeChatPhotoExport",
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, uac_admin=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="WeChatPhotoExport")
