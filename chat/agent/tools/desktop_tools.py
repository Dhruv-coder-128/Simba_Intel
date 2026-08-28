"""Desktop application, window (minimize/maximize/restore/switch), mouse, keyboard, and input automation tools for SIMBA_INTEL Agent.
Executes real local desktop actions on the user's Windows operating system with truthful verification and risk gating.
"""
import logging
import os
import re
import shutil
import subprocess
import time
from typing import Any, Dict, List, Optional, Union

from .registry import ExecutionResult, RiskLevel, Tool, ToolParameter, global_tool_registry
from .windows_utils import (
    close_window_or_process,
    empty_windows_recycle_bin,
    find_window_by_process_name,
    find_window_by_title_substring,
    find_window_flexible,
    force_focus_window,
    get_active_window_info,
    get_clipboard_text,
    get_mouse_position,
    get_system_telemetry,
    is_process_running,
    maximize_window,
    maximize_window_by_hwnd,
    minimize_window,
    minimize_window_by_hwnd,
    mouse_click,
    mouse_double_click,
    mouse_move,
    mouse_right_click,
    mouse_scroll,
    paste_clipboard,
    restore_window,
    restore_window_by_hwnd,
    send_hotkey,
    send_key,
    send_keys_sequence,
    send_unicode_text,
    set_clipboard_text,
    switch_to_window,
    system_power,
    wait_for_process,
    wait_for_window_by_title,
)

logger = logging.getLogger("simba_intel.agent.desktop")

