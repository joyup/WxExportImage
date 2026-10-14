"""校验当前标签及构建文件，以草稿上传完成后发布 GitHub 预览版。"""
import argparse
import ast
import hashlib
import json
import subprocess
import tempfile
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ("WeChatPhotoExport-windows-x64.zip", "SHA256SUMS.txt",
          "wechat-photo-export-source.zip", "wechat-photo-export-source.zip.sha256")


def validate(root, directory, tag):
    version = tomllib.loads((root/"pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    tree = ast.parse((root/"src/wechat_photo_export/__init__.py").read_text(encoding="utf-8"))
    app_versions = [ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets)]
    if tag != "v"+version or app_versions != [version]:
        raise ValueError("Release tag, project version and application version must match")
    assets = [directory/name for name in ASSETS]
    if not all(path.is_file() for path in assets):
        raise ValueError("Missing release build files")
    for name, checksum in ((ASSETS[0], ASSETS[1]), (ASSETS[2], ASSETS[3])):
        record = (directory/checksum).read_text(encoding="utf-8").split()
        with (directory/name).open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if record != [digest, name]:
            raise ValueError("Release checksum mismatch: "+name)
    with zipfile.ZipFile(assets[0]) as archive:
        info = json.loads(archive.read("WeChatPhotoExport/build-info.json"))
    with zipfile.ZipFile(assets[2]) as archive:
        source_version = tomllib.loads(archive.read("pyproject.toml").decode("utf-8"))["project"]["version"]
    if info.get("version") != version or source_version != version or info.get("platform") != "windows-x64":
        raise ValueError("Build files do not match the release version or platform")
    if info.get("signed") is not False:
        raise ValueError("This workflow publishes unsigned preview builds")
    return assets, info


def gh(repo, *arguments, check=True):
    return subprocess.run(["gh", "release", *arguments, "--repo", repo],
                          check=check, capture_output=True, text=True)


def publish(root, directory, repo, tag):
    assets, info = validate(root, directory, tag)
    result = gh(repo, "view", tag, "--json", "isDraft,assets", check=False)
    if result.returncode == 0:
        existing = json.loads(result.stdout)
        if not existing["isDraft"]:
            if not set(ASSETS) <= {asset["name"] for asset in existing["assets"]}:
                raise ValueError("Published release is incomplete; existing assets are preserved")
            print("Release already published; existing assets are preserved:", tag)
            return
    else:
        if "release not found" not in result.stderr.lower() and "HTTP 404" not in result.stderr:
            raise RuntimeError("Cannot inspect GitHub release: "+result.stderr.strip())
        qt = info["dependencies"]["PySide6-Essentials"]
        notes = (f"WxExportImage {tag}：Windows x64 未签名预览版。\n\n"
                 "下载 WeChatPhotoExport-windows-x64.zip，完整解压后运行 WeChatPhotoExport.exe，无需安装 Python。\n\n"
                 f"构建运行时：Python {info['python']} / Qt {qt}。Windows 包摘要见 SHA256SUMS.txt；"
                 "源码 ZIP 摘要见 wechat-photo-export-source.zip.sha256。\n\n"
                 "WXGF 原文件保留，转换生成静态图；动画与透明效果尚不保证完整恢复。"
                 "支持范围及客户端验证记录见仓库的 docs/兼容性.md。\n")
        with tempfile.TemporaryDirectory(prefix="wx-release-notes-") as temporary:
            notes_path = Path(temporary)/"notes.md"
            notes_path.write_text(notes, encoding="utf-8")
            gh(repo, "create", tag, "--verify-tag", "--draft", "--prerelease", "--latest=false",
               "--title", "WxExportImage "+tag, "--notes-file", str(notes_path))
    gh(repo, "upload", tag, *(str(path) for path in assets), "--clobber")
    uploaded = json.loads(gh(repo, "view", tag, "--json", "isDraft,assets").stdout)
    expected = {path.name: path.stat().st_size for path in assets}
    actual = {asset["name"]: asset["size"] for asset in uploaded["assets"]}
    if not uploaded["isDraft"] or actual != expected:
        raise ValueError("Release upload is incomplete; draft remains unpublished")
    gh(repo, "edit", tag, "--draft=false", "--prerelease", "--latest=false")
    print("Published preview release:", f"https://github.com/{repo}/releases/tag/{tag}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--directory", type=Path, default=ROOT/"dist")
    args = parser.parse_args(argv)
    publish(ROOT, args.directory, args.repo, args.tag)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
