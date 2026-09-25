#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apps.py -- start and stop the acquisition programs a session needs.

NIRStar hangs on quit often enough that Task Manager became part of the
protocol. This gives the control panel the same two operations, over a fixed
list of programs from configs/settings.json -> "applications":

    "applications": {
        "NIRStar": {
            "window": "NIRx NIRStar",            partial window title
            "exe":    "C:\\\\NIRx\\\\NIRStar.exe",     what to launch
            "image":  "NIRStar.exe"              process name, for the case
        }                                        where the window is gone but
    }                                            the process is not

Only programs listed there can be launched or killed -- there is no way to
name an arbitrary process from the UI, deliberately.

Killing is two-stage: a polite taskkill first, then /F /T if the process is
still there a moment later. A hung GUI ignores the polite one, which is
precisely the case this exists for.
"""

import os
import subprocess
import sys
import time

__all__ = ['registry', 'status', 'launch', 'kill', 'kill_supported',
           'NOT_RUNNING', 'RUNNING', 'NOT_RESPONDING']

NOT_RUNNING    = 'not running'
RUNNING        = 'running'
NOT_RESPONDING = 'not responding'

_NO_WINDOW = 0x08000000 if os.name == 'nt' else 0

try:
    import win32gui
    import win32process
    _WIN32 = True
except Exception:
    _WIN32 = False


def kill_supported():
    """Stopping a program by window or image name is a Windows affair."""
    return os.name == 'nt'


def registry(settings):
    """Ordered {name: spec} from settings, skipping malformed entries."""
    apps = (settings or {}).get('applications', {}) or {}
    clean = {}
    for name, spec in apps.items():
        if isinstance(spec, dict):
            clean[str(name)] = {
                'window': str(spec.get('window', '') or ''),
                'exe':    str(spec.get('exe', '') or ''),
                'image':  str(spec.get('image', '') or ''),
                'args':   spec.get('args') or [],
            }
    return clean


# ---- finding it -------------------------------------------------------------- #
def _find_window(fragment):
    if not (_WIN32 and fragment):
        return None
    found = []

    def visit(hwnd, sink):
        try:
            if fragment in win32gui.GetWindowText(hwnd):
                sink.append(hwnd)
        except Exception:
            pass
        return True

    try:
        win32gui.EnumWindows(visit, found)
    except Exception:
        return None
    return found[0] if found else None


def _is_hung(hwnd):
    """True when Windows itself considers the window unresponsive."""
    if not hwnd:
        return False
    try:
        import ctypes
        return bool(ctypes.windll.user32.IsHungAppWindow(hwnd))
    except Exception:
        return False


def _pid_for_window(hwnd):
    if not (_WIN32 and hwnd):
        return None
    try:
        _thread, pid = win32process.GetWindowThreadProcessId(hwnd)
        return int(pid) or None
    except Exception:
        return None


def _image_running(image):
    """Fallback for a process whose window has already gone."""
    if not (image and os.name == 'nt'):
        return False
    try:
        done = subprocess.run(['tasklist', '/FI', f'IMAGENAME eq {image}', '/NH'],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              timeout=5, creationflags=_NO_WINDOW)
    except Exception:
        return False
    return image.lower() in done.stdout.decode('utf-8', 'replace').lower()


def status(spec):
    """{'state', 'pid', 'hwnd'} for one application spec."""
    hwnd = _find_window(spec.get('window'))
    if hwnd:
        return {'state': NOT_RESPONDING if _is_hung(hwnd) else RUNNING,
                'pid': _pid_for_window(hwnd), 'hwnd': hwnd}
    if _image_running(spec.get('image')):
        return {'state': RUNNING, 'pid': None, 'hwnd': None}
    return {'state': NOT_RUNNING, 'pid': None, 'hwnd': None}


# ---- starting it ------------------------------------------------------------- #
def launch(spec):
    """(ok, message). Uses the same opener as Play Video Instructions."""
    exe = spec.get('exe')
    if not exe:
        return False, "no exe configured (add it to configs/settings.local.json)"
    if not os.path.exists(exe) and os.name == 'nt':
        return False, f"not found: {exe}"
    try:
        args = list(spec.get('args') or [])
        if sys.platform == 'win32' and not args:
            os.startfile(exe)                    # honours shortcuts and associations
        elif sys.platform == 'win32':
            subprocess.Popen([exe] + args, close_fds=True)
        else:
            opener = 'open' if sys.platform == 'darwin' else 'xdg-open'
            subprocess.Popen([opener, exe] + args, close_fds=True)
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    return True, f"launched {os.path.basename(exe)}"


# ---- stopping it ------------------------------------------------------------- #
def _taskkill(args):
    try:
        done = subprocess.run(['taskkill'] + args, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=15,
                              creationflags=_NO_WINDOW)
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    text = done.stdout.decode('utf-8', 'replace').strip().splitlines()
    return done.returncode == 0, (text[-1] if text else f"exit {done.returncode}")


def kill(spec, grace=2.5):
    """Ask the program to close, then force it. (ok, message)."""
    if not kill_supported():
        return False, "stopping programs this way only works on Windows"

    state = status(spec)
    if state['state'] == NOT_RUNNING:
        return False, "not running"

    pid = state['pid']
    target = ['/PID', str(pid)] if pid else (
        ['/IM', spec['image']] if spec.get('image') else None)
    if target is None:
        return False, ("no PID and no image name configured; add \"image\" to "
                       "this app in settings")

    _taskkill(target)                      # polite: a hung app will ignore this
    deadline = time.time() + grace
    while time.time() < deadline:
        if status(spec)['state'] == NOT_RUNNING:
            return True, "closed"
        time.sleep(0.25)

    ok, message = _taskkill(target + ['/F', '/T'])
    if status(spec)['state'] == NOT_RUNNING:
        return True, "force-killed"
    return ok, f"still running after force kill ({message})"