ALLOWED_APPLICATIONS: Dict[str, Dict[str, Any]] = {
    # Text editors & IDEs
    "notepad": {
        "cmd": "notepad.exe",
        "candidate_paths": [
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WindowsApps\notepad.exe"),
            os.path.expandvars(r"%SystemRoot%\System32\notepad.exe"),
            os.path.expandvars(r"%SystemRoot%\notepad.exe"),
        ],
        "protocol": "shell:appsFolder\\Microsoft.WindowsNotepad_8wekyb3d8bbwe!App",
        "window_title": "Notepad",
        "name": "Notepad",
    },
    "note pad": {
        "cmd": "notepad.exe",
        "candidate_paths": [
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WindowsApps\notepad.exe"),
            os.path.expandvars(r"%SystemRoot%\System32\notepad.exe"),
            os.path.expandvars(r"%SystemRoot%\notepad.exe"),
        ],
        "protocol": "shell:appsFolder\\Microsoft.WindowsNotepad_8wekyb3d8bbwe!App",
        "window_title": "Notepad",
        "name": "Notepad",
    },
    "text editor": {
        "cmd": "notepad.exe",
        "candidate_paths": [
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WindowsApps\notepad.exe"),
            os.path.expandvars(r"%SystemRoot%\System32\notepad.exe"),
            os.path.expandvars(r"%SystemRoot%\notepad.exe"),
        ],
        "protocol": "shell:appsFolder\\Microsoft.WindowsNotepad_8wekyb3d8bbwe!App",
        "window_title": "Notepad",
        "name": "Notepad",
    },
    "vscode": {
        "cmd": "code",
        "candidate_paths": [
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
            os.path.expandvars(r"%ProgramFiles%\Microsoft VS Code\Code.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft VS Code\Code.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\bin\code.cmd"),
        ],
        "window_title": "Visual Studio Code",
        "name": "Visual Studio Code",
    },
    "vs code": {
        "cmd": "code",
        "candidate_paths": [
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
            os.path.expandvars(r"%ProgramFiles%\Microsoft VS Code\Code.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft VS Code\Code.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\bin\code.cmd"),
        ],
        "window_title": "Visual Studio Code",
        "name": "Visual Studio Code",
    },
    "code": {
        "cmd": "code",
        "candidate_paths": [
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
            os.path.expandvars(r"%ProgramFiles%\Microsoft VS Code\Code.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft VS Code\Code.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\bin\code.cmd"),
        ],
        "window_title": "Visual Studio Code",
        "name": "Visual Studio Code",
    },
    "visual studio code": {
        "cmd": "code",
        "candidate_paths": [
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
            os.path.expandvars(r"%ProgramFiles%\Microsoft VS Code\Code.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft VS Code\Code.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\bin\code.cmd"),
        ],
        "window_title": "Visual Studio Code",
        "name": "Visual Studio Code",
    },

    # System Utilities
    "calculator": {
        "cmd": "calc.exe",
        "protocol": "calculator:",
        "candidate_paths": [os.path.expandvars(r"%SystemRoot%\System32\calc.exe")],
        "window_title": "Calculator",
        "name": "Calculator",
    },
    "calc": {
        "cmd": "calc.exe",
        "protocol": "calculator:",
        "candidate_paths": [os.path.expandvars(r"%SystemRoot%\System32\calc.exe")],
        "window_title": "Calculator",
        "name": "Calculator",
    },
    "windows calculator": {
        "cmd": "calc.exe",
        "protocol": "calculator:",
        "candidate_paths": [os.path.expandvars(r"%SystemRoot%\System32\calc.exe")],
        "window_title": "Calculator",
        "name": "Calculator",
    },
    "paint": {
        "cmd": "mspaint.exe",
        "candidate_paths": [os.path.expandvars(r"%SystemRoot%\System32\mspaint.exe")],
        "window_title": "Paint",
        "name": "Paint",
    },
    "mspaint": {
        "cmd": "mspaint.exe",
        "candidate_paths": [os.path.expandvars(r"%SystemRoot%\System32\mspaint.exe")],
        "window_title": "Paint",
        "name": "Paint",
    },
    "explorer": {
        "cmd": "explorer.exe",
        "candidate_paths": [os.path.expandvars(r"%SystemRoot%\explorer.exe")],
        "window_title": "File Explorer",
        "name": "File Explorer",
    },
    "file explorer": {
        "cmd": "explorer.exe",
        "candidate_paths": [os.path.expandvars(r"%SystemRoot%\explorer.exe")],
        "window_title": "File Explorer",
        "name": "File Explorer",
    },
    "files": {
        "cmd": "explorer.exe",
        "candidate_paths": [os.path.expandvars(r"%SystemRoot%\explorer.exe")],
        "window_title": "File Explorer",
        "name": "File Explorer",
    },
    "task manager": {
        "cmd": "taskmgr.exe",
        "candidate_paths": [os.path.expandvars(r"%SystemRoot%\System32\taskmgr.exe")],
        "window_title": "Task Manager",
        "name": "Task Manager",
    },
    "taskmgr": {
        "cmd": "taskmgr.exe",
        "candidate_paths": [os.path.expandvars(r"%SystemRoot%\System32\taskmgr.exe")],
        "window_title": "Task Manager",
        "name": "Task Manager",
    },
    "cmd": {
        "cmd": "cmd.exe",
        "candidate_paths": [os.path.expandvars(r"%SystemRoot%\System32\cmd.exe")],
        "window_title": "Command Prompt",
        "name": "Command Prompt",
    },
    "command prompt": {
        "cmd": "cmd.exe",
        "candidate_paths": [os.path.expandvars(r"%SystemRoot%\System32\cmd.exe")],
        "window_title": "Command Prompt",
        "name": "Command Prompt",
    },
    "terminal": {
        "cmd": "wt.exe",
        "candidate_paths": [
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WindowsApps\wt.exe"),
            os.path.expandvars(r"%SystemRoot%\System32\cmd.exe"),
        ],
        "window_title": "Terminal",
        "name": "Terminal",
    },
    "powershell": {
        "cmd": "powershell.exe",
        "candidate_paths": [
            os.path.expandvars(r"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"),
        ],
        "window_title": "PowerShell",
        "name": "PowerShell",
    },
    "settings": {
        "protocol": "ms-settings:",
        "cmd": "control.exe",
        "candidate_paths": [os.path.expandvars(r"%SystemRoot%\System32\control.exe")],
        "window_title": "Settings",
        "name": "Windows Settings",
    },
    "windows settings": {
        "protocol": "ms-settings:",
        "cmd": "control.exe",
        "candidate_paths": [os.path.expandvars(r"%SystemRoot%\System32\control.exe")],
        "window_title": "Settings",
        "name": "Windows Settings",
    },
    "control panel": {
        "cmd": "control.exe",
        "candidate_paths": [os.path.expandvars(r"%SystemRoot%\System32\control.exe")],
        "window_title": "Control Panel",
        "name": "Control Panel",
    },
    "snipping tool": {
        "cmd": "snippingtool.exe",
        "candidate_paths": [os.path.expandvars(r"%SystemRoot%\System32\snippingtool.exe")],
        "window_title": "Snipping Tool",
        "name": "Snipping Tool",
    },

    # Browsers & Media
    "chrome": {
        "cmd": "chrome.exe",
        "candidate_paths": [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ],
        "window_title": "Google Chrome",
        "name": "Google Chrome",
    },
    "google chrome": {
        "cmd": "chrome.exe",
        "candidate_paths": [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ],
        "window_title": "Google Chrome",
        "name": "Google Chrome",
    },
    "edge": {
        "cmd": "msedge.exe",
        "candidate_paths": [
            os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        ],
        "window_title": "Microsoft Edge",
        "name": "Microsoft Edge",
    },
    "microsoft edge": {
        "cmd": "msedge.exe",
        "candidate_paths": [
            os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        ],
        "window_title": "Microsoft Edge",
        "name": "Microsoft Edge",
    },
    "spotify": {
        "protocol": "spotify:",
        "cmd": "spotify.exe",
        "candidate_paths": [os.path.expandvars(r"%APPDATA%\Spotify\Spotify.exe")],
        "window_title": "Spotify",
        "name": "Spotify",
    },
}


def _resolve_app_config(application: str) -> Optional[Dict[str, Any]]:
    """Resolves application configuration from ALLOWED_APPLICATIONS."""
    app_key = application.lower().strip()
    config = ALLOWED_APPLICATIONS.get(app_key)
    if not config:
        for k, v in ALLOWED_APPLICATIONS.items():
            if k == app_key or (len(k) > 3 and k in app_key):
                config = v
                break
    return config


def _launch_app_candidate(cmd: str, candidate_paths: Optional[List[str]] = None, protocol: Optional[str] = None, args: Optional[List[str]] = None) -> bool:
    """Safely launches a Windows application in the active user desktop session."""
    launch_args = args or []

    if protocol and not launch_args:
        try:
            os.startfile(protocol)
            return True
        except Exception as e:
            logger.debug("Protocol %s launch failed: %s", protocol, e)

    if candidate_paths:
        for p in candidate_paths:
            if p and os.path.exists(p):
                try:
                    if launch_args:
                        subprocess.Popen([p] + launch_args, shell=False)
                    else:
                        os.startfile(p)
                    return True
                except Exception as e:
                    logger.debug("Launch %s failed: %s", p, e)
                    try:
                        subprocess.Popen([p] + launch_args, shell=False)
                        return True
                    except Exception:
                        pass

    resolved = shutil.which(cmd)
    if resolved and os.path.exists(resolved):
        try:
            if launch_args:
                if resolved.lower().endswith((".cmd", ".bat")):
                    subprocess.Popen(["cmd.exe", "/c", resolved] + launch_args, shell=False)
                else:
                    subprocess.Popen([resolved] + launch_args, shell=False)
            else:
                os.startfile(resolved)
            return True
        except Exception as e:
            logger.debug("Launch resolved %s failed: %s", resolved, e)
            try:
                subprocess.Popen([resolved] + launch_args, shell=False)
                return True
            except Exception:
                pass

    try:
        full_cmd = ["cmd.exe", "/c", "start", "", cmd] + launch_args
        subprocess.Popen(full_cmd, shell=False)
        return True
    except Exception as e:
        logger.debug("cmd start %s failed: %s", cmd, e)

    return False


