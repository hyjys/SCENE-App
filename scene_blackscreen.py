"""SCENE App's silent, borderless black secondary-monitor cover.

Windows 10/11, Python standard library only. The keyboard callback recognizes
only Alt+F4 over the covered monitor; all other input is passed to Windows.
Adapted from SCENE BlackScreen's display-only behavior. No device brightness,
projector, audio or power configuration is changed.
"""

from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
from dataclasses import dataclass
import threading
from collections.abc import Callable

APP_NAME = "SCENE App BlackScreen"
CLASS_NAME = "SCENE.App.BlackScreen.Window.v1"
MUTEX_NAME = "Local\\SCENE.BlackScreen.Instance.v1"

LRESULT = C.c_ssize_t
WPARAM = C.c_size_t
LPARAM = C.c_ssize_t
HANDLE = C.c_void_p
WNDPROC = C.WINFUNCTYPE(LRESULT, W.HWND, W.UINT, WPARAM, LPARAM)
HOOKPROC = C.WINFUNCTYPE(LRESULT, C.c_int, WPARAM, LPARAM)
MONITORENUMPROC = C.WINFUNCTYPE(W.BOOL, HANDLE, W.HDC, C.POINTER(W.RECT), LPARAM)

user32 = C.WinDLL("user32", use_last_error=True)
kernel32 = C.WinDLL("kernel32", use_last_error=True)
gdi32 = C.WinDLL("gdi32", use_last_error=True)


class MONITORINFOEXW(C.Structure):
    _fields_ = [("cbSize", W.DWORD), ("rcMonitor", W.RECT),
                ("rcWork", W.RECT), ("dwFlags", W.DWORD),
                ("szDevice", W.WCHAR * 32)]


class WNDCLASSEXW(C.Structure):
    _fields_ = [("cbSize", W.UINT), ("style", W.UINT),
                ("lpfnWndProc", WNDPROC), ("cbClsExtra", C.c_int),
                ("cbWndExtra", C.c_int), ("hInstance", W.HINSTANCE),
                ("hIcon", HANDLE), ("hCursor", HANDLE),
                ("hbrBackground", W.HBRUSH), ("lpszMenuName", W.LPCWSTR),
                ("lpszClassName", W.LPCWSTR), ("hIconSm", HANDLE)]


class PAINTSTRUCT(C.Structure):
    _fields_ = [("hdc", W.HDC), ("fErase", W.BOOL),
                ("rcPaint", W.RECT), ("fRestore", W.BOOL),
                ("fIncUpdate", W.BOOL), ("rgbReserved", W.BYTE * 32)]


class KBDLLHOOKSTRUCT(C.Structure):
    _fields_ = [("vkCode", W.DWORD), ("scanCode", W.DWORD),
                ("flags", W.DWORD), ("time", W.DWORD),
                ("dwExtraInfo", C.c_size_t)]


def _api(dll, name, result, *args):
    function = getattr(dll, name)
    function.restype = result
    function.argtypes = list(args)
    return function


_api(kernel32, "GetModuleHandleW", W.HMODULE, W.LPCWSTR)
_api(kernel32, "CreateMutexW", HANDLE, HANDLE, W.BOOL, W.LPCWSTR)
_api(kernel32, "CloseHandle", W.BOOL, HANDLE)
_api(kernel32, "SetThreadExecutionState", W.DWORD, W.DWORD)
_api(user32, "EnumDisplayMonitors", W.BOOL, W.HDC, C.POINTER(W.RECT), MONITORENUMPROC, LPARAM)
_api(user32, "GetMonitorInfoW", W.BOOL, HANDLE, C.POINTER(MONITORINFOEXW))
_api(user32, "RegisterClassExW", W.WORD, C.POINTER(WNDCLASSEXW))
_api(user32, "UnregisterClassW", W.BOOL, W.LPCWSTR, W.HINSTANCE)
_api(user32, "CreateWindowExW", W.HWND, W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD,
     C.c_int, C.c_int, C.c_int, C.c_int, W.HWND, W.HMENU, W.HINSTANCE, HANDLE)
_api(user32, "DefWindowProcW", LRESULT, W.HWND, W.UINT, WPARAM, LPARAM)
_api(user32, "DestroyWindow", W.BOOL, W.HWND)
_api(user32, "ShowWindow", W.BOOL, W.HWND, C.c_int)
_api(user32, "IsWindowVisible", W.BOOL, W.HWND)
_api(user32, "SetWindowPos", W.BOOL, W.HWND, W.HWND,
     C.c_int, C.c_int, C.c_int, C.c_int, W.UINT)
