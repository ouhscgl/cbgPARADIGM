#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fleet.py -- which build is on which machine, without a server.

Every time the control panel starts it drops one small JSON file named after
the machine into a shared folder:

    <project_root>/_fleet/BIOCHEMLAB-03.json

One file per machine, overwritten each launch. Listing that folder is the
whole inventory, and `python auxfunc/fleet.py` prints it as a table:

    HOST              VERSION              BRANCH  LAUNCHES  LAST SEEN
    BIOCHEMLAB-01     v8.0                 main          142  2026-09-23 14:02
    BIOCHEMLAB-03     v7.1                 main           88  2026-09-19 09:31
    NIRS-LAPTOP       v8.0-2-g91ab3de *    dev            7  2026-09-23 11:47

    * = local edits (git describe reported -dirty)

The write happens on a background thread: the share is usually a mapped drive,
and a drive that has gone away must not hold up the control panel's startup.
Nothing reads these files at run time, so losing one costs nothing.
"""

import argparse
import getpass
import json
import os
import platform
import socket
import sys
import tempfile
import threading
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from auxfunc.version import details as version_details
    from auxfunc.config import load_config
except Exception:                       # run directly from inside auxfunc/
    from version import details as version_details
    from config import load_config

__all__ = ['resolve_fleet_dir', 'report', 'collate', 'FLEET_DIRNAME']

FLEET_DIRNAME = '_fleet'


def _hostname():
    try:
        return socket.gethostname().split('.')[0] or 'unknown-host'
    except Exception:
        return 'unknown-host'


def _safe_name(text):
    keep = [c if (c.isalnum() or c in '-_.') else '-' for c in str(text)]
    return ''.join(keep)[:60] or 'unknown-host'


def resolve_fleet_dir(settings=None):
    """paths.fleet_dir, else <project_root>/_fleet, else None (feature off)."""
    if settings is None:
        try:
            settings = load_config('settings.json')
        except Exception:
            return None
    paths = (settings or {}).get('paths', {})
    configured = (paths.get('fleet_dir') or '').strip()
    if configured:
        return os.path.expandvars(os.path.expanduser(configured))
    project_root = (paths.get('project_root') or '').strip()
    if not project_root:
        return None
    return os.path.join(os.path.expandvars(os.path.expanduser(project_root)),
                        FLEET_DIRNAME)


def _build_record(app, extra=None):
    info = version_details()
    record = {
        'host':     _hostname(),
        'user':     (getpass.getuser() if hasattr(getpass, 'getuser') else ''),
        'app':      app,
        'version':  info['version'],
        'commit':   info['commit'],
        'branch':   info['branch'],
        'dirty':    info['dirty'],
        'source':   info['source'],
        'repo':     info['repo'],
        'python':   platform.python_version(),
        'platform': platform.platform(),
        'updated':  datetime.now().isoformat(timespec='seconds'),
        'launches': 1,
    }
    if extra:
        record.update(extra)
    return record


def _write_record(fleet_dir, record):
    os.makedirs(fleet_dir, exist_ok=True)
    target = os.path.join(fleet_dir, _safe_name(record['host']) + '.json')

    # Carry forward what the previous launch knew, so the table can show how
    # much a machine is actually used and when it first appeared.
    try:
        with open(target, 'r', encoding='utf-8') as handle:
            previous = json.load(handle)
        record['launches'] = int(previous.get('launches', 0)) + 1
        record['first_seen'] = previous.get('first_seen') or previous.get('updated')
    except Exception:
        record.setdefault('first_seen', record['updated'])

    # Write beside the target and swap it in, so a half-written file is never
    # what another machine reads.
    handle = None
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(dir=fleet_dir, prefix='.fleet-', suffix='.tmp')
        handle = os.fdopen(fd, 'w', encoding='utf-8')
        json.dump(record, handle, indent=2, sort_keys=True)
        handle.close()
        handle = None
        os.replace(tmp_path, target)
        tmp_path = None
    finally:
        if handle is not None:
            try:
                handle.close()
            except Exception:
                pass
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
    return target


def report(fleet_dir, app='control_panel', extra=None, logger=None,
           background=True):
    """Record this machine's build in the shared folder. Never raises."""
    if not fleet_dir:
        return None
    record = _build_record(app, extra)

    def run():
        try:
            target = _write_record(fleet_dir, record)
            if logger is not None:
                logger.log(f"Fleet: reported {record['version']} to {target}")
        except Exception as exc:
            if logger is not None:
                logger.warn(f"Fleet: could not write to {fleet_dir} -> {exc}")

    if background:
        threading.Thread(target=run, name='fleet-report', daemon=True).start()
        return None
    run()
    return record


# ---- reading it back -------------------------------------------------------- #
def collate(fleet_dir):
    """Every machine's last report, newest first."""
    rows = []
    try:
        names = sorted(os.listdir(fleet_dir))
    except OSError:
        return rows
    for name in names:
        if not name.endswith('.json') or name.startswith('.'):
            continue
        try:
            with open(os.path.join(fleet_dir, name), 'r', encoding='utf-8') as handle:
                rows.append(json.load(handle))
        except Exception:
            continue
    rows.sort(key=lambda r: (str(r.get('version')), str(r.get('host'))))
    return rows


def _print_table(rows, fleet_dir):
    if not rows:
        print(f"No machines have reported to {fleet_dir} yet.")
        return
    header = ('HOST', 'VERSION', 'BRANCH', 'PYTHON', 'LAUNCHES', 'LAST SEEN')
    table = []
    for row in rows:
        version = str(row.get('version', '?'))
        if row.get('dirty'):
            version += ' *'
        seen = str(row.get('updated', ''))[:16].replace('T', ' ')
        table.append((str(row.get('host', '?')), version,
                      str(row.get('branch') or '-'), str(row.get('python', '?')),
                      str(row.get('launches', '?')), seen))
    widths = [max(len(header[i]), max(len(r[i]) for r in table))
              for i in range(len(header))]
    line = '  '.join(h.ljust(widths[i]) for i, h in enumerate(header))
    print(line)
    print('-' * len(line))
    for row in table:
        print('  '.join(row[i].ljust(widths[i]) for i in range(len(header))))
    if any(r.get('dirty') for r in rows):
        print("\n* = local edits on that machine (git describe reported -dirty)")
    versions = {}
    for row in rows:
        versions[str(row.get('version'))] = versions.get(str(row.get('version')), 0) + 1
    print("\n" + ", ".join(f"{count}x {name}" for name, count
                           in sorted(versions.items(), key=lambda kv: -kv[1])))


def main():
    parser = argparse.ArgumentParser(
        description="Show which build each machine last reported.")
    parser.add_argument('--root', help="fleet folder (default: from settings.json)")
    parser.add_argument('--json', action='store_true', help="raw JSON instead of a table")
    parser.add_argument('--report', action='store_true',
                        help="write this machine's record instead of reading")
    args = parser.parse_args()

    fleet_dir = args.root or resolve_fleet_dir()
    if not fleet_dir:
        print("No fleet folder configured: set paths.fleet_dir or paths.project_root "
              "in configs/settings.json (or pass --root).")
        return 1

    if args.report:
        record = report(fleet_dir, app='cli', background=False)
        print(json.dumps(record, indent=2, sort_keys=True))
        return 0

    rows = collate(fleet_dir)
    if args.json:
        print(json.dumps(rows, indent=2, sort_keys=True))
    else:
        _print_table(rows, fleet_dir)
    return 0


if __name__ == '__main__':
    sys.exit(main())