def open_application(application: str, target_path: Optional[str] = None) -> ExecutionResult:
    """Launches an allowlisted Windows application and verifies its execution on the OS."""
    config = _resolve_app_config(application)
    if not config:
        allowed_list = sorted(list(set(v["name"] for v in ALLOWED_APPLICATIONS.values())))
        return ExecutionResult(
            success=False,
            tool="open_application",
            action="launch_application",
            target=application,
            error=f"Application '{application}' is not in the allowlist. Allowed applications: {', '.join(allowed_list)}",
            action_type="desktop_app",
            details={"verification": {"launch_executed": False, "process_detected": False, "window_detected": False}},
        )

    app_name = config["name"]
    cmd = config.get("cmd", "")
    protocol = config.get("protocol")
    candidate_paths = config.get("candidate_paths", [])
    window_title = config.get("window_title", app_name)

    proc_candidates = []
    if cmd:
        proc_candidates.append(cmd.replace(".exe", ""))
        proc_candidates.append(cmd)
    if candidate_paths:
        for p in candidate_paths:
            base = os.path.basename(p)
            proc_candidates.append(base)
            proc_candidates.append(base.replace(".exe", ""))

    launch_args = [target_path] if target_path else []

    try:
        launched = _launch_app_candidate(cmd, candidate_paths=candidate_paths, protocol=protocol, args=launch_args)
        if not launched:
            return ExecutionResult(
                success=False,
                tool="open_application",
                action="launch_application",
                target=app_name,
                error=f"Could not launch {app_name} on your computer.",
                details={"app": app_name, "verification": {"launch_executed": False, "process_detected": False, "window_detected": False}},
                action_type="desktop_app",
            )

        proc_detected = wait_for_process(proc_candidates, timeout=3.0)
        hwnd = wait_for_window_by_title(window_title, timeout=3.0)
        win_detected = hwnd is not None

        if hwnd:
            force_focus_window(hwnd)

        verification_data = {
            "launch_executed": True,
            "process_detected": proc_detected,
            "window_detected": win_detected,
            "hwnd": hwnd,
        }

        output_msg = f"Done — {app_name} is open."
        if target_path:
            output_msg = f"Done — {app_name} opened with '{os.path.basename(target_path)}'."

        return ExecutionResult(
            success=True,
            tool="open_application",
            action="launch_application",
            target=app_name,
            output=output_msg,
            details={"app": app_name, "command": cmd, "target_path": target_path, "verification": verification_data},
            action_type="desktop_app",
        )
    except Exception as e:
        logger.exception("Failed to open application %s: %s", app_name, e)
        return ExecutionResult(
            success=False,
            tool="open_application",
            action="launch_application",
            target=app_name,
            error=f"Could not open {app_name}: {str(e)}",
            details={"app": app_name, "verification": {"launch_executed": False, "process_detected": False, "window_detected": False}},
            action_type="desktop_app",
        )


def close_application(application: str) -> ExecutionResult:
    """Closes an active desktop application."""
    config = _resolve_app_config(application)
    target = config.get("window_title", application) if config else application
    proc_cmd = config.get("cmd", "") if config else ""
    app_name = config.get("name", application) if config else application

    closed = close_window_or_process(target)
    if not closed and proc_cmd:
        closed = close_window_or_process(proc_cmd)

    if closed:
        return ExecutionResult(
            success=True,
            tool="close_application",
            action="close_application",
            target=app_name,
            output=f"Closed {app_name}.",
            details={"app": app_name},
            action_type="desktop_app",
        )
    return ExecutionResult(
        success=False,
        tool="close_application",
        action="close_application",
        target=app_name,
        error=f"Could not find an active window or process for '{app_name}' to close.",
        details={"app": app_name},
        action_type="desktop_app",
    )


def switch_to_application(application: str) -> ExecutionResult:
    """Switches to and brings to foreground the target application window."""
    config = _resolve_app_config(application)
    target_title = config.get("window_title", application) if config else application
    app_name = config.get("name", application) if config else application

    hwnd = wait_for_window_by_title(target_title, timeout=3.0)
    if not hwnd and config:
        for cand in [config.get("cmd", "").replace(".exe", ""), app_name, application]:
            if cand:
                hwnd = find_window_flexible(cand)
                if hwnd:
                    break

    if not hwnd and config:
        # If not running, open it
        open_application(application)
        hwnd = wait_for_window_by_title(target_title, timeout=3.0)
        if not hwnd:
            for cand in [config.get("cmd", "").replace(".exe", ""), app_name, application]:
                if cand:
                    hwnd = find_window_flexible(cand)
                    if hwnd:
                        break

    if hwnd:
        ok = force_focus_window(hwnd)
        return ExecutionResult(
            success=ok,
            tool="switch_to_application",
            action="switch_to_application",
            target=app_name,
            output=f"Switched to {app_name}." if ok else f"Could not focus {app_name}.",
            details={"app": app_name, "hwnd": hwnd},
            action_type="window",
        )
    return ExecutionResult(
        success=False,
        tool="switch_to_application",
        action="switch_to_application",
        target=app_name,
        error=f"Could not find an active window for '{app_name}'.",
        action_type="window",
    )


