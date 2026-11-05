"""Behavior checks for the production callbacks without covering the desktop."""

import ctypes as C
from ctypes import wintypes as W
import unittest
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch


import scene_blackscreen as scene

PASS_RESULT = 0x123456789
SECONDARY = scene.Monitor(r"\\.\DISPLAY2", -1920, -200, 0, 880, False)
PRIMARY = scene.Monitor(r"\\.\DISPLAY1", 0, 0, 2560, 1440, True)


class CallbackTests(unittest.TestCase):
    def setUp(self):
        # Constructor reads stock resources only; it does not create a window.
        self.app = scene.BlackScreenApp()
        self.app.hwnd = 0xABC
        self.app.hook = 0xDEF
        self.app.target = SECONDARY
        self.position = (-500, 200)

        def get_cursor(pointer):
            point = C.cast(pointer, C.POINTER(W.POINT)).contents
            point.x, point.y = self.position
            return True

        self.native = SimpleNamespace(
            IsWindowVisible=Mock(return_value=True),
            GetCursorPos=Mock(side_effect=get_cursor),
            CallNextHookEx=Mock(return_value=PASS_RESULT),
            PostMessageW=Mock(return_value=True),
            PostQuitMessage=Mock(),
            DestroyWindow=Mock(return_value=True),
            DefWindowProcW=Mock(return_value=PASS_RESULT),
            ShowWindow=Mock(return_value=True),
            SetWindowPos=Mock(return_value=True),
        )
        self.native_patch = patch.object(scene, "user32", self.native)
        self.native_patch.start()
        self.addCleanup(self.native_patch.stop)

    def key(self, message, vk=0x73, flags=0, code=0):
        event = scene.KBDLLHOOKSTRUCT(vk, 0, flags, 0, 0x123456789ABCDEF)
        # Invoke the actual ctypes callback to exercise pointer-sized marshalling.
        return self.app.keyboard_callback(code, message, C.addressof(event))

    def test_secondary_alt_f4_is_paired_and_exits_on_release(self):
        self.assertEqual(self.key(scene.WM_SYSKEYDOWN, flags=0x20), 1)
        self.assertTrue(self.app.f4_armed)
        self.native.PostMessageW.assert_not_called()
        self.assertFalse(self.app.exit_requested)
        # Key auto-repeat must neither reach the sound player nor exit early.
        self.assertEqual(self.key(scene.WM_SYSKEYDOWN, flags=0x20), 1)
        self.native.PostMessageW.assert_not_called()
        # Finish the intercepted pair even if Alt is released/mouse leaves first.
        self.position = (300, 300)
        self.assertEqual(self.key(scene.WM_KEYUP, flags=0x80), 1)
        self.assertTrue(self.app.exit_requested)
        self.assertFalse(self.app.f4_armed)
        self.native.PostMessageW.assert_called_once_with(
            self.app.hwnd, scene.WM_APP_EXIT, 0, 0)
        self.native.CallNextHookEx.assert_not_called()

    def test_primary_alt_f4_reaches_foreground_app(self):
        self.position = (500, 400)
        self.assertEqual(self.key(scene.WM_SYSKEYDOWN, flags=0x20), PASS_RESULT)
        self.assertEqual(self.key(scene.WM_SYSKEYUP, flags=0xA0), PASS_RESULT)
        self.assertFalse(self.app.f4_armed)
        self.assertFalse(self.app.exit_requested)
        self.assertEqual(self.native.CallNextHookEx.call_count, 2)
        self.native.PostMessageW.assert_not_called()

    def test_other_keys_and_plain_f4_are_passed_through(self):
        for vk, flags in ((0x1B, 0), (0x57, 0), (0x73, 0), (0x70, 0x20)):
            with self.subTest(vk=vk, flags=flags):
                self.assertEqual(self.key(scene.WM_KEYDOWN, vk, flags), PASS_RESULT)
                self.assertEqual(self.key(scene.WM_KEYUP, vk, flags | 0x80), PASS_RESULT)
        self.assertFalse(self.app.exit_requested)
        self.assertFalse(self.app.f4_armed)
        self.native.PostMessageW.assert_not_called()

    def test_negative_hook_code_does_not_dereference_input(self):
        self.assertEqual(
            self.app.keyboard_callback(-1, scene.WM_SYSKEYDOWN, 0), PASS_RESULT)
        self.native.GetCursorPos.assert_not_called()
        self.native.PostMessageW.assert_not_called()

    def test_hidden_overlay_does_not_capture_alt_f4(self):
        self.native.IsWindowVisible.return_value = False
        self.assertEqual(self.key(scene.WM_SYSKEYDOWN, flags=0x20), PASS_RESULT)
        self.assertFalse(self.app.f4_armed)

    def test_failed_cursor_query_does_not_capture_alt_f4(self):
        self.native.GetCursorPos.side_effect = None
        self.native.GetCursorPos.return_value = False
        self.assertEqual(self.key(scene.WM_SYSKEYDOWN, flags=0x20), PASS_RESULT)
        self.assertFalse(self.app.f4_armed)

    def test_shared_monitor_edge_is_outside_secondary(self):
        self.position = (0, 100)
        self.assertEqual(self.key(scene.WM_SYSKEYDOWN, flags=0x20), PASS_RESULT)
        self.assertFalse(self.app.f4_armed)

    def test_close_and_window_management_cannot_destroy_overlay(self):
        self.assertEqual(self.app.window_callback(self.app.hwnd, scene.WM_CLOSE, 0, 0), 0)
        for command in (0xF000, 0xF010, 0xF020, 0xF030, 0xF060, 0xF063):
            with self.subTest(command=command):
                self.assertEqual(self.app.window_callback(
                    self.app.hwnd, scene.WM_SYSCOMMAND, command, 0), 0)
        self.native.DestroyWindow.assert_not_called()
        self.native.DefWindowProcW.assert_not_called()

    def test_private_exit_message_requires_keyboard_authorization(self):
        self.assertEqual(self.app.window_callback(
            self.app.hwnd, scene.WM_APP_EXIT, 0, 0), 0)
        self.native.DestroyWindow.assert_not_called()
        self.key(scene.WM_SYSKEYDOWN, flags=0x20)
        self.key(scene.WM_SYSKEYUP, flags=0xA0)
        self.assertEqual(self.app.window_callback(
            self.app.hwnd, scene.WM_APP_EXIT, 0, 0), 0)
        self.native.PostQuitMessage.assert_called_once_with(0)
        self.native.DestroyWindow.assert_not_called()

    def test_unknown_window_message_preserves_pointer_sized_arguments(self):
        wparam, lparam = 0x123456789ABC, -0x123456789
        self.assertEqual(self.app.window_callback(
            self.app.hwnd, 0x5678, wparam, lparam), PASS_RESULT)
        self.native.DefWindowProcW.assert_called_once_with(
            self.app.hwnd, 0x5678, wparam, lparam)

    def test_removed_secondary_hides_cover_instead_of_using_primary(self):
        with patch.object(scene, "list_monitors", return_value=[PRIMARY]):
            self.app.refresh_display()
        self.assertIsNone(self.app.target)
        self.native.ShowWindow.assert_called_once_with(self.app.hwnd, 0)
        self.native.SetWindowPos.assert_not_called()

    def test_refresh_uses_entire_negative_coordinate_monitor(self):
        with patch.object(scene, "list_monitors", return_value=[PRIMARY, SECONDARY]):
            self.app.refresh_display()
        call = self.native.SetWindowPos.call_args.args
        self.assertEqual(call[0], self.app.hwnd)
        self.assertEqual(call[1].value, C.c_void_p(-1).value)
        self.assertEqual(call[2:6], (-1920, -200, 1920, 1080))
        self.assertEqual(call[6], 0x0010 | 0x0040)

    def test_display_change_hides_before_queued_refresh(self):
        self.assertEqual(self.app.window_callback(
            self.app.hwnd, scene.WM_DISPLAYCHANGE, 0, 0), 0)
        self.assertIsNone(self.app.target)
        self.native.ShowWindow.assert_called_once_with(self.app.hwnd, 0)
        self.native.PostMessageW.assert_called_once_with(
            self.app.hwnd, scene.WM_APP_REFRESH, 0, 0)
        self.native.SetWindowPos.assert_not_called()


