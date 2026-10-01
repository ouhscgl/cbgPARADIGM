#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
trigger_probe.py -- find out, on the machine that actually has the problem,
why Windows dings when a trigger fires.

Run this on the acquisition PC with Aurora / g.Recorder / NIRStar open exactly
as they are during a session, but with no participant. It exercises only the
window-focus and simulated-keystroke path -- no stimuli, no LSL, no data files.

The question it answers: the ding heard on every LEFT/RIGHT cue in
fingertapping comes from `trigger.send()`, which is called immediately before
each spoken cue. Inside it, the old focus code injected a real ALT keystroke
into whichever window had focus. On a windowed app with a menu bar (Aurora,
g.Recorder) ALT opens the menu bar; if the SetForegroundWindow that follows is
then refused -- Windows refuses it routinely, and always for a hidden window --
the trigger key is still injected globally, arrives at that menu-mode window as
a menu mnemonic, finds no '8' or F8 to match, and Windows plays the default
beep. So the beep is the audible half of a trigger delivered to the wrong
window.

Three things to try, in this order:

  1  python auxfunc/trigger_probe.py --list-windows
     Confirm the "window" strings in profiles.json match real, visible windows.
     A profile pointing at a hidden helper window can never be focused.

  2  python auxfunc/trigger_probe.py --profile fingertapping --compare
     Six focus attempts with the legacy ALT method, then six with the quiet
     one, announcing each phase. Listen. If the dings stop when it switches to
     "quiet", the ALT injection was the cause and the fix is already in place.

  3  python auxfunc/trigger_probe.py --profile fingertapping --compare --keys
     Same, but actually injects the trigger keys, so it reproduces the full
     path. This writes real markers into whatever recording is open, so only
     run it with no participant.

