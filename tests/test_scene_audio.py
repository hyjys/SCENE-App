"""Stage audio cue selection and live transport safety without a sound device."""

from pathlib import Path
import hashlib
import json
import queue
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
import wave

import customtkinter as ctk

from backend import AppError
from scene_audio import AudioPreparation, AudioTransport, StageAudioFrame, TrackSettings, cue_number, cue_sort_key, format_time, list_media
from ui_theme import prepare_ui


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

    def test_recursive_scan_keeps_root_cues_first_and_orders_each_folder_by_name(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            names = ["커튼콜/bgm1_last.mp3", "오프닝/효과음/bgm0_nested.wav", "오프닝/bgm10_end.mp3",
                     "오프닝/bgm2_start.mp3", "Zulu/bgm0_z.mp4", "alpha/bgm0_a.MP3",
                     "bgm10_main.mp3", "bgm2_main.wav", "bgm0_empty/script.txt"]
            for name in names:
                path = folder / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            self.assertEqual([p.relative_to(folder).as_posix() for p in list_media(folder)], [
                "bgm2_main.wav", "bgm10_main.mp3", "alpha/bgm0_a.MP3", "Zulu/bgm0_z.mp4",
                "오프닝/bgm2_start.mp3", "오프닝/bgm10_end.mp3", "오프닝/효과음/bgm0_nested.wav",
                "커튼콜/bgm1_last.mp3"])

    def test_recursive_scan_does_not_follow_linked_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "linked").mkdir()
            (folder / "linked" / "bgm1_duplicated.mp3").touch()
            (folder / "bgm2_main.wav").touch()
            with patch.object(Path, "is_symlink", lambda path: path.name == "linked"):
                self.assertEqual([p.name for p in list_media(folder)], ["bgm2_main.wav"])

    def test_missing_folder_reports_the_folder_instead_of_an_empty_list(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(AppError, "음원 폴더를 읽을 수 없습니다"):
                list_media(Path(directory) / "missing")

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


class FolderFrameTests(unittest.TestCase):
    """Exercise real Tk group controls without opening audio devices or workers."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name).resolve()
        self.addCleanup(self.temporary.cleanup)
        prepare_ui()
        self.root = ctk.CTk()
        self.root.withdraw()
        self.errors = []
        self.root.report_callback_exception = lambda *error: self.errors.append(error)
        preparation = Mock(events=queue.Queue())
        preparation.cached.side_effect = lambda path: path
        self.preparation_patch = patch("scene_audio.AudioPreparation", return_value=preparation)
        self.preparation_patch.start()
        self.addCleanup(self.preparation_patch.stop)
        self.frame = StageAudioFrame(self.root, {})
        self.frame.pack(fill="both", expand=True)
        self.frame.transport = AudioTransport(self.frame, FakePlayer(), on_change=self.frame._refresh_transport)
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        self.frame.destroy()
        for timer in self.root.tk.call("after", "info"):
            self.root.tk.call("after", "cancel", timer)
        self.root.destroy()
        self.assertEqual(self.errors, [])

    def make_file(self, name):
        path = self.folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        return path

    def test_root_rows_precede_sorted_collapsible_folders_with_nested_only_groups(self):
        root_cue = self.make_file("bgm10_main.wav")
        nested = self.make_file("오프닝/효과음/bgm1_nested.wav")
        curtain = self.make_file("커튼콜/bgm0_end.wav")
        english = self.make_file("alpha/bgm0_first.wav")
        (self.folder / "empty").mkdir()
        self.frame.load_folder(self.folder)
        self.assertEqual(self.frame.tracks, [root_cue, english, nested, curtain])
        groups = self.frame._folder_groups
        self.assertEqual([path.relative_to(self.folder).as_posix() for path in groups],
                         ["alpha", "오프닝", "오프닝/효과음", "커튼콜"])
        root_row = int(self.frame._rows[root_cue].grid_info()["row"])
        headers = [groups[self.folder / name][0] for name in ("alpha", "오프닝", "커튼콜")]
        self.assertTrue(all(int(header.grid_info()["row"]) > root_row for header in headers))
        self.assertEqual([int(header.grid_info()["row"]) for header in headers], [1, 3, 5])
        header, body = groups[self.folder / "오프닝"]
        self.assertFalse(body.grid_info())
        self.assertTrue(header.cget("text").startswith("▶"))
        header.invoke()
        self.assertTrue(body.grid_info())
        self.assertTrue(header.cget("text").startswith("▼"))
        header.invoke()
        self.assertFalse(body.grid_info())

    def test_playing_a_hidden_nested_cue_reveals_it_and_collapse_does_not_stop_it(self):
        nested = self.make_file("오프닝/효과음/bgm1_start.wav")
        self.frame.load_folder(self.folder)
        self.frame.execute_cue("play", "오프닝/효과음/bgm1_start.wav")
        self.assertEqual(self.frame.transport.player.path, nested)
        self.assertEqual(self.frame.selected, nested)
        for directory in (nested.parent.parent, nested.parent):
            self.assertTrue(self.frame._folder_groups[directory][1].grid_info())
        self.frame._folder_groups[nested.parent.parent][0].invoke()
        self.assertFalse(self.frame._folder_groups[nested.parent.parent][1].grid_info())
        self.assertEqual(self.frame.transport.state, "playing")
        self.frame._reload()
        self.assertEqual(self.frame.transport.state, "playing")
        self.assertNotIn(nested.parent.parent, self.frame._expanded_folders)
        self.assertIn(nested.parent, self.frame._expanded_folders)

    def test_relative_targets_disambiguate_duplicate_names_and_bgm_numbers(self):
        main = self.make_file("bgm1_same.wav")
        opening = self.make_file("오프닝/bgm1_same.wav")
        self.frame.load_folder(self.folder)
        for target in ("1", "bgm1_same", "bgm1_same.wav"):
            with self.subTest(target=target), self.assertRaisesRegex(AppError, "여러 개"):
                self.frame._resolve_target(target)
        self.assertEqual(self.frame._resolve_target("오프닝\\bgm1_same.wav"), opening)
        self.assertEqual(self.frame._resolve_target("오프닝/bgm1_same"), opening)
        self.assertEqual(self.frame._resolve_target("./bgm1_same.wav"), main)

    def test_same_named_tracks_retain_and_save_their_own_directory_settings(self):
        main = self.make_file("bgm1_same.wav")
        opening = self.make_file("오프닝/bgm1_same.wav")
        curtain = self.make_file("커튼콜/bgm1_same.wav")
        for path, volume in ((main, 20), (opening, 40), (curtain, 60)):
            (path.parent / ".scene-audio.json").write_text(
                json.dumps({path.name: {"default_volume": volume}}), encoding="utf-8")
        self.frame.load_folder(self.folder)
        self.assertEqual([self.frame.track_settings(path).default_volume for path in (main, opening, curtain)],
                         [20, 40, 60])
        self.frame._save_track_settings(opening, {"default_volume": 45})
        self.assertEqual(self.frame.track_settings(opening).default_volume, 45)
        saved = json.loads((opening.parent / ".scene-audio.json").read_text(encoding="utf-8"))
        self.assertEqual(set(saved), {opening.name})
        self.assertEqual(saved[opening.name]["default_volume"], 45)
        self.frame.load_folder(self.folder)
        self.assertEqual([self.frame.track_settings(path).default_volume for path in (main, opening, curtain)],
                         [20, 45, 60])
        self.frame._save_track_settings(opening, None)
        self.frame.load_folder(self.folder)
        self.assertEqual([self.frame.track_settings(path).default_volume for path in (main, opening, curtain)],
                         [20, 100, 60])

    def test_invalid_subfolder_settings_leave_the_loaded_show_unchanged(self):
        main = self.make_file("bgm1_main.wav")
        self.frame.load_folder(self.folder)
        opening = self.make_file("오프닝/bgm2_start.wav")
        (opening.parent / ".scene-audio.json").write_text('{"bgm2_start.wav": {"default_volume": 101}}', encoding="utf-8")
        with self.assertRaisesRegex(AppError, "음원별 설정 파일"):
            self.frame.load_folder(self.folder)
        self.assertEqual(self.frame.tracks, [main])

    def test_settings_for_audio_still_playing_after_folder_switch_preserve_both_shows(self):
        playing = self.make_file("A/bgm1_same.wav")
        other_a = self.make_file("A/bgm2_other.wav")
        same_b = self.make_file("B/bgm1_same.wav")
        other_b = self.make_file("B/bgm3_other.wav")
        source_settings = {playing.name: {"default_volume": 23}, other_a.name: {"default_volume": 37}}
        current_settings = {same_b.name: {"default_volume": 61}, other_b.name: {"default_volume": 79}}
        source_file = playing.parent / ".scene-audio.json"
        current_file = same_b.parent / ".scene-audio.json"
        source_file.write_text(json.dumps(source_settings), encoding="utf-8")
        current_file.write_text(json.dumps(current_settings), encoding="utf-8")
        self.frame.load_folder(playing.parent)
        self.frame.execute_cue("play", playing.name)
        self.frame.load_folder(same_b.parent)
        self.assertIsNone(self.frame.selected)
        self.assertEqual(self.frame.transport.path, playing)
        self.assertEqual(self.frame.track_settings(playing).default_volume, 23)
        self.assertEqual(self.frame.track_settings(same_b).default_volume, 61)
        with patch.object(self.frame, "_settings_dialog") as dialog:
            self.frame._settings_selected()
        dialog.assert_called_once_with(playing)
        current_bytes = current_file.read_bytes()
        current_overrides = dict(self.frame.overrides)

        self.frame._save_track_settings(playing, {"default_volume": 45})
        saved_source = json.loads(source_file.read_text(encoding="utf-8"))
        self.assertEqual(set(saved_source), {playing.name, other_a.name})
        self.assertEqual(saved_source[other_a.name], source_settings[other_a.name])
        self.assertEqual(saved_source[playing.name]["default_volume"], 45)
        self.assertEqual(self.frame.track_settings(playing).default_volume, 45)
        self.assertEqual(current_file.read_bytes(), current_bytes)
        self.assertEqual(self.frame.overrides, current_overrides)

        self.frame._save_track_settings(playing, None)
        self.assertEqual(json.loads(source_file.read_text(encoding="utf-8")), {other_a.name: source_settings[other_a.name]})
        self.assertEqual(self.frame.track_settings(playing).default_volume, self.frame.defaults.default_volume)
        self.assertEqual(current_file.read_bytes(), current_bytes)
        self.assertEqual(self.frame.overrides, current_overrides)
        self.assertEqual(self.frame.track_settings(same_b).default_volume, 61)
        self.assertEqual(self.frame.transport.state, "playing")

    def test_saving_track_settings_merges_with_new_entries_on_disk(self):
        main = self.make_file("bgm1_main.wav")
        other = self.make_file("bgm2_other.wav")
        self.frame.load_folder(self.folder)
        destination = self.folder / ".scene-audio.json"
        destination.write_text(json.dumps({other.name: {"default_volume": 39}}), encoding="utf-8")
        self.frame._save_track_settings(main, {"default_volume": 17})
        saved = json.loads(destination.read_text(encoding="utf-8"))
        self.assertEqual(saved[other.name], {"default_volume": 39})
        self.assertEqual(saved[main.name]["default_volume"], 17)


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
