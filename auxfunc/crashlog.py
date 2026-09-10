#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
crashlog.py -- run / crash logging for the cbgPARADIGM toolchain.
Created by: zkaposzt @ OU

Why this exists
---------------
Before this module the control panel launched every paradigm with

    subprocess.Popen(..., stdout=subprocess.PIPE, stderr=subprocess.PIPE)

and then never read either pipe. Two things follow from that:

  1. Any traceback the paradigm produced went into a pipe nobody drained, so a
     crash left literally no evidence behind.
  2. A Windows anonymous pipe buffer is ~4 KB. Once the paradigm has printed
     4 KB it blocks on the next write, forever. That is a hang, not a crash,
     but from the operator's chair it looks identical.

So: every launch now gets a plain-text log file under <repo>/logs/, the control
panel redirects the subprocess's stdout+stderr into that file at the OS level
(no pipe, no buffer limit, nothing to drain), and this module adds the pieces a
bare redirect does not give you -- an excepthook that prints a full traceback,
faulthandler for hard native crashes inside SDL/liblsl, and a structured
[EVENT] line for anything worth finding later with a text search.

Abnormal exits also append one line to logs/crashes.log, so a month of sessions
can be triaged without opening thirty files.

Typical use
-----------
    from auxfunc import crashlog
    log = crashlog.install('nback', subject_id=args.subject_id,
                           profile=args.profile, path=args.log_file)
    ...
    log.event('segment_start', segment='rest', index=0)
"""

import atexit
import datetime
import faulthandler
import json
import os
import re
import sys
import threading
import traceback

__all__ = ['install', 'get', 'RunLogger', 'repo_root', 'resolve_log_dir',
           'new_log_path', 'CRASH_INDEX']

CRASH_INDEX = 'crashes.log'

_ACTIVE = None
_LOCK = threading.Lock()


# Paths
# ---------------------------------------------------------------------------
def repo_root():
    """Directory that holds main.py (auxfunc/ lives one level below it)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _safe(text, limit=48):
    """Filesystem-safe fragment for use in a log file name."""
    cleaned = re.sub(r'[^A-Za-z0-9._-]+', '-', str(text)).strip('-')
    return cleaned[:limit] or 'unknown'


def resolve_log_dir(configured=None):
    """Return a writable log directory, creating it if need be.

    `configured` comes from settings.json -> paths.log_dir. If it cannot be
    created (unmapped network drive, read-only share) we fall back to
    <repo>/logs, and if even that fails, to the OS temp directory -- logging
    must never be the thing that takes a session down.
    """
    candidates = []
    if configured:
        candidates.append(os.path.expandvars(os.path.expanduser(str(configured))))
    candidates.append(os.path.join(repo_root(), 'logs'))
    import tempfile
    candidates.append(os.path.join(tempfile.gettempdir(), 'cbgPARADIGM_logs'))

    for directory in candidates:
        try:
            os.makedirs(directory, exist_ok=True)
            probe = os.path.join(directory, '.write_probe')
            with open(probe, 'w') as handle:
                handle.write('ok')
            os.unlink(probe)
            return directory
        except Exception:
            continue
    return os.path.abspath(os.curdir)


def new_log_path(component, subject_id=None, profile=None, configured_dir=None):
    """<log_dir>/YYYYmmdd_HHMMSS_<component>[_<subject>][_<profile>].log"""
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    parts = [stamp, _safe(component, 24)]
    if subject_id and str(subject_id).upper() != 'UNKNOWN':
        parts.append(_safe(subject_id, 24))
    if profile:
        parts.append(_safe(profile, 24))
    return os.path.join(resolve_log_dir(configured_dir), '_'.join(parts) + '.log')


# stdout/stderr tee
# ---------------------------------------------------------------------------
class _Tee(object):
    """Write to the original stream and to the log file at the same time.

    Used only when this process owns its log file (the control panel, or a
    paradigm started by hand from a terminal). When the control panel launches
    a paradigm it redirects fd 1 and fd 2 straight at the file instead, which
    captures native writes too, so no tee is needed there.
    """

    def __init__(self, stream, sink):
        self._stream = stream
        self._sink = sink

    def write(self, data):
        try:
            if self._stream is not None:
                self._stream.write(data)
        except Exception:
            pass
        try:
            self._sink.write(data)
            self._sink.flush()
        except Exception:
            pass
        return len(data)

    def flush(self):
        for target in (self._stream, self._sink):
            try:
                if target is not None:
                    target.flush()
            except Exception:
                pass

    def isatty(self):
        try:
            return bool(self._stream) and self._stream.isatty()
        except Exception:
            return False

    def fileno(self):
        # faulthandler and subprocess redirection both want a real descriptor.
        return self._sink.fileno()