_api(user32, "GetClientRect", W.BOOL, W.HWND, C.POINTER(W.RECT))
_api(user32, "FillRect", C.c_int, W.HDC, C.POINTER(W.RECT), W.HBRUSH)
_api(user32, "BeginPaint", W.HDC, W.HWND, C.POINTER(PAINTSTRUCT))
_api(user32, "EndPaint", W.BOOL, W.HWND, C.POINTER(PAINTSTRUCT))
_api(user32, "SetCursor", HANDLE, HANDLE)
_api(user32, "GetCursorPos", W.BOOL, C.POINTER(W.POINT))
_api(user32, "SetTimer", C.c_size_t, W.HWND, C.c_size_t, W.UINT, HANDLE)
_api(user32, "KillTimer", W.BOOL, W.HWND, C.c_size_t)
_api(user32, "PostMessageW", W.BOOL, W.HWND, W.UINT, WPARAM, LPARAM)
_api(user32, "PostQuitMessage", None, C.c_int)
_api(user32, "GetMessageW", W.BOOL, C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT)
_api(user32, "TranslateMessage", W.BOOL, C.POINTER(W.MSG))
_api(user32, "DispatchMessageW", LRESULT, C.POINTER(W.MSG))
_api(user32, "SetWindowsHookExW", HANDLE, C.c_int, HOOKPROC, W.HINSTANCE, W.DWORD)
_api(user32, "UnhookWindowsHookEx", W.BOOL, HANDLE)
_api(user32, "CallNextHookEx", LRESULT, HANDLE, C.c_int, WPARAM, LPARAM)
_api(gdi32, "GetStockObject", HANDLE, C.c_int)

WM_DESTROY = 0x0002
WM_PAINT = 0x000F
WM_CLOSE = 0x0010
WM_QUERYENDSESSION = 0x0011
WM_ENDSESSION = 0x0016
WM_ERASEBKGND = 0x0014
WM_SETCURSOR = 0x0020
WM_MOUSEACTIVATE = 0x0021
WM_DISPLAYCHANGE = 0x007E
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_SYSCOMMAND = 0x0112
WM_TIMER = 0x0113
WM_DPICHANGED = 0x02E0
WM_APP_EXIT = 0x8001
WM_APP_REFRESH = 0x8002
HWND_TOPMOST = W.HWND(-1)
ES_CONTINUOUS = 0x80000000


@dataclass(frozen=True)
class Monitor:
    device: str
    left: int
    top: int
    right: int
    bottom: int
    primary: bool

    def contains(self, x: int, y: int) -> bool:
        return self.left <= x < self.right and self.top <= y < self.bottom


def list_monitors() -> list[Monitor]:
    monitors = []
    errors = []

    @MONITORENUMPROC
    def collect(handle, _hdc, _rect, _data):
        info = MONITORINFOEXW()
        info.cbSize = C.sizeof(info)
        if not user32.GetMonitorInfoW(handle, C.byref(info)):
            errors.append(C.WinError(C.get_last_error()))
            return False
        r = info.rcMonitor
        monitors.append(Monitor(info.szDevice, r.left, r.top, r.right,
                                r.bottom, bool(info.dwFlags & 1)))
        return True

    if not user32.EnumDisplayMonitors(None, None, collect, 0):
        raise errors[0] if errors else C.WinError(C.get_last_error())
    return monitors


def choose_secondary(monitors: list[Monitor]) -> Monitor | None:
    # Never use the primary monitor as a fallback, including in mirror mode.
    secondary = [m for m in monitors if not m.primary
                 and m.right > m.left and m.bottom > m.top]
    return min(secondary, key=lambda m: (
        m.device.upper() != r"\\.\DISPLAY2", m.device.upper())) if secondary else None


def enable_dpi_awareness():
    try:
        set_context = _api(user32, "SetProcessDpiAwarenessContext", W.BOOL, HANDLE)
        set_context(HANDLE(-4))  # PER_MONITOR_AWARE_V2; manifest may already set it.
    except AttributeError:
        _api(user32, "SetProcessDPIAware", W.BOOL)()


