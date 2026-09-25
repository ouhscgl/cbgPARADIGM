#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
config.py -- one loader for configs/, with a per-machine overlay.

Every machine in the lab needs its own paths (nirx_data, emotiv_data, the
instruction video, monitor_index) while sharing everything else. Tracking
settings.json in git and editing it on each machine makes every `git pull`
either a conflict or a silent clobber of whoever fixed a path last.

So: `configs/settings.json` stays in git as the shared defaults, and each
machine may keep an untracked `configs/settings.local.json` holding only the
keys it overrides. This loader deep-merges the second over the first, which
means a key added upstream still reaches every machine on the next pull --
unlike untracking the whole file, where new keys never arrive.

The same applies to any config. `profiles.json` + `profiles.local.json` is
the important second case: a site that shortens a rest period, or adds a
protocol of its own, puts that in the overlay instead of editing the tracked
file -- so an update can never clash with it or overwrite it. A local profile
that shares a key with a shared one wins, and the control panel marks it
[local] in the dropdown so nobody wonders which definition ran.

Setting a key to null in an overlay REMOVES it, which is how a machine hides a
protocol it never runs.

JSON has no comments, so any key beginning with __ is treated as one and
dropped at load. Without that, a "__comment" at the top of an overlay arrives
in profiles as an entry whose value is a string, and the control panel dies
trying to read a display_name off it before it can even draw a window.

    settings.json        settings.local.json        result
    paths.nirx_data      paths.nirx_data            local wins
    paths.log_dir        (absent)                   shared value
    display.width        (absent)                   shared value
    (absent)             display.monitor_index      local value
"""

import argparse
import json
import os
import subprocess
import sys

__all__ = ['load_config', 'load_overlay', 'config_dir', 'local_path_for',
           'applied_overlays', 'deep_merge', 'diff_tree', 'strip_comments',
           'profile_problems']

# Overlay files actually used this process, for logging at startup.
_applied = []


def config_dir():
    """<repo>/configs, regardless of which subfolder the caller lives in."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, '..', 'configs'))


def local_path_for(filename, directory=None):
    """configs/settings.json -> configs/settings.local.json"""
    stem, ext = os.path.splitext(filename)
    return os.path.join(directory or config_dir(), f"{stem}.local{ext}")


def strip_comments(value):
    """Drop every __-prefixed key, at any depth. JSON has no comments."""
    if isinstance(value, dict):
        return {key: strip_comments(item) for key, item in value.items()
                if not (isinstance(key, str) and key.startswith('__'))}
    if isinstance(value, list):
        return [strip_comments(item) for item in value]
    return value


def deep_merge(base, overlay):
    """Overlay wins. Dicts merge key by key; everything else is replaced.

    Lists are replaced wholesale on purpose: a machine overriding
    window_size means [420, 600], not [400, 545] with 420 mixed in.

    A null in the overlay deletes the key, so a machine can drop a profile it
    never runs without touching the shared file.
    """
    if not isinstance(base, dict) or not isinstance(overlay, dict):
        return overlay
    merged = dict(base)
    for key, value in overlay.items():
        if value is None and key in merged:
            del merged[key]
        elif key in merged:
            merged[key] = deep_merge(merged[key], value)
        elif value is not None:
            merged[key] = value
    return merged


def load_config(filename, directory=None):
    """Load configs/<filename> and merge configs/<stem>.local.<ext> over it.

    The base file behaves like open(): a missing one raises FileNotFoundError
    and a malformed one raises json.JSONDecodeError, so existing callers keep
    their error handling. A missing overlay is normal and silent; a malformed
    overlay raises, because running with half a machine's paths is worse than
    not starting.
    """
    directory = directory or config_dir()
    with open(os.path.join(directory, filename), 'r', encoding='utf-8-sig') as handle:
        data = strip_comments(json.load(handle))

    overlay_path = local_path_for(filename, directory)
    if os.path.exists(overlay_path):
        with open(overlay_path, 'r', encoding='utf-8-sig') as handle:
            data = deep_merge(data, strip_comments(json.load(handle)))
        if overlay_path not in _applied:
            _applied.append(overlay_path)
    return data


def load_overlay(filename, directory=None):
    """Just this machine's overlay for <filename>, or {} when there is none.

    Callers use it for provenance -- which profiles are local, what a machine
    has changed -- not for configuration; load_config() is the merged view.
    """
    overlay_path = local_path_for(filename, directory)
    if not os.path.exists(overlay_path):
        return {}
    try:
        with open(overlay_path, 'r', encoding='utf-8-sig') as handle:
            return strip_comments(json.load(handle))
    except Exception:
        return {}


