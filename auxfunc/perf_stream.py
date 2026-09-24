#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
perf_stream.py -- one-way trial feed from a paradigm to the live monitor.

The paradigm appends one JSON object per line; the monitor (a separate
process) tails that file. Deliberately not a socket: nothing to handshake,
no firewall prompt, the monitor can be opened halfway through a run and still
see everything that came before, and the file survives as a record of the run.

The stimulus loop must never wait for a disk. emit() therefore only puts a
dict on a bounded in-memory queue -- a couple of microseconds -- and a daemon
thread does the encoding and the write. A full queue drops the record and
counts it rather than blocking the caller, because a missing dot on a monitor
is nothing and a stalled stimulus is a ruined run.

Record shapes (one per line, all carrying 't'):
    {"type":"run",   "subject":..., "profile":..., "blocks":[...], "rt_window":2.0}
    {"type":"block", "event":"start"|"end", "index":0, "name":"nback_0a", "n":32}
    {"type":"trial", "block":0, "name":"nback_0a", "idx":3, "n":32,
                     "stim":"W", "target":1, "pressed":1, "rt":0.412,
                     "outcome":"hit"|"miss"|"fa"|"cr", "skipped":0}
    {"type":"run",   "event":"end", "complete":true}
"""

import json
import os
import queue
import threading
import time

# Same timebase as the LSL markers (marker_relay.lsl_clock), but resolved once
# here instead of per call: that helper does `import pylsl` on every
# invocation, which is cheap when pylsl is installed and expensive when it is
# not -- and this runs inside the stimulus loop.
try:
    import pylsl as _pylsl

    def lsl_clock():
        return _pylsl.local_clock()
except Exception:
    def lsl_clock():
        return time.perf_counter()

__all__ = ['PerfEmitter', 'JsonlTail', 'classify', 'default_path']

SCHEMA = 1


def default_path(run_log_path):
    """The trial file that belongs beside a given run log."""
    if not run_log_path:
        return None
    return os.path.splitext(str(run_log_path))[0] + '.trials.jsonl'


def classify(target, pressed):
    """Signal-detection outcome for one n-back trial."""
    if target:
        return 'hit' if pressed else 'miss'
    return 'fa' if pressed else 'cr'


# ---- paradigm side ---------------------------------------------------------- #
class PerfEmitter(object):
    """Append records to `path` without ever blocking the caller."""

    def __init__(self, path, logger=None, maxsize=2048):
        self.path    = path
        self._log    = logger
        self._queue  = queue.Queue(maxsize=maxsize)
        self._thread = None
        self.written = 0
        self.dropped = 0
        self.ok      = False

        if not path:
            return
        try:
            folder = os.path.dirname(os.path.abspath(path))
            if folder:
                os.makedirs(folder, exist_ok=True)
            # Create it now, so a monitor opened before the first trial finds
            # a file rather than an error.
            with open(path, 'a', encoding='utf-8'):
                pass
        except Exception as exc:
            self._note(f"PerfEmitter: cannot use {path} -> {exc}", level='ERROR')
            return

        self._thread = threading.Thread(target=self._serve, name='perf-emitter',
                                        daemon=True)
        self._thread.start()
        self.ok = True
        self._note(f"PerfEmitter: writing trials to {path}")

    def _note(self, message, level='INFO'):
        if self._log is not None:
            try:
                self._log.log(message, level=level)
                return
            except Exception:
                pass
        print(message)

    def emit(self, **fields):
        """Queue one record. Returns False if it was dropped."""
        if not self.ok:
            return False
        fields.setdefault('t', lsl_clock())
        fields.setdefault('wall', time.time())
        try:
            self._queue.put_nowait(fields)
            return True
        except queue.Full:
            self.dropped += 1
            return False

    def _serve(self):
        handle = None
        try:
            handle = open(self.path, 'a', encoding='utf-8', errors='replace')
        except Exception as exc:
            self._note(f"PerfEmitter: writer thread could not open {self.path} "
                       f"-> {exc}", level='ERROR')
            return
        try:
            while True:
                item = self._queue.get()
                if item is None:
                    break
                try:
                    handle.write(json.dumps(item, default=str) + "\n")
                    handle.flush()
                    self.written += 1
                except Exception as exc:
                    # One bad record must not kill the feed.
                    self._note(f"PerfEmitter: write failed -> {exc}", level='WARN')
        finally:
            try:
                handle.close()
            except Exception:
                pass

    def close(self, timeout=1.5):
        """Drain what is queued, then stop the writer thread."""
        if not self.ok:
            return
        self.ok = False
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        if self.dropped:
            self._note(f"PerfEmitter: {self.dropped} record(s) dropped "
                       f"(queue full), {self.written} written", level='WARN')


# ---- monitor side ----------------------------------------------------------- #
class JsonlTail(object):
    """Incremental reader for a file another process is appending to."""

    def __init__(self, path):
        self.path      = path
        self.offset    = 0
        self._partial  = ''
        self.bad_lines = 0

    def reset(self):
        self.offset = 0
        self._partial = ''

    def poll(self):
        """Return the records appended since the last call (possibly empty)."""
        records = []
        try:
            size = os.path.getsize(self.path)
        except OSError:
            return records                      # not created yet, or gone

        if size < self.offset:                  # truncated or replaced
            self.reset()
        if size == self.offset:
            return records

        try:
            with open(self.path, 'r', encoding='utf-8', errors='replace') as handle:
                handle.seek(self.offset)
                chunk = handle.read()
                self.offset = handle.tell()
        except OSError:
            return records

        text = self._partial + chunk
        # A trailing fragment means the writer is mid-line; keep it for next time.
        if text and not text.endswith('\n'):
            text, _, self._partial = text.rpartition('\n')
        else:
            self._partial = ''

        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception:
                self.bad_lines += 1
        return records
