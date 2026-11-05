"""Projector video selection and real H.264/MP3 conversion, without public media."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import unittest
from unittest.mock import patch
import uuid

import backend
import scene_video as video


ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = ROOT / ".test-work"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class RecordingRunner(backend.ProcessRunner):
    def __init__(self):
        self.events = []
        self.commands = []
        super().__init__(lambda kind, payload: self.events.append((kind, payload)))

    def run(self, command, cwd=None):
        self.commands.append(command)
        return super().run(command, cwd)


def fmt(identifier, *, kind="video", **raw):
    defaults = {"vcodec": "h264" if kind == "video" else "none",
                "acodec": "aac", "height": 720, "fps": 30, "tbr": 1000}
    defaults.update(raw)
    return backend.MediaFormat(identifier, kind, ext="mp4" if kind == "video" else "m4a", raw=defaults)


def info(videos, audios=()):
    return backend.MediaInfo("https://example.com/video", "원본 영상", 0.4, list(audios), list(videos))


class VideoSelectionTests(unittest.TestCase):
    def select(self, media):
        runner = RecordingRunner()
        with patch.object(backend, "_executable"), patch.object(backend, "fetch_formats", return_value=media), \
                patch.object(video, "_produce", return_value=Path("done.mp4")) as produce, \
                patch.object(backend, "_download_format", side_effect=lambda _, selected, *_args: Path(selected.format_id)) as download:
            result = video.download_scene_video(media.url, "007.50", "커튼콜", runner, {})
            sources = produce.call_args.args[4](Path("work"))
        self.assertEqual(result, Path("done.mp4"))
        self.assertEqual(produce.call_args.args[:2], ("007.50", "커튼콜"))
        return sources, download, runner

    def test_highest_quality_muxed_video_works_without_audio_only(self):
        selected = fmt("best", height=1080, fps=60, tbr=4000)
        sources, download, _ = self.select(info([fmt("low"), selected]))
        self.assertEqual(sources, (Path("best"), None))
        self.assertIs(download.call_args.args[1], selected)
        self.assertEqual(download.call_count, 1)

    def test_quality_uses_height_then_framerate_then_bitrate(self):
        best = fmt("best", height=1080, fps=60, tbr=3000)
        sources, _, _ = self.select(info([
            fmt("resolution-first", height=720, fps=120, tbr=90000),
            fmt("fps-second", height=1080, fps=30, tbr=90000),
            fmt("bitrate-third", height=1080, fps=60, tbr=1000),
            fmt("malformed", height=float("nan"), fps=float("inf"), tbr=-1), best,
        ]))
        self.assertEqual(sources[0], Path("best"))

    def test_best_separate_audio_overrides_muxed_audio(self):
        sources, download, _ = self.select(info([fmt("video")], [fmt("a-low", kind="audio", abr=64),
                                                                   fmt("a-high", kind="audio", abr=192)]))
        self.assertEqual(sources, (Path("video"), Path("a-high")))
        self.assertEqual(download.call_count, 2)

    def test_unusable_audio_only_candidates_fall_back_to_muxed_audio(self):
        candidates = [fmt("drm-audio", kind="audio", has_drm=True),
                      fmt("muxed-in-audio-list", kind="audio", vcodec="h264"),
                      fmt("no-audio", kind="audio", acodec="none")]
        sources, download, _ = self.select(info([fmt("muxed")], candidates))
        self.assertEqual(sources, (Path("muxed"), None))
        self.assertEqual(download.call_count, 1)

    def test_silent_video_is_a_valid_download(self):
        sources, _, _ = self.select(info([fmt("silent", acodec="none")]))
        self.assertEqual(sources, (Path("silent"), None))

    def test_drm_nonvideo_storyboards_and_missing_ids_are_rejected(self):
        storyboard = fmt("storyboard")
        storyboard.ext = "mhtml"
        invalid = [fmt("drm", has_drm=True), fmt("audio", kind="audio"),
                   fmt("no-codec", vcodec="none"), fmt(""), storyboard,
                   fmt("images", protocol="mhtml")]
        with patch.object(backend, "_executable"), patch.object(backend, "fetch_formats", return_value=info(invalid)), \
                patch.object(backend, "_download_format") as download:
            with self.assertRaisesRegex(backend.AppError, "영상 형식이 없습니다"):
                video.download_scene_video("https://example.com/video", "1", "제목", RecordingRunner(), {})
        download.assert_not_called()

    def test_invalid_number_title_and_settings_stop_before_network_and_ffmpeg(self):
        cases = [("-1", "제목", {}), ("1.2.3", "제목", {}), ("1", " ", {}),
                 ("1", "제목", {"video_encoder": "unsupported"}),
                 ("1", "제목", {"video_preset": "arbitrary"}),
                 ("1", "제목", {"default_volume": float("nan")}),
                 ("1", "제목", {"fade_in_seconds": -1})]
        for number, title, settings in cases:
            with self.subTest(number=number, settings=settings), patch.object(backend, "fetch_formats") as fetch, \
                    patch.object(backend, "_executable") as executable:
                with self.assertRaises(backend.AppError):
                    video.download_scene_video("https://example.com/video", number, title, RecordingRunner(), settings)
            fetch.assert_not_called()
            executable.assert_not_called()

    def test_cancel_before_download_or_local_file_access(self):
        runner = RecordingRunner()
        runner.cancel()
        with patch.object(backend, "fetch_formats") as fetch, patch.object(backend, "_executable") as executable:
            with self.assertRaises(backend.Cancelled):
                video.download_scene_video("https://example.com/video", "1", "제목", runner, {})
            with self.assertRaises(backend.Cancelled):
                video.convert_scene_video(Path("missing.mp4"), "1", "제목", runner, {})
        fetch.assert_not_called()
        executable.assert_not_called()

    def test_default_command_and_hardware_encoder_options(self):
        with patch.object(backend, "_executable", return_value=Path("ffmpeg.exe")):
            command = video.video_command(Path("source.mp4"), None, Path("output.mp4"), {})
            self.assertEqual(command[command.index("-c:v") + 1], "libx264")
            self.assertEqual(command[command.index("-preset") + 1], "veryslow")
            self.assertEqual(command[command.index("-c:a") + 1], "libmp3lame")
            self.assertEqual(command[command.index("-q:a") + 1], "2")
            self.assertIn("0:a:0?", command)
            self.assertIn("+faststart", command)
            for encoder in ("h264_nvenc", "h264_qsv"):
                gpu = video.video_command(Path("source.mp4"), Path("audio.m4a"), Path("out.mp4"),
                                          {"video_encoder": encoder})
                self.assertEqual(gpu[gpu.index("-c:v") + 1], encoder)
                self.assertIn("1:a:0", gpu)
                self.assertNotIn("-crf", gpu)


class VideoConversionIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (ROOT / "ffmpeg.exe").is_file():
            raise unittest.SkipTest("Adjacent FFmpeg is required")
        TEST_ROOT.mkdir(exist_ok=True)
        cls.workspace = TEST_ROOT / ("video-" + uuid.uuid4().hex)
        cls.workspace.mkdir()
        cls.directory_patch = None
        try:
            os.link(ROOT / "ffmpeg.exe", cls.workspace / "ffmpeg.exe")
            cls.fixtures = cls.workspace / "fixtures"
            cls.fixtures.mkdir()
            cls.source = cls.fixtures / "외부 원본 영상.mkv"
            cls.silent = cls.fixtures / "무음 영상.mkv"
            cls.ffmpeg = str(cls.workspace / "ffmpeg.exe")
            cls.run_ffmpeg(["-f", "lavfi", "-i", "testsrc=size=65x49:rate=10",
                            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
                            "-t", "0.4", "-c:v", "ffv1", "-c:a", "pcm_s16le", str(cls.source)])
            cls.run_ffmpeg(["-i", str(cls.source), "-map", "0:v:0", "-c:v", "copy", str(cls.silent)])
            cls.original_digest = hashlib.sha256(cls.source.read_bytes()).hexdigest()
            cls.directory_patch = patch.object(backend, "app_dir", return_value=cls.workspace)
            cls.directory_patch.start()
        except BaseException:
            cls.cleanup()
            raise

    @classmethod
    def run_ffmpeg(cls, arguments, *, check=True):
        return subprocess.run([cls.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", *arguments],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", check=check,
                              creationflags=NO_WINDOW, timeout=30)

    @classmethod
    def cleanup(cls):
        if cls.directory_patch:
            cls.directory_patch.stop()
        if cls.workspace.exists():
            resolved = cls.workspace.resolve()
            allowed = TEST_ROOT.resolve()
            if resolved == allowed or not resolved.is_relative_to(allowed):
                raise RuntimeError(f"Unsafe test cleanup target: {resolved}")
            shutil.rmtree(resolved)

    @classmethod
    def tearDownClass(cls):
        cls.cleanup()

    def assert_source_preserved(self):
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.original_digest)

    def inspect(self, path):
        result = subprocess.run([self.ffmpeg, "-hide_banner", "-i", str(path)], capture_output=True,
                                text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW, timeout=20)
        return re.findall(r"^\s*Stream #.*$", result.stderr, re.MULTILINE)

    def test_default_real_encoding_pads_odd_sizes_and_preserves_source(self):
        runner = RecordingRunner()
        output = video.convert_scene_video(self.source, "007.50", "커튼콜", runner, {})
        self.assertEqual(output.name, "bgm007.50_커튼콜.mp4")
        self.assertEqual(output.parent, self.workspace / "Downloads")
        streams = self.inspect(output)
        self.assertEqual(sum("Video: h264" in row for row in streams), 1)
        self.assertEqual(sum("Audio: mp3" in row for row in streams), 1)
        self.assertTrue(any("66x50" in row and "yuv420p" in row for row in streams), streams)
        command = runner.commands[0]
        self.assertEqual(command[command.index("-preset") + 1], "veryslow")
        self.assertEqual(command[command.index("-q:a") + 1], "2")
        self.assertEqual(runner.progress_duration, None)
        self.run_ffmpeg(["-i", str(output), "-f", "null", "-"])
        self.assert_source_preserved()

    def test_silent_source_remains_video_without_fabricated_audio(self):
        output = video.convert_scene_video(self.silent, "2", "무음", RecordingRunner(), {})
        streams = self.inspect(output)
        self.assertTrue(any("Video: h264" in row for row in streams))
        self.assertFalse(any("Audio:" in row for row in streams))

    def test_duplicate_number_and_title_never_overwrite_existing_file(self):
        folder = self.workspace / "Downloads"
        folder.mkdir(exist_ok=True)
        previous = folder / "bgm3_중복.mp4"
        previous.write_bytes(b"previous file")
        output = video.convert_scene_video(self.silent, "3", "중복", RecordingRunner(), {})
        self.assertEqual(output.name, "bgm3_중복 (2).mp4")
        self.assertEqual(previous.read_bytes(), b"previous file")

    def test_separate_selected_audio_is_really_encoded(self):
        media = info([fmt("v", acodec="none")], [fmt("a", kind="audio", abr=192)])
        runner = RecordingRunner()
        with patch.object(backend, "fetch_formats", return_value=media), \
                patch.object(backend, "_download_format", side_effect=[self.silent, self.source]) as download:
            output = video.download_scene_video(media.url, "4", "분리 음향", runner, {})
        streams = self.inspect(output)
        self.assertTrue(any("Audio: mp3" in row for row in streams))
        self.assertEqual(download.call_count, 2)
        self.assertIn("1:a:0", runner.commands[0])
        self.assert_source_preserved()

    def test_cancelled_after_encoding_retains_partial_without_publishing(self):
        class CancelBeforePublish(RecordingRunner):
            def run(self, command, cwd=None):
                result = super().run(command, cwd)
                self.cancel()
                return result
        runner = CancelBeforePublish()
        with self.assertRaises(backend.Cancelled) as raised:
            video.convert_scene_video(self.source, "5", "취소", runner, {})
        self.assertIn("미완성 파일 보관 위치", str(raised.exception))
        self.assertFalse((self.workspace / "Downloads" / "bgm5_취소.mp4").exists())
        self.assertTrue(list((self.workspace / "Downloads").glob(".gui-yt-dlp-*/converted.mp4")))
        self.assertIsNone(runner.progress_duration)
        self.assert_source_preserved()

    def test_post_publish_cleanup_failure_reports_success_and_keeps_result(self):
        runner = RecordingRunner()
        with patch.object(backend, "_cleanup_work_dir", side_effect=OSError("locked temporary folder")):
            output = video.convert_scene_video(self.silent, "6", "정리", runner, {})
        self.assertTrue(output.is_file())
        self.assertTrue(any("임시 파일 정리" in str(payload) for kind, payload in runner.events if kind == "log"))

    def test_missing_empty_and_nonmedia_inputs_do_not_alter_original(self):
        empty = self.fixtures / "empty.mp4"
        empty.touch()
        broken = self.fixtures / "broken.mp4"
        broken.write_bytes(b"not a video")
        for path in (self.fixtures / "missing.mp4", empty, broken):
            with self.subTest(path=path), self.assertRaises(backend.AppError):
                video.convert_scene_video(path, "7", "오류", RecordingRunner(), {})
        self.assertEqual(broken.read_bytes(), b"not a video")
        self.assert_source_preserved()


if __name__ == "__main__":
    unittest.main()