def minimize_application(application: str) -> ExecutionResult:
    """Minimizes the target application window."""
    config = _resolve_app_config(application)
    target_title = config.get("window_title", application) if config else application
    app_name = config.get("name", application) if config else application

    ok, hwnd = minimize_window(target_title)
    if ok and hwnd:
        return ExecutionResult(
            success=True,
            tool="minimize_application",
            action="minimize_application",
            target=app_name,
            output=f"Minimized {app_name}.",
            details={"app": app_name, "hwnd": hwnd, "is_minimized": True},
            action_type="window",
        )
    return ExecutionResult(
        success=False,
        tool="minimize_application",
        action="minimize_application",
        target=app_name,
        error=f"Could not find or minimize window for '{app_name}'.",
        action_type="window",
    )


def maximize_application(application: str) -> ExecutionResult:
    """Maximizes the target application window."""
    config = _resolve_app_config(application)
    target_title = config.get("window_title", application) if config else application
    app_name = config.get("name", application) if config else application

    ok, hwnd = maximize_window(target_title)
    if ok and hwnd:
        return ExecutionResult(
            success=True,
            tool="maximize_application",
            action="maximize_application",
            target=app_name,
            output=f"Maximized {app_name}.",
            details={"app": app_name, "hwnd": hwnd, "is_maximized": True},
            action_type="window",
        )
    return ExecutionResult(
        success=False,
        tool="maximize_application",
        action="maximize_application",
        target=app_name,
        error=f"Could not find or maximize window for '{app_name}'.",
        action_type="window",
    )


def restore_application(application: str) -> ExecutionResult:
    """Restores the target application window from minimized/maximized state."""
    config = _resolve_app_config(application)
    target_title = config.get("window_title", application) if config else application
    app_name = config.get("name", application) if config else application

    ok, hwnd = restore_window(target_title)
    if ok and hwnd:
        return ExecutionResult(
            success=True,
            tool="restore_application",
            action="restore_application",
            target=app_name,
            output=f"Restored {app_name}.",
            details={"app": app_name, "hwnd": hwnd},
            action_type="window",
        )
    return ExecutionResult(
        success=False,
        tool="restore_application",
        action="restore_application",
        target=app_name,
        error=f"Could not find or restore window for '{app_name}'.",
        action_type="window",
    )


def type_text(text: str, target_app: Optional[str] = None) -> ExecutionResult:
    """Window-aware text typing using SendInput with verified window focus and truthful result checks."""
    if not text:
        return ExecutionResult(
            success=False,
            tool="type_text",
            action="type_text",
            target=target_app,
            error="Text content cannot be empty",
            action_type="type_text",
        )

    target_hwnd = None
    app_display_name = target_app or "Active Window"

    # 1. Window-aware focus: find or launch target application
    if target_app:
        config = _resolve_app_config(target_app)
        window_title = config["window_title"] if config else target_app
        app_display_name = config["name"] if config else target_app

        target_hwnd = find_window_by_title_substring(window_title)
        if not target_hwnd:
            open_application(target_app)
            target_hwnd = wait_for_window_by_title(window_title, timeout=6.0)

        if target_hwnd:
            force_focus_window(target_hwnd)
            time.sleep(0.3)
        else:
            return ExecutionResult(
                success=False,
                tool="type_text",
                action="type_text",
                target=app_display_name,
                error=f"Could not find or focus window for '{app_display_name}'.",
                action_type="type_text",
            )
    else:
        active_info = get_active_window_info()
        target_hwnd = active_info.get("hwnd")

    # 2. Dispatch text using Win32 SendInput Unicode keystrokes
    typed = send_unicode_text(text)

    # 3. Fallback: if SendInput was blocked, use clipboard paste with verified focus
    if not typed:
        set_clipboard_text(text)
        time.sleep(0.05)
        typed = paste_clipboard()

    time.sleep(0.1)

    if typed:
        preview = (text[:60] + "...") if len(text) > 60 else text
        return ExecutionResult(
            success=True,
            tool="type_text",
            action="type_text",
            target=app_display_name,
            output=f"Typed text into {app_display_name}.",
            details={"target_app": app_display_name, "text_preview": preview, "char_count": len(text), "hwnd": target_hwnd},
            action_type="type_text",
        )
    else:
        return ExecutionResult(
            success=False,
            tool="type_text",
            action="type_text",
            target=app_display_name,
            error=f"Failed to write text to {app_display_name}.",
            details={"target_app": app_display_name},
            action_type="type_text",
        )


def press_key(key: str) -> ExecutionResult:
    """Presses a single key."""
    success = send_key(key)
    return ExecutionResult(
        success=success,
        tool="press_key",
        action="press_key",
        target=key,
        output=f"Pressed key '{key}'." if success else f"Could not press key '{key}'.",
        error=None if success else f"Key '{key}' is not recognized or could not be simulated.",
        action_type="keyboard",
    )


def press_keys_tool(keys: List[str]) -> ExecutionResult:
    """Presses multiple keys in sequence."""
    success = send_keys_sequence(keys)
    keys_str = ", ".join(keys)
    return ExecutionResult(
        success=success,
        tool="press_keys",
        action="press_keys",
        target=keys_str,
        output=f"Pressed key sequence: {keys_str}." if success else f"Failed to press key sequence: {keys_str}.",
        action_type="keyboard",
    )