class MonitorSelectionTests(unittest.TestCase):
    def test_only_primary_or_empty_list_never_covers_main_screen(self):
        self.assertIsNone(scene.choose_secondary([]))
        self.assertIsNone(scene.choose_secondary([PRIMARY]))

    def test_display_two_is_preferred_among_secondary_monitors(self):
        other = scene.Monitor(r"\\.\DISPLAY3", 2560, 0, 4480, 1080, False)
        self.assertEqual(scene.choose_secondary([other, PRIMARY, SECONDARY]), SECONDARY)

    def test_display_two_marked_primary_is_never_chosen(self):
        primary_two = scene.Monitor(r"\\.\DISPLAY2", 0, 0, 1920, 1080, True)
        secondary_one = scene.Monitor(r"\\.\DISPLAY1", -1920, 0, 0, 1080, False)
        self.assertEqual(scene.choose_secondary([primary_two, secondary_one]), secondary_one)
        self.assertIsNone(scene.choose_secondary([primary_two]))

    def test_nonpositive_monitor_rectangles_are_ignored(self):
        invalid = [scene.Monitor(r"\\.\DISPLAY2", 0, 0, 0, 1080, False),
                   scene.Monitor(r"\\.\DISPLAY3", 10, 0, 0, 1080, False),
                   scene.Monitor(r"\\.\DISPLAY4", 0, 100, 1920, 100, False)]
        self.assertIsNone(scene.choose_secondary([PRIMARY] + invalid))

    def test_negative_monitor_bounds_are_half_open(self):
        self.assertTrue(SECONDARY.contains(-1920, -200))
        self.assertTrue(SECONDARY.contains(-1, 879))
        self.assertFalse(SECONDARY.contains(0, 0))
        self.assertFalse(SECONDARY.contains(-1, 880))
        self.assertFalse(SECONDARY.contains(-1921, 0))


