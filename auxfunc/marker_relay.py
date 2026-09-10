#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
marker_relay.py -- keep ONE LSL outlet alive for an entire session.
Created by: zkaposzt @ OU

The problem this replaces
------------------------
The old design passed ownership of the 'TriggerStream' outlet back and forth:
the control panel held it between runs, destroyed it just before spawning a
paradigm, and the paradigm created its own with the same source_id. Two things
went wrong with that.

  * The control panel's reclaim path was dead code. check_progress() set
    experiment_complete=True as soon as the paradigm reported 100% -- which
    happens while the paradigm is still sitting in its "window still open"
    screen -- so the later `if not self.experiment_complete:` branch that
    recreated the outlet never ran.
  * A finished paradigm keeps running (by design -- the blank screen stops the
    participant seeing the desktop), and start_experiment() happily launched
    the next one anyway. Every leftover process still owned an outlet, so after
    a couple of runs several outlets advertised the same name AND source_id at
    once. Which one NIRStar latched onto was luck. That is the
    nback -> fingertapping -> nback-loses-LSL sequence.

The fix
-------
Nobody hands anything off any more. The control panel creates exactly one
outlet at startup and holds it until the application quits, so a consumer binds
once and never sees the stream drop. Paradigm subprocesses do not create
outlets at all -- they send each marker to the control panel as a localhost UDP
datagram carrying the value and an LSL timestamp sampled at the instant of the
trigger. The control panel pushes that sample with the supplied timestamp, so
marker timing is what it was before; only the socket hop (tens of microseconds
on loopback) is new, and it happens after the timestamp is taken.

UDP rather than TCP on purpose: no connection state to lose, no accept backlog,
no half-open sockets if a paradigm is killed, and a send that cannot block the
stimulus loop.

Wire format -- one JSON object per datagram:
    {"op": "ping"}                          -> {"op": "pong", "magic": ...}
    {"op": "marker", "v": 8, "t": 1234.567} -> no reply
    {"op": "note",  "text": "..."}          -> no reply (logged by the panel)
