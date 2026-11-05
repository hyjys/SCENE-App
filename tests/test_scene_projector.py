"""Projector frame timing, seek generations, fade readiness, and real decoding."""
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from backend import AppError
from scene_blackscreen import Monitor
from scene_projector import ProjectorController, _DecodeJob, _Session, _decode, _prepare, _cleanup, _duration
from tests.test_scene_audio import FakePlayer, Scheduler


class ProjectorTimingTests(unittest.TestCase):
    def setUp(self):
        self.scheduler = Scheduler()
        self.status = Mock()
        self.controller = ProjectorController(self.scheduler, self.status, clock=lambda: self.scheduler.time, player_factory=FakePlayer)
        self.folder = Path(tempfile.mkdtemp(prefix="scene-projector-test-"))
        self.session = _Session(Path("video.mp4"), (2, 2), self.folder)
        self.session.duration = .12
        self.session.ready.set()
        self.controller._session = self.session
        self.controller._job = _DecodeJob(0)
        self.controller.window = Mock()
        self.controller.path = self.session.path
        self.controller._screen_size = (2, 2)
        self.controller._next_monitor_check = 9999
        self.controller._draw = Mock()

    def tearDown(self):
        self.controller.stop()
        for _ in range(20):
            if not self.folder.exists():
                break
            time.sleep(.01)

    def test_frames_are_clocked_and_last_frame_is_held_until_end_timestamp(self):
        frames = self.controller._job.frames
        frames.put((0, bytes([1] * 12)))
        frames.put((.04, bytes([2] * 12)))
        frames.put(("end", .08))
        self.controller._tick()
        self.assertEqual(self.controller._last_image.getpixel((0, 0)), (1, 1, 1))
        self.scheduler.advance(.03)
        self.assertEqual(self.controller._last_image.getpixel((0, 0)), (1, 1, 1))
        self.scheduler.advance(.03)
        self.assertEqual(self.controller._last_image.getpixel((0, 0)), (2, 2, 2))
        self.assertTrue(self.controller.running)
        self.scheduler.advance(.04)
        self.assertFalse(self.controller.running)

    def test_pause_before_readiness_starts_with_first_frame_frozen_then_resumes(self):
        self.controller.pause()
        self.controller._job.frames.put((0, bytes([1] * 12)))
        self.controller._job.frames.put((.04, bytes([2] * 12)))
        self.controller._tick()
        self.scheduler.advance(1)
        self.assertEqual(self.controller.position, 0)
        self.assertEqual(self.controller._last_image.getpixel((0, 0)), (1, 1, 1))
        self.controller.resume()
        self.scheduler.advance(.06)
        self.assertEqual(self.controller._last_image.getpixel((0, 0)), (2, 2, 2))

    def test_fade_waits_for_first_frame_and_manual_volume_invalidates_stale_steps(self):
        self.controller.fade(1, 0, 100)
        self.scheduler.advance(5)
        self.assertEqual(self.controller.volume, 0)
        self.controller._job.frames.put((0, bytes([1] * 12)))
        self.controller._tick()
        self.scheduler.advance(.5)
        self.assertAlmostEqual(self.controller.volume, 50, delta=3)
        stale = [callback for due, callback in self.scheduler.pending.values()]
        self.controller.set_volume(42)
        for callback in stale:
            callback()
        self.scheduler.advance(1)
        self.assertEqual(self.controller.volume, 42)

    def test_zero_fade_to_black_holds_output_and_resume_or_fade_in_restores_it(self):
        self.controller.fade(0, 100, 0)
        self.controller._job.frames.put((0, bytes([1] * 12)))
        self.controller._tick()
        self.assertTrue(self.controller.running)
        self.assertTrue(self.controller.held_black)
        self.assertEqual(self.controller.status_snapshot()["state"], "black")
        self.assertEqual(self.controller.opacity, 0)
        self.assertFalse(any("오류" in str(call) for call in self.status.call_args_list))
        self.controller.resume()
        self.assertFalse(self.controller.held_black)
        self.assertEqual(self.controller.opacity, 1)
        self.controller.fade(0, 100, 0)
        self.controller.fade(0, 10, 60)
        self.assertFalse(self.controller.held_black)
        self.assertEqual(self.controller.opacity, .6)
        self.assertEqual(self.controller.volume, 60)
        self.assertIsNone(self.controller._paused_at)

    def test_pause_during_preparation_defers_pending_fade_until_resume(self):
        self.controller.fade(1, 0, 100)
        self.controller.pause()
        self.controller._job.frames.put((0, bytes([1] * 12)))
        self.controller._tick()
        self.scheduler.advance(3)
        self.assertEqual(self.controller.volume, 0)
        self.controller.resume()
        self.scheduler.advance(.5)
        self.assertAlmostEqual(self.controller.volume, 50, delta=3)

    def test_seek_keeps_pause_intent_and_validates_actual_duration(self):
        self.controller._started = 0
        self.controller.pause()
        self.controller._start_decoder = Mock()
        self.controller.seek(.08)
        self.controller._start_decoder.assert_called_once_with(.08)
        self.assertIsNotNone(self.controller._paused_at)
        self.assertIsNone(self.controller._started)
        self.assertEqual(self.controller.position, .08)
        for value in (-1, .13, float("nan"), float("inf"), True):
            with self.subTest(value=value), self.assertRaises(AppError):
                self.controller.seek(value)

    def test_old_tick_generation_cannot_poll_or_stop_new_playback(self):
        self.controller._job.frames.put(("error", "stale decoder"))
        self.controller._tick(self.controller._generation - 1)
        self.assertTrue(self.controller.running)
        self.assertEqual(self.controller._job.frames.qsize(), 1)

    def test_silent_video_tail_continues_after_shorter_audio_finishes(self):
        self.controller._started = 0
        self.controller._audio_open = True
        self.controller.player.duration = .04
        self.controller.player.point = .04
        self.controller.player.state = "stopped"
        self.assertEqual(self.controller.position, .04)
        self.scheduler.advance(.06)
        self.assertAlmostEqual(self.controller.position, .1)
        self.controller.pause()
        self.scheduler.advance(1)
        self.assertAlmostEqual(self.controller.position, .1)
        self.controller.resume()
        self.scheduler.advance(.02)
        self.assertAlmostEqual(self.controller.position, .12)

    def test_duration_parse_and_volume_validation(self):
        self.assertAlmostEqual(_duration("Duration: 01:02:03.45, start: 0"), 3723.45)
        for value in (101, -1, float("nan"), True):
            with self.subTest(value=value), self.assertRaises(AppError):
                self.controller.set_volume(value)