def hotkey(keys: Union[List[str], str]) -> ExecutionResult:
    """Presses a combination of keys (e.g. 'ctrl+s' or ['ctrl', 's'])."""
    success = send_hotkey(keys)
    if isinstance(keys, list):
        combo_str = " + ".join(k.upper() for k in keys)
    else:
        combo_str = str(keys).upper()
    return ExecutionResult(
        success=success,
        tool="hotkey",
        action="hotkey",
        target=combo_str,
        output=f"Sent hotkey {combo_str}." if success else f"Could not send hotkey {combo_str}.",
        error=None if success else f"Hotkey '{combo_str}' could not be simulated.",
        action_type="keyboard",
    )


def click_mouse_tool(button: str = "left", x: Optional[int] = None, y: Optional[int] = None) -> ExecutionResult:
    """Clicks mouse button ('left', 'right', 'middle'), optionally at (x, y)."""
    ok = mouse_click(button, x=x, y=y)
    loc_str = f" at ({x}, {y})" if x is not None and y is not None else ""
    return ExecutionResult(
        success=ok,
        tool="click",
        action=f"mouse_{button}_click",
        target=f"({x}, {y})" if x is not None else button,
        output=f"Mouse {button} click performed{loc_str}." if ok else f"Mouse {button} click failed.",
        action_type="mouse",
    )


def double_click_mouse_tool(button: str = "left", x: Optional[int] = None, y: Optional[int] = None) -> ExecutionResult:
    """Double-clicks mouse button, optionally at (x, y)."""
    ok = mouse_double_click(button, x=x, y=y)
    loc_str = f" at ({x}, {y})" if x is not None and y is not None else ""
    return ExecutionResult(
        success=ok,
        tool="double_click",
        action="mouse_double_click",
        target=f"({x}, {y})" if x is not None else button,
        output=f"Mouse double-click performed{loc_str}." if ok else "Mouse double-click failed.",
        action_type="mouse",
    )


def right_click_mouse_tool(x: Optional[int] = None, y: Optional[int] = None) -> ExecutionResult:
    """Right-clicks mouse, optionally at (x, y)."""
    ok = mouse_right_click(x=x, y=y)
    loc_str = f" at ({x}, {y})" if x is not None and y is not None else ""
    return ExecutionResult(
        success=ok,
        tool="right_click",
        action="mouse_right_click",
        target=f"({x}, {y})" if x is not None else "right",
        output=f"Mouse right-click performed{loc_str}." if ok else "Mouse right-click failed.",
        action_type="mouse",
    )


def move_mouse_tool(x: int, y: int) -> ExecutionResult:
    """Moves mouse cursor to pixel coordinates (x, y)."""
    ok = mouse_move(x, y)
    curr_x, curr_y = get_mouse_position()
    return ExecutionResult(
        success=ok,
        tool="move_mouse",
        action="move_mouse",
        target=f"({x}, {y})",
        output=f"Moved mouse to ({x}, {y})." if ok else f"Failed to move mouse to ({x}, {y}).",
        details={"x": x, "y": y, "actual_pos": (curr_x, curr_y)},
        action_type="mouse",
    )


def scroll_mouse_tool(clicks: int = 3, direction: str = "down") -> ExecutionResult:
    """Scrolls mouse wheel up or down."""
    ok = mouse_scroll(clicks=clicks, direction=direction)
    dir_clean = direction.lower().strip()
    return ExecutionResult(
        success=ok,
        tool="scroll",
        action="mouse_scroll",
        target=f"{dir_clean} {abs(clicks)}",
        output=f"Scrolled mouse {dir_clean} by {abs(clicks)} click(s)." if ok else "Mouse scroll failed.",
        details={"clicks": abs(clicks), "direction": dir_clean},
        action_type="mouse",
    )


def open_folder(folder_name_or_path: str = "downloads") -> ExecutionResult:
    """Opens a user directory (Downloads, Documents, Desktop, Pictures, etc.) in File Explorer."""
    raw = folder_name_or_path.lower().strip()
    userprofile = os.environ.get("USERPROFILE", os.path.expanduser("~"))

    standard_map = {
        "downloads": os.path.join(userprofile, "Downloads"),
        "download": os.path.join(userprofile, "Downloads"),
        "documents": os.path.join(userprofile, "Documents"),
        "document": os.path.join(userprofile, "Documents"),
        "my documents": os.path.join(userprofile, "Documents"),
        "desktop": os.path.join(userprofile, "Desktop"),
        "pictures": os.path.join(userprofile, "Pictures"),
        "photos": os.path.join(userprofile, "Pictures"),
        "images": os.path.join(userprofile, "Pictures"),
        "videos": os.path.join(userprofile, "Videos"),
        "movies": os.path.join(userprofile, "Videos"),
        "music": os.path.join(userprofile, "Music"),
        "home": userprofile,
        "user": userprofile,
        "userprofile": userprofile,
    }

    target_path = standard_map.get(raw)
    display_name = raw.capitalize()

    if not target_path:
        if os.path.isabs(folder_name_or_path):
            target_path = folder_name_or_path
            display_name = os.path.basename(folder_name_or_path) or folder_name_or_path
        else:
            cand = os.path.join(userprofile, folder_name_or_path)
            if os.path.exists(cand):
                target_path = cand
                display_name = folder_name_or_path

    if not target_path or not os.path.exists(target_path):
        return ExecutionResult(
            success=False,
            tool="open_folder",
            action="open_folder",
            target=folder_name_or_path,
            error=f"Folder '{folder_name_or_path}' could not be found.",
            action_type="open_folder",
        )

    try:
        os.startfile(target_path)
        return ExecutionResult(
            success=True,
            tool="open_folder",
            action="open_folder",
            target=display_name,
            output=f"Done — {display_name} folder is open.",
            details={"folder": display_name, "path": target_path},
            action_type="open_folder",
        )
    except Exception as e:
        logger.exception("Failed to open folder %s: %s", target_path, e)
        return ExecutionResult(
            success=False,
            tool="open_folder",
            action="open_folder",
            target=display_name,
            error=f"Failed to open folder: {str(e)}",
            details={"path": target_path},
            action_type="open_folder",
        )


