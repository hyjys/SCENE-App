"""SCENE cue naming, audio selection and real portable media conversion tests."""

from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import unittest
from unittest.mock import patch
import uuid

import backend
import scene_backend
import i18n


ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = ROOT / ".test-work"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def setUpModule():
    global _previous_language
    _previous_language = i18n.get_language()
    i18n.set_language("ko")


def tearDownModule():
    i18n.set_language(_previous_language)


class RecordingRunner(backend.ProcessRunner):
    def __init__(self):
        self.events = []
        self.commands = []
        super().__init__(lambda kind, payload: self.events.append((kind, payload)))

    def run(self, command, cwd=None):
        self.commands.append(command)
        return super().run(command, cwd)


def audio(format_id, abr=None, tbr=None, **raw):
    return backend.MediaFormat(format_id, "audio", raw={
        "abr": abr, "tbr": tbr, "vcodec": "none", "acodec": "opus", **raw,
    })


class SceneSelectionTests(unittest.TestCase):
    def info(self, formats):
        return backend.MediaInfo("https://example.com/media", "원래 제목", 1, formats, [])

    def test_cue_number_and_title_are_used_verbatim_when_safe(self):
        self.assertEqual(scene_backend.scene_output_name("13", "본막 시작"), "bgm13_본막 시작.mp3")
        self.assertEqual(scene_backend.scene_output_name(" 0013 ", " 오프닝 "), "bgm0013_오프닝.mp3")
        self.assertEqual(scene_backend.scene_output_name("7", "오프닝"), "bgm7_오프닝.mp3")
        self.assertEqual(scene_backend.scene_output_name("007", "오프닝"), "bgm007_오프닝.mp3")

    def test_decimal_cue_numbers_preserve_integer_and_fractional_zeros(self):
        for number in ("7.5", "13.1", "007.50", "0", "0.0", "00.000", "12345678901.2"):
            with self.subTest(number=number):
                self.assertEqual(scene_backend.scene_output_name(f" {number} ", "Title"), f"bgm{number}_Title.mp3")

    def test_invalid_number_and_empty_title_are_rejected(self):
        for number, title in [("", "음원"), ("-1", "음원"), ("-1.5", "음원"),
                              ("１２", "음원"), ("1/2", "음원"), ("1" * 13, "음원"),
                              (".5", "음원"), ("5.", "음원"), ("1.2.3", "음원"),
                              ("1e3", "음원"), ("+1.5", "음원"), ("1,5", "음원"),
                              ("123456789012.3", "음원"), ("1 .5", "음원"),
                              ("13", " "), ("13", "...")]:
            with self.subTest(number=number, title=title), self.assertRaises(backend.AppError):
                scene_backend.scene_output_name(number, title)

    def test_windows_filename_characters_and_traversal_are_sanitized(self):
        name = scene_backend.scene_output_name("13", '../C:\\음원:<도입>|?*\n')
        self.assertEqual(Path(name).name, name)
        self.assertFalse(re.search(r'[<>:"/\\|?*\x00-\x1f]', name))
        self.assertTrue(name.startswith("bgm13_"))
        self.assertTrue(name.endswith(".mp3"))

    def test_long_unicode_title_is_shortened_at_a_character_boundary(self):
        name = scene_backend.scene_output_name("13", "🎭가" * 100)
        self.assertLessEqual(len(name.encode("utf-16-le")) // 2, 120)
        self.assertNotIn("�", name)

    def test_numerical_bitrate_beats_codec_and_video_bitrate(self):
        best = audio("highest", abr="192")
        info = self.info([audio("low", abr=96), best,
                          audio("video", abr=9999, vcodec="h264"),
                          audio("drm", abr=2000, has_drm=True)])
        self.assertIs(scene_backend._select_audio(info, RecordingRunner()), best)

    def test_tbr_is_fallback_for_invalid_abr_and_known_bitrate_wins(self):
        best = audio("fallback", abr=float("nan"), tbr="256")
        info = self.info([audio("negative", abr=-1, tbr=120),
                          audio("missing", asr=192000), best,
                          audio("infinity", abr=float("inf"), tbr=128), audio("lower", abr=192)])
        runner = RecordingRunner()
        self.assertIs(scene_backend._select_audio(info, runner), best)
        self.assertTrue(any("일부 형식" in str(value) for _, value in runner.events))

    def test_unknown_bitrate_falls_back_honestly(self):
        better = audio("higher-sample-rate", asr=48000)
        runner = RecordingRunner()
        selected = scene_backend._select_audio(self.info([audio("other", asr=44100), better]), runner)
        self.assertIs(selected, better)
        self.assertTrue(any("비트레이트 정보가 없어" in str(value) for _, value in runner.events))

    def test_video_only_info_is_rejected(self):
        with self.assertRaisesRegex(backend.AppError, "오디오 전용"):
            scene_backend._select_audio(self.info([]), RecordingRunner())

    def test_download_requests_exact_audio_id_and_original_make_mp3_options(self):
        best = audio("a-best", abr=192)
        info = self.info([audio("a-low", abr=64), best])
        runner = RecordingRunner()
        with patch.object(backend, "_executable"), patch.object(backend, "fetch_formats", return_value=info) as fetch, \
                patch.object(backend, "download_media", return_value=Path("done.mp3")) as download:
            result = scene_backend.download_scene_audio(info.url, "013.50", "커튼콜", runner)
        self.assertEqual(result, Path("done.mp3"))
        fetch.assert_called_once_with(info.url, runner)
        download.assert_called_once_with(info, None, best, True, False, False, runner,
                                         output_name="bgm013.50_커튼콜.mp3")

    def test_invalid_naming_stops_before_any_process_or_lookup(self):
        with patch.object(backend, "fetch_formats") as fetch, patch.object(backend, "_executable") as executable:
            with self.assertRaises(backend.AppError):
                scene_backend.download_scene_audio("https://example.com", "abc", "제목", RecordingRunner())
        fetch.assert_not_called()
        executable.assert_not_called()

    def test_optional_output_name_cannot_escape_downloads(self):
        runner = RecordingRunner()
        with self.assertRaises(backend.AppError):
            backend.download_media(self.info([]), None, None, True, False, False, runner,
                                   output_name="../escaped.mp3")
        self.assertFalse(runner.commands)

    def test_already_cancelled_operations_do_not_launch_processes(self):
        runner = RecordingRunner()
        runner.cancel()
        with self.assertRaises(backend.Cancelled):
            scene_backend.convert_scene_file(Path("missing.wav"), "13", "제목", runner)
        with self.assertRaises(backend.Cancelled):
            scene_backend.download_scene_audio("https://example.com", "13", "제목", runner)
        self.assertFalse(runner.commands)


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


class SceneMediaIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (ROOT / "ffmpeg.exe").is_file():
            raise unittest.SkipTest("Adjacent FFmpeg is required")
        TEST_ROOT.mkdir(exist_ok=True)
        cls.workspace = TEST_ROOT / ("scene-" + uuid.uuid4().hex)
        cls.workspace.mkdir()
        cls.server = None
        cls.directory_patch = None
        try:
            for name in ("ffmpeg.exe",):
                os.link(ROOT / name, cls.workspace / name)
            if (ROOT / "vendor" / "deno.exe").is_file():
                (cls.workspace / "vendor").mkdir()
                os.link(ROOT / "vendor" / "deno.exe", cls.workspace / "vendor" / "deno.exe")
            cls.fixtures = cls.workspace / "fixtures"
            cls.fixtures.mkdir()
            ffmpeg = str(cls.workspace / "ffmpeg.exe")
            cls.wav = cls.fixtures / "원본 음원.wav"
            subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
                            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
                            "-t", "0.8", str(cls.wav)], check=True, capture_output=True,
                           creationflags=NO_WINDOW, timeout=30)
            subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
                            "-i", str(cls.wav), "-map", "0:a:0", "-map", "0:a:0",
                            "-c:a", "aac", "-b:a:0", "64k", "-b:a:1", "160k",
                            "-f", "dash", "sample.mpd"], cwd=cls.fixtures,
                           check=True, capture_output=True, creationflags=NO_WINDOW, timeout=30)
            cls.server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(cls.fixtures)))
            cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
            cls.server_thread.start()
            cls.url = f"http://127.0.0.1:{cls.server.server_port}/sample.mpd"
            cls.directory_patch = patch.object(backend, "app_dir", return_value=cls.workspace)
            cls.directory_patch.start()
            backend._js_runtime_args.cache_clear()
        except BaseException:
            cls._cleanup()
            raise

    @classmethod
    def _cleanup(cls):
        backend._js_runtime_args.cache_clear()
        if cls.directory_patch:
            cls.directory_patch.stop()
        if cls.server:
            cls.server.shutdown()
            cls.server.server_close()
            cls.server_thread.join(timeout=5)
        if cls.workspace.exists():
            resolved = cls.workspace.resolve()
            if not resolved.is_relative_to(TEST_ROOT.resolve()) or resolved == TEST_ROOT.resolve():
                raise RuntimeError(f"Refusing to clean unsafe test directory: {resolved}")
            shutil.rmtree(resolved)

    @classmethod
    def tearDownClass(cls):
        cls._cleanup()

    def assert_mp3_audio_only(self, path):
        result = subprocess.run([str(self.workspace / "ffmpeg.exe"), "-hide_banner", "-i", str(path)],
                                capture_output=True, text=True, encoding="utf-8", errors="replace",
                                creationflags=NO_WINDOW, timeout=15)
        self.assertIn("Audio: mp3", result.stderr)
        self.assertNotIn("Video:", result.stderr)
        self.assertGreater(path.stat().st_size, 0)

    def test_local_file_converts_without_using_yt_dlp_and_preserves_source(self):
        original = self.wav.read_bytes()
        runner = RecordingRunner()
        with patch.object(backend.yt_dlp, "YoutubeDL", side_effect=AssertionError("Local conversion must not use yt-dlp")):
            output = scene_backend.convert_scene_file(self.wav, "007.50", "본막", runner)
        self.assertEqual(output.name, "bgm007.50_본막.mp3")
        self.assertEqual(self.wav.read_bytes(), original)
        self.assert_mp3_audio_only(output)
        self.assertEqual(len(runner.commands), 1)
        command = runner.commands[0]
        self.assertEqual(command[command.index("-c:a") + 1], "libmp3lame")
        self.assertEqual(command[command.index("-q:a") + 1], "2")
        self.assertEqual(command[command.index("-map") + 1], "0:a:0")
        self.assertIn("-vn", command)
        self.assertFalse(list(output.parent.glob(".gui-yt-dlp-*")))

    def test_existing_mp3_with_same_target_name_is_preserved(self):
        first = scene_backend.convert_scene_file(self.wav, "14", "커튼콜", RecordingRunner())
        original = first.read_bytes()
        second = scene_backend.convert_scene_file(first, "14", "커튼콜", RecordingRunner())
        self.assertEqual(second.name, "bgm14_커튼콜 (2).mp3")
        self.assertEqual(first.read_bytes(), original)
        self.assert_mp3_audio_only(second)

    def test_full_download_chain_chooses_higher_bitrate_and_custom_name(self):
        runner = RecordingRunner()
        output = scene_backend.download_scene_audio(self.url, "015", "등장", runner)
        self.assertEqual(output.name, "bgm015_등장.mp3")
        self.assert_mp3_audio_only(output)
        self.assertFalse((self.workspace / "yt-dlp.exe").exists())
        self.assertEqual(len(runner.commands), 1, "Only FFmpeg conversion launches a subprocess")
        convert_command = runner.commands[0]
        self.assertEqual(convert_command[convert_command.index("-c:a") + 1], "libmp3lame")
        self.assertEqual(convert_command[convert_command.index("-q:a") + 1], "2")
        self.assertTrue(any("160 kbps" in str(payload) for _, payload in runner.events))
        self.assertTrue(any("오디오 다운로드 · 1 /" in str(payload) for _, payload in runner.events))
        self.assertFalse(list(output.parent.glob(".gui-yt-dlp-*")))

    def test_missing_and_empty_sources_fail_without_creating_downloads(self):
        empty = self.fixtures / "empty.wav"
        empty.touch()
        for source in (empty, self.fixtures / "missing.wav", self.fixtures):
            runner = RecordingRunner()
            with self.subTest(source=source), self.assertRaises(backend.AppError):
                scene_backend.convert_scene_file(source, "16", "잘못된 음원", runner)
            self.assertFalse(runner.commands)

    def test_cancelled_conversion_preserves_source_and_partial_without_publishing(self):
        original = self.wav.read_bytes()
        runner = RecordingRunner()
        downloads = self.workspace / "Downloads"
        downloads.mkdir(exist_ok=True)
        before = set(downloads.glob(".gui-yt-dlp-*"))

        def interrupt(command, cwd=None):
            Path(command[-1]).write_bytes(b"partial mp3")
            runner.cancel()
            raise backend.Cancelled("작업을 취소했습니다.")

        with patch.object(runner, "run", side_effect=interrupt):
            with self.assertRaisesRegex(backend.Cancelled, "미완성 파일"):
                scene_backend.convert_scene_file(self.wav, "17", "취소 확인", runner)
        self.assertEqual(self.wav.read_bytes(), original)
        self.assertFalse((downloads / "bgm17_취소 확인.mp3").exists())
        retained = set(downloads.glob(".gui-yt-dlp-*")) - before
        self.assertEqual(len(retained), 1)
        work_dir = retained.pop()
        self.assertEqual((work_dir / "converted.mp3").read_bytes(), b"partial mp3")
        backend._cleanup_work_dir(work_dir, downloads)

    def test_unreadable_audio_returns_ffmpeg_error_and_preserves_original(self):
        invalid = self.fixtures / "invalid.wav"
        invalid.write_bytes(b"not an audio file")
        with self.assertRaisesRegex(backend.AppError, "ffmpeg.exe"):
            scene_backend.convert_scene_file(invalid, "18", "실패 확인", RecordingRunner())
        self.assertEqual(invalid.read_bytes(), b"not an audio file")
        self.assertFalse((self.workspace / "Downloads" / "bgm18_실패 확인.mp3").exists())


if __name__ == "__main__":
    unittest.main()
