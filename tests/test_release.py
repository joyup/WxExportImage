"""Release 发布使用人工构建文件与模拟 CLI；测试不访问 GitHub。"""
import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("publish_release", ROOT/"tools/publish_release.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.directory = self.root/"dist"
        self.directory.mkdir()
        (self.root/"pyproject.toml").write_text('[project]\nversion = "0.2.0"\n', encoding="utf-8")
        source = self.root/"src/wechat_photo_export"
        source.mkdir(parents=True)
        (source/"__init__.py").write_text('__version__ = "0.2.0"\n', encoding="utf-8")
        with zipfile.ZipFile(self.directory/module.ASSETS[0], "w") as archive:
            archive.writestr("WeChatPhotoExport/build-info.json", json.dumps({"version": "0.2.0",
                "python": "3.13.8", "platform": "windows-x64", "signed": False,
                "dependencies": {"PySide6-Essentials": "6.12.0"}}))
        with zipfile.ZipFile(self.directory/module.ASSETS[2], "w") as archive:
            archive.writestr("pyproject.toml", (self.root/"pyproject.toml").read_bytes())
        for name, checksum in ((module.ASSETS[0], module.ASSETS[1]), (module.ASSETS[2], module.ASSETS[3])):
            digest = hashlib.sha256((self.directory/name).read_bytes()).hexdigest()
            (self.directory/checksum).write_text(digest+"  "+name+"\n", encoding="utf-8")
        self.assets = [{"name": name, "size": (self.directory/name).stat().st_size} for name in module.ASSETS]

    def response(self, data=None, *, code=0, error=""):
        return subprocess.CompletedProcess([], code, json.dumps(data) if data is not None else "", error)

    def publish(self):
        module.publish(self.root, self.directory, "example/repository", "v0.2.0")

    def test_wrong_tag_does_not_call_github(self):
        with patch.object(module, "gh") as gh, self.assertRaises(ValueError):
            module.publish(self.root, self.directory, "example/repository", "v0.3.0")
        gh.assert_not_called()

    def test_missing_or_changed_asset_does_not_call_github(self):
        source = self.directory/module.ASSETS[2]
        source.unlink()
        with patch.object(module, "gh") as gh, self.assertRaises(ValueError):
            self.publish()
        gh.assert_not_called()
        source.write_bytes(b"changed source archive")
        with patch.object(module, "gh") as gh, self.assertRaises(ValueError):
            self.publish()
        gh.assert_not_called()

    def test_application_version_must_match(self):
        (self.root/"src/wechat_photo_export/__init__.py").write_text('__version__ = "0.3.0"\n', encoding="utf-8")
        with patch.object(module, "gh") as gh, self.assertRaises(ValueError):
            self.publish()
        gh.assert_not_called()

    def test_published_release_is_preserved(self):
        with patch.object(module, "gh", return_value=self.response({"isDraft": False, "assets": self.assets})) as gh:
            self.publish()
        self.assertEqual(gh.call_count, 1)

    def test_failed_upload_does_not_publish_draft(self):
        responses = [self.response(code=1, error="release not found"), self.response(),
                     subprocess.CalledProcessError(1, ["gh", "release", "upload"])]
        with patch.object(module, "gh", side_effect=responses) as gh, self.assertRaises(subprocess.CalledProcessError):
            self.publish()
        self.assertIn("--draft", gh.call_args_list[1].args)
        self.assertFalse(any(call.args[1] == "edit" for call in gh.call_args_list))

    def test_incomplete_remote_upload_does_not_publish(self):
        responses = [self.response({"isDraft": True, "assets": []}), self.response(),
                     self.response({"isDraft": True, "assets": self.assets[:-1]})]
        with patch.object(module, "gh", side_effect=responses) as gh, self.assertRaises(ValueError):
            self.publish()
        self.assertFalse(any(call.args[1] == "edit" for call in gh.call_args_list))

    def test_only_verified_assets_are_uploaded_then_published_as_preview(self):
        (self.directory/"unrelated-private-file.txt").write_bytes(b"synthetic file that must not be uploaded")
        responses = [self.response(code=1, error="release not found"), self.response(), self.response(),
                     self.response({"isDraft": True, "assets": self.assets}), self.response()]
        with patch.object(module, "gh", side_effect=responses) as gh:
            self.publish()
        self.assertIn("--verify-tag", gh.call_args_list[1].args)
        uploaded = gh.call_args_list[2].args
        self.assertEqual(set(uploaded[3:-1]), {str(self.directory/name) for name in module.ASSETS})
        published = gh.call_args_list[-1].args
        self.assertIn("--draft=false", published)
        self.assertIn("--prerelease", published)


if __name__ == "__main__":
    unittest.main()