def open_file(path: str) -> ExecutionResult:
    """Launches a file with its default Windows application."""
    userprofile = os.environ.get("USERPROFILE", os.path.expanduser("~"))
    desktop = os.path.join(userprofile, "Desktop")
    downloads = os.path.join(userprofile, "Downloads")
    documents = os.path.join(userprofile, "Documents")

    clean = path.strip().strip('"\'')
    candidates = [
        clean,
        os.path.join(desktop, clean),
        os.path.join(downloads, clean),
        os.path.join(documents, clean),
        os.path.join(userprofile, clean),
    ]

    target = None
    for cand in candidates:
        if os.path.exists(cand):
            target = cand
            break

    if not target:
        return ExecutionResult(
            success=False,
            tool="open_file",
            action="open_file",
            target=clean,
            error=f"File '{clean}' was not found on your system.",
            action_type="open_file",
        )

    try:
        os.startfile(target)
        return ExecutionResult(
            success=True,
            tool="open_file",
            action="open_file",
            target=os.path.basename(target),
            output=f"Opened '{os.path.basename(target)}'.",
            details={"path": target},
            action_type="open_file",
        )
    except Exception as e:
        return ExecutionResult(
            success=False,
            tool="open_file",
            action="open_file",
            target=clean,
            error=f"Could not open file: {str(e)}",
            details={"path": target},
            action_type="open_file",
        )


def clipboard_read() -> ExecutionResult:
    """Reads text from Windows clipboard."""
    text = get_clipboard_text()
    return ExecutionResult(
        success=True,
        tool="clipboard_read",
        action="read_clipboard",
        output=text if text else "(Clipboard is empty)",
        details={"char_count": len(text)},
        action_type="clipboard",
    )


def clipboard_write(text: str) -> ExecutionResult:
    """Copies text to Windows clipboard."""
    ok = set_clipboard_text(text)
    return ExecutionResult(
        success=ok,
        tool="clipboard_write",
        action="write_clipboard",
        output="Copied text to clipboard." if ok else "Failed to set clipboard text.",
        details={"char_count": len(text)},
        action_type="clipboard",
    )


def window_focus(title: str) -> ExecutionResult:
    """Brings a window matching title to the foreground with force_focus."""
    return switch_to_application(title)


def window_close(title: str) -> ExecutionResult:
    """Closes a window matching title."""
    return close_application(title)


def get_active_window() -> ExecutionResult:
    """Gets title and process of active foreground window."""
    info = get_active_window_info()
    return ExecutionResult(
        success=True,
        tool="read_active_window",
        action="read_active_window",
        target=info["title"],
        output=f"Active window: {info['title']} ({info['process_name']})",
        details=info,
        action_type="window",
    )


def get_system_information() -> ExecutionResult:
    """Retrieves safe system telemetry."""
    telemetry = get_system_telemetry()
    summary = (
        f"OS: {telemetry['os']} {telemetry['os_release']} ({telemetry['architecture']}) | "
        f"CPU: {telemetry['cpu_percent']}% | RAM: {telemetry['ram_percent']}% "
        f"({telemetry['ram_used_gb']}GB / {telemetry['ram_total_gb']}GB)"
    )
    return ExecutionResult(
        success=True,
        tool="get_system_information",
        action="get_system_information",
        output=summary,
        details=telemetry,
        action_type="system_info",
    )


def empty_recycle_bin(confirmed: bool = False) -> ExecutionResult:
    """Empties the Windows Recycle Bin. Requires explicit confirmation."""
    if not confirmed:
        return ExecutionResult(
            success=False,
            tool="empty_recycle_bin",
            action="empty_recycle_bin",
            is_sensitive=True,
            requires_confirmation=True,
            risk_level=RiskLevel.DANGEROUS.value,
            confirmation_prompt="Permanently empty the Windows Recycle Bin?",
            sensitive_action_data={"tool_name": "empty_recycle_bin", "args": {"confirmed": True}},
            output="Pending confirmation to empty Recycle Bin.",
            action_type="system_power",
        )

    ok = empty_windows_recycle_bin(confirm=True)
    return ExecutionResult(
        success=ok,
        tool="empty_recycle_bin",
        action="empty_recycle_bin",
        output="Recycle Bin emptied successfully." if ok else "Failed to empty Recycle Bin.",
        action_type="system_power",
        risk_level=RiskLevel.DANGEROUS.value,
    )


def system_power_action(action: str = "lock", confirmed: bool = False) -> ExecutionResult:
    """Executes Windows system power operations (lock, sleep, restart, shutdown). Requires confirmation for shutdown/restart."""
    act = action.lower().strip()
    is_dangerous = act in ["shutdown", "restart"]

    if is_dangerous and not confirmed:
        action_label = "Shut down" if act == "shutdown" else "Restart"
        return ExecutionResult(
            success=False,
            tool="system_power_action",
            action=f"system_{act}",
            target=act,
            is_sensitive=True,
            requires_confirmation=True,
            risk_level=RiskLevel.DANGEROUS.value,
            confirmation_prompt=f"{action_label} your Windows PC now?",
            sensitive_action_data={"tool_name": "system_power_action", "args": {"action": act, "confirmed": True}},
            output=f"Pending confirmation to {act} PC.",
            action_type="system_power",
        )

    ok = system_power(act)
    return ExecutionResult(
        success=ok,
        tool="system_power_action",
        action=f"system_{act}",
        target=act,
        output=f"System {act} initiated." if ok else f"Failed to execute system {act}.",
        action_type="system_power",
        risk_level=RiskLevel.DANGEROUS.value if is_dangerous else RiskLevel.SAFE.value,
    )


