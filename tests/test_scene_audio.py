"""Stage audio cue selection and live transport safety without a sound device."""

from pathlib import Path
import hashlib
import subprocess
import tempfile
import unittest
from unittest.mock import Mock
import wave

from backend import AppError
from scene_audio import AudioPreparation, AudioTransport, StageAudioFrame, TrackSettings, cue_number, cue_sort_key, format_time, list_media


class Scheduler:
    def __init__(self):
        self.time = 0
        self.pending = {}
        self.counter = 0

    def after(self, ms, callback):
        self.counter += 1
        self.pending[self.counter] = (self.time + ms / 1000, callback)
        return self.counter

    def after_cancel(self, ident):
        self.pending.pop(ident, None)

    def advance(self, seconds):
        end = self.time + seconds
        while self.pending:
            ident, (due, callback) = min(self.pending.items(), key=lambda item: item[1][0])
            if due > end:
                break
            self.time = due
            del self.pending[ident]
            callback()
        self.time = end


class FakePlayer:
    duration = 120

    def __init__(self):
        self.path = None
        self.volume = 100
        self.point = 0
        self.state = "stopped"
        self.opened = []
        self.prepared_paths = {}

    def open(self, path):
        self.path = path
        self.opened.append(path)
        self.point = 0

    def play(self):
        self.state = "playing"

    def pause(self):
        self.state = "paused"

    def stop(self):
        self.state = "stopped"
        self.point = 0

    def seek(self, seconds, playing=False):
        self.point = seconds
        self.state = "playing" if playing else "stopped"

    def set_volume(self, percent):
        self.volume = percent

    def position(self):
        return self.point

    def mode(self):
        return self.state

    def close(self):
        self.path = None
        self.state = "stopped"


