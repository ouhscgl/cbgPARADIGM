#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
updater.py -- is this machine behind, and can it safely catch up?

Read-only by default. check() fetches and reports; apply() is the only thing
that changes the working copy, and it refuses unless the update is a clean
fast-forward onto an unmodified tree. Nothing here ever pulls on its own --
a machine part-way through a study does not change version because a timer
went off.

The guards exist because each one is a way people lose work:

    dirty tree      someone edited this copy; pulling would clash or clobber.
                    Config edits belong in a .local.json overlay instead.
    not ff          this copy has commits the server does not. Merging on a
                    lab machine is never the right answer.
    paradigm alive  updating mid-session leaves an old control panel driving
                    new paradigm code. The caller checks this one.
"""

import os
import subprocess

__all__ = ['check', 'apply_update', 'repo_root']

_NO_WINDOW = 0x08000000 if os.name == 'nt' else 0

# Git must never stop and ask a human anything. Without this, a machine whose
# stored credentials have expired -- or any private remote -- pops a Git
# Credential Manager window, or blocks on a prompt that nobody is looking at,
# and the check thread hangs until the timeout instead of failing in a second.
_NO_PROMPTS = {
    'GIT_TERMINAL_PROMPT': '0',
    'GIT_ASKPASS':         'echo',
    'SSH_ASKPASS':         'echo',
    'GCM_INTERACTIVE':     'never',
}

# The automatic check at startup gets a shorter leash than a click does: no one
# is waiting on it, but no one wants a thread sitting on a dead VPN either.
AUTO_TIMEOUT   = 25
MANUAL_TIMEOUT = 60


def repo_root():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, '..'))


def _run(args, cwd, timeout=60):
    """(returncode, stdout, stderr) -- never raises."""
    environment = dict(os.environ)
    environment.update(_NO_PROMPTS)
    try:
        done = subprocess.run(['git'] + args, cwd=cwd, timeout=timeout,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              env=environment, creationflags=_NO_WINDOW)
    except FileNotFoundError:
        return 127, '', 'git is not installed on this machine'
    except subprocess.TimeoutExpired:
        return 124, '', f'git {args[0]} timed out'
    except Exception as exc:
        return 1, '', f'{type(exc).__name__}: {exc}'
    return (done.returncode,
            done.stdout.decode('utf-8', 'replace').strip(),
            done.stderr.decode('utf-8', 'replace').strip())


def _upstream(root, branch):
    """The remote branch to compare against, or None."""
    code, out, _ = _run(['rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}'],
                        root)
    if code == 0 and out:
        return out
    if branch:
        code, _, _ = _run(['rev-parse', '--verify', f'origin/{branch}'], root)
        if code == 0:
            return f'origin/{branch}'
    return None


def check(root=None, fetch=True, timeout=MANUAL_TIMEOUT):
    """What is waiting for this machine.

    {'ok', 'error', 'branch', 'upstream', 'dirty', 'behind', 'ahead',
     'incoming': [(sha, subject)], 'target': tag or sha}
    """
    root = root or repo_root()
    info = {'ok': False, 'error': None, 'branch': None, 'upstream': None,
            'dirty': False, 'behind': 0, 'ahead': 0, 'incoming': [],
            'target': None}

    code, _, err = _run(['rev-parse', '--git-dir'], root)
    if code != 0:
        info['error'] = err or 'not a git repository'
        return info

    info['branch'] = _run(['rev-parse', '--abbrev-ref', 'HEAD'], root)[1] or None
    info['dirty'] = _run(['diff', '--quiet', 'HEAD'], root)[0] != 0

    if fetch:
        code, _, err = _run(['fetch', '--tags', '--prune'], root, timeout=timeout)
        if code != 0:
            info['error'] = err or 'could not reach the remote'
            return info

    upstream = _upstream(root, info['branch'])
    if not upstream:
        info['error'] = 'this branch has no upstream to compare against'
        return info
    info['upstream'] = upstream

    code, out, err = _run(['rev-list', '--left-right', '--count',
                           f'HEAD...{upstream}'], root)
    if code != 0:
        info['error'] = err or 'could not compare with the remote'
        return info
    try:
        ahead, behind = out.split()
        info['ahead'], info['behind'] = int(ahead), int(behind)
    except ValueError:
        info['error'] = f'unexpected output from git: {out!r}'
        return info

    if info['behind']:
        listing = _run(['log', '--oneline', '--no-decorate', '-20',
                        f'HEAD..{upstream}'], root)[1]
        for line in listing.splitlines():
            sha, _, subject = line.partition(' ')
            info['incoming'].append((sha, subject))
        info['target'] = (_run(['describe', '--tags', '--abbrev=0', upstream], root)[1]
                          or _run(['rev-parse', '--short', upstream], root)[1])

    info['ok'] = True
    return info


def apply_update(root=None):
    """Fast-forward this copy. (ok, message). Refuses anything risky."""
    root = root or repo_root()

    if _run(['diff', '--quiet', 'HEAD'], root)[0] != 0:
        changed = _run(['status', '--short', '--untracked-files=no'], root)[1]
        return False, ("This copy has local edits, so nothing was changed:\n\n"
                       f"{changed}\n\n"
                       "If they are in configs/, move them into an overlay:\n"
                       "    python auxfunc/config.py --extract settings.json --write\n"
                       "    python auxfunc/config.py --extract profiles.json --write\n"
                       "    git checkout -- configs")

    code, out, err = _run(['pull', '--ff-only'], root, timeout=120)
    if code != 0:
        return False, ((err or out or 'git pull failed') +
                       "\n\nNothing was changed.")
    return True, out or 'Updated.'
