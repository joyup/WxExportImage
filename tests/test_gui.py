"""界面选择绑定完整身份，过滤或排序后不会导错群。"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"src"))

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from wechat_photo_export.gui.window import Window
    from wechat_photo_export.services.catalog import Session
except ImportError:
    Window = None


@unittest.skipIf(Window is None, "Install desktop dependencies for Qt tests")
class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        with patch.object(Window, "run_task"):
            self.window = Window()
        self.addCleanup(self.window.close)
        self.rows = [Session("a"*32, "同名群", "群聊", "db"),
                     Session("b"*32, "同名群", "群聊", "db"),
                     Session("c"*32, "联系人", "单聊", "user")]
        self.window.populate(self.rows)

    def test_sort_and_filter_preserve_selected_identity(self):
        self.window.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
        self.window.table.sortItems(4, Qt.SortOrder.DescendingOrder)
        self.window.search.setText("联系人")
        self.assertEqual(self.window.selected, {"a"*32})
        self.window.search.setText("")
        checked = [self.window.table.item(i, 0).data(Qt.ItemDataRole.UserRole)
            for i in range(3) if self.window.table.item(i, 0).checkState() == Qt.CheckState.Checked]
        self.assertEqual(checked, ["a"*32])

    def test_all_selection_is_explicit_and_includes_hidden_contact(self):
        self.assertFalse(self.window.selected)
        self.window.kind.setCurrentText("群聊")
        self.window.set_selection(True)
        self.assertEqual(self.window.selected, {"a"*32, "b"*32, "c"*32})
        self.window.set_selection(False)
        self.assertFalse(self.window.selected)

    def test_output_change_invalidates_preview(self):
        self.window.plan = object()
        self.window.output.setText("new-output")
        self.assertIsNone(self.window.plan)
        self.assertFalse(self.window.start.isEnabled())


if __name__ == "__main__":
    unittest.main()
