"""Exercise the yt-dlp module and FFmpeg against a tiny local DASH video.

No YouTube access is required, and no test writes to the real Downloads folder.
"""

from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch
import uuid

import backend
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


def remove_test_workspace(path: Path) -> None:
    resolved = path.resolve()
    allowed = TEST_ROOT.resolve()
    if not resolved.is_relative_to(allowed) or resolved == allowed:
        raise RuntimeError(f"Refusing to delete outside the test workspace: {resolved}")
    shutil.rmtree(resolved)


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


class RecordingRunner(backend.ProcessRunner):
    def __init__(self):
        self.events: list[tuple[str, object]] = []
        self.commands: list[list[str]] = []
        super().__init__(lambda kind, payload: self.events.append((kind, payload)))

    def run(self, command: list[str], cwd: Path | None = None) -> list[str]:
        self.commands.append(command)
        return super().run(command, cwd)


class LocalMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for name in ("ffmpeg.exe",):
            if not (ROOT / name).is_file():
                raise unittest.SkipTest(f"Adjacent {name} is required for integration tests")
        TEST_ROOT.mkdir(exist_ok=True)
        cls.workspace = TEST_ROOT / ("backend-" + uuid.uuid4().hex)
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
            command = [str(cls.workspace / "ffmpeg.exe"), "-hide_banner", "-loglevel", "error",
                       "-nostdin", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10",
                       "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
                       "-t", "1.2", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                       "-c:a", "aac", "-f", "dash", "sample.mpd"]
            subprocess.run(command, cwd=cls.fixtures, check=True, capture_output=True,
                           creationflags=NO_WINDOW, timeout=30)
            cls.server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(cls.fixtures)))
            cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
            cls.server_thread.start()
            cls.url = f"http://127.0.0.1:{cls.server.server_port}/sample.mpd"
            cls.directory_patch = patch.object(backend, "app_dir", return_value=cls.workspace)
            cls.directory_patch.start()
            backend._js_runtime_args.cache_clear()
            cls.fetch_runner = RecordingRunner()
            cls.info = backend.fetch_formats(cls.url, cls.fetch_runner)
            cls.video = cls.info.video_formats[0]
            cls.audio = cls.info.audio_formats[0]
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
            remove_test_workspace(cls.workspace)

    @classmethod
    def tearDownClass(cls):
        cls._cleanup()

    def download(self, video=None, audio=None, mp3=True, mp4=True, fast=False):
        runner = RecordingRunner()
        result = backend.download_media(self.info, video, audio, mp3, mp4, fast, runner)
        self.assertTrue(result.is_file())
        self.assertGreater(result.stat().st_size, 0)
        self.assertEqual(result.parent, self.workspace / "Downloads")
        self.assertFalse(list(result.parent.glob(".gui-yt-dlp-*")))
        return result, runner

    def stream_info(self, path):
        result = subprocess.run([str(self.workspace / "ffmpeg.exe"), "-hide_banner", "-i", str(path)],
                                capture_output=True, text=True, encoding="utf-8", errors="replace",
                                creationflags=NO_WINDOW, timeout=15)
        return result.stderr

    def assert_streams(self, path, video=None, audio=None):
        text = self.stream_info(path)
        video_lines = re.findall(r"^\s*Stream #.*Video:.*$", text, re.MULTILINE)
        audio_lines = re.findall(r"^\s*Stream #.*Audio:.*$", text, re.MULTILINE)
        self.assertEqual(len(video_lines), int(video is not None), text)
        self.assertEqual(len(audio_lines), int(audio is not None), text)
        if video:
            self.assertIn("Video: " + video, video_lines[0])
        if audio:
            self.assertIn("Audio: " + audio, audio_lines[0])

    def test_fetch_lists_audio_and_video_using_module_without_sidecar(self):
        self.assertTrue(self.info.video_formats)
        self.assertTrue(self.info.audio_formats)
        self.assertFalse((self.workspace / "yt-dlp.exe").exists())
        self.assertEqual(self.fetch_runner.commands, [])
        self.assertTrue(any("Python 모듈" in str(payload) for kind, payload in self.fetch_runner.events if kind == "log"))
        self.assertTrue(all(fmt.kind == "audio" and fmt.raw.get("vcodec") == "none"
                            for fmt in self.info.audio_formats))
        self.assertTrue(all(fmt.kind == "video" for fmt in self.info.video_formats))
        self.assertFalse(any(str(payload).startswith("{") for kind, payload in self.fetch_runner.events
                             if kind == "log"), "Full media URLs should not flood the GUI log")

    def test_audio_mp3_vbr2(self):
        output, runner = self.download(audio=self.audio)
        self.assertEqual(output.suffix, ".mp3")
        self.assert_streams(output, audio="mp3")
        command = runner.commands[-1]
        self.assertEqual(command[command.index("-c:a") + 1], "libmp3lame")
        self.assertEqual(command[command.index("-q:a") + 1], "2")

    def test_video_mp4_slow_without_audio(self):
        output, runner = self.download(video=self.video)
        self.assertEqual(output.suffix, ".mp4")
        self.assert_streams(output, video="h264")
        command = runner.commands[-1]
        self.assertEqual(command[command.index("-preset") + 1], "slow")
        self.assertIn("-an", command)

    def test_video_and_audio_mp4_fast(self):
        output, runner = self.download(video=self.video, audio=self.audio, fast=True)
        self.assertEqual(output.suffix, ".mp4")
        self.assert_streams(output, video="h264", audio="mp3")
        command = runner.commands[-1]
        self.assertEqual(command[command.index("-preset") + 1], "fast")
        self.assertEqual(command[command.index("-c:a") + 1], "libmp3lame")
        self.assertEqual(command[command.index("-q:a") + 1], "2")
        self.assertIn("+faststart", command)

    def test_audio_original_codec(self):
        output, runner = self.download(audio=self.audio, mp3=False)
        self.assert_streams(output, audio="aac")
        self.assertEqual(len(runner.commands), 0, "Original audio must not be reencoded")

    def test_video_original_codec(self):
        output, runner = self.download(video=self.video, mp4=False)
        self.assert_streams(output, video="h264")
        self.assertEqual(len(runner.commands), 0, "Pure video must not be reencoded")

    def test_video_and_audio_original_codecs_in_mkv(self):
        output, runner = self.download(video=self.video, audio=self.audio, mp4=False)
        self.assertEqual(output.suffix, ".mkv")
        self.assert_streams(output, video="h264", audio="aac")
        command = runner.commands[-1]
        self.assertEqual(command[command.index("-c") + 1], "copy")

    def test_existing_result_is_preserved(self):
        first, _ = self.download(audio=self.audio)
        original = first.read_bytes()
        second, _ = self.download(audio=self.audio)
        self.assertNotEqual(first, second)
        self.assertEqual(first.read_bytes(), original)
        self.assertTrue(second.is_file())

    def test_no_selection_rejected_without_new_downloads(self):
        with self.assertRaises(backend.AppError):
            backend.download_media(self.info, None, None, True, True, False, RecordingRunner())

    def test_unavailable_selection_rejected(self):
        missing = backend.MediaFormat("not-present", "video")
        with self.assertRaises(backend.AppError):
            backend.download_media(self.info, missing, None, True, True, False, RecordingRunner())


