"""Activation hotkey through the Windows API RegisterHotKey."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import threading
import time
from typing import Callable


class HotkeyActivator:
    """Listens for Ctrl+Alt+J through the Windows API RegisterHotKey."""

    def __init__(self, on_activate: Callable[[], None]) -> None:
        self.on_activate = on_activate
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=3)

    def _run(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        MOD_CONTROL = 0x0002
        MOD_ALT = 0x0001
        MOD_NOREPEAT = 0x4000
        VK_J = 0x4A

        # Create a hidden window to receive messages
        class WNDCLASS(ctypes.Structure):
            _fields_ = [
                ("style", ctypes.c_uint),
                ("lpfnWndProc", ctypes.c_void_p),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", ctypes.c_void_p),
                ("hIcon", ctypes.c_void_p),
                ("hCursor", ctypes.c_void_p),
                ("hbrBackground", ctypes.c_void_p),
                ("lpszMenuName", ctypes.c_wchar_p),
                ("lpszClassName", ctypes.c_wchar_p),
            ]

        def wnd_proc(hwnd, msg, wparam, lparam):
            if msg == 0x0312:  # WM_HOTKEY
                self.on_activate()
            return user32.DefWindowProcW(hwnd, msg, ctypes.c_longlong(wparam), ctypes.c_longlong(lparam))

        WNDPROC = ctypes.WINFUNCTYPE(
            ctypes.c_longlong, ctypes.wintypes.HWND, ctypes.c_uint,
            ctypes.c_longlong, ctypes.c_longlong,
        )
        wndproc = WNDPROC(wnd_proc)

        wc = WNDCLASS()
        wc.lpfnWndProc = ctypes.cast(wndproc, ctypes.c_void_p)
        wc.hInstance = kernel32.GetModuleHandleW(None)
        wc.lpszClassName = "JarvisHotkeyWindow"

        atom = user32.RegisterClassW(ctypes.byref(wc))
        if not atom:
            return

        hwnd = user32.CreateWindowExW(
            0, "JarvisHotkeyWindow", "Jarvis", 0, 0, 0, 0, 0,
            None, None, wc.hInstance, None,
        )
        if not hwnd:
            return

        result = user32.RegisterHotKey(hwnd, 1, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_J)
        if not result:
            user32.DestroyWindow(hwnd)
            return

        # Message loop
        msg = ctypes.wintypes.MSG()
        while self._running:
            ret = user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1)  # PM_REMOVE
            if ret:
                if msg.message == 0x0312:
                    self.on_activate()
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            time.sleep(0.01)

        user32.UnregisterHotKey(hwnd, 1)
        user32.DestroyWindow(hwnd)