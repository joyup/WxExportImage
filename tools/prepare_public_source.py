"""生成新 GitHub 仓库用的干净快照，不复制旧 Git 历史或本机数据。"""
import argparse
import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ("README.md", "CHANGELOG.md", "LICENSE", "SECURITY.md", "CONTRIBUTING.md", "THIRD_PARTY_NOTICES.md",
         "pyproject.toml", "requirements-desktop.lock", ".gitignore", ".gitattributes", "docs/桌面工具使用.md",
         "docs/开源发布指南.md", "docs/桌面架构.md", "docs/兼容性.md", "tools/build_windows.py",
         "tools/prepare_public_source.py", "tools/publish_release.py", "tests/test_desktop.py", "tests/test_gui.py",
         "tests/test_formats.py", "tests/test_public_source.py", "tests/test_release.py")
TREES = ("src/wechat_photo_export", "packaging", ".github", "licenses", ".agents/skills/wechat-photo-export")
ALLOWED_SUFFIXES = {".py", ".md", ".spec", ".yml", ".yaml"}


def source_files():
    files = [ROOT/name for name in FILES]
    for name in TREES:
        files += [p for p in (ROOT/name).rglob("*") if p.is_file() and (p.suffix in ALLOWED_SUFFIXES or name == "licenses")
                  and "__pycache__" not in p.parts]
    for path in files:
        if path.is_symlink() or ".." in path.relative_to(ROOT).parts:
            raise ValueError("Unsafe source path")
        if not path.is_file():
            raise FileNotFoundError(path.relative_to(ROOT))
    return sorted(set(files))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT/"dist/wechat-photo-export-source.zip")
    parser.add_argument("--directory", type=Path, help="同时生成独立源码目录；目标须不存在或为空")
    args = parser.parse_args(argv)
    files = source_files()
    if args.output.resolve() in {path.resolve() for path in files}:
        raise ValueError("Output must not replace a source file")
    if args.directory is not None:
        if args.directory.is_symlink() or (hasattr(args.directory, "is_junction") and args.directory.is_junction()):
            raise ValueError("Source directory must not be a link")
        if args.directory.exists() and (not args.directory.is_dir() or any(args.directory.iterdir())):
            raise ValueError("Source directory must be empty; existing files are preserved")
        if args.output.resolve().is_relative_to(args.directory.resolve()):
            raise ValueError("ZIP output must be outside the source directory")
    # 只读取一次，确保目录、ZIP 与摘要清单使用同一份内容。
    snapshot = {path.relative_to(ROOT).as_posix(): path.read_bytes() for path in files}
    # 自有文本统一为 LF；第三方原文的字节必须与上游摘要一致。
    snapshot = {name: data if name.startswith("licenses/") else data.replace(b"\r\n", b"\n")
                for name, data in snapshot.items()}
    manifest = {name: hashlib.sha256(data).hexdigest() for name, data in snapshot.items()}
    snapshot["SOURCE_MANIFEST.json"] = (json.dumps(manifest, indent=2)+"\n").encode("utf-8")
    if args.directory is not None:
        args.directory.mkdir(parents=True, exist_ok=True)
        for name, data in snapshot.items():
            destination = args.directory/name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(snapshot.items()):
            # 不复制本机修改时间和文件属性，相同内容生成相同 ZIP。
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, data, compress_type=zipfile.ZIP_DEFLATED)
    digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
    args.output.with_name(args.output.name+".sha256").write_text(digest+"  "+args.output.name+"\n", encoding="utf-8")
    print("Source files:", len(files), "SHA256:", digest)
    if args.directory is not None:
        print("Source directory:", args.directory)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
