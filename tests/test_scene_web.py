"""Runtime discovery without loading a browser or changing the registry."""
import sys
import unittest
from unittest.mock import Mock, patch

from backend import AppError
import scene_web


@unittest.skipUnless(sys.platform == "win32", "Windows runtime registration")
class RuntimeDiscoveryTests(unittest.TestCase):
    def test_missing_registry_does_not_load_tkwebview(self):
        with patch("winreg.OpenKey", side_effect=FileNotFoundError), \
                patch.dict(sys.modules, {"tkwebview": None}):
            self.assertIsNone(scene_web.webview2_runtime_version())
            with self.assertRaisesRegex(AppError, "WebView2 Runtime"):
                scene_web.create_browser(Mock())

    def test_searches_machine_registration_after_missing_user_keys(self):
        import winreg
        opened = Mock()
        opened.__enter__ = Mock(return_value=opened)
        opened.__exit__ = Mock(return_value=False)
        with patch("winreg.OpenKey", side_effect=[FileNotFoundError, FileNotFoundError, opened]) as read, \
                patch("winreg.QueryValueEx", return_value=("156.0.4314.58", winreg.REG_SZ)):
            self.assertEqual(scene_web.webview2_runtime_version(), "156.0.4314.58")
        self.assertEqual(read.call_args.args[0], winreg.HKEY_LOCAL_MACHINE)
        self.assertTrue(read.call_args.args[3] & winreg.KEY_WOW64_32KEY)

    def test_empty_zero_or_malformed_versions_are_not_installed(self):
        import winreg
        for value in ("", "0.0.0.0", "not a version", None):
            with self.subTest(value=value), patch("winreg.OpenKey"), \
                    patch("winreg.QueryValueEx", return_value=(value, winreg.REG_SZ)):
                self.assertIsNone(scene_web.webview2_runtime_version())


class PlatformTests(unittest.TestCase):
    def test_unsupported_platform_uses_actionable_error(self):
        with patch.object(scene_web.sys, "platform", "linux"):
            self.assertIsNone(scene_web.webview2_runtime_version())
            with self.assertRaisesRegex(AppError, "Windows"):
                scene_web.create_browser(Mock())


if __name__ == "__main__":
    unittest.main()