# The logger
# ---------------------------------------------------------------------------
class RunLogger(object):
    """One of these per process. Writes human-readable lines to `path`.

    Two modes:
      own_file=True  -- open `path` ourselves and tee stdout/stderr into it.
      own_file=False -- our stdout/stderr are *already* pointed at `path` by the
                        parent process, so just print and let the redirect do
                        the work.
    """

    def __init__(self, component, path=None, subject_id=None, profile=None,
                 log_dir=None, own_file=True, echo=True):
        self.component = component
        self.subject_id = subject_id
        self.profile = profile
        self.started = datetime.datetime.now()
        self.log_dir = resolve_log_dir(log_dir)
        self.path = path or new_log_path(component, subject_id, profile, log_dir)
        self.crash_index = os.path.join(self.log_dir, CRASH_INDEX)

        self._own_file = bool(own_file)
        self._handle = None
        self._saved_hooks = {}
        self._closed = False
        self.fatal_recorded = False

        if self._own_file:
            try:
                self._handle = open(self.path, 'a', buffering=1, encoding='utf-8',
                                    errors='replace')
            except Exception as exc:
                sys.__stderr__.write(f'crashlog: cannot open {self.path} ({exc})\n')
                self._own_file = False

        if self._own_file and echo:
            sys.stdout = _Tee(sys.__stdout__, self._handle)
            sys.stderr = _Tee(sys.__stderr__, self._handle)

        self._enable_faulthandler()
        self._install_hooks()

        self.log('=' * 78)
        self.log(f'{component} started {self.started:%Y-%m-%d %H:%M:%S}')
        self.log(f'log file    : {self.path}')
        if subject_id:
            self.log(f'subject     : {subject_id}')
        if profile:
            self.log(f'profile     : {profile}')
        self.log(f'python      : {sys.version.split()[0]}  pid {os.getpid()}')
        self.log(f'cwd         : {os.path.abspath(os.curdir)}')
        self.log('=' * 78)

        atexit.register(self.close)

    # -- plumbing ---------------------------------------------------------- #
    def _enable_faulthandler(self):
        """Catch hard native crashes (SDL, liblsl, pywin32) that never raise."""
        try:
            target = self._handle if self._own_file and self._handle else sys.stderr
            faulthandler.enable(file=target, all_threads=True)
        except Exception as exc:
            self._raw(f'crashlog: faulthandler unavailable ({exc})')

    def _install_hooks(self):
        self._saved_hooks['excepthook'] = sys.excepthook
        sys.excepthook = self._excepthook
        if hasattr(sys, 'unraisablehook'):
            self._saved_hooks['unraisablehook'] = sys.unraisablehook
            sys.unraisablehook = self._unraisablehook
        if hasattr(threading, 'excepthook'):
            self._saved_hooks['thread_excepthook'] = threading.excepthook
            threading.excepthook = self._thread_excepthook

    def _excepthook(self, exc_type, exc_value, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            self.log('interrupted by KeyboardInterrupt', level='WARN')
        else:
            self.exception('uncaught exception', (exc_type, exc_value, tb), fatal=True)
        original = self._saved_hooks.get('excepthook')
        if original is not None:
            try:
                original(exc_type, exc_value, tb)
            except Exception:
                pass

    def _unraisablehook(self, unraisable):
        # Fires for exceptions inside __del__ -- which is exactly where the old
        # LSL teardown lived, so these are worth seeing.
        self.exception(
            f'unraisable exception in {unraisable.object!r}',
            (unraisable.exc_type, unraisable.exc_value, unraisable.exc_traceback),
            fatal=False)

    def _thread_excepthook(self, args):
        self.exception(
            f'uncaught exception in thread {getattr(args.thread, "name", "?")}',
            (args.exc_type, args.exc_value, args.exc_traceback), fatal=False)

    def _raw(self, text):
        try:
            sys.__stderr__.write(text + '\n')
            sys.__stderr__.flush()
        except Exception:
            pass

    # -- public API -------------------------------------------------------- #
    def log(self, message, level='INFO'):
        line = f'[{datetime.datetime.now():%H:%M:%S.%f}][{level:<5}] {message}'
        with _LOCK:
            try:
                print(line, flush=True)
            except Exception:
                self._raw(line)
        return line

    def warn(self, message):
        return self.log(message, level='WARN')

    def error(self, message):
        return self.log(message, level='ERROR')

    def event(self, kind, **fields):
        """Structured, greppable line: [EVENT] kind {json}

        Used for segment boundaries, triggers, and skips, so a run can be
        reconstructed afterwards even when the CSV is incomplete.
        """
        try:
            payload = json.dumps(fields, default=str, sort_keys=True)
        except Exception:
            payload = repr(fields)
        return self.log(f'[EVENT] {kind} {payload}')

    def exception(self, message, exc_info=None, fatal=True):
        """Write a full traceback, and index it in crashes.log when fatal."""
        exc_info = exc_info or sys.exc_info()
        text = ''.join(traceback.format_exception(*exc_info)).rstrip()
        self.log(f'{message}', level='FATAL' if fatal else 'ERROR')
        for line in text.splitlines():
            self.log(f'    {line}', level='FATAL' if fatal else 'ERROR')
        if fatal:
            self.fatal_recorded = True
            self._append_crash_index(message, exc_info)
        return text

    def _append_crash_index(self, message, exc_info):
        try:
            exc_type, exc_value = exc_info[0], exc_info[1]
            summary = (f'{datetime.datetime.now():%Y-%m-%d %H:%M:%S}\t'
                       f'{self.component}\t{self.subject_id or "-"}\t'
                       f'{self.profile or "-"}\t'
                       f'{getattr(exc_type, "__name__", exc_type)}: {exc_value}\t'
                       f'{os.path.basename(self.path)}\n')
            with open(self.crash_index, 'a', encoding='utf-8', errors='replace') as handle:
                handle.write(summary)
        except Exception as exc:
            self._raw(f'crashlog: could not update crash index ({exc})')

    def note_abnormal_exit(self, description):
        """Record a bad exit that produced no Python exception.

        The control panel calls this when a paradigm dies with a nonzero return
        code -- a segfault, or a Windows kill -- so crashes.log stays a complete
        index of bad endings rather than only of tracebacks.
        """
        self.error(description)
        try:
            summary = (f'{datetime.datetime.now():%Y-%m-%d %H:%M:%S}\t'
                       f'{self.component}\t{self.subject_id or "-"}\t'
                       f'{self.profile or "-"}\t{description}\t'
                       f'{os.path.basename(self.path)}\n')
            with open(self.crash_index, 'a', encoding='utf-8', errors='replace') as handle:
                handle.write(summary)
        except Exception:
            pass

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            elapsed = (datetime.datetime.now() - self.started).total_seconds()
            self.log(f'{self.component} finished after {elapsed:.1f}s')
        except Exception:
            pass
        for name, hook in self._saved_hooks.items():
            try:
                if name == 'excepthook':
                    sys.excepthook = hook
                elif name == 'unraisablehook':
                    sys.unraisablehook = hook
                elif name == 'thread_excepthook':
                    threading.excepthook = hook
            except Exception:
                pass
        if self._own_file:
            if isinstance(sys.stdout, _Tee):
                sys.stdout = sys.__stdout__
            if isinstance(sys.stderr, _Tee):
                sys.stderr = sys.__stderr__
            try:
                if self._handle:
                    self._handle.close()
            except Exception:
                pass


class _NullLogger(object):
    """Stand-in so callers never have to guard on `if log is not None`."""

    path = None
    crash_index = None
    fatal_recorded = False

    def log(self, message, level='INFO'):
        print(f'[{level}] {message}')

    warn = error = log

    def event(self, kind, **fields):
        pass

    def exception(self, message, exc_info=None, fatal=True):
        traceback.print_exception(*(exc_info or sys.exc_info()))

    def note_abnormal_exit(self, description):
        print(description)

    def close(self):
        pass


def install(component, path=None, subject_id=None, profile=None,
            log_dir=None, own_file=None, echo=True):
    """Create (once) and return the process-wide RunLogger.

    `own_file` defaults to True when no `path` was handed in, and to False when
    one was -- a path passed in means the parent already redirected our streams
    at it, so opening it a second time would only interleave badly.
    """
    global _ACTIVE
    if _ACTIVE is not None:
        return _ACTIVE
    if own_file is None:
        own_file = path is None
    try:
        _ACTIVE = RunLogger(component, path=path, subject_id=subject_id,
                            profile=profile, log_dir=log_dir,
                            own_file=own_file, echo=echo)
    except Exception as exc:
        sys.__stderr__.write(f'crashlog: install failed ({exc}); continuing without a log file\n')
        _ACTIVE = _NullLogger()
    return _ACTIVE


def get():
    """The active logger, or a no-op stand-in if install() was never called."""
    return _ACTIVE if _ACTIVE is not None else _NullLogger()
