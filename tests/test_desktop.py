"""桌面服务的人工样本回归；不需要微信进程或个人照片。"""
import hashlib
import io
import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"src"))
from PIL import Image
from Crypto.Cipher import AES
from wechat_photo_export.core.errors import AppError, error_code
from wechat_photo_export.core.files import child, output_lock, read_json, write_json
from wechat_photo_export.core.images import V2_MAGIC
from wechat_photo_export.core.selection import select_sessions
from wechat_photo_export.services.accounts import account_at, discover_accounts
from wechat_photo_export.services.catalog import sessions
from wechat_photo_export.services.jobs import build_plan, export, validate_image
from wechat_photo_export.services.state import State


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root/"账号🖼"/"msg"/"attach"
        self.source.mkdir(parents=True)
        self.account = account_at(self.source)
        self.state = State(self.account, self.root/"private")
        self.addCleanup(self.state.close)
        self.output = self.root/"照片🖼"
        self.key, self.xor = b"fixture-key-1234", 0x6a
        self.group_id = "100000001@chatroom"
        self.group = hashlib.md5(self.group_id.encode()).hexdigest()
        self.other = "f"*32

    def image(self, color="red"):
        stream = io.BytesIO()
        Image.new("RGB", (8, 8), color).save(stream, "PNG")
        return stream.getvalue()

    def file(self, fid="a"*32, suffix="_W", full_hash=None, data=None, v2=False):
        directory = self.source/(full_hash or self.group)/"2026-10"
        directory.mkdir(parents=True, exist_ok=True)
        plain = self.image() if data is None else data
        if v2:
            head, tail = plain[:32], plain[32:]
            encrypted = AES.new(self.key, AES.MODE_ECB).encrypt(head+b"\x10"*16)
            raw = V2_MAGIC+struct.pack("<II", len(head), len(tail))+b"\0"+encrypted+bytes(v ^ self.xor for v in tail)
        else:
            raw = bytes(v ^ self.xor for v in plain)
        path = directory/(fid+suffix+".dat")
        path.write_bytes(raw)
        return path

    def plan(self, hashes=None):
        return build_plan(self.account, self.state, hashes or [self.group], self.output)

    def test_preview_is_read_only_and_keeps_full_fids_highest_versions(self):
        self.file(suffix="")
        self.file(suffix="_t")
        self.file(suffix="_W")
        self.file(suffix="_h", v2=True)
        self.file(fid="a"*8+"b"*24)
        plan = self.plan()
        self.assertEqual(len(plan.items), 2)
        self.assertEqual(plan.items[0].rank, 3)
        self.assertFalse(self.output.exists())
        result = export(plan, self.state, (self.key, self.xor))
        self.assertEqual(result.completed, 2)
        images = list(self.output.rglob("*.png"))
        self.assertEqual(len(images), 2)
        self.assertEqual(images[0].read_bytes(), self.image())
        self.assertNotEqual(images[0].name, images[1].name)

    def test_cancel_then_resume_and_repeat_export(self):
        self.file()
        self.file(fid="b"*32)
        cancelled = [False]
        def progress(value):
            if value.completed == 1:
                cancelled[0] = True
        result = export(self.plan(), self.state, (self.key, self.xor),
                        cancelled=lambda: cancelled[0], progress=progress)
        self.assertTrue(result.cancelled)
        self.assertEqual(result.completed, 1)
        result = export(self.plan(), self.state, (self.key, self.xor))
        self.assertEqual((result.completed, result.skipped), (1, 1))
        self.assertEqual(export(self.plan(), self.state, (self.key, self.xor)).skipped, 2)

    def test_v2_plain_middle_is_preserved_and_bad_segment_size_rejected(self):
        from wechat_photo_export.core.images import decrypt_v2
        plain = self.image()
        head, middle, tail = plain[:32], plain[32:-16], plain[-16:]
        cipher = AES.new(self.key, AES.MODE_ECB).encrypt(head+b"\x10"*16)
        raw = V2_MAGIC+struct.pack("<II", 32, 16)+b"\0"+cipher+middle+bytes(v ^ self.xor for v in tail)
        decoded = decrypt_v2(raw, self.key, self.xor)
        self.assertEqual(decoded, plain)
        self.assertEqual(validate_image(decoded), "png")
        bad = raw[:10]+struct.pack("<I", len(raw)+1)+raw[14:]
        self.assertIsNone(decrypt_v2(bad, self.key, self.xor))

    def test_missing_target_is_restored_but_changed_target_is_preserved(self):
        self.file()
        export(self.plan(), self.state, (self.key, self.xor))
        image = next(self.output.rglob("*.png"))
        image.unlink()
        self.assertEqual(export(self.plan(), self.state, (self.key, self.xor)).completed, 1)
        image.write_bytes(b"user-modified")
        result = export(self.plan(), self.state, (self.key, self.xor))
        self.assertEqual(result.errors, {"target_conflict": 1})
        self.assertEqual(image.read_bytes(), b"user-modified")

    def test_crash_after_publish_before_manifest_is_reconciled(self):
        self.file()
        with patch.object(self.state, "record", side_effect=OSError("crash")):
            with self.assertRaises(OSError):
                export(self.plan(), self.state, (self.key, self.xor))
        result = export(self.plan(), self.state, (self.key, self.xor))
        self.assertEqual(result.completed, 1)
        self.assertEqual(len(list(self.output.rglob("*.png"))), 1)

    def test_changed_or_removed_source_after_preview_fails(self):
        source = self.file()
        plan = self.plan()
        source.write_bytes(b"changed")
        result = export(plan, self.state, (self.key, self.xor))
        self.assertEqual(result.errors, {"source_changed": 1})
        self.assertFalse(list(self.output.rglob("*.png")))

    def test_wrong_key_and_corrupt_image_are_not_successes(self):
        self.file(suffix="_h", v2=True)
        result = export(self.plan(), self.state, (b"x"*16, self.xor))
        self.assertEqual(result.failed, 1)
        with self.assertRaises(AppError):
            validate_image(b"\x89PNGtruncated")

    def test_wxgf_failure_keeps_raw_and_can_retry(self):
        self.file(data=b"wxgfsynthetic")
        result = export(self.plan(), self.state, (self.key, self.xor))
        self.assertEqual((result.completed, result.pending_conversion), (0, 1))
        self.assertEqual(len(list(self.output.rglob("*.wxgf"))), 1)
        class FakeDecoder:
            def decode(_, data, cancelled):
                return self.image()
        result = export(self.plan(), self.state, (self.key, self.xor), FakeDecoder())
        self.assertEqual(result.completed, 1)
        self.assertEqual(len(list(self.output.rglob("*.wxgf"))), 1)

    def test_output_account_ownership_and_source_overlap(self):
        self.file()
        for path in (self.source, self.root/"账号🖼", self.root):
            with self.assertRaises(AppError):
                build_plan(self.account, self.state, [self.group], path)
        export(self.plan(), self.state, (self.key, self.xor))
        second_root = self.root/"account2"/"msg"/"attach"
        (second_root/self.group).mkdir(parents=True)
        second = account_at(second_root)
        with State(second, self.root/"private") as state:
            with self.assertRaises(AppError) as exc:
                build_plan(second, state, [self.group], self.output)
            self.assertEqual(exc.exception.code, "output_owned")
            self.assertEqual(state.names(), {})

    def test_unowned_output_and_path_traversal_are_rejected(self):
        self.file()
        self.output.mkdir()
        (self.output/"existing.txt").write_text("keep")
        with self.assertRaises(AppError):
            self.plan()
        for value in ("../escape", str(self.root.absolute()), "photo.jpg:hidden", "CON.txt"):
            with self.assertRaises(AppError):
                child(self.output, value)

    @unittest.skipUnless(os.name == "nt", "Windows junction")
    def test_junction_is_rejected_before_reading_or_writing(self):
        import subprocess
        target = self.root/"junction-target"
        target.mkdir()
        link = self.root/"junction-link"
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                                capture_output=True, check=False)
        if result.returncode:
            self.skipTest("Cannot create junction in this environment")
        with self.assertRaises(AppError):
            child(self.root, link.name)
        self.assertFalse(list(target.iterdir()))

    def test_malicious_metadata_is_rejected(self):
        self.file()
        self.output.mkdir()
        write_json(self.output/"_导出信息.json", {"schema": 1, "account": self.account.uid,
            "sessions": {self.group: {"dir": "../escape"}}})
        with self.assertRaises(AppError):
            self.plan()

    def test_output_lock_blocks_other_job(self):
        self.output.mkdir()
        with output_lock(self.output):
            with self.assertRaises(AppError) as exc:
                with output_lock(self.output):
                    pass
            self.assertEqual(exc.exception.code, "output_busy")

    def test_manual_names_override_db_and_group_aliases_still_work(self):
        self.file()
        catalog = {self.group: {"id": self.group_id, "name": "数据库名", "verified": True,
                               "is_chatroom": True, "aliases": ["群备注"]}}
        self.state.replace_database_names(catalog)
        self.state.confirm_name(self.group, "人工名称")
        names = self.state.names()
        self.assertEqual(names[self.group[:16]]["name"], "人工名称")
        self.assertEqual(select_sessions([self.group], names, ["数据库名"]), [self.group])
        self.assertEqual(sessions(self.account, self.state)[0].kind, "群聊")
        invalid = {self.group: {"id": "wrong", "name": "bad", "verified": True}}
        with self.assertRaises(ValueError):
            self.state.replace_database_names(invalid)
        self.assertEqual(self.state.names(), names)

    def test_index_escapes_untrusted_names_and_encodes_urls(self):
        self.file()
        self.state.confirm_name(self.group, '<img src=x onerror="alert(1)"># &')
        export(self.plan(), self.state, (self.key, self.xor))
        document = (self.output/"_索引.html").read_text(encoding="utf-8")
        self.assertIn("&lt;img", document)
        self.assertNotIn("<script", document)
        self.assertIn("%23", document)

    def test_account_discovery_lists_multiple_accounts_without_selection(self):
        self.file()
        root = self.root/"discover"
        for label in ("first", "second"):
            (root/label/"msg"/"attach").mkdir(parents=True)
        accounts = discover_accounts([root], defaults=False)
        self.assertEqual(sum(a.root.parent == root for a in accounts), 2)

    def test_diagnostics_error_codes_never_include_exception_text(self):
        self.assertEqual(error_code(RuntimeError("secret and personal path")), "unexpected")
        self.assertEqual(error_code(OSError(28, "secret")), "disk_full")

    def test_photo_preview_uses_hd_only_and_creates_no_output(self):
        from wechat_photo_export.services.preview import preview_images
        self.file(suffix="_t", data=b"not-an-image")
        self.file(suffix="_W")
        with patch("wechat_photo_export.services.preview.image_keys", return_value=(self.key, self.xor)), \
             patch("wechat_photo_export.services.preview.decoder_path", return_value=None):
            images = preview_images(self.account, self.state, self.group)
        self.assertEqual(len(images), 1)
        self.assertEqual(validate_image(images[0]), "png")
        self.assertFalse(self.output.exists())

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI")
    def test_dpapi_account_binding_and_no_plaintext_cache(self):
        from wechat_photo_export.platforms.windows import protect
        secret = b"synthetic private key"
        blob = protect(secret, self.account.uid.encode())
        self.assertNotIn(secret, blob)
        self.assertEqual(protect(blob, self.account.uid.encode(), decrypt=True), secret)
        with self.assertRaises(AppError):
            protect(blob, b"other-account", decrypt=True)


if __name__ == "__main__":
    unittest.main()