@unittest.skipUnless((Path(__file__).resolve().parents[1] / "ffmpeg.exe").is_file(), "Bundled FFmpeg required")
class ProjectorDecoderTests(unittest.TestCase):
    def test_real_silent_video_and_seek_decode_preserve_source_and_frame_size(self):
        executable = Path(__file__).resolve().parents[1] / "ffmpeg.exe"
        with tempfile.TemporaryDirectory(prefix="scene-projector-source-") as directory:
            source = Path(directory) / "bgm2_무음 영상.mp4"
            subprocess.run([str(executable), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                            "color=c=blue:s=64x48:r=25:d=0.4", "-c:v", "libx264", "-preset", "ultrafast", str(source)],
                           check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            original = source.read_bytes()
            folder = Path(tempfile.mkdtemp(prefix="scene-projector-decode-"))
            session = _Session(source, (32, 24), folder)
            try:
                _prepare(session)
                self.assertEqual(session.error, "")
                self.assertIsNone(session.audio)
                self.assertAlmostEqual(session.duration, .4, delta=.04)
                job = _DecodeJob(.2)
                thread = threading.Thread(target=_decode, args=(session, job))
                session.jobs.append(job)
                session.threads.append(thread)
                thread.start()
                frames = []
                while True:
                    timestamp, data = job.frames.get(timeout=5)
                    if timestamp == "error":
                        self.fail(data)
                    if timestamp == "end":
                        self.assertAlmostEqual(data, .4, delta=.04)
                        break
                    frames.append((timestamp, data))
                thread.join(timeout=2)
                self.assertFalse(thread.is_alive())
                self.assertEqual(len(frames), 5)
                self.assertEqual(frames[0][0], .2)
                self.assertEqual(len(frames[0][1]), 32 * 24 * 3)
                self.assertEqual(source.read_bytes(), original)
                # Cancel while the bounded queue is full: cleanup must release
                # both FFmpeg pipe reads and a producer waiting for the GUI.
                blocked = _DecodeJob(0)
                blocked_thread = threading.Thread(target=_decode, args=(session, blocked))
                session.jobs.append(blocked)
                session.threads.append(blocked_thread)
                blocked_thread.start()
                deadline = time.monotonic() + 3
                while blocked.frames.qsize() < 4 and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertEqual(blocked.frames.qsize(), 4)
                blocked.cancel.set()
                blocked_thread.join(timeout=2)
                self.assertFalse(blocked_thread.is_alive())
            finally:
                session.cancel.set()
                _cleanup(session)
            self.assertFalse(folder.exists())


if __name__ == "__main__":
    unittest.main()