class CueListTests(unittest.TestCase):
    def test_cue_order_preserves_decimal_order_and_places_non_numbered_media_last(self):
        names = ["bgm10_song.mp3", "bgm2.5_scene.mp4", "bgm2_opening.wav", "bgm013.50_end.mp3",
                 "misc10.mp3", "misc2.mp3", "BGM02.05_gun.mp3", "bgm1_intro.mp3"]
        self.assertEqual(sorted(names, key=cue_sort_key), ["bgm1_intro.mp3", "bgm2_opening.wav", "BGM02.05_gun.mp3",
                                                         "bgm2.5_scene.mp4", "bgm10_song.mp3", "bgm013.50_end.mp3",
                                                         "misc2.mp3", "misc10.mp3"])
        self.assertIsNone(cue_number("bgm2abc.mp3"))

    def test_folder_includes_videos_and_supported_audio_only(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            for name in ("bgm2_video.MP4", "bgm1_audio.mp3", ".scene-audio.json", "script.docx"):
                (folder / name).touch()
            (folder / "bgm0_fake.mp3").mkdir()
            self.assertEqual([p.name for p in list_media(folder)], ["bgm1_audio.mp3", "bgm2_video.MP4"])

    def test_global_defaults_and_per_track_overrides_combine(self):
        global_defaults = TrackSettings.from_dict({"default_volume": 55, "fade_out_seconds": 8})
        cue = TrackSettings.from_dict({"fade_in_to": 65}, global_defaults)
        self.assertEqual(cue.default_volume, 55)
        self.assertEqual(cue.fade_out_seconds, 8)
        self.assertEqual(cue.fade_in_to, 65)
        self.assertEqual(cue.fade_in_seconds, 3)

    def test_non_finite_and_out_of_range_settings_rejected(self):
        for value in ("nan", "inf", -1, 101, "invalid", True):
            with self.subTest(value=value), self.assertRaises(AppError):
                TrackSettings.from_dict({"default_volume": value})
        with self.assertRaises(AppError):
            TrackSettings.from_dict({"fade_in_seconds": 601})

    def test_target_resolution_accepts_number_and_exact_name_and_rejects_duplicate_cues(self):
        frame = object.__new__(StageAudioFrame)
        frame.tracks = [Path("bgm1_first.mp3"), Path("bgm1_video.mp4"), Path("bgm2.5_second.mp3")]
        self.assertEqual(frame._resolve_target("02.50"), frame.tracks[2])
        self.assertEqual(frame._resolve_target("BGM2.5"), frame.tracks[2])
        self.assertEqual(frame._resolve_target("bgm1_first"), frame.tracks[0])
        with self.assertRaisesRegex(AppError, "여러 개"):
            frame._resolve_target("1")
        with self.assertRaisesRegex(AppError, "찾을 수 없습니다"):
            frame._resolve_target("99")

    def test_time_format_handles_long_cues(self):
        self.assertEqual(format_time(199.8), "3:19")
        self.assertEqual(format_time(3601), "60:01")


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.scheduler = Scheduler()
        self.player = FakePlayer()
        self.changed = Mock()
        self.transport = AudioTransport(self.scheduler, self.player, clock=lambda: self.scheduler.time, on_change=self.changed)
        self.path = Path("bgm1_test.mp3").resolve()

    def test_play_pause_seek_and_resume_preserve_position_and_volume(self):
        self.transport.play(self.path, 55)
        self.transport.seek(35)
        self.transport.pause()
        self.transport.play(self.path)
        self.assertEqual(self.player.point, 35)
        self.assertEqual(self.player.volume, 55)
        self.assertEqual(self.transport.state, "playing")
        self.assertEqual(self.player.opened, [self.path])
        self.transport.stop()
        self.assertEqual(self.player.point, 0)

    def test_fade_interpolates_and_finishes_at_custom_end_volume(self):
        self.transport.play(self.path, 0)
        self.transport.fade(10, 70, 3)
        self.scheduler.advance(1.5)
        self.assertAlmostEqual(self.player.volume, 40, delta=1)
        self.scheduler.advance(1.6)
        self.assertEqual(self.player.volume, 70)
        self.assertEqual(self.transport.state, "playing")
        self.assertFalse(self.scheduler.pending)

    def test_fade_out_stops_at_zero_and_clears_timers(self):
        self.transport.play(self.path)
        self.transport.fade(100, 0, 1, stop_at_zero=True)
        self.scheduler.advance(1.1)
        self.assertEqual(self.player.volume, 0)
        self.assertEqual(self.transport.state, "stopped")
        self.assertFalse(self.scheduler.pending)

    def test_zero_duration_fade_completes_synchronously(self):
        self.transport.play(self.path)
        self.transport.fade(100, 35, 0, stop_at_zero=True)
        self.assertEqual(self.player.volume, 35)
        self.assertEqual(self.transport.state, "playing")
        self.assertFalse(self.scheduler.pending)

    def test_operator_volume_cancels_pending_fade_including_stale_callbacks(self):
        self.transport.play(self.path)
        self.transport.fade(0, 100, 3)
        stale_callback = next(iter(self.scheduler.pending.values()))[1]
        self.scheduler.advance(1)
        self.transport.set_volume(42)
        stale_callback()
        self.scheduler.advance(5)
        self.assertEqual(self.player.volume, 42)
        self.assertFalse(self.scheduler.pending)

    def test_switching_track_cancels_previous_fade(self):
        self.transport.play(self.path)
        self.transport.fade(100, 0, 3, stop_at_zero=True)
        second = Path("bgm2_test.mp3").resolve()
        self.transport.play(second, 60)
        self.scheduler.advance(4)
        self.assertEqual(self.player.path, second)
        self.assertEqual(self.player.volume, 60)
        self.assertEqual(self.transport.state, "playing")

    def test_close_and_pause_cancel_fades(self):
        self.transport.play(self.path)
        self.transport.fade(0, 100, 3)
        self.transport.pause()
        self.assertFalse(self.scheduler.pending)
        self.transport.play(self.path)
        self.transport.fade(0, 100, 3)
        self.transport.close()
        self.assertIsNone(self.player.path)
        self.assertFalse(self.scheduler.pending)


class FrameCueTests(unittest.TestCase):
    def setUp(self):
        self.frame = object.__new__(StageAudioFrame)
        self.frame.defaults = TrackSettings()
        self.frame.overrides = {}
        self.frame.selected = None
        self.frame._video_active = False
        self.frame._video_path = None
        self.frame._pending = None
        self.frame._select = Mock()
        self.frame._refresh_transport = Mock()
        self.frame.folder_var = Mock()
        self.frame.folder = Path("show")
        self.first = Path("bgm1_first.mp3").resolve()
        self.second = Path("bgm2_second.mp3").resolve()
        self.video = Path("bgm3_video.mp4").resolve()
        self.frame.tracks = [self.first, self.second, self.video]
        self.frame._preparation = Mock()
        self.frame._preparation.cached.side_effect = lambda path: path
        self.frame.on_video = Mock()
        self.frame.on_video_action = Mock()
        self.player = FakePlayer()
        self.scheduler = Scheduler()
        self.frame.transport = AudioTransport(self.scheduler, self.player, clock=lambda: self.scheduler.time)

    def test_pause_on_unrelated_row_does_not_pause_live_cue(self):
        self.frame.execute_cue("play", "1")
        with self.assertRaisesRegex(AppError, "현재 재생"):
            self.frame.execute_cue("pause", "2")
        self.assertEqual(self.player.state, "playing")
        self.assertEqual(self.player.path, self.first)

    def test_volume_and_seek_cues_validate_values_and_duration(self):
        self.frame.execute_cue("play", "1")
        self.frame.execute_cue("volume", "1", 42)
        self.frame.execute_cue("seek", "1", 25)
        self.assertEqual(self.player.volume, 42)
        self.assertEqual(self.player.point, 25)
        for action, value in (("volume", 101), ("seek", 121), ("seek", True), ("seek", float("nan"))):
            with self.subTest(action=action, value=value), self.assertRaises(AppError):
                self.frame.execute_cue(action, "1", value)

    def test_pending_play_is_canceled_by_stop_on_current_transport(self):
        self.frame.execute_cue("play", "1")
        self.frame._preparation.cached.side_effect = lambda path: None
        self.frame.execute_cue("play", "2")
        self.assertEqual(self.frame._pending[1], self.second)
        self.assertEqual(self.player.path, self.first)
        self.frame.execute_cue("stop")
        self.assertIsNone(self.frame._pending)
        self.assertEqual(self.player.state, "stopped")

    def test_new_go_replaces_pending_audio_and_video_controls_forward_value(self):
        self.frame._preparation.cached.side_effect = lambda path: None
        self.frame.execute_cue("play", "1")
        self.frame.execute_cue("play", "2")
        self.assertEqual(self.frame._pending[1], self.second)
        self.frame.execute_cue("play", "3")
        self.assertIsNone(self.frame._pending)
        self.frame.on_video.assert_called_once_with(self.video)
        self.frame.execute_cue("volume", "3", 40)
        self.frame.on_video_action.assert_called_with("volume", self.video, 40)
        self.frame.execute_cue("seek", "3", 20)
        self.frame.on_video_action.assert_called_with("seek", self.video, 20)

    def test_stop_all_is_safe_idle_and_cancels_pending_and_active_video(self):
        self.frame.stop_all()
        self.frame.execute_cue("play", "3")
        self.frame._pending = ("play", self.first, None)
        self.frame.stop_all()
        self.assertIsNone(self.frame._pending)
        self.assertFalse(self.frame._video_active)
        self.frame.on_video_action.assert_called_with("stop", self.video, None)

    def test_play_on_same_active_video_resumes_without_reopening(self):
        self.frame.execute_cue("play", "3")
        self.frame.execute_cue("pause", "3")
        self.frame.execute_cue("play", "3")
        self.frame.on_video.assert_called_once_with(self.video)
        self.frame.on_video_action.assert_called_with("play", self.video, None)


@unittest.skipUnless((Path(__file__).resolve().parents[1] / "ffmpeg.exe").is_file(), "Bundled FFmpeg required")
class PreparationTests(unittest.TestCase):
    def test_vbr_mp3_decodes_to_exact_pcm_timeline_preserving_source_and_cleans_cache(self):
        executable = Path(__file__).resolve().parents[1] / "ffmpeg.exe"
        with tempfile.TemporaryDirectory(prefix="scene-audio-test-") as directory:
            folder = Path(directory)
            source_wav, source_mp3 = folder / "original.wav", folder / "bgm1_VBR.mp3"
            with wave.open(str(source_wav), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(44100)
                output.writeframes(b"\0\0" * 44100 * 2)
            subprocess.run([str(executable), "-hide_banner", "-loglevel", "error", "-i", str(source_wav),
                            "-c:a", "libmp3lame", "-q:a", "2", str(source_mp3)],
                           check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            original_hash = hashlib.sha256(source_mp3.read_bytes()).digest()
            preparation = AudioPreparation()
            cache_directory = preparation._directory
            try:
                preparation.request(source_mp3, urgent=True)
                path, decoded, error = preparation.events.get(timeout=5)
                self.assertEqual(path, source_mp3.resolve())
                self.assertEqual(error, "")
                self.assertEqual(preparation.cached(source_mp3), decoded)
                with wave.open(str(decoded), "rb") as pcm:
                    self.assertEqual(pcm.getnframes() / pcm.getframerate(), 2)
                self.assertEqual(hashlib.sha256(source_mp3.read_bytes()).digest(), original_hash)
                source_mp3.write_bytes(source_mp3.read_bytes() + b"\0")
                self.assertIsNone(preparation.cached(source_mp3), "Changing the source must invalidate cached audio")
            finally:
                preparation.close()
                preparation._worker.join(timeout=3)
            self.assertFalse(cache_directory.exists())


if __name__ == "__main__":
    unittest.main()
