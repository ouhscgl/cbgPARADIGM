#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cloudsync.py -- has OneDrive actually taken this file, or is it still local?

There is no supported way to ask OneDrive "is this uploaded yet". What Windows
does expose is the placeholder state of a file under a sync root, and that is
enough to answer the question that matters:

    online-only   OneDrive holds it and has freed the local copy. Uploaded.
    synced        a hydrated placeholder: OneDrive holds it AND it is local.
    pending       inside a sync root but not a placeholder yet -- OneDrive has
                  not finished with it. (Also what everything looks like when
                  Files On-Demand is switched off, which is why that case is
                  reported as ambiguous rather than as a failure.)
    local only    not inside any OneDrive root. Nothing is being backed up.
    unknown       not Windows, or the attributes could not be read.

Uploads are asynchronous, so a file checked immediately after being copied is
normally 'pending'. That is not an error: it means ask again in a minute.

    python auxfunc/cloudsync.py "C:\\Projects"
"""

import os
import sys

__all__ = ['onedrive_roots', 'classify', 'describe_tree',
           'ONLINE_ONLY', 'SYNCED', 'PENDING', 'LOCAL_ONLY', 'UNKNOWN']

ONLINE_ONLY = 'online-only'
SYNCED      = 'synced'
PENDING     = 'pending'
LOCAL_ONLY  = 'local only'
UNKNOWN     = 'unknown'

# Windows file attributes that describe cloud placeholders.
FILE_ATTRIBUTE_REPARSE_POINT         = 0x00000400
FILE_ATTRIBUTE_OFFLINE               = 0x00001000
FILE_ATTRIBUTE_RECALL_ON_OPEN        = 0x00040000
FILE_ATTRIBUTE_PINNED                = 0x00080000
FILE_ATTRIBUTE_UNPINNED              = 0x00100000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x00400000


def onedrive_roots():
    """Every OneDrive sync root this user has, from the environment."""
    roots = []
    for name in ('OneDrive', 'OneDriveCommercial', 'OneDriveConsumer'):
        value = os.environ.get(name, '').strip()
        if value and os.path.isdir(value):
            resolved = os.path.normcase(os.path.abspath(value))
            if resolved not in roots:
                roots.append(resolved)
    return roots


def _root_for(path):
    target = os.path.normcase(os.path.abspath(path))
    for root in onedrive_roots():
        if target == root or target.startswith(root + os.sep):
            return root
    return None


def _attributes(path):
    if os.name != 'nt':
        return None
    try:
        import ctypes
        value = ctypes.windll.kernel32.GetFileAttributesW(str(path))
    except Exception:
        return None
    return None if value == 0xFFFFFFFF else value


def classify(path):
    """{'state', 'detail', 'root'} for one file or folder."""
    root = _root_for(path)
    if root is None:
        return {'state': LOCAL_ONLY, 'root': None,
                'detail': 'not inside a OneDrive folder'}

    if os.name != 'nt':
        return {'state': UNKNOWN, 'root': root,
                'detail': 'sync state is only readable on Windows'}

    attributes = _attributes(path)
    if attributes is None:
        return {'state': UNKNOWN, 'root': root,
                'detail': 'could not read file attributes'}

    if attributes & FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS:
        return {'state': ONLINE_ONLY, 'root': root,
                'detail': 'uploaded; local copy freed'}
    if attributes & (FILE_ATTRIBUTE_REPARSE_POINT | FILE_ATTRIBUTE_OFFLINE
                     | FILE_ATTRIBUTE_RECALL_ON_OPEN | FILE_ATTRIBUTE_PINNED):
        return {'state': SYNCED, 'root': root, 'detail': 'uploaded and kept locally'}
    return {'state': PENDING, 'root': root,
            'detail': 'not a placeholder yet: still uploading, or Files '
                      'On-Demand is off'}


def describe_tree(path, limit=400):
    """Aggregate state for a folder: {'state', 'detail', 'counts', 'root'}."""
    if os.path.isfile(path):
        single = classify(path)
        single['counts'] = {single['state']: 1}
        return single

    root = _root_for(path)
    if root is None:
        return {'state': LOCAL_ONLY, 'root': None, 'counts': {},
                'detail': 'not inside a OneDrive folder'}

    counts = {}
    seen = 0
    for base, _dirs, files in os.walk(path):
        for name in files:
            if seen >= limit:
                break
            state = classify(os.path.join(base, name))['state']
            counts[state] = counts.get(state, 0) + 1
            seen += 1
        if seen >= limit:
            break

    if not counts:
        return {'state': UNKNOWN, 'root': root, 'counts': counts,
                'detail': 'no files to check'}

    # One pending file means the folder is not safe yet, so it wins.
    for state in (UNKNOWN, PENDING, SYNCED, ONLINE_ONLY):
        if counts.get(state):
            summary = ', '.join(f"{number} {name}"
                                for name, number in sorted(counts.items()))
            return {'state': state, 'root': root, 'counts': counts,
                    'detail': summary}
    return {'state': UNKNOWN, 'root': root, 'counts': counts, 'detail': ''}


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else None
    if not target:
        try:
            from auxfunc.config import load_config
        except ImportError:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from config import load_config
        target = load_config('settings.json').get('paths', {}).get('project_root', '')
        print(f"No path given; using project_root from settings: {target or '(unset)'}")

    roots = onedrive_roots()
    print(f"OneDrive roots on this machine: {roots or 'none found'}")
    if not target:
        return 1
    print(f"Checking: {target}")
    if not os.path.exists(target):
        print("  does not exist")
        return 1

    result = describe_tree(target)
    print(f"  state : {result['state']}")
    print(f"  detail: {result['detail']}")
    print(f"  root  : {result['root'] or '-'}")
    if result['state'] == LOCAL_ONLY:
        print("\n  -> this path is NOT in OneDrive. Nothing exported here is "
              "being backed up.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