"""

import json
import socket
import threading
import time

__all__ = ['MarkerRelayServer', 'MarkerRelayClient', 'RELAY_HOST', 'MAGIC']

RELAY_HOST = '127.0.0.1'
MAGIC = 'cbgPARADIGM-marker-relay/1'
MAX_DATAGRAM = 1024


def lsl_clock():
    """pylsl.local_clock() when available, else a monotonic stand-in.

    liblsl's local_clock is the same system clock in every process on the
    machine, which is what makes a timestamp taken in the paradigm meaningful
    when the control panel pushes it.
    """
    try:
        import pylsl
        return pylsl.local_clock()
    except Exception:
        return time.perf_counter()


# Server (control panel side)
# ---------------------------------------------------------------------------
class MarkerRelayServer(object):
    """Receive marker datagrams and hand them to `push`.

    `push(value, timestamp)` runs on the relay thread, so it must only touch
    the LSL outlet -- never Tk. Counters below are for the UI to poll.
    """

    def __init__(self, push, logger=None, host=RELAY_HOST):
        self._push = push
        self._log = logger
        self._stop = threading.Event()
        self._thread = None

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind((host, 0))          # port 0 -> OS picks a free one
        self._sock.settimeout(0.5)          # so the loop can notice _stop
        self.port = self._sock.getsockname()[1]

        self.markers_relayed = 0
        self.last_value = None
        self.last_time = None
        self.last_error = None

    def start(self):
        self._thread = threading.Thread(target=self._serve, name='marker-relay',
                                        daemon=True)
        self._thread.start()
        self._note(f'MarkerRelay: listening on {RELAY_HOST}:{self.port}')
        return self.port

    def _note(self, message, level='INFO'):
        if self._log is not None:
            self._log.log(message, level=level)
        else:
            print(message)

    def _serve(self):
        while not self._stop.is_set():
            try:
                data, addr = self._sock.recvfrom(MAX_DATAGRAM)
            except socket.timeout:
                continue
            except OSError:
                break                        # socket closed under us: we are done
            except Exception as exc:
                self.last_error = str(exc)
                self._note(f'MarkerRelay: recv failed -> {exc}', level='ERROR')
                continue

            try:
                message = json.loads(data.decode('utf-8'))
            except Exception:
                continue                     # not ours; ignore silently

            op = message.get('op')
            if op == 'ping':
                try:
                    self._sock.sendto(
                        json.dumps({'op': 'pong', 'magic': MAGIC}).encode('utf-8'),
                        addr)
                except Exception as exc:
                    self._note(f'MarkerRelay: pong failed -> {exc}', level='WARN')
            elif op == 'marker':
                self._handle_marker(message)
            elif op == 'note':
                self._note(f'MarkerRelay: paradigm says: {message.get("text", "")}')

    def _handle_marker(self, message):
        try:
            value = int(message.get('v', 8))
        except Exception:
            value = 8
        stamp = message.get('t')
        try:
            stamp = float(stamp) if stamp is not None else None
        except Exception:
            stamp = None
        try:
            self._push(value, stamp)
            self.markers_relayed += 1
            self.last_value = value
            self.last_time = time.time()
        except Exception as exc:
            self.last_error = str(exc)
            self._note(f'MarkerRelay: push failed -> {exc}', level='ERROR')

    def stop(self):
        self._stop.set()
        try:
            self._sock.close()
        except Exception:
            pass
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.5)


# Client (paradigm side)
# ---------------------------------------------------------------------------
class MarkerRelayClient(object):
    """Send markers to the control panel's relay.

    `ok` is False when the handshake failed, which lets TriggerManager treat
    LSL as unavailable and demote those programs to their keystroke fallback --
    the same cascade the old code used when an outlet could not be created.
    """

    def __init__(self, port, logger=None, host=RELAY_HOST,
                 handshake_timeout=0.75, attempts=4):
        self.port = int(port)
        self.addr = (host, self.port)
        self._log = logger
        self._sock = None
        self.ok = False
        self.sent = 0
        self.failed = 0
        self.last_error = None

        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.settimeout(handshake_timeout)
            self.ok = self._handshake(attempts)
        except Exception as exc:
            self.last_error = str(exc)
            self._note(f'MarkerRelay: client socket failed -> {exc}', level='ERROR')

        if self._sock is not None:
            # Never let a marker send stall the stimulus loop.
            try:
                self._sock.setblocking(False)
            except Exception:
                pass

    def _note(self, message, level='INFO'):
        if self._log is not None:
            self._log.log(message, level=level)
        else:
            print(message)

    def _handshake(self, attempts):
        payload = json.dumps({'op': 'ping'}).encode('utf-8')
        for attempt in range(1, attempts + 1):
            try:
                self._sock.sendto(payload, self.addr)
                data, _ = self._sock.recvfrom(MAX_DATAGRAM)
                reply = json.loads(data.decode('utf-8'))
                if reply.get('op') == 'pong' and reply.get('magic') == MAGIC:
                    self._note(f'MarkerRelay: connected to control panel on '
                               f'port {self.port} (attempt {attempt})')
                    return True
            except Exception as exc:
                self.last_error = str(exc)
            time.sleep(0.1)
        self._note(f'MarkerRelay: no answer from control panel on port '
                   f'{self.port}; LSL markers will not be relayed '
                   f'(last error: {self.last_error})', level='ERROR')
        return False

    def send(self, value, timestamp=None):
        if not self.ok or self._sock is None:
            return False
        if timestamp is None:
            timestamp = lsl_clock()
        try:
            self._sock.sendto(
                json.dumps({'op': 'marker', 'v': int(value),
                            't': float(timestamp)}).encode('utf-8'),
                self.addr)
            self.sent += 1
            return True
        except Exception as exc:
            self.failed += 1
            self.last_error = str(exc)
            self._note(f'MarkerRelay: marker send failed -> {exc}', level='WARN')
            return False

    def note(self, text):
        """Push a one-line message into the control panel's log."""
        if not self.ok or self._sock is None:
            return False
        try:
            self._sock.sendto(
                json.dumps({'op': 'note', 'text': str(text)[:400]}).encode('utf-8'),
                self.addr)
            return True
        except Exception:
            return False

    def close(self):
        try:
            if self._sock is not None:
                self._sock.close()
        except Exception:
            pass
        self._sock = None
        self.ok = False
