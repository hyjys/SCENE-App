"""Stage-workspace integration without external displays, network or user settings."""

from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import customtkinter as ctk

from scene_audio import TrackSettings
from scene_settings import DEFAULTS
import scene_stage as stage
from ui_theme import prepare_ui


class StageWorkspaceTests(unittest.TestCase):
    def setUp(self):
        prepare_ui()
        self.root = ctk.CTk()
        self.root.withdraw()
        self.root.geometry("1300x850")
        self.workspace = None
        self.addCleanup(self._cleanup)
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)
        self.settings = {**DEFAULTS, "audio_folder": "", "check_updates": False}
        self.errors = []
        self.root.report_callback_exception = lambda *error: self.errors.append(error)
        self.projector = Mock(running=False, path=None)
        self.projector_patch = patch.object(stage, "ProjectorController", return_value=self.projector)
        self.projector_patch.start()
        self.blackscreen_on = Mock()
        self.blackscreen_off = Mock()
        self.workspace = stage.StageWorkspace(self.root, self.settings, on_error=self.errors.append,
            blackscreen_on=self.blackscreen_on, blackscreen_off=self.blackscreen_off)
        self.workspace.pack(fill="both", expand=True)
        self.root.update_idletasks()

    def _cleanup(self):
        if self.workspace is not None:
            self.workspace.close()
        for timer in self.root.tk.call("after", "info"):
            self.root.tk.call("after", "cancel", timer)
        self.root.destroy()
        self.projector_patch.stop()
        self.temporary.cleanup()
        self.assertEqual(self.errors, [])

    def test_each_side_can_independently_switch_local_and_web(self):
        self.assertTrue(self.workspace.audio.grid_info())
        self.assertTrue(self.workspace.script.grid_info())
        self.assertFalse(self.workspace.web_audio.grid_info())
        self.assertFalse(self.workspace.web_script.grid_info())
        self.workspace.update_settings({**self.settings, "script_source": "web",
                                        "script_url": "https://docs.google.com/document/d/sample/edit"})
        self.assertTrue(self.workspace.audio.grid_info())
        self.assertFalse(self.workspace.script.grid_info())
        self.assertTrue(self.workspace.web_script.grid_info())
        self.workspace.update_settings({**self.settings, "audio_source": "web"})
        self.assertFalse(self.workspace.audio.grid_info())
        self.assertTrue(self.workspace.web_audio.grid_info())
        self.assertTrue(self.workspace.script.grid_info())

    def test_transport_and_numeric_script_cues_reach_the_same_audio_panel(self):
        self.workspace.audio.execute_cue = Mock()
        self.workspace.execute_cue("fade_in", "2.5")
        self.workspace.audio.execute_cue.assert_called_with("fade_in", "2.5")
        self.workspace.execute_cue("volume", "2.5", 51)
        self.workspace.audio.execute_cue.assert_called_with("volume", "2.5", 51)
        self.workspace.execute_cue("seek", "2.5", 12.25)
        self.workspace.audio.execute_cue.assert_called_with("seek", "2.5", 12.25)

    def test_video_uses_same_per_track_volume_and_fade_settings(self):
        path = self.folder / "bgm3_영상.mp4"
        config = TrackSettings(default_volume=43, fade_in_seconds=4.5, fade_in_from=12, fade_in_to=75)
        self.workspace.audio.track_settings = Mock(return_value=config)
        self.workspace.play_video(path)
        self.blackscreen_off.assert_called_once()
        self.projector.play.assert_called_once_with(path)
        self.projector.set_volume.assert_called_with(43)
        self.projector.running = True
        self.projector.path = path
        self.workspace.video_action("fade_in", path)
        self.projector.fade.assert_called_once_with(4.5, 12, 75)

    def test_blackscreen_stops_video_before_enabling_cover(self):
        order = []
        self.projector.stop.side_effect = lambda: order.append("stop_video")
        self.workspace._blackout(lambda: order.append("blackout"))
        self.assertEqual(order, ["stop_video", "blackout"])

    def test_google_import_downloads_text_off_thread_and_opens_local_annotations(self):
        class Response:
            headers = {"Content-Type": "text/plain; charset=utf-8"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit):
                return "배우: 안녕!\n음악 시작".encode("utf-8")

        self.workspace._show(self.workspace.right, self.workspace.script, self.workspace.web_script, "웹 / Google")
        with patch.object(stage, "urlopen", return_value=Response()) as request, \
                patch.object(stage, "settings_path", return_value=self.folder / "settings.json"):
            self.workspace.import_google_script("https://docs.google.com/document/d/shared-id/edit")
            deadline = time.monotonic() + 3
            while self.workspace.script.document is None and time.monotonic() < deadline:
                self.root.update()
                time.sleep(.01)
        self.assertIsNotNone(self.workspace.script.document)
        self.assertEqual(self.workspace.script.document.text, "배우: 안녕!\n음악 시작")
        self.assertEqual(self.workspace.script.document.path.parent, (self.folder / "Google 대본").resolve())
        self.assertTrue(self.workspace.script.grid_info())
        self.assertFalse(self.workspace.web_script.grid_info())
        self.assertEqual(request.call_count, 1)
        self.assertIn("/document/d/shared-id/export?format=txt", request.call_args.args[0].full_url)


class WebUrlTests(unittest.TestCase):
    def test_rejects_file_script_and_credentials_before_embedded_browser(self):
        for value in ("file:///C:/secret.txt", "javascript:alert(1)", "https://u:p@example.com", "not an address"):
            with self.subTest(url=value), self.assertRaises(stage.AppError):
                stage.web_url(value)
        self.assertEqual(stage.web_url(" https://drive.google.com/drive/u/0/ "),
                         "https://drive.google.com/drive/u/0/")