class BlackScreenApp:
    def __init__(self, callback=None, stop_event=None):
        self.hwnd = None
        self.hook = None
        self.target = None
        self.exit_requested = False
        self.f4_armed = False
        self.callback_error = None
        self.previous_execution_state = 0
        self._callback = callback or (lambda _state, _detail: None)
        self._stop_event = stop_event or threading.Event()
        self._last_state = None
        self._window_lock = threading.Lock()
        self.class_name = f"{CLASS_NAME}.{id(self):x}"
        self.instance = kernel32.GetModuleHandleW(None)
        self.black_brush = gdi32.GetStockObject(4)  # BLACK_BRUSH = RGB(0, 0, 0).
        self.window_callback = WNDPROC(self.window_proc)
        self.keyboard_callback = HOOKPROC(self.keyboard_proc)

    def cursor_over_target(self) -> bool:
        point = W.POINT()
        return bool(self.target and user32.IsWindowVisible(self.hwnd)
                    and user32.GetCursorPos(C.byref(point))
                    and self.target.contains(point.x, point.y))

    def keyboard_proc(self, code, wparam, lparam):
        # Do not log, buffer, or modify other keys. Keep this callback short;
        # Windows dispatches it on this thread, which continuously pumps messages.
        if code == 0 and wparam in (WM_KEYDOWN, WM_SYSKEYDOWN, WM_KEYUP, WM_SYSKEYUP):
            event = C.cast(lparam, C.POINTER(KBDLLHOOKSTRUCT)).contents
            if event.vkCode == 0x73:
                if self.f4_armed:
                    if wparam in (WM_KEYUP, WM_SYSKEYUP):
                        self.f4_armed = False
                        self.exit_requested = True
                        user32.PostMessageW(self.hwnd, WM_APP_EXIT, 0, 0)
                    return 1
                if (wparam in (WM_KEYDOWN, WM_SYSKEYDOWN)
                        and event.flags & 0x20 and self.cursor_over_target()):
                    # Pair the key down/up so the sound player sees neither.
                    self.f4_armed = True
                    return 1
        return user32.CallNextHookEx(self.hook, code, wparam, lparam)

    def _notify(self, state, detail=""):
        if state in {"on", "waiting"} and self._stop_event.is_set():
            return
        value = (state, detail)
        if self._last_state != value:
            self._last_state = value
            self._callback(state, detail)

    def request_stop(self):
        """May be called by the GUI; native destruction stays on the worker."""
        self._stop_event.set()
        self.exit_requested = True
        with self._window_lock:
            if self.hwnd:
                user32.PostMessageW(self.hwnd, WM_APP_EXIT, 0, 0)

    def refresh_display(self):
        if self._stop_event.is_set():
            self.exit_requested = True
            user32.PostQuitMessage(0)
            return
        target = choose_secondary(list_monitors())
        if target is None:
            self.target = None
            user32.ShowWindow(self.hwnd, 0)  # SW_HIDE; reconnect is checked by timer.
            self._notify("waiting")
            return
        self.target = target
        if not user32.SetWindowPos(
                self.hwnd, HWND_TOPMOST, target.left, target.top,
                target.right - target.left, target.bottom - target.top,
                0x0010 | 0x0040):  # SWP_NOACTIVATE | SWP_SHOWWINDOW
            raise C.WinError(C.get_last_error())
        self._notify("on", target.device)

    def window_proc(self, hwnd, message, wparam, lparam):
        try:
            if message == WM_PAINT:
                paint = PAINTSTRUCT()
                user32.BeginPaint(hwnd, C.byref(paint))
                try:
                    user32.FillRect(paint.hdc, C.byref(paint.rcPaint), self.black_brush)
                finally:
                    user32.EndPaint(hwnd, C.byref(paint))
                return 0
            if message == WM_ERASEBKGND:
                rect = W.RECT()
                user32.GetClientRect(hwnd, C.byref(rect))
                user32.FillRect(W.HDC(wparam), C.byref(rect), self.black_brush)
                return 1
            if message == WM_SETCURSOR:
                user32.SetCursor(None)
                return 1
            if message == WM_MOUSEACTIVATE:
                return 3  # MA_NOACTIVATE: sound cue player retains keyboard focus.
            if message == WM_CLOSE:
                return 0
            if message == WM_SYSCOMMAND and (wparam & 0xFFF0) in (
                    0xF000, 0xF010, 0xF020, 0xF030, 0xF060):
                return 0  # Disable resize, move, minimize, maximize and close.
            if message == WM_APP_EXIT:
                if self.exit_requested:
                    user32.PostQuitMessage(0)
                return 0
            if message in (WM_DISPLAYCHANGE, WM_DPICHANGED):
                # Windows may relocate windows after an unplug. Hide immediately;
                # re-enumerate before showing anything again.
                self.target = None
                user32.ShowWindow(hwnd, 0)
                self._notify("waiting")
                user32.PostMessageW(hwnd, WM_APP_REFRESH, 0, 0)
                return 0
            if message == WM_APP_REFRESH or (message == WM_TIMER and wparam == 1):
                self.refresh_display()
                return 0
            if message == WM_QUERYENDSESSION:
                return 1  # Respect Windows shutdown/logoff.
            if message == WM_ENDSESSION and wparam:
                user32.PostQuitMessage(0)
                return 0
            if message == WM_DESTROY:
                user32.KillTimer(hwnd, 1)
                user32.PostQuitMessage(0)
                return 0
        except Exception as error:
            self.callback_error = error
            user32.ShowWindow(hwnd, 0)
            user32.PostQuitMessage(1)
            return 0
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def run(self) -> int:
        self.target = choose_secondary(list_monitors())
        if self._stop_event.is_set():
            return 0
        if self.target is None:
            raise RuntimeError("no_secondary_monitor")

        wc = WNDCLASSEXW()
        wc.cbSize = C.sizeof(wc)
        wc.lpfnWndProc = self.window_callback
        wc.hInstance = self.instance
        wc.hbrBackground = self.black_brush
        wc.lpszClassName = self.class_name
        if not user32.RegisterClassExW(C.byref(wc)):
            raise C.WinError(C.get_last_error())
        try:
            m = self.target
            # WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE; WS_POPUP.
            # No WS_VISIBLE: the black brush is ready before first presentation.
            self.hwnd = user32.CreateWindowExW(
                0x00000008 | 0x00000080 | 0x08000000, self.class_name, APP_NAME,
                0x80000000, m.left, m.top, m.right - m.left, m.bottom - m.top,
                None, None, self.instance, None)
            if not self.hwnd:
                raise C.WinError(C.get_last_error())
            self.hook = user32.SetWindowsHookExW(
                13, self.keyboard_callback, self.instance, 0)  # WH_KEYBOARD_LL
            if not self.hook:
                raise C.WinError(C.get_last_error())
            if not user32.SetTimer(self.hwnd, 1, 1000, None):
                raise C.WinError(C.get_last_error())
            self.previous_execution_state = kernel32.SetThreadExecutionState(
                ES_CONTINUOUS | 0x00000001 | 0x00000002)
            if self._stop_event.is_set():
                return 0
            self.refresh_display()
            message = W.MSG()
            while True:
                result = user32.GetMessageW(C.byref(message), None, 0, 0)
                if result == -1:
                    raise C.WinError(C.get_last_error())
                if result == 0:
                    break
                user32.TranslateMessage(C.byref(message))
                user32.DispatchMessageW(C.byref(message))
            if self.callback_error:
                raise self.callback_error
            return int(message.wParam)
        finally:
            self._notify("stopping")
            if self.hook:
                user32.UnhookWindowsHookEx(self.hook)
                self.hook = None
            with self._window_lock:
                hwnd, self.hwnd = self.hwnd, None
            if hwnd:
                user32.DestroyWindow(hwnd)
            if self.previous_execution_state:
                kernel32.SetThreadExecutionState(self.previous_execution_state)
            user32.UnregisterClassW(self.class_name, self.instance)