class NativeAbiTests(unittest.TestCase):
    def test_windows_x64_struct_sizes(self):
        self.assertEqual(C.sizeof(C.c_void_p), 8)
        self.assertEqual(C.sizeof(scene.MONITORINFOEXW), 104)
        self.assertEqual(C.sizeof(scene.WNDCLASSEXW), 80)
        self.assertEqual(C.sizeof(scene.PAINTSTRUCT), 72)
        self.assertEqual(C.sizeof(scene.KBDLLHOOKSTRUCT), 24)
        self.assertEqual(C.sizeof(scene.LRESULT), 8)
        self.assertEqual(C.sizeof(scene.WPARAM), 8)
        self.assertEqual(C.sizeof(scene.LPARAM), 8)

    def test_handle_and_callback_return_prototypes_are_pointer_sized(self):
        for dll, name in ((scene.kernel32, "GetModuleHandleW"),
                          (scene.kernel32, "CreateMutexW"),
                          (scene.user32, "CreateWindowExW"),
                          (scene.user32, "SetWindowsHookExW"),
                          (scene.user32, "DefWindowProcW"),
                          (scene.user32, "CallNextHookEx")):
            with self.subTest(function=name):
                self.assertEqual(C.sizeof(getattr(dll, name).restype), 8)


class NativeLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.app = scene.BlackScreenApp(lambda *event: self.events.append(event))
        self.native = SimpleNamespace(**{
            name: Mock(return_value=value) for name, value in {
                "RegisterClassExW": 1, "CreateWindowExW": 0xABC,
                "SetWindowsHookExW": 0xDEF, "SetTimer": 1,
                "SetWindowPos": 1, "GetMessageW": 0,
                "UnhookWindowsHookEx": 1, "DestroyWindow": 1,
                "UnregisterClassW": 1, "ShowWindow": 1,
                "PostMessageW": 1, "PostQuitMessage": None,
            }.items()
        })
        self.system = SimpleNamespace(SetThreadExecutionState=Mock(return_value=scene.ES_CONTINUOUS))
        for target, replacement in (("user32", self.native), ("kernel32", self.system)):
            change = patch.object(scene, target, replacement)
            change.start()
            self.addCleanup(change.stop)
        change = patch.object(scene, "list_monitors", return_value=[PRIMARY, SECONDARY])
        self.monitors = change.start()
        self.addCleanup(change.stop)

    def test_normal_exit_releases_hook_window_class_and_sleep_request(self):
        self.assertEqual(self.app.run(), 0)
        creation = self.native.CreateWindowExW.call_args.args
        self.assertEqual(creation[0], 0x00000008 | 0x00000080 | 0x08000000)
        self.assertEqual(creation[4:8], (-1920, -200, 1920, 1080))
        self.native.UnhookWindowsHookEx.assert_called_once_with(0xDEF)
        self.native.DestroyWindow.assert_called_once_with(0xABC)
        self.native.UnregisterClassW.assert_called_once_with(self.app.class_name, self.app.instance)
        self.assertEqual(self.system.SetThreadExecutionState.call_args_list[-1].args,
                         (scene.ES_CONTINUOUS,))
        self.assertEqual(self.events, [("on", SECONDARY.device), ("stopping", "")])
        self.assertIsNone(self.app.hwnd)
        self.assertIsNone(self.app.hook)

    def test_hook_startup_failure_still_destroys_window_and_unregisters(self):
        self.native.SetWindowsHookExW.return_value = 0
        with self.assertRaises(OSError):
            self.app.run()
        self.native.DestroyWindow.assert_called_once_with(0xABC)
        self.native.UnregisterClassW.assert_called_once()
        self.native.UnhookWindowsHookEx.assert_not_called()
        self.assertIsNone(self.app.hwnd)

    def test_timer_startup_failure_also_releases_hook(self):
        self.native.SetTimer.return_value = 0
        with self.assertRaises(OSError):
            self.app.run()
        self.native.UnhookWindowsHookEx.assert_called_once_with(0xDEF)
        self.native.DestroyWindow.assert_called_once_with(0xABC)
        self.native.UnregisterClassW.assert_called_once()

    def test_message_loop_failure_still_releases_all_native_resources(self):
        self.native.GetMessageW.return_value = -1
        with self.assertRaises(OSError):
            self.app.run()
        self.native.UnhookWindowsHookEx.assert_called_once_with(0xDEF)
        self.native.DestroyWindow.assert_called_once_with(0xABC)
        self.native.UnregisterClassW.assert_called_once()
        self.assertEqual(self.system.SetThreadExecutionState.call_args_list[-1].args,
                         (scene.ES_CONTINUOUS,))

    def test_no_secondary_does_not_register_or_create_window(self):
        self.monitors.return_value = [PRIMARY]
        with self.assertRaisesRegex(RuntimeError, "no_secondary_monitor"):
            self.app.run()
        self.native.RegisterClassExW.assert_not_called()
        self.native.CreateWindowExW.assert_not_called()

    def test_stop_before_start_never_creates_cover(self):
        self.app.request_stop()
        self.assertEqual(self.app.run(), 0)
        self.native.CreateWindowExW.assert_not_called()
        self.native.PostQuitMessage.assert_not_called()

    def test_disconnect_and_reconnect_publish_state_changes_once(self):
        self.app.hwnd = 0xABC
        self.app.refresh_display()
        self.app.refresh_display()
        self.monitors.return_value = [PRIMARY]
        self.app.refresh_display()
        self.app.refresh_display()
        self.monitors.return_value = [PRIMARY, SECONDARY]
        self.app.refresh_display()
        self.assertEqual(self.events, [("on", SECONDARY.device), ("waiting", ""),
                                       ("on", SECONDARY.device)])

    def test_gui_stop_posts_exit_without_destroying_on_calling_thread(self):
        self.app.hwnd = 0xABC
        self.app.request_stop()
        self.assertTrue(self.app.exit_requested)
        self.native.PostMessageW.assert_called_once_with(0xABC, scene.WM_APP_EXIT, 0, 0)
        self.native.DestroyWindow.assert_not_called()
        self.native.PostQuitMessage.assert_not_called()


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.thread_ids = []
        self.entered = threading.Event()
        self.created = []
        test = self

        class FakeApp:
            def __init__(self, callback, stop_event):
                self.callback, self.stop_event = callback, stop_event
                test.created.append(self)

            def run(self):
                self.callback("on", SECONDARY.device)
                test.entered.set()
                self.stop_event.wait(3)
                self.callback("stopping", "")

            def request_stop(self):
                self.stop_event.set()

        change = patch.object(scene, "BlackScreenApp", FakeApp)
        change.start()
        self.addCleanup(change.stop)
        self.system = SimpleNamespace(CreateMutexW=Mock(return_value=0x88), CloseHandle=Mock())
        change = patch.object(scene, "kernel32", self.system)
        change.start()
        self.addCleanup(change.stop)

        def callback(state, detail):
            self.events.append((state, detail))
            self.thread_ids.append(threading.get_ident())

        self.controller = scene.BlackScreenController(callback)
        self.addCleanup(self.controller.close)

    def test_on_off_are_nonblocking_and_callbacks_stay_on_worker(self):
        self.controller.start()
        self.assertTrue(self.entered.wait(1))
        self.assertTrue(self.controller.running)
        self.controller.stop()
        self.assertTrue(self.controller.close())
        self.assertFalse(self.controller.running)
        self.assertEqual(self.events, [("starting", ""), ("on", SECONDARY.device),
                                       ("stopping", ""), ("off", "")])
        self.assertEqual(len(set(self.thread_ids)), 1)
        self.assertNotEqual(self.thread_ids[0], threading.get_ident())
        self.system.CloseHandle.assert_called_once_with(0x88)

    def test_duplicate_start_and_repeated_stop_do_not_duplicate_cover(self):
        self.controller.start()
        self.assertTrue(self.entered.wait(1))
        self.controller.start()
        self.assertEqual(len(self.created), 1)
        self.controller.stop()
        self.controller.stop()
        self.assertTrue(self.controller.close())
        self.controller.start()
        self.assertTrue(self.controller.close())
        self.assertLessEqual(len(self.created), 2)
        self.assertEqual(self.events.count(("off", "")), 2)

    def test_startup_failure_releases_mutex_and_preserves_error_state(self):
        with patch.object(scene, "BlackScreenApp", side_effect=RuntimeError("no_secondary_monitor")):
            self.controller.start()
            with self.controller._lock:
                thread = self.controller._thread
            thread.join(1)
        self.assertFalse(self.controller.running)
        self.assertEqual(self.events[-1], ("error", "no_secondary_monitor"))
        self.assertNotIn(("off", ""), self.events)
        self.system.CloseHandle.assert_called_once_with(0x88)

    def test_existing_cover_reports_error_without_starting_another(self):
        def existing(*_args):
            C.set_last_error(183)
            return 0x88

        self.system.CreateMutexW.side_effect = existing
        self.controller.start()
        with self.controller._lock:
            thread = self.controller._thread
        thread.join(1)
        self.assertFalse(self.controller.running)
        self.assertEqual(self.events[-1], ("error", "already_running"))
        self.assertEqual(self.created, [])
        self.system.CloseHandle.assert_called_once_with(0x88)

    def test_failed_mutex_does_not_create_native_window(self):
        self.system.CreateMutexW.return_value = 0
        self.controller.start()
        with self.controller._lock:
            thread = self.controller._thread
        thread.join(1)
        self.assertFalse(self.controller.running)
        self.assertEqual(self.events[-1][0], "error")
        self.assertEqual(self.created, [])
        self.system.CloseHandle.assert_not_called()

    def test_stop_during_constructor_is_remembered_before_native_run(self):
        constructing, release = threading.Event(), threading.Event()
        stop_seen = []

        class DelayedApp:
            def __init__(self, callback, stop_event):
                self.stop_event = stop_event
                constructing.set()
                release.wait(2)

            def run(self):
                stop_seen.append(self.stop_event.is_set())

            def request_stop(self):
                self.stop_event.set()

        with patch.object(scene, "BlackScreenApp", DelayedApp):
            try:
                self.controller.start()
                self.assertTrue(constructing.wait(1))
                self.controller.stop()
                self.assertFalse(self.controller.close(timeout=0.01))
            finally:
                release.set()
                self.assertTrue(self.controller.close())
        self.assertEqual(stop_seen, [True])
        self.assertEqual(self.events[-1], ("off", ""))

    def test_callback_failure_cannot_prevent_cleanup(self):
        self.controller._callback = Mock(side_effect=RuntimeError("UI closed"))
        self.controller.start()
        self.assertTrue(self.entered.wait(1))
        self.assertTrue(self.controller.close())
        self.system.CloseHandle.assert_called_once_with(0x88)


if __name__ == "__main__":
    unittest.main()
