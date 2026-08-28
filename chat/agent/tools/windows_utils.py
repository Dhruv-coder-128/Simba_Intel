"""Native Windows utilities for clipboard, window focusing, window states (minimize/maximize/restore),
input simulation (SendInput / mouse / keyboard hotkeys), system telemetry, and power actions via Win32 API.
"""
import ctypes
import os
import platform
import sys
import time
from ctypes import wintypes
from typing import Any, Dict, List, Optional, Tuple, Union

# Windows API constants
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

SW_HIDE = 0
SW_SHOWNORMAL = 1
SW_SHOWMINIMIZED = 2
SW_MAXIMIZE = 3
SW_SHOWMAXIMIZED = 3
SW_SHOWNOACTIVATE = 4
SW_SHOW = 5
SW_MINIMIZE = 6
SW_SHOWMINNOACTIVE = 7
SW_SHOWNA = 8
SW_RESTORE = 9
SW_SHOWDEFAULT = 10
SW_FORCEMINIMIZE = 11

HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_SHOWWINDOW = 0x0040

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000

# Virtual key codes dictionary
VK_MAP = {
    # Modifiers
    "control": 0x11,
    "ctrl": 0x11,
    "shift": 0x10,
    "alt": 0x12,
    "win": 0x5B,
    "windows": 0x5B,
    "cmd": 0x5B,
    "command": 0x5B,

    # Basic keys
    "enter": 0x0D,
    "return": 0x0D,
    "tab": 0x09,
    "space": 0x20,
    "escape": 0x1B,
    "esc": 0x1B,
    "backspace": 0x08,
    "delete": 0x2E,
    "del": 0x2E,
    "insert": 0x2D,
    "capslock": 0x14,
    "caps_lock": 0x14,
    "prtscn": 0x2C,
    "printscreen": 0x2C,

    # Navigation
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "page_up": 0x21,
    "pagedown": 0x22,
    "page_down": 0x22,

    # Function keys F1-F12
    "f1": 0x70,
    "f2": 0x71,
    "f3": 0x72,
    "f4": 0x73,
    "f5": 0x74,
    "f6": 0x75,
    "f7": 0x76,
    "f8": 0x77,
    "f9": 0x78,
    "f10": 0x79,
    "f11": 0x7A,
    "f12": 0x7B,

    # Letters A-Z
    "a": 0x41, "b": 0x42, "c": 0x43, "d": 0x44, "e": 0x45,
    "f": 0x46, "g": 0x47, "h": 0x48, "i": 0x49, "j": 0x4A,
    "k": 0x4B, "l": 0x4C, "m": 0x4D, "n": 0x4E, "o": 0x4F,
    "p": 0x50, "q": 0x51, "r": 0x52, "s": 0x53, "t": 0x54,
    "u": 0x55, "v": 0x56, "w": 0x57, "x": 0x58, "y": 0x59,
    "z": 0x5A,

    # Numbers 0-9
    "0": 0x30, "1": 0x31, "2": 0x32, "3": 0x33, "4": 0x34,
    "5": 0x35, "6": 0x36, "7": 0x37, "8": 0x38, "9": 0x39,
}

_is_windows = os.name == "nt"

if _is_windows:
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        shell32 = ctypes.windll.shell32

        # Configure Win32 API functions
        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.OpenClipboard.restype = wintypes.BOOL
        user32.CloseClipboard.argtypes = []
        user32.CloseClipboard.restype = wintypes.BOOL
        user32.EmptyClipboard.argtypes = []
        user32.EmptyClipboard.restype = wintypes.BOOL
        user32.GetClipboardData.argtypes = [wintypes.UINT]
        user32.GetClipboardData.restype = wintypes.HANDLE
        user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
        user32.SetClipboardData.restype = wintypes.HANDLE

        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalLock.restype = wintypes.LPVOID
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalUnlock.restype = wintypes.BOOL
        kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalFree.restype = wintypes.HGLOBAL

        user32.GetForegroundWindow.argtypes = []
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wintypes.BOOL
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.BringWindowToTop.argtypes = [wintypes.HWND]
        user32.BringWindowToTop.restype = wintypes.BOOL
        user32.SetFocus.argtypes = [wintypes.HWND]
        user32.SetFocus.restype = wintypes.HWND

        user32.IsIconic.argtypes = [wintypes.HWND]
        user32.IsIconic.restype = wintypes.BOOL
        user32.IsZoomed.argtypes = [wintypes.HWND]
        user32.IsZoomed.restype = wintypes.BOOL

        user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        user32.GetCursorPos.restype = wintypes.BOOL
        user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        user32.SetCursorPos.restype = wintypes.BOOL

        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD

        kernel32.GetCurrentThreadId.argtypes = []
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD
        user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
        user32.AttachThreadInput.restype = wintypes.BOOL

        user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.SetWindowPos.restype = wintypes.BOOL
    except Exception:
        user32 = None
        kernel32 = None
        shell32 = None