def applied_overlays():
    """Overlay files merged so far in this process (for the startup log)."""
    return list(_applied)


def profile_problems(profiles):
    """Human-readable complaints about a merged profiles dict.

    Returns [(key, problem)]. An overlay is hand-written on a lab machine at
    an awkward hour, so the failure mode has to be a sentence, not a
    traceback.
    """
    found = []
    for key, value in (profiles or {}).items():
        if not isinstance(value, dict):
            found.append((key, f"is a {type(value).__name__}, not a profile "
                               f"(a stray comment or a typo in an overlay?)"))
            continue
        if not value.get('module'):
            found.append((key, "has no \"module\""))
        elif not str(value['module']).endswith('.py'):
            found.append((key, f"module {value['module']!r} is not a .py file"))
    return found


# ---- migrating a machine that already has hand-edits ------------------------ #
_UNCHANGED = object()

_NO_WINDOW = 0x08000000 if os.name == 'nt' else 0


def diff_tree(base, current):
    """The smallest overlay that turns `base` into `current`.

    Keys dropped in `current` come back as null, which deep_merge() reads as a
    deletion, so the round trip is exact.
    """
    if not isinstance(base, dict) or not isinstance(current, dict):
        return current if base != current else _UNCHANGED

    out = {}
    for key, value in current.items():
        if key not in base:
            out[key] = value
            continue
        delta = diff_tree(base[key], value)
        if delta is not _UNCHANGED:
            out[key] = delta
    for key in base:
        if key not in current:
            out[key] = None
    return out if out else _UNCHANGED


def _git(args, cwd):
    try:
        done = subprocess.run(['git'] + args, cwd=cwd, timeout=5,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              creationflags=_NO_WINDOW)
    except Exception:
        return None
    if done.returncode != 0:
        return None
    return done.stdout.decode('utf-8-sig', 'replace')


def committed_version(filename, directory=None):
    """configs/<filename> as it is in git HEAD, or None."""
    directory = directory or config_dir()
    root = os.path.normpath(os.path.join(directory, '..'))
    text = _git(['show', f'HEAD:configs/{filename}'], root)
    if text is None:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def extract_overlay(filename, directory=None):
    """What this machine changed in a tracked config, as an overlay dict."""
    base = committed_version(filename, directory)
    if base is None:
        return None
    directory = directory or config_dir()
    with open(os.path.join(directory, filename), 'r', encoding='utf-8-sig') as handle:
        current = json.load(handle)
    delta = diff_tree(base, current)
    return {} if delta is _UNCHANGED else delta


# ---- CLI --------------------------------------------------------------------- #
def _cmd_status(directory):
    root = os.path.normpath(os.path.join(directory, '..'))
    names = sorted(n for n in os.listdir(directory)
                   if n.endswith('.json') and '.local' not in n)
    for name in names:
        edited = _git(['diff', '--quiet', 'HEAD', '--', f'configs/{name}'], root)
        dirty = edited is None      # non-zero exit means the file differs
        print(f"{name}")

        # Three different situations used to print the same "(none)": no file,
        # a file that will not parse, and a file whose every key is still
        # commented out with __. Say which.
        overlay_path = local_path_for(name, directory)
        if not os.path.exists(overlay_path):
            print("    overlay : (none)")
        else:
            try:
                with open(overlay_path, 'r', encoding='utf-8-sig') as handle:
                    raw = json.load(handle)
            except Exception as exc:
                print(f"    overlay : {overlay_path}")
                print(f"    !! INVALID, so it is being ignored: {exc}")
            else:
                live = strip_comments(raw)
                print(f"    overlay : {overlay_path}")
                if live:
                    print(f"    overrides: {', '.join(sorted(live))}")
                else:
                    commented = [str(k) for k in raw if str(k).startswith('__')]
                    print("    !! HAS NO EFFECT: every key is still commented out "
                          "with __")
                    if commented:
                        print(f"       {', '.join(commented)}")
                    print("       remove the __ prefix from the section you want "
                          "to apply")
        if dirty:
            print("    !! this tracked file has local edits -- an update will "
                  "clash with them.")
            print(f"       move them out with:  python auxfunc/config.py "
                  f"--extract {name} --write")
    return 0


def _offending_file(name, directory):
    """Which of the two files behind a merged config actually fails to parse."""
    for path in (os.path.join(directory, name), local_path_for(name, directory)):
        if not os.path.exists(path):
            continue
        try:
            with open(path, 'r', encoding='utf-8-sig') as handle:
                json.load(handle)
        except json.JSONDecodeError as exc:
            return path, exc
        except Exception as exc:
            return path, exc
    return None, None