# -------------------------------------------------------------------------
# Register All Tools into global_tool_registry
# -------------------------------------------------------------------------

global_tool_registry.register(
    Tool(
        name="open_application",
        description="Opens a safe, allowlisted Windows application (e.g. Notepad, Calculator, VS Code, Paint, File Explorer, Task Manager, Chrome, Edge, Spotify).",
        parameters=[
            ToolParameter(name="application", type="string", description="The name of the application to open.", required=True),
            ToolParameter(name="target_path", type="string", description="Optional file or folder path to open in the application.", required=False, default=None),
        ],
        func=open_application,
        action_type="desktop_app",
        risk_level=RiskLevel.SAFE.value,
        timeout_seconds=10.0,
    )
)

global_tool_registry.register(
    Tool(
        name="launch_application",
        description="Alias for open_application. Launches a Windows desktop application.",
        parameters=[
            ToolParameter(name="application", type="string", description="The name of the application to open.", required=True),
            ToolParameter(name="target_path", type="string", description="Optional path.", required=False, default=None),
        ],
        func=open_application,
        action_type="desktop_app",
        risk_level=RiskLevel.SAFE.value,
        timeout_seconds=10.0,
    )
)

global_tool_registry.register(
    Tool(
        name="close_application",
        description="Closes an active Windows application window or process.",
        parameters=[
            ToolParameter(name="application", type="string", description="Name of the application or window title to close.", required=True),
        ],
        func=close_application,
        action_type="desktop_app",
        risk_level=RiskLevel.SAFE.value,
    )
)

global_tool_registry.register(
    Tool(
        name="focus_application",
        description="Brings an application window to the active foreground.",
        parameters=[
            ToolParameter(name="title", type="string", description="Application name or window title to focus.", required=True),
        ],
        func=window_focus,
        action_type="window",
        risk_level=RiskLevel.SAFE.value,
    )
)

global_tool_registry.register(
    Tool(
        name="switch_to_application",
        description="Switches to and focuses a specific running application window.",
        parameters=[
            ToolParameter(name="application", type="string", description="Name of the application to switch to.", required=True),
        ],
        func=switch_to_application,
        action_type="window",
        risk_level=RiskLevel.SAFE.value,
    )
)

global_tool_registry.register(
    Tool(
        name="minimize_application",
        description="Minimizes an application window to the taskbar.",
        parameters=[
            ToolParameter(name="application", type="string", description="Name of the application or window to minimize.", required=True),
        ],
        func=minimize_application,
        action_type="window",
        risk_level=RiskLevel.SAFE.value,
    )
)

global_tool_registry.register(
    Tool(
        name="maximize_application",
        description="Maximizes an application window to fill the screen.",
        parameters=[
            ToolParameter(name="application", type="string", description="Name of the application or window to maximize.", required=True),
        ],
        func=maximize_application,
        action_type="window",
        risk_level=RiskLevel.SAFE.value,
    )
)

global_tool_registry.register(
    Tool(
        name="restore_application",
        description="Restores an application window from minimized or maximized state.",
        parameters=[
            ToolParameter(name="application", type="string", description="Name of the application or window to restore.", required=True),
        ],
        func=restore_application,
        action_type="window",
        risk_level=RiskLevel.SAFE.value,
    )
)

global_tool_registry.register(
    Tool(
        name="type_text",
        description="Types text or code into the active or specified application window using native Windows SendInput with verified focus.",
        parameters=[
            ToolParameter(name="text", type="string", description="The text or code to write.", required=True),
            ToolParameter(name="target_app", type="string", description="Optional application to focus before typing (e.g. 'notepad', 'vscode').", required=False, default=None),
        ],
        func=type_text,
        action_type="type_text",
        risk_level=RiskLevel.SAFE.value,
        timeout_seconds=10.0,
    )
)

global_tool_registry.register(
    Tool(
        name="press_key",
        description="Simulates pressing a single key (e.g. 'enter', 'tab', 'escape', 'space', 'backspace').",
        parameters=[
            ToolParameter(name="key", type="string", description="Key name to press.", required=True),
        ],
        func=press_key,
        action_type="keyboard",
        risk_level=RiskLevel.SAFE.value,
    )
)

global_tool_registry.register(
    Tool(
        name="press_keys",
        description="Simulates pressing multiple keys sequentially in order.",
        parameters=[
            ToolParameter(name="keys", type="array", description="List of key names.", required=True),
        ],
        func=press_keys_tool,
        action_type="keyboard",
        risk_level=RiskLevel.SAFE.value,
    )
)

global_tool_registry.register(
    Tool(
        name="hotkey",
        description="Simulates pressing a hotkey combination (e.g. 'ctrl+s', 'ctrl+c', 'ctrl+v', ['alt', 'tab']).",
        parameters=[
            ToolParameter(name="keys", type="string", description="Hotkey combination string or list (e.g. 'ctrl+s').", required=True),
        ],
        func=hotkey,
        action_type="keyboard",
        risk_level=RiskLevel.SAFE.value,
    )
)