Everything it observes also goes to a log file under logs/.
"""

import argparse
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auxfunc import crashlog
from auxfunc.config import load_config
from auxfunc import paradigm_utils as pu


def list_windows(fragment=None):
    """Every top-level window with a title, so profile strings can be checked."""
    if not pu._WIN32_AVAILABLE:
        print("This probe only means anything on Windows.")
        return 1
    import win32gui
    rows = []

    def visit(hwnd, sink):
        try:
            title = win32gui.GetWindowText(hwnd)
        except Exception:
            return True
        if not title:
            return True
        if fragment and fragment.lower() not in title.lower():
            return True
        try:
            visible = bool(win32gui.IsWindowVisible(hwnd))
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            size = f"{right-left}x{bottom-top}"
            owned = bool(win32gui.GetWindow(hwnd, 4))      # GW_OWNER
        except Exception:
            visible, size, owned = False, '?', False
        sink.append((hwnd, title, visible, size, owned))
        return True

    win32gui.EnumWindows(visit, rows)
    rows.sort(key=lambda r: (not r[2], r[1].lower()))
    print(f"{'hwnd':>10}  {'vis':<4} {'owned':<6} {'size':<12} title")
    print('-' * 100)
    for hwnd, title, visible, size, owned in rows:
        print(f"{hwnd:>10}  {'yes' if visible else 'NO':<4} "
              f"{'yes' if owned else '-':<6} {size:<12} {title[:60]}")
    print(f"\n{len(rows)} windows. A profile's \"window\" value must be a substring "
          f"of one of the rows marked vis=yes.")
    return 0


def keystroke_programs(profile_key):
    profiles = load_config('profiles.json')
    if profile_key not in profiles:
        print(f"No profile '{profile_key}'. Available: {', '.join(sorted(profiles))}")
        return None
    programs = profiles[profile_key].get('keystroke_programs', []) or []
    # Only the keystroke path can produce this beep, and probing an LSL program
    # would push markers at a recording for no reason.
    return [p for p in programs
            if str(p.get('transport', 'keystroke')).lower() == 'keystroke']


def probe_round(programs, method, send_keys, log):
    """One pass over every program. Returns a list of result dicts."""
    import win32con
    from win32api import keybd_event

    pu.configure_triggers({'focus_method': method, 'alt_fallback': False,
                           'verify_focus': True})
    results = []
    for prog in programs:
        window = prog.get('window', '')
        key = str(prog.get('key', 'F8')).upper()
        candidates = pu.window_candidates(window)
        hwnd = candidates[0][0] if candidates else None
        before = pu._window_title(pu._foreground_hwnd())

        started = time.perf_counter()
        focused = pu._ensure_focus(hwnd, log=log) if hwnd else False
        elapsed = (time.perf_counter() - started) * 1000.0
        after = pu._window_title(pu._foreground_hwnd())

        sent = False
        if send_keys and hwnd:
            vk = pu.VK_MAP.get(key)
            if vk is not None:
                try:
                    keybd_event(vk, 0, 0, 0)
                    time.sleep(0.01)
                    keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
                    sent = True
                except Exception as exc:
                    log.warn(f"probe: keystroke to {window} failed ({exc})")

        row = {'window': window, 'key': key, 'hwnd': hwnd, 'method': method,
               'candidates': len(candidates), 'focused': focused,
               'ms': elapsed, 'before': before, 'after': after, 'sent': sent}
        results.append(row)

        state = 'OK    ' if focused else ('no window' if hwnd is None else 'FAILED')
        log.log(f"[{method:<5}] {window:<22} hwnd {str(hwnd or '-'):<10} "
                f"focus={state}  {elapsed:6.0f}ms  "
                f"fg '{before[:28]}' -> '{after[:28]}'"
                f"{'  key ' + key if sent else ''}")
        time.sleep(0.25)
    return results


def summarise(rows):
    print()
    print(f"{'method':<7} {'window':<22} {'tries':>5} {'focused':>8} {'failed':>7} {'mean ms':>8}")
    print('-' * 64)
    keys = []
    for row in rows:
        entry = (row['method'], row['window'])
        if entry not in keys:
            keys.append(entry)
    for method, window in keys:
        group = [r for r in rows if r['method'] == method and r['window'] == window]
        ok = sum(1 for r in group if r['focused'])
        mean = statistics.mean(r['ms'] for r in group)
        print(f"{method:<7} {window:<22} {len(group):>5} {ok:>8} "
              f"{len(group)-ok:>7} {mean:>8.0f}")

    failures = [r for r in rows if not r['focused'] and r['hwnd']]
    print()
    if failures:
        print("Focus failed at least once. With the legacy 'alt' method that is "
              "exactly the case that dings: ALT had already opened the menu bar "
              "of the window that kept focus, and the trigger key then hits it "
              "as a menu mnemonic. It also means the marker went to the wrong "
              "window.")
        by_method = {}
        for row in failures:
            by_method.setdefault(row['method'], set()).add(row['window'])
        for method in sorted(by_method):
            print(f"  {method:<6} failed for: {', '.join(sorted(by_method[method]))}")
    else:
        print("Focus landed on every attempt. If you still heard a ding, note "
              "which phase it happened in and re-run with --keys to test the "
              "keystroke half.")
    missing = sorted({r['window'] for r in rows if not r['hwnd']})
    if missing:
        print(f"  never found a window for: {', '.join(missing)} "
              f"-- check --list-windows")


def main():
    parser = argparse.ArgumentParser(
        description='Probe the trigger focus/keystroke path for the Windows beep.')
    parser.add_argument('--list-windows', action='store_true',
                        help='List top-level windows and exit')
    parser.add_argument('--filter', default=None,
                        help='Substring filter for --list-windows')
    parser.add_argument('--profile', default='fingertapping',
                        help='Profile whose keystroke_programs to probe')
    parser.add_argument('--method', default='quiet', choices=['quiet', 'alt', 'none'],
                        help='Focus method to test')
    parser.add_argument('--compare', action='store_true',
                        help="Run 'alt' then 'quiet' so the two can be heard side by side")
    parser.add_argument('--repeats', type=int, default=6,
                        help='Trigger rounds per method')
    parser.add_argument('--interval', type=float, default=1.5,
                        help='Seconds between rounds (a cue is ~1.5 s apart in fingertapping)')
    parser.add_argument('--keys', action='store_true',
                        help='Actually inject the trigger keys. Writes real markers '
                             'into any open recording -- no participant, please.')
    args = parser.parse_args()

    if args.list_windows:
        return list_windows(args.filter)

    log = crashlog.install('trigger_probe', profile=args.profile)
    programs = keystroke_programs(args.profile)
    if programs is None:
        return 1
    if not programs:
        log.log(f"Profile '{args.profile}' has no keystroke programs -- nothing "
                f"to probe. This beep only comes from the keystroke path.")
        return 0

    log.log(f"Probing {len(programs)} keystroke target(s): "
            f"{[(p.get('window'), p.get('key')) for p in programs]}")
    log.log(f"Injecting keys: {'YES' if args.keys else 'no (focus only)'}")
    methods = ['alt', 'quiet'] if args.compare else [args.method]

    rows = []
    for method in methods:
        print()
        log.log('=' * 70)
        log.log(f"METHOD '{method}' -- {args.repeats} rounds, {args.interval}s apart. "
                f"{'Listen for the Windows ding now.' if method == 'alt' else 'Should be silent.'}")
        log.log('=' * 70)
        time.sleep(1.0)
        for index in range(args.repeats):
            log.log(f"-- round {index+1}/{args.repeats} ({method})")
            rows += probe_round(programs, method, args.keys, log)
            time.sleep(args.interval)

    summarise(rows)
    print(f"\nFull log: {log.path}")
    log.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
