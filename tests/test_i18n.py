"""OS display-language detection and localized backend behavior."""

from __future__ import annotations

import ast
from pathlib import Path
import re
import string
import unittest
from unittest.mock import patch

import backend
import i18n
import scene_backend


ROOT = Path(__file__).resolve().parents[1]


class LanguageDetectionTests(unittest.TestCase):
    def test_windows_display_language_takes_precedence_over_region(self):
        with patch.object(i18n.sys, "platform", "win32"), \
                patch.object(i18n, "_windows_ui_language", return_value=0x0409), \
                patch.object(i18n.locale, "getlocale", return_value=("ko_KR", "UTF-8")):
            self.assertEqual(i18n.detect_language(), "en")

    def test_korean_primary_language_and_other_windows_languages(self):
        for langid, expected in [(0x0412, "ko"), (0x0812, "ko"), (0x0409, "en"), (0x0411, "en")]:
            with self.subTest(langid=langid), patch.object(i18n.sys, "platform", "win32"), \
                    patch.object(i18n, "_windows_ui_language", return_value=langid):
                self.assertEqual(i18n.detect_language(), expected)

    def test_locale_fallback_on_other_platforms(self):
        for language, expected in [("ko_KR", "ko"), ("ko-KR", "ko"), ("Korean_Korea", "ko"),
                                   ("en_US", "en"), ("ja_JP", "en"), (None, "en")]:
            with self.subTest(language=language), patch.object(i18n.sys, "platform", "linux"), \
                    patch.object(i18n.locale, "getlocale", return_value=(language, "UTF-8")):
                self.assertEqual(i18n.detect_language(), expected)

    def test_missing_windows_api_falls_back_without_deprecated_locale_api(self):
        with patch.object(i18n.sys, "platform", "win32"), \
                patch.object(i18n, "_windows_ui_language", side_effect=OSError("unavailable")), \
                patch.object(i18n.locale, "getlocale", return_value=("ko_KR", "UTF-8")):
            self.assertEqual(i18n.detect_language(), "ko")


class TranslationTests(unittest.TestCase):
    def setUp(self):
        self.previous = i18n.get_language()

    def tearDown(self):
        i18n.set_language(self.previous)

    def test_korean_and_english_preserve_format_values(self):
        for language, expected in [("ko", "저장 완료: cue {1}.mp3"), ("en", "Saved: cue {1}.mp3")]:
            i18n.set_language(language)
            self.assertEqual(i18n.tr("저장 완료: {path}", path="cue {1}.mp3"), expected)

    def test_backend_error_and_cancel_are_english(self):
        i18n.set_language("en")
        with self.assertRaisesRegex(backend.AppError, "Enter a valid http"):
            backend._validate_url("not a URL")
        runner = backend.ProcessRunner(lambda *_args: None)
        runner.cancel()
        with self.assertRaisesRegex(backend.Cancelled, "Operation cancelled"):
            runner.check_cancelled()
        with self.assertRaisesRegex(backend.AppError, "cue number"):
            scene_backend.scene_output_name("bad", "Title")

    def test_decimal_cue_validation_guidance_in_both_languages(self):
        for language, message in [("ko", "소수점"), ("en", "decimal point")]:
            i18n.set_language(language)
            self.assertEqual(scene_backend.scene_output_name("007.50", "Title"), "bgm007.50_Title.mp3")
            with self.assertRaisesRegex(backend.AppError, message):
                scene_backend.scene_output_name(".5", "Title")

    def test_english_scene_selection_keeps_ids_and_bitrate(self):
        i18n.set_language("en")
        events = []
        runner = backend.ProcessRunner(lambda kind, payload: events.append((kind, payload)))
        best = backend.MediaFormat("best", "audio", raw={"abr": 192, "vcodec": "none"})
        info = backend.MediaInfo("https://example.com", "Title", 1, [best], [])
        self.assertIs(scene_backend._select_audio(info, runner), best)
        log = "\n".join(str(payload) for _, payload in events)
        self.assertIn("Auto-selected: audio-only ID best · 192 kbps", log)
        self.assertNotRegex(log, r"[가-힣]")

    def test_all_backend_korean_message_templates_have_translations(self):
        for filename in ("backend.py", "scene_backend.py"):
            tree = ast.parse((ROOT / filename).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and re.search(r"[가-힣]", node.value):
                    with self.subTest(filename=filename, line=node.lineno):
                        self.assertIn(node.value, i18n._english)

    def test_registered_translations_preserve_placeholder_names(self):
        formatter = string.Formatter()
        for korean, english in i18n._english.items():
            fields = lambda template: {field for _, field, _, _ in formatter.parse(template) if field is not None}
            with self.subTest(template=korean):
                self.assertEqual(fields(korean), fields(english))

    def test_unknown_messages_and_invalid_language(self):
        i18n.set_language("en")
        self.assertEqual(i18n.tr("Unchanged {value}", value="text"), "Unchanged text")
        with self.assertRaises(ValueError):
            i18n.set_language("fr")


if __name__ == "__main__":
    unittest.main()