global_tool_registry.register(
    Tool(
        name="click",
        description="Simulates a mouse click (left, right, or middle) at current position or optional (x, y) coordinates.",
        parameters=[
            ToolParameter(name="button", type="string", description="Mouse button ('left', 'right', 'middle').", required=False, default="left"),
            ToolParameter(name="x", type="integer", description="Optional X screen coordinate.", required=False, default=None),
            ToolParameter(name="y", type="integer", description="Optional Y screen coordinate.", required=False, default=None),
        ],
        func=click_mouse_tool,
        action_type="mouse",
        risk_level=RiskLevel.SAFE.value,
    )
)

global_tool_registry.register(
    Tool(
        name="double_click",
        description="Simulates mouse double-click at current position or optional (x, y) coordinates.",
        parameters=[
            ToolParameter(name="button", type="string", description="Mouse button.", required=False, default="left"),
            ToolParameter(name="x", type="integer", description="Optional X coordinate.", required=False, default=None),
            ToolParameter(name="y", type="integer", description="Optional Y coordinate.", required=False, default=None),
        ],
        func=double_click_mouse_tool,
        action_type="mouse",
        risk_level=RiskLevel.SAFE.value,
    )
)

global_tool_registry.register(
    Tool(
        name="right_click",
        description="Simulates mouse right-click at current position or optional (x, y) coordinates.",
        parameters=[
            ToolParameter(name="x", type="integer", description="Optional X coordinate.", required=False, default=None),
            ToolParameter(name="y", type="integer", description="Optional Y coordinate.", required=False, default=None),
        ],
        func=right_click_mouse_tool,
        action_type="mouse",
        risk_level=RiskLevel.SAFE.value,
    )
)

global_tool_registry.register(
    Tool(
        name="move_mouse",
        description="Moves mouse cursor to pixel coordinates (x, y).",
        parameters=[
            ToolParameter(name="x", type="integer", description="X screen coordinate.", required=True),
            ToolParameter(name="y", type="integer", description="Y screen coordinate.", required=True),
        ],
        func=move_mouse_tool,
        action_type="mouse",
        risk_level=RiskLevel.SAFE.value,
    )
)

global_tool_registry.register(
    Tool(
        name="scroll",
        description="Scrolls mouse wheel up or down by a given amount of clicks.",
        parameters=[
            ToolParameter(name="clicks", type="integer", description="Number of scroll steps.", required=False, default=3),
            ToolParameter(name="direction", type="string", description="Direction ('up' or 'down').", required=False, default="down"),
        ],
        func=scroll_mouse_tool,
        action_type="mouse",
        risk_level=RiskLevel.SAFE.value,
    )
)

global_tool_registry.register(
    Tool(
        name="open_folder",
        description="Opens a user directory in Windows File Explorer.",
        parameters=[
            ToolParameter(name="folder_name_or_path", type="string", description="Name of the folder.", required=False, default="downloads"),
        ],
        func=open_folder,
        action_type="open_folder",
        risk_level=RiskLevel.SAFE.value,
    )
)

global_tool_registry.register(
    Tool(
        name="open_file",
        description="Opens a local file in its default Windows associated program.",
        parameters=[
            ToolParameter(name="path", type="string", description="Path or filename to open.", required=True),
        ],
        func=open_file,
        action_type="open_file",
        risk_level=RiskLevel.SAFE.value,
    )
)

global_tool_registry.register(
    Tool(
        name="clipboard_read",
        description="Reads the current text on the Windows clipboard.",
        parameters=[],
        func=clipboard_read,
        action_type="clipboard",
        risk_level=RiskLevel.SAFE.value,
    )
)

global_tool_registry.register(
    Tool(
        name="clipboard_write",
        description="Writes text to the Windows clipboard.",
        parameters=[
            ToolParameter(name="text", type="string", description="Text to copy.", required=True),
        ],
        func=clipboard_write,
        action_type="clipboard",
        risk_level=RiskLevel.SAFE.value,
    )
)

global_tool_registry.register(
    Tool(
        name="read_active_window",
        description="Returns the active foreground window title, process name, and HWND.",
        parameters=[],
        func=get_active_window,
        action_type="window",
        risk_level=RiskLevel.SAFE.value,
    )
)

global_tool_registry.register(
    Tool(
        name="get_system_information",
        description="Returns safe system performance and telemetry information (CPU, RAM, OS, disk).",
        parameters=[],
        func=get_system_information,
        action_type="system_info",
        risk_level=RiskLevel.SAFE.value,
    )
)

global_tool_registry.register(
    Tool(
        name="empty_recycle_bin",
        description="Empties the Windows Recycle Bin. Requires explicit confirmation.",
        parameters=[
            ToolParameter(name="confirmed", type="boolean", description="Whether user explicitly confirmed.", required=False, default=False),
        ],
        func=empty_recycle_bin,
        action_type="system_power",
        risk_level=RiskLevel.DANGEROUS.value,
        is_sensitive=True,
    )
)

global_tool_registry.register(
    Tool(
        name="system_power_action",
        description="Controls Windows system power (lock, sleep, restart, shutdown). Shutdown/restart require explicit confirmation.",
        parameters=[
            ToolParameter(name="action", type="string", description="Power action ('lock', 'sleep', 'restart', 'shutdown').", required=False, default="lock"),
            ToolParameter(name="confirmed", type="boolean", description="Whether user explicitly confirmed.", required=False, default=False),
        ],
        func=system_power_action,
        action_type="system_power",
        risk_level=RiskLevel.DANGEROUS.value,
        is_sensitive=True,
    )
)
