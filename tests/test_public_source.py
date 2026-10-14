"""公开快照只含白名单代码和人工样本，不含运行数据和旧历史。"""
import importlib.util
import tempfile
import unittest
import zipfile
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("public_source", ROOT/"tools/prepare_public_source.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PublicSourceTests(unittest.TestCase):
    def test_qt_license_resources_match_the_pinned_manifest(self):
        manifest = json.loads((ROOT/"licenses/UPSTREAM_MANIFEST.json").read_text())
        self.assertEqual(manifest["version"], "6.12.0")
        self.assertTrue(any("LGPL-3.0" in entry["file"] for entry in manifest["files"]))
        for entry in manifest["files"]:
            resource = ROOT/"licenses"/entry["file"]
            self.assertTrue(resource.resolve().is_relative_to((ROOT/"licenses").resolve()))
            self.assertEqual(hashlib.sha256(resource.read_bytes()).hexdigest(), entry["sha256"])

    def test_public_snapshot_excludes_private_roots_and_binary_assets(self):
        files = module.source_files()
        names = [file.relative_to(ROOT).as_posix() for file in files]
        self.assertTrue(names)
        for name in names:
            self.assertNotIn(name.split("/")[0], {"data", "archive", "scripts", "output", ".git", "libs"})
            self.assertFalse(name.endswith((".dat", ".dll", ".jpg", ".png", ".dpapi", ".sqlite3")))

    def test_zip_has_no_git_history_or_user_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/"source.zip"
            self.assertEqual(module.main(["--output", str(path)]), 0)
            with zipfile.ZipFile(path) as archive:
                self.assertIn("SOURCE_MANIFEST.json", archive.namelist())
                self.assertIn(".agents/skills/wechat-photo-export/SKILL.md", archive.namelist())
                self.assertNotIn("data/names_user.json", archive.namelist())
                self.assertFalse(any(name.startswith(".git/") for name in archive.namelist()))
                manifest = json.loads(archive.read("SOURCE_MANIFEST.json"))
                self.assertEqual(set(archive.namelist()), {*manifest, "SOURCE_MANIFEST.json"})
                for name, digest in manifest.items():
                    self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), digest)
            self.assertEqual(path.with_name("source.zip.sha256").read_text().split()[0],
                             hashlib.sha256(path.read_bytes()).hexdigest())

    def test_source_directory_matches_the_zip(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory, path = root/"github-source", root/"source.zip"
            self.assertEqual(module.main(["--output", str(path), "--directory", str(directory)]), 0)
            with zipfile.ZipFile(path) as archive:
                exported = {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()}
                self.assertEqual(exported, set(archive.namelist()))
                for name in exported:
                    self.assertEqual((directory/name).read_bytes(), archive.read(name))

    def test_existing_source_directory_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory, path = root/"github-source", root/"source.zip"
            directory.mkdir()
            existing = directory/"personal-data.txt"
            existing.write_bytes(b"keep existing content")
            with self.assertRaises(ValueError):
                module.main(["--output", str(path), "--directory", str(directory)])
            self.assertEqual(existing.read_bytes(), b"keep existing content")
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
