#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
version.py -- what build is this machine actually running?

`git describe` is the source of truth, because it cannot drift: it names the
last tag, how far past it the working copy is, and whether anything has been
edited locally.

    v8.0                  exactly the v8.0 release
    v8.0-3-gab12f34       three commits past v8.0
    v8.0-3-gab12f34-dirty three commits past v8.0 AND edited on this machine
    8.0 (VERSION file)    deployed as a copy, no git available
    unknown               neither

The -dirty suffix is the one to watch: it means that machine's copy no longer
matches anything in the repository.
"""

import os
import subprocess

__all__ = ['describe', 'details', 'repo_root']

_cache = None

# Keep git from flashing a console window on Windows when the panel starts.
_NO_WINDOW = 0x08000000 if os.name == 'nt' else 0


def repo_root():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, '..'))


def _git(args, cwd, timeout=3.0):
    try:
        done = subprocess.run(['git'] + args, cwd=cwd, timeout=timeout,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              creationflags=_NO_WINDOW)
    except Exception:
        return None                      # no git, not a repo, or it hung
    if done.returncode != 0:
        return None
    text = done.stdout.decode('utf-8', 'replace').strip()
    return text or None


def _version_file(root):
    try:
        with open(os.path.join(root, 'VERSION'), 'r', encoding='utf-8') as handle:
            return handle.read().strip() or None
    except Exception:
        return None


def details(refresh=False):
    """{'version', 'commit', 'branch', 'dirty', 'source', 'repo'}"""
    global _cache
    if _cache is not None and not refresh:
        return dict(_cache)

    root = repo_root()
    info = {'version': 'unknown', 'commit': None, 'branch': None,
            'dirty': False, 'source': 'unknown', 'repo': root}

    described = _git(['describe', '--tags', '--always', '--dirty'], root)
    if described:
        info['version'] = described
        info['dirty']   = described.endswith('-dirty')
        info['commit']  = _git(['rev-parse', '--short', 'HEAD'], root)
        info['branch']  = _git(['rev-parse', '--abbrev-ref', 'HEAD'], root)
        info['source']  = 'git'
    else:
        stamped = _version_file(root)
        if stamped:
            info['version'] = stamped
            info['source']  = 'VERSION'

    _cache = dict(info)
    return dict(info)


def describe(refresh=False):
    """One string for a title bar or a log line."""
    info = details(refresh=refresh)
    if info['source'] == 'VERSION':
        return f"{info['version']} (VERSION file)"
    return info['version']


if __name__ == '__main__':
    for key, value in sorted(details().items()):
        print(f"{key:<8} {value}")