else:
    user32 = None
    kernel32 = None
    shell32 = None


# Win32 SendInput Structures
class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_ulonglong),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_ulonglong),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("pad", ctypes.c_ubyte * 32)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUT_UNION)]


def set_clipboard_text(text: str) -> bool:
    """Sets unicode text to Windows clipboard using native Win32 API."""
    if not _is_windows or not user32 or not kernel32:
        return False
    try:
        if not user32.OpenClipboard(None):
            return False
        user32.EmptyClipboard()
        encoded = (text + '\0').encode('utf-16le')
        h_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(encoded))
        if not h_mem:
            user32.CloseClipboard()
            return False
        p_mem = kernel32.GlobalLock(h_mem)
        if not p_mem:
            kernel32.GlobalFree(h_mem)
            user32.CloseClipboard()
            return False
        ctypes.memmove(p_mem, encoded, len(encoded))
        kernel32.GlobalUnlock(h_mem)
        user32.SetClipboardData(CF_UNICODETEXT, h_mem)
        user32.CloseClipboard()
        return True
    except Exception:
        return False


def get_clipboard_text() -> str:
    """Gets unicode text from Windows clipboard using native Win32 API."""
    if not _is_windows or not user32 or not kernel32:
        return ""
    try:
        if not user32.OpenClipboard(None):
            return ""
        h_mem = user32.GetClipboardData(CF_UNICODETEXT)
        if not h_mem:
            user32.CloseClipboard()
            return ""
        p_mem = kernel32.GlobalLock(h_mem)
        if not p_mem:
            user32.CloseClipboard()
            return ""
        text = ctypes.c_wchar_p(p_mem).value or ""
        kernel32.GlobalUnlock(h_mem)
        user32.CloseClipboard()
        return text
    except Exception:
        return ""


def _enum_windows_helper(callback_fn: Any) -> None:
    """Helper that enumerates windows on the active interactive desktop as well as fallback EnumWindows."""
    if not _is_windows or not user32:
        return
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    cb = WNDENUMPROC(callback_fn)
    try:
        hdesk = user32.OpenInputDesktop(0, False, 0x01FF)
        if hdesk:
            user32.SetThreadDesktop(hdesk)
            user32.EnumDesktopWindows(hdesk, cb, 0)
            user32.CloseDesktop(hdesk)
            return
    except Exception:
        pass
    try:
        user32.EnumWindows(cb, 0)
    except Exception:
        pass


def find_window_by_title_substring(title_substr: str) -> Optional[int]:
    """Finds top-level visible window HWND matching a title substring or window class."""
    if not _is_windows or not user32:
        return None

    matching_hwnd = None
    title_lower = title_substr.lower().strip()

    def enum_callback(hwnd, lparam):
        nonlocal matching_hwnd
        # Check window visibility or minimized state (IsIconic)
        if user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            title_text = ""
            if length > 0:
                buff = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buff, length + 1)
                title_text = buff.value.lower()

            cls_buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls_buf, 256)
            cls_name = cls_buf.value.lower()

            if (title_text and title_lower in title_text) or (title_lower in cls_name and length > 0):
                matching_hwnd = hwnd
                return False  # stop enumeration
        return True

    _enum_windows_helper(enum_callback)
    return matching_hwnd


