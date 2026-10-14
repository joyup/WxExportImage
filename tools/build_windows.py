"""在隔离环境构建目录版；许可和源码归档均来自明确白名单。"""
import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEP_NAMES = ("PySide6-Essentials", "shiboken6", "pycryptodome", "Pillow", "PyInstaller")


def main():
    if os.name != "nt" or sys.maxsize <= 2**32:
        raise SystemExit("Build on Windows x64.")
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", str(ROOT/"packaging/windows.spec")],
                   cwd=ROOT, check=True)
    destination = ROOT/"dist/WeChatPhotoExport"
    licenses = destination/"licenses"
    licenses.mkdir(exist_ok=True)
    upstream = ROOT/"licenses/UPSTREAM_MANIFEST.json"
    manifest = json.loads(upstream.read_text(encoding="utf-8"))
    if importlib.metadata.version("PySide6-Essentials") != manifest["version"]:
        raise SystemExit("Update pinned Qt license resources for this dependency version.")
    for record in manifest["files"]:
        source = ROOT/"licenses"/record["file"]
        if hashlib.sha256(source.read_bytes()).hexdigest() != record["sha256"]:
            raise SystemExit("Qt license resource checksum mismatch.")
        target = licenses/record["file"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    shutil.copy2(upstream, licenses/upstream.name)
    python_license = Path(sys.base_prefix)/"LICENSE.txt"
    if not python_license.is_file():
        raise SystemExit("Python LICENSE.txt is required for distribution.")
    shutil.copy2(python_license, licenses/"Python-LICENSE.txt")
    versions = {}
    for name in DEP_NAMES:
        distribution = importlib.metadata.distribution(name)
        versions[name] = distribution.version
        copied = 0
        for file in distribution.files or []:
            # wheel 自带的原文，包括 Qt 第三方组件 notice；保持子目录结构。
            if any("license" in part.casefold() or "copying" in part.casefold() or
                   "notice" in part.casefold() for part in file.parts):
                if ".." in file.parts:
                    continue
                source = Path(distribution.locate_file(file))
                if source.is_file():
                    target = licenses/name/Path(file)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
                    copied += 1
        if not copied:
            raise SystemExit("Missing license text for "+name)
    for file in ("LICENSE", "THIRD_PARTY_NOTICES.md", "docs/桌面工具使用.md"):
        shutil.copy2(ROOT/file, destination/Path(file).name)
    (destination/"build-info.json").write_text(json.dumps({"python": sys.version.split()[0],
        "dependencies": versions, "platform": "windows-x64", "signed": False}, indent=2), encoding="utf-8")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    result = subprocess.run([str(destination/"WeChatPhotoExport.exe"), "--self-test"], env=env, timeout=120)
    if result.returncode:
        raise SystemExit("Frozen self-test failed; no distribution ZIP generated.")
    archive = ROOT/"dist/WeChatPhotoExport-windows-x64.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as package:
        for path in sorted(destination.rglob("*")):
            if path.is_file():
                package.write(path, path.relative_to(destination.parent))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (ROOT/"dist/SHA256SUMS.txt").write_text(digest+"  "+archive.name+"\n", encoding="ascii")
    print("Built:", archive.name, "SHA256:", digest)


if __name__ == "__main__":
    main()