class BlackScreenController:
    """Own the native overlay and its message loop without blocking Tk.

    ``callback(state, detail)`` runs on the worker thread; UI clients should queue
    these events. Error detail ``no_secondary_monitor`` means Windows needs an
    extended secondary display; ``already_running`` means another cover owns it.
    A failure ends with ``error`` rather than overwriting it with ``off``.
    """

    def __init__(self, callback: Callable[[str, str], None]) -> None:
        self._callback = callback
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._app: BlackScreenApp | None = None
        self._stop_event = threading.Event()

    @property
    def running(self) -> bool:
        with self._lock:
            return bool(self._thread and self._thread.is_alive())

    def _publish(self, state: str, detail: str = "") -> None:
        # A consumer disappearing during shutdown must not strand the cover.
        try:
            self._callback(state, detail)
        except Exception:
            pass

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event = threading.Event()
            self._thread = threading.Thread(
                target=self._run, args=(self._stop_event,),
                name="SCENE BlackScreen", daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            self._stop_event.set()
            app = self._app
        if app is not None:
            app.request_stop()

    def close(self, timeout: float = 3.0) -> bool:
        self.stop()
        with self._lock:
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, timeout))
        return not self.running

    def _run(self, stop_event: threading.Event) -> None:
        mutex = None
        error = None
        self._publish("starting")
        try:
            if stop_event.is_set():
                return
            C.set_last_error(0)
            mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
            if not mutex:
                raise C.WinError(C.get_last_error())
            if C.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
                raise RuntimeError("already_running")
            app = BlackScreenApp(self._publish, stop_event)
            with self._lock:
                self._app = app
            app.run()
        except Exception as exc:
            error = str(exc)
        finally:
            with self._lock:
                self._app = None
            if mutex:
                kernel32.CloseHandle(mutex)
            if error is None:
                self._publish("off")
            else:
                self._publish("error", error)