def _show_json_error(path, exc):
    """Point at the broken line, because 'line 26 column 5' is not enough.

    JSON's message for a trailing comma names the NEXT line -- the closing
    brace -- not the line with the stray comma, which is why this prints a few
    lines of context and says so out loud.
    """
    print(f"    in {path}")
    lineno = getattr(exc, 'lineno', None)
    if lineno is None:
        print(f"    {exc}")
        return
    print(f"    {exc.msg}: line {lineno}, column {exc.colno}")
    try:
        with open(path, 'r', encoding='utf-8-sig') as handle:
            lines = handle.read().splitlines()
    except Exception:
        return

    for number in range(max(1, lineno - 3), min(len(lines), lineno + 1) + 1):
        marker = '>>' if number == lineno else '  '
        print(f"    {marker} {number:>4} | {lines[number - 1]}")
        if number == lineno:
            print(f"           {' ' * (exc.colno + 3)}^")

    # The overwhelmingly common cause in a hand-edited config.
    previous = '\n'.join(lines[:lineno - 1]).rstrip()
    if previous.endswith(',') and lines[lineno - 1].strip() in ('}', ']', '},', '],'):
        print("    -> a comma after the LAST item in a block. Delete the comma "
              "on the line above.")


def _cmd_validate(directory):
    """Load every config the way the app does and report anything broken."""
    problems = 0
    for name in sorted(n for n in os.listdir(directory)
                       if n.endswith('.json') and '.local' not in n):
        try:
            data = load_config(name, directory)
        except Exception as exc:
            print(f"{name}: FAILED to load -> {type(exc).__name__}")
            path, detail = _offending_file(name, directory)
            if path is not None:
                _show_json_error(path, detail)
            else:
                print(f"    {exc}")
            problems += 1
            continue

        note = ""
        if os.path.exists(local_path_for(name, directory)):
            note = f" (+ {os.path.basename(local_path_for(name, directory))})"
        print(f"{name}{note}: loads, {len(data)} top-level entries")

        if name == 'profiles.json':
            for key, complaint in profile_problems(data):
                print(f"    !! {key} {complaint}")
                problems += 1

    print("\nNo problems found." if not problems
          else f"\n{problems} problem(s) -- the control panel will complain about "
               f"these at startup.")
    return 1 if problems else 0


def _cmd_extract(filename, directory, write, force):
    delta = extract_overlay(filename, directory)
    if delta is None:
        print(f"Cannot compare configs/{filename} against git "
              f"(not a repository, git missing, or the file is untracked).")
        return 1
    if not delta:
        print(f"configs/{filename} matches the committed version. "
              f"Nothing to extract.")
        return 0

    text = json.dumps(delta, indent=4, sort_keys=False, ensure_ascii=False)
    target = local_path_for(filename, directory)

    if not write:
        print(f"This machine's changes to configs/{filename}, as an overlay:\n")
        print(text)
        print(f"\nWrite it with:  python auxfunc/config.py --extract {filename} --write")
        return 0

    if os.path.exists(target) and not force:
        print(f"{target} already exists. Merge by hand, or pass --force to replace it.")
        return 1
    with open(target, 'w', encoding='utf-8') as handle:
        handle.write(text + "\n")
    print(f"Wrote {target}")
    print(f"Now restore the shared file:  git checkout -- configs/{filename}")
    print("The overlay is untracked, so updates can no longer clash with it.")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Inspect configs/ and move local edits into .local.json overlays.")
    parser.add_argument('--extract', metavar='FILE',
                        help="show what this machine changed in configs/FILE, "
                             "as an overlay")
    parser.add_argument('--write', action='store_true',
                        help="with --extract: write the overlay file")
    parser.add_argument('--force', action='store_true',
                        help="with --write: replace an existing overlay")
    parser.add_argument('--status', action='store_true',
                        help="show each config, its overlay and what it overrides "
                             "(this is also what runs with no arguments)")
    parser.add_argument('--validate', action='store_true',
                        help="load every config the way the app does and report "
                             "anything broken")
    parser.add_argument('--dir', default=None, help="configs folder to inspect")
    args = parser.parse_args()

    directory = args.dir or config_dir()
    if args.validate:
        return _cmd_validate(directory)
    if args.extract:
        return _cmd_extract(args.extract, directory, args.write, args.force)
    return _cmd_status(directory)


if __name__ == '__main__':
    sys.exit(main())