class ErrorAndProcessTests(unittest.TestCase):
    def test_invalid_url_rejected_before_starting_process(self):
        runner = RecordingRunner()
        for invalid in ("", "not a URL", "file:///C:/Windows/win.ini", "https://example.com/\n-o evil"):
            with self.subTest(invalid=invalid), self.assertRaises(backend.AppError):
                backend.fetch_formats(invalid, runner)
        self.assertFalse(runner.commands)

    def test_missing_ffmpeg_has_useful_error(self):
        with patch.object(backend, "app_dir", return_value=ROOT / ".test-work" / "missing-sidecars"):
            with self.assertRaisesRegex(backend.AppError, "ffmpeg.exe"):
                backend._executable("ffmpeg.exe")

    def test_subprocess_failure_preserves_error_detail(self):
        runner = RecordingRunner()
        with self.assertRaisesRegex(backend.AppError, "useful diagnostic"):
            runner.run([sys.executable, "-c", "import sys; print('useful diagnostic'); sys.exit(7)"])

    def test_cancel_terminates_running_process_promptly(self):
        ready = threading.Event()
        errors = []
        runner = backend.ProcessRunner(lambda kind, payload: ready.set() if payload == "READY" else None)

        def work():
            try:
                runner.run([sys.executable, "-u", "-c", "import time; print('READY', flush=True); time.sleep(60)"])
            except BaseException as exc:
                errors.append(exc)

        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        try:
            self.assertTrue(ready.wait(8), "Child process did not start")
            runner.cancel()
            thread.join(timeout=8)
            self.assertFalse(thread.is_alive(), "Cancellation did not stop the subprocess")
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], backend.Cancelled)
        finally:
            runner.cancel()
            thread.join(timeout=8)

    def test_frozen_executable_directory_is_used(self):
        fake_exe = ROOT / ".test-work" / "relocated" / "gui-yt-dlp.exe"
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", str(fake_exe)):
            self.assertEqual(backend.app_dir(), fake_exe.resolve().parent)