def find_window_by_process_name(proc_name: str) -> Optional[int]:
    """Finds top-level window HWND owned by process matching name (e.g. 'chrome', 'notepad')."""
    if not _is_windows or not user32:
        return None
    try:
        import psutil
        target_pids = set()
        proc_clean = proc_name.lower().replace(".exe", "").strip()
        for p in psutil.process_iter(['name', 'pid']):
            try:
                name = (p.info.get('name') or '').lower()
                if proc_clean in name:
                    target_pids.add(p.info['pid'])
            except Exception:
                continue

        if not target_pids:
            return None

        matching_hwnd = None

        def enum_cb(hwnd, lparam):
            nonlocal matching_hwnd
            if user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value in target_pids:
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        matching_hwnd = hwnd
                        return False
            return True

        _enum_windows_helper(enum_cb)
        return matching_hwnd
    except Exception:
        return None


def find_window_flexible(identifier: str) -> Optional[int]:
    """Searches for window by title substring first, then by process name candidate."""
    if not identifier:
        return None
    hwnd = find_window_by_title_substring(identifier)
    if hwnd:
        return hwnd
    return find_window_by_process_name(identifier)


def wait_for_window_by_title(title_substr: str, timeout: float = 10.0) -> Optional[int]:
    """Polls up to `timeout` seconds to find a top-level window matching title or process."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        hwnd = find_window_flexible(title_substr)
        if hwnd:
            return hwnd
        time.sleep(0.15)
    return None


def force_focus_window(hwnd: int) -> bool:
    """Bulletproof window focus on Windows 10/11 using AttachThreadInput and SetWindowPos."""
    if not _is_windows or not user32 or not kernel32:
        return False
    try:
        user32.ShowWindow(hwnd, SW_RESTORE)
        current_thread = kernel32.GetCurrentThreadId()
        fg_hwnd = user32.GetForegroundWindow()
        fg_thread = user32.GetWindowThreadProcessId(fg_hwnd, None) if fg_hwnd else 0
        target_thread = user32.GetWindowThreadProcessId(hwnd, None)

        if fg_thread and fg_thread != current_thread:
            user32.AttachThreadInput(current_thread, fg_thread, True)
        if target_thread and target_thread != current_thread:
            user32.AttachThreadInput(current_thread, target_thread, True)

        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        user32.SetForegroundWindow(hwnd)
        user32.BringWindowToTop(hwnd)
        user32.SetFocus(hwnd)

        if fg_thread and fg_thread != current_thread:
            user32.AttachThreadInput(current_thread, fg_thread, False)
        if target_thread and target_thread != current_thread:
            user32.AttachThreadInput(current_thread, target_thread, False)

        return True
    except Exception:
        return False


def set_foreground_window(hwnd: int) -> bool:
    """Brings window to foreground and restores if minimized."""
    return force_focus_window(hwnd)


def minimize_window_by_hwnd(hwnd: int) -> bool:
    """Minimizes the specified window HWND and verifies state via IsIconic."""
    if not _is_windows or not user32:
        return False
    try:
        user32.ShowWindow(hwnd, SW_MINIMIZE)
        time.sleep(0.1)
        return bool(user32.IsIconic(hwnd))
    except Exception:
        return False


def maximize_window_by_hwnd(hwnd: int) -> bool:
    """Maximizes the specified window HWND and verifies state via IsZoomed."""
    if not _is_windows or not user32:
        return False
    try:
        user32.ShowWindow(hwnd, SW_MAXIMIZE)
        time.sleep(0.1)
        return bool(user32.IsZoomed(hwnd))
    except Exception:
        return False


def restore_window_by_hwnd(hwnd: int) -> bool:
    """Restores the specified window from minimized or maximized state."""
    if not _is_windows or not user32:
        return False
    try:
        user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.1)
        force_focus_window(hwnd)
        return not bool(user32.IsIconic(hwnd))
    except Exception:
        return False


def minimize_window(title_substr: str) -> Tuple[bool, Optional[int]]:
    """Locates window matching title or process substring and minimizes it."""
    hwnd = find_window_flexible(title_substr)
    if not hwnd:
        return False, None
    ok = minimize_window_by_hwnd(hwnd)
    return ok, hwnd


def maximize_window(title_substr: str) -> Tuple[bool, Optional[int]]:
    """Locates window matching title or process substring and maximizes it."""
    hwnd = find_window_flexible(title_substr)
    if not hwnd:
        return False, None
    ok = maximize_window_by_hwnd(hwnd)
    return ok, hwnd


def restore_window(title_substr: str) -> Tuple[bool, Optional[int]]:
    """Locates window matching title or process substring and restores it."""
    hwnd = find_window_flexible(title_substr)
    if not hwnd:
        return False, None
    ok = restore_window_by_hwnd(hwnd)
    return ok, hwnd


def switch_to_window(title_substr: str) -> Tuple[bool, Optional[int]]:
    """Locates window matching title or process substring and brings it to foreground."""
    hwnd = find_window_flexible(title_substr)
    if not hwnd:
        return False, None
    ok = force_focus_window(hwnd)
    return ok, hwnd


def get_active_window_info() -> Dict[str, Any]:
    """Returns title, process name, HWND, and state of current foreground window."""
    if not _is_windows or not user32:
        return {"title": "Unknown", "pid": None, "process_name": "Unknown", "hwnd": 0, "is_minimized": False, "is_maximized": False}

    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return {"title": "None", "pid": None, "process_name": "None", "hwnd": 0, "is_minimized": False, "is_maximized": False}

        length = user32.GetWindowTextLengthW(hwnd)
        title = ""
        if length > 0:
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            title = buff.value

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        proc_pid = pid.value

        proc_name = "Unknown"
        if proc_pid:
            try:
                import psutil
                p = psutil.Process(proc_pid)
                proc_name = p.name()
            except Exception:
                pass

        is_min = bool(user32.IsIconic(hwnd))
        is_max = bool(user32.IsZoomed(hwnd))

        return {
            "title": title or proc_name,
            "pid": proc_pid,
            "process_name": proc_name,
            "hwnd": hwnd,
            "is_minimized": is_min,
            "is_maximized": is_max,
        }
    except Exception:
        return {"title": "Unknown", "pid": None, "process_name": "Unknown", "hwnd": 0, "is_minimized": False, "is_maximized": False}


def send_unicode_text(text: str) -> bool:
    """Directly dispatches raw Unicode keystrokes to active control using Win32 SendInput."""
    if not _is_windows or not user32:
        return False
    if not text:
        return True

    inputs = []
    for char in text:
        if char == '\n' or char == '\r':
            inp_down = INPUT(type=1)
            inp_down.u.ki = KEYBDINPUT(wVk=0x0D, wScan=0, dwFlags=0, time=0, dwExtraInfo=0)
            inp_up = INPUT(type=1)
            inp_up.u.ki = KEYBDINPUT(wVk=0x0D, wScan=0, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=0)
            inputs.extend([inp_down, inp_up])
        elif char == '\t':
            inp_down = INPUT(type=1)
            inp_down.u.ki = KEYBDINPUT(wVk=0x09, wScan=0, dwFlags=0, time=0, dwExtraInfo=0)
            inp_up = INPUT(type=1)
            inp_up.u.ki = KEYBDINPUT(wVk=0x09, wScan=0, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=0)
            inputs.extend([inp_down, inp_up])
        else:
            code = ord(char)
            inp_down = INPUT(type=1)
            inp_down.u.ki = KEYBDINPUT(wVk=0, wScan=code, dwFlags=KEYEVENTF_UNICODE, time=0, dwExtraInfo=0)
            inp_up = INPUT(type=1)
            inp_up.u.ki = KEYBDINPUT(wVk=0, wScan=code, dwFlags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, time=0, dwExtraInfo=0)
            inputs.extend([inp_down, inp_up])

    if inputs:
        try:
            n = len(inputs)
            arr = (INPUT * n)(*inputs)
            sent = user32.SendInput(n, arr, ctypes.sizeof(INPUT))
            return sent == n
        except Exception:
            return False
    return False


def paste_clipboard() -> bool:
    """Simulates Ctrl+V press and release."""
    if not _is_windows or not user32:
        return False
    try:
        vk_ctrl = VK_MAP["ctrl"]
        vk_v = VK_MAP["v"]
        user32.keybd_event(vk_ctrl, 0, 0, 0)
        time.sleep(0.04)
        user32.keybd_event(vk_v, 0, 0, 0)
        time.sleep(0.04)
        user32.keybd_event(vk_v, 0, KEYEVENTF_KEYUP, 0)
        time.sleep(0.04)
        user32.keybd_event(vk_ctrl, 0, KEYEVENTF_KEYUP, 0)
        return True
    except Exception:
        return False


def send_key(key_name: str) -> bool:
    """Simulates pressing and releasing a single key."""
    if not _is_windows or not user32:
        return False
    key_lower = key_name.lower().strip()
    vk_code = VK_MAP.get(key_lower)
    if not vk_code:
        if len(key_lower) == 1:
            vk_code = ord(key_lower.upper())
        else:
            return False
    try:
        user32.keybd_event(vk_code, 0, 0, 0)
        time.sleep(0.03)
        user32.keybd_event(vk_code, 0, KEYEVENTF_KEYUP, 0)
        return True
    except Exception:
        return False


def send_hotkey(keys: Union[List[str], str]) -> bool:
    """Simulates pressing a combination of keys (e.g. ['ctrl', 's'] or 'ctrl+s')."""
    if not _is_windows or not user32:
        return False

    key_list = []
    if isinstance(keys, str):
        parts = keys.replace("+", " ").replace(",", " ").split()
        key_list = [p.strip() for p in parts if p.strip()]
    elif isinstance(keys, list):
        key_list = [str(k).strip() for k in keys if str(k).strip()]

    if not key_list:
        return False

    vk_codes = []
    for k in key_list:
        k_lower = k.lower().strip()
        vk = VK_MAP.get(k_lower)
        if not vk and len(k_lower) == 1:
            vk = ord(k_lower.upper())
        if vk:
            vk_codes.append(vk)

    if not vk_codes:
        return False

    try:
        for code in vk_codes:
            user32.keybd_event(code, 0, 0, 0)
            time.sleep(0.02)
        time.sleep(0.04)
        for code in reversed(vk_codes):
            user32.keybd_event(code, 0, KEYEVENTF_KEYUP, 0)
            time.sleep(0.02)
        return True
    except Exception:
        return False


def send_keys_sequence(keys: List[str]) -> bool:
    """Presses a sequence of keys in order."""
    if not keys:
        return True
    success = True
    for k in keys:
        if not send_key(k):
            success = False
        time.sleep(0.05)
    return success


def get_mouse_position() -> Tuple[int, int]:
    """Gets current mouse cursor coordinates."""
    if not _is_windows or not user32:
        return 0, 0
    try:
        pt = wintypes.POINT()
        if user32.GetCursorPos(ctypes.byref(pt)):
            return pt.x, pt.y
    except Exception:
        pass
    return 0, 0


def mouse_move(x: int, y: int) -> bool:
    """Moves mouse cursor to pixel coordinates (x, y)."""
    if not _is_windows or not user32:
        return False
    try:
        return bool(user32.SetCursorPos(int(x), int(y)))
    except Exception:
        return False


def mouse_click(button: str = "left", x: Optional[int] = None, y: Optional[int] = None) -> bool:
    """Clicks mouse button ('left', 'right', 'middle'), optionally at coordinates (x, y)."""
    if not _is_windows or not user32:
        return False
    try:
        if x is not None and y is not None:
            user32.SetCursorPos(int(x), int(y))
            time.sleep(0.03)

        b = button.lower().strip()
        if b == "right":
            user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
            time.sleep(0.03)
            user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
        elif b == "middle":
            user32.mouse_event(MOUSEEVENTF_MIDDLEDOWN, 0, 0, 0, 0)
            time.sleep(0.03)
            user32.mouse_event(MOUSEEVENTF_MIDDLEUP, 0, 0, 0, 0)
        else:
            user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(0.03)
            user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        return True
    except Exception:
        return False


def mouse_right_click(x: Optional[int] = None, y: Optional[int] = None) -> bool:
    """Right-clicks mouse, optionally at coordinates (x, y)."""
    return mouse_click(button="right", x=x, y=y)


def mouse_double_click(button: str = "left", x: Optional[int] = None, y: Optional[int] = None) -> bool:
    """Double-clicks mouse button, optionally at coordinates (x, y)."""
    if x is not None and y is not None:
        mouse_move(x, y)
        time.sleep(0.03)
    ok1 = mouse_click(button)
    time.sleep(0.08)
    ok2 = mouse_click(button)
    return ok1 and ok2


def mouse_scroll(clicks: int = 1, direction: str = "down") -> bool:
    """Scrolls mouse wheel up or down."""
    if not _is_windows or not user32:
        return False
    try:
        dir_lower = direction.lower().strip()
        sign = 1 if (dir_lower == "up" or clicks > 0 and dir_lower != "down") else -1
        delta = abs(clicks) * 120 * sign
        user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, delta, 0)
        return True
    except Exception:
        return False


def is_process_running(proc_name: str) -> bool:
    """Checks if a process name exists in running processes."""
    p_lower = proc_name.lower().strip()
    try:
        import psutil
        for p in psutil.process_iter(['name']):
            try:
                name = (p.info.get('name') or '').lower()
                if p_lower in name:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass
    return False


def wait_for_process(candidate_proc_names: List[str], timeout: float = 10.0) -> bool:
    """Polls up to `timeout` seconds to verify that candidate process is running."""
    start_time = time.time()
    candidates_lower = [c.lower().strip() for c in candidate_proc_names if c]
    if not candidates_lower:
        return True

    while time.time() - start_time < timeout:
        try:
            import psutil
            for p in psutil.process_iter(['name']):
                try:
                    name = (p.info.get('name') or '').lower()
                    if any(cand in name for cand in candidates_lower):
                        return True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception:
            return True
        time.sleep(0.15)
    return False


def close_window_or_process(target: str) -> bool:
    """Safely closes a window matching title or terminates process by name."""
    closed = False
    hwnd = find_window_by_title_substring(target)
    if hwnd and user32:
        WM_CLOSE = 0x0010
        try:
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            closed = True
        except Exception:
            pass

    target_lower = target.lower().strip()
    try:
        import psutil
        for p in psutil.process_iter(['name', 'pid']):
            try:
                name = (p.info.get('name') or '').lower()
                if target_lower in name:
                    p.terminate()
                    closed = True
            except Exception:
                continue
    except Exception:
        pass
    return closed


def empty_windows_recycle_bin(confirm: bool = False) -> bool:
    """Empties the Windows Recycle Bin."""
    if not _is_windows or not shell32:
        return False
    try:
        SHERB_NOCONFIRMATION = 0x00000001
        SHERB_NOPROGRESSUI = 0x00000002
        SHERB_NOSOUND = 0x00000004
        res = shell32.SHEmptyRecycleBinW(None, None, SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND)
        return res == 0
    except Exception:
        return False


def system_power(action: str = "lock") -> bool:
    """Executes Windows system power actions."""
    if not _is_windows:
        return False
    act = action.lower().strip()
    try:
        if act == "lock":
            user32.LockWorkStation()
            return True
        elif act == "shutdown":
            os.system("shutdown /s /t 5")
            return True
        elif act == "restart":
            os.system("shutdown /r /t 5")
            return True
        elif act == "sleep":
            os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")
            return True
    except Exception:
        pass
    return False


def get_system_telemetry() -> Dict[str, Any]:
    """Gathers safe system telemetry (CPU, RAM, OS, disk, platform)."""
    telemetry = {
        "os": platform.system(),
        "os_release": platform.release(),
        "os_version": platform.version(),
        "architecture": platform.machine(),
        "cpu_percent": 0.0,
        "ram_percent": 0.0,
        "ram_total_gb": 0.0,
        "ram_used_gb": 0.0,
        "disk_free_gb": 0.0,
        "disk_total_gb": 0.0,
    }
    try:
        import psutil
        telemetry["cpu_percent"] = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        telemetry["ram_percent"] = mem.percent
        telemetry["ram_total_gb"] = round(mem.total / (1024 ** 3), 1)
        telemetry["ram_used_gb"] = round(mem.used / (1024 ** 3), 1)

        disk = psutil.disk_usage(os.path.expanduser("~"))
        telemetry["disk_free_gb"] = round(disk.free / (1024 ** 3), 1)
        telemetry["disk_total_gb"] = round(disk.total / (1024 ** 3), 1)
    except Exception:
        pass
    return telemetry
