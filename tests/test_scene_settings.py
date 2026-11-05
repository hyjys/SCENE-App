import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scene_settings import DEFAULTS, load_settings, save_settings, validate_settings


class SettingsTests(unittest.TestCase):
    def test_round_trip_keeps_independent_sources_and_custom_fades(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"nested"/"settings.json"
            values = dict(DEFAULTS,audio_source="web",script_source="local",fade_in_seconds=7.5,fade_out_to=18,video_encoder="h264_nvenc")
            save_settings(values,path)
            self.assertEqual(load_settings(path),values)
            self.assertEqual(list(path.parent.iterdir()),[path])

    def test_rejects_nan_infinity_ranges_and_unsupported_encoders(self):
        for key,value in (("default_volume",101),("fade_in_seconds",-1),("fade_in_seconds",float("nan")),
                          ("fade_out_from",float("inf")),("audio_source","bad"),("video_encoder","bad")):
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):
                validate_settings({key:value})

    def test_corrupt_settings_fall_back_without_overwriting_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"settings.json"
            path.write_text('{broken',encoding="utf-8")
            self.assertEqual(load_settings(path),DEFAULTS)
            self.assertEqual(path.read_text(encoding="utf-8"),'{broken')

    def test_failed_atomic_replace_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"settings.json"
            save_settings(DEFAULTS,path)
            original=path.read_bytes()
            with patch.object(Path,"replace",side_effect=OSError("disk error")),self.assertRaises(OSError):
                save_settings(dict(DEFAULTS,default_volume=22),path)
            self.assertEqual(path.read_bytes(),original)
            self.assertEqual(list(path.parent.iterdir()),[path])