class ModuleApiTests(unittest.TestCase):
    def setUp(self):
        TEST_ROOT.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="module-", dir=TEST_ROOT)
        self.workspace = Path(self.temporary.name)
        self.directory_patch = patch.object(backend, "app_dir", return_value=self.workspace)
        self.runtime_patch = patch.object(backend, "_js_runtimes", return_value={})
        self.directory_patch.start()
        self.runtime_patch.start()

    def tearDown(self):
        self.runtime_patch.stop()
        self.directory_patch.stop()
        self.temporary.cleanup()

    def test_extract_info_uses_api_and_preserves_module_error(self):
        runner = RecordingRunner()
        fake = MagicMock()
        fake.__enter__.return_value = fake
        fake.extract_info.side_effect = backend.yt_dlp.utils.DownloadError("useful API diagnostic")
        with patch.object(backend.yt_dlp, "YoutubeDL", return_value=fake) as ydl:
            with self.assertRaisesRegex(backend.AppError, "useful API diagnostic"):
                backend.fetch_formats("https://example.com/media", runner)
        fake.extract_info.assert_called_once_with("https://example.com/media", download=False)
        options = ydl.call_args.args[0]
        self.assertTrue(options["noplaylist"])
        self.assertEqual(options["socket_timeout"], 10)
        self.assertFalse(runner.commands)

    def test_download_treats_format_id_literally_and_reports_api_progress(self):
        runner = RecordingRunner()
        selected = backend.MediaFormat("a/b+id", "audio", "m4a")
        info = backend.MediaInfo("https://example.com/media", "한글 제목", 1, [selected], [])
        options_seen = []
        fake = MagicMock()
        fake.__enter__.return_value = fake

        def extract(url, download):
            self.assertTrue(download)
            options = options_seen[0]
            available = [{"format_id": "a"}, {"format_id": selected.format_id}, {"format_id": "b+id"}]
            self.assertEqual(list(options["format"]({"formats": available})), [available[1]])
            options["progress_hooks"][0]({"status": "downloading", "downloaded_bytes": 50,
                                          "total_bytes": 100, "speed": 1024, "eta": 2})
            output = Path(options["paths"]["home"]) / "한글 제목.m4a"
            output.write_bytes(b"audio")
            options["post_hooks"][0](str(output))
            return {"filepath": str(output)}

        def factory(options):
            options_seen.append(options)
            return fake

        fake.extract_info.side_effect = extract
        with patch.object(backend.yt_dlp, "YoutubeDL", side_effect=factory):
            output = backend._download_format(info, selected, self.workspace, runner)
        self.assertEqual(output.read_bytes(), b"audio")
        self.assertIn(("progress", 50.0), runner.events)
        self.assertTrue(any("남은 시간 2초" in str(payload) for _, payload in runner.events))
        self.assertFalse(runner.commands)

    def test_api_progress_hook_cancellation_retains_partial_without_publishing(self):
        runner = RecordingRunner()
        selected = backend.MediaFormat("1", "audio", "m4a")
        info = backend.MediaInfo("https://example.com/media", "취소", 1, [selected], [])
        fake = MagicMock()
        fake.__enter__.return_value = fake
        options_seen = []

        def factory(options):
            options_seen.append(options)
            return fake

        def extract(url, download):
            options = options_seen[0]
            (Path(options["paths"]["home"]) / "partial.m4a.part").write_bytes(b"partial")
            runner.cancel()
            options["progress_hooks"][0]({"status": "downloading"})

        fake.extract_info.side_effect = extract
        with patch.object(backend.yt_dlp, "YoutubeDL", side_effect=factory):
            with self.assertRaisesRegex(backend.Cancelled, "미완성 파일"):
                backend.download_media(info, None, selected, False, False, False, runner)
        downloads = self.workspace / "Downloads"
        self.assertEqual(list(downloads.glob("*.m4a")), [])
        self.assertEqual(len(list(downloads.glob(".gui-yt-dlp-*/audio/partial.m4a.part"))), 1)