class AppModeIntegrationTests(unittest.TestCase):
    def setUp(self):
        import scene_app
        self.module = scene_app
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.projector_patch = patch.object(stage, "ProjectorController", return_value=Mock(running=False, path=None))
        self.projector_patch.start()
        self.addCleanup(self.projector_patch.stop)
        # show_dialogs=False deliberately bypasses all per-user settings I/O and
        # automatic update checks; no test touches the operator's configuration.
        self.app = scene_app.SceneApp(show_dialogs=False)
        self.app.withdraw()
        self.app.state = Mock(return_value="withdrawn")
        self.errors = []
        self.app.report_callback_exception = lambda *error: self.errors.append(error)
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        if self.app._runner is not None:
            self.app._runner.cancel()
        if self.app._worker is not None:
            self.app._worker.join(timeout=3)
        for timer in self.app.tk.call("after", "info"):
            self.app.tk.call("after", "cancel", timer)
        self.app.destroy()
        self.assertEqual(self.errors, [])

    def test_switching_reuses_stage_and_retains_open_script_and_preparation_inputs(self):
        self.app.number_var.set("13.5")
        self.app.title_var.set("커튼콜")
        self.app._select_app_mode("무대 모드")
        self.assertEqual(self.app.app_mode, "무대 모드")
        self.assertIsNotNone(self.app.stage)
        self.app.state.assert_called_with("zoomed")
        self.assertFalse(self.app.preparation_frame.grid_info())
        path = self.folder / "대본.txt"
        path.write_text("배우 대사\n음악 시작", encoding="utf-8")
        self.app.stage.script.open_file(path)
        workspace = self.app.stage
        workspace.audio.stop_all = Mock(wraps=workspace.audio.stop_all)
        self.app._select_app_mode("준비 모드")
        workspace.audio.stop_all.assert_called_once()
        workspace.projector.stop.assert_called_once()
        self.assertTrue(self.app.preparation_frame.grid_info())
        self.assertEqual(self.app.number_var.get(), "13.5")
        self.assertEqual(self.app.title_var.get(), "커튼콜")
        self.app._select_app_mode("무대 모드")
        self.assertIs(self.app.stage, workspace)
        self.assertEqual(workspace.script.document.path, path.resolve())

    def test_leaving_stage_with_empty_or_only_selected_audio_does_not_raise(self):
        self.app._select_app_mode("무대 모드")
        self.assertEqual(self.app.stage.audio.tracks, [])
        self.app._select_app_mode("준비 모드")
        self.assertEqual(self.app.app_mode, "준비 모드")
        self.app._select_app_mode("무대 모드")
        path = self.folder / "bgm1_idle.mp3"
        path.touch()
        audio = self.app.stage.audio
        audio.tracks = [path]
        audio.selected = path
        self.assertIsNone(audio.transport.path)
        self.app._select_app_mode("준비 모드")
        self.assertEqual(self.app.app_mode, "준비 모드")

    def test_script_body_keeps_more_room_than_compact_cue_list(self):
        self.app._select_app_mode("무대 모드")
        self.app.geometry("1000x700")
        self.app.deiconify()
        self.app.update()
        viewer = self.app.stage.script
        self.assertGreater(viewer.body.winfo_height(), viewer.cue_list._parent_frame.winfo_height())
        self.assertLessEqual(viewer.cue_list._parent_frame.winfo_height(), 140 * viewer._get_widget_scaling())

    def test_running_preparation_or_update_blocks_mode_change(self):
        for flag in ("_busy", "_update_busy"):
            with self.subTest(flag=flag):
                setattr(self.app, flag, True)
                self.app._select_app_mode("무대 모드")
                self.assertEqual(self.app.app_mode, "준비 모드")
                self.assertIsNone(self.app.stage)
                self.assertEqual(self.app.mode_selector.get(), "준비 모드")
                setattr(self.app, flag, False)

    def test_stage_keyboard_submit_cannot_start_download_or_update(self):
        self.app._select_app_mode("무대 모드")
        with patch.object(self.app, "_start_job") as download, \
                patch.object(self.module, "check_for_update") as update:
            self.app._begin()
            self.app._check_updates()
            self.app._update_action()
        download.assert_not_called()
        update.assert_not_called()

    def test_video_toggle_changes_preview_and_action_while_audio_remains_default(self):
        self.app.number_var.set("4")
        self.app.title_var.set("막간")
        self.assertFalse(self.app.video_var.get())
        self.assertEqual(self.app.filename_var.get(), "bgm4_막간.mp3")
        self.app.video_var.set(True)
        self.app._on_video_changed()
        self.assertEqual(self.app.filename_var.get(), "bgm4_막간.mp4")
        self.assertIn("MP4", self.app.action_button.cget("text"))
        self.app.video_var.set(False)
        self.app._on_video_changed()
        self.assertEqual(self.app.filename_var.get(), "bgm4_막간.mp3")

    def test_settings_refresh_stage_defaults_without_writing_user_profile(self):
        self.app._select_app_mode("무대 모드")
        with patch.object(self.module, "save_settings") as save:
            self.app._open_settings()
            dialog = self.app._settings_dialog
            dialog.withdraw()
            dialog.vars["default_volume"].set("42")
            dialog.vars["audio_source"].set("web")
            save_button = next(widget for widget in dialog.winfo_children()
                               if isinstance(widget, ctk.CTkButton) and widget.cget("text") == "설정 저장")
            save_button.invoke()
        save.assert_not_called()
        self.assertEqual(self.app.settings["default_volume"], 42)
        self.assertEqual(self.app.stage.audio.defaults.default_volume, 42)
        self.assertTrue(self.app.stage.web_audio.grid_info())
        self.assertTrue(self.app.stage.script.grid_info())


if __name__ == "__main__":
    unittest.main()