class JsRuntimeTests(unittest.TestCase):
    def setUp(self):
        backend._js_runtime_args.cache_clear()

    def tearDown(self):
        backend._js_runtime_args.cache_clear()

    def test_source_bundled_deno_is_preferred_over_system_node(self):
        bundled = ROOT / "vendor" / "deno.exe"
        with patch.object(sys, "frozen", False, create=True), \
                patch.object(backend, "app_dir", return_value=ROOT), \
                patch.object(backend, "_runtime_is_supported", return_value=True) as supported, \
                patch.object(backend.shutil, "which", side_effect=AssertionError("Node search must not run")):
            args = backend._js_runtime_args()
        self.assertEqual(args, ["--no-js-runtimes", "--js-runtimes", f"deno:{bundled}"])
        supported.assert_called_once_with(bundled, "deno")

    def test_frozen_uses_embedded_deno_without_path_or_node(self):
        deno_source = ROOT / "vendor" / "deno.exe"
        if not deno_source.is_file():
            self.skipTest("vendor/deno.exe is required for the bundled runtime integration test")
        TEST_ROOT.mkdir(exist_ok=True)
        workspace = TEST_ROOT / ("runtime-" + uuid.uuid4().hex)
        runtime_dir = workspace / "bundle" / "runtime"
        runtime_dir.mkdir(parents=True)
        embedded = runtime_dir / "deno.exe"
        os.link(deno_source, embedded)
        try:
            with patch.object(sys, "frozen", True, create=True), \
                    patch.object(sys, "_MEIPASS", str(workspace / "bundle"), create=True), \
                    patch.object(sys, "executable", str(workspace / "app" / "gui-yt-dlp.exe")), \
                    patch.object(backend, "app_dir", return_value=workspace / "app"), \
                    patch.dict(os.environ, {"PATH": ""}), \
                    patch.object(backend.shutil, "which", side_effect=AssertionError("Node search must not run")):
                args = backend._js_runtime_args()
            self.assertEqual(args, ["--no-js-runtimes", "--js-runtimes", f"deno:{embedded}"])
        finally:
            backend._js_runtime_args.cache_clear()
            remove_test_workspace(workspace)

    def test_frozen_missing_deno_fails_without_node_fallback(self):
        with patch.object(sys, "frozen", True, create=True), \
                patch.object(sys, "_MEIPASS", str(ROOT / ".test-work" / "missing-bundle"), create=True), \
                patch.object(backend, "app_dir", return_value=ROOT), \
                patch.object(backend, "_runtime_is_supported", return_value=False), \
                patch.object(backend.shutil, "which", side_effect=AssertionError("Node search must not run")):
            with self.assertRaisesRegex(backend.AppError, "Deno"):
                backend._js_runtime_args()

    def test_vendor_deno_evaluates_javascript_with_empty_path(self):
        deno = ROOT / "vendor" / "deno.exe"
        if not deno.is_file():
            self.skipTest("vendor/deno.exe is required for the runtime integration test")
        environment = os.environ.copy()
        environment.update(PATH="", DENO_NO_UPDATE_CHECK="1")
        result = subprocess.run(
            [str(deno), "eval", "console.log(JSON.stringify({engine: Deno.version.deno, answer: 6 * 7}))"],
            env=environment, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            creationflags=NO_WINDOW, timeout=15, check=True,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["answer"], 42)
        self.assertGreaterEqual(int(payload["engine"].split(".")[0]), 2)


if __name__ == "__main__":
    unittest.main()
