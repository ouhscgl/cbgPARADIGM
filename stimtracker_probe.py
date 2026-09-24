#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stimtracker_probe.py -- standalone Cedrus StimTracker connectivity probe.

TEMPORARY DIAGNOSTIC. Nothing in cbgPARADIGM imports this file; it exists to
answer one question before any of the TTL work goes into the toolchain:

    can this machine talk to the StimTracker at all, and if not, at which
    layer does it fail -- driver, port ownership, baud rate, XID mode,
    or pyxid2?

Run it with the control panel CLOSED. main.py's probe_capabilities() opens
every XID device at startup and closes it inside a bare try/except, so a panel
left running is itself a candidate for "the port is inaccessible".

Typical use
-----------
    python stimtracker_probe.py                 # identify only, fires nothing
    python stimtracker_probe.py --port COM3     # skip the scan, test one port
    python stimtracker_probe.py --listen 20     # watch for unprompted traffic
                                                #   (light / audio sensor events)
    python stimtracker_probe.py --pulse         # ask first, then fire test pulses

Everything printed is also written to stimtracker_probe_<timestamp>.log next
to this script, so the whole run can be pasted somewhere for a second opinion.
"""

import argparse
import datetime
import os
import platform
import sys
import time

# The only XID query used here that is documented and stable across generations.
# Every Cedrus device in XID mode answers it with something like b'_xid0'.
XID_IDENTIFY = b'_c1'

# Sent only for extra context; the replies are printed raw and NOT interpreted,
# because their meaning differs between XID generations. Check anything
# surprising against Cedrus's XID protocol document for your model.
XID_EXTRA_QUERIES = [b'_d2', b'_d3', b'_d4']

BAUD_CANDIDATES = [115200, 57600, 38400, 19200, 9600]

FTDI_VID = 0x0403          # Cedrus boxes enumerate through an FTDI USB serial chip


# ---- output ---------------------------------------------------------------- #
class Tee(object):
    """Print to the console and to a log file at the same time."""

    def __init__(self, path):
        self.handle = None
        self.path = None
        if path is None:
            return
        try:
            self.handle = open(path, 'w', encoding='utf-8')
            self.path = path
        except Exception as exc:
            print(f"(could not open log file {path}: {exc})")

    def __call__(self, message=''):
        print(message)
        if self.handle is not None:
            try:
                self.handle.write(str(message) + "\n")
                self.handle.flush()
            except Exception:
                pass

    def close(self):
        if self.handle is not None:
            try:
                self.handle.close()
            except Exception:
                pass


def header(say, number, title):
    say('')
    say(f"=== {number}. {title} " + "=" * max(0, 58 - len(title)))


# ---- 1. environment --------------------------------------------------------- #
def check_environment(say):
    say(f"date            : {datetime.datetime.now().isoformat(timespec='seconds')}")
    say(f"python          : {sys.version.split()[0]} ({platform.architecture()[0]})")
    say(f"platform        : {platform.platform()}")
    say(f"executable      : {sys.executable}")

    serial_mod = None
    try:
        import serial
        import serial.tools.list_ports          # noqa: F401  (imported for later use)
        serial_mod = serial
        say(f"pyserial        : {getattr(serial, '__version__', 'unknown')}")
    except ImportError:
        say("pyserial        : NOT INSTALLED  ->  pip install pyserial")

    pyxid2_mod = None
    try:
        import pyxid2
        pyxid2_mod = pyxid2
        version = getattr(pyxid2, '__version__', None)
        if version is None:
            try:
                from importlib.metadata import version as _v
                version = _v('pyxid2')
            except Exception:
                version = 'unknown'
        say(f"pyxid2          : {version}")
    except ImportError:
        say("pyxid2          : NOT INSTALLED  ->  pip install pyxid2  (optional for"
            " the raw serial tests below)")

    # A stray interpreter still holding the COM port is the most common reason
    # for "access is denied", so name any that are running.
    try:
        import psutil
        mine = os.getpid()
        others = []
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            if proc.info['pid'] == mine:
                continue
            name = (proc.info['name'] or '').lower()
            if 'python' in name or 'pythonw' in name:
                cmd = ' '.join(proc.info['cmdline'] or [])[:90]
                others.append(f"    pid {proc.info['pid']:>6}  {cmd}")
        if others:
            say("other python processes running (any of these could hold the port):")
            for line in others:
                say(line)
        else:
            say("other python    : none running")
    except ImportError:
        say("psutil          : not installed; cannot list other python processes")

    return serial_mod, pyxid2_mod


# ---- 2. what is on the bus -------------------------------------------------- #
def list_ports(say, serial_mod):
    """Enumerate serial ports and flag the ones that look like a Cedrus box."""
    from serial.tools import list_ports as lp

    ports = sorted(lp.comports(), key=lambda p: p.device)
    if not ports:
        say("No serial ports found at all. The box is not enumerating: check the")
        say("cable, the power, and Device Manager (a Cedrus device showing as an")
        say("unknown device means the driver is missing).")
        return []

    say(f"{len(ports)} serial port(s):")
    candidates = []
    for port in ports:
        vid = getattr(port, 'vid', None)
        pid = getattr(port, 'pid', None)
        blob = ' '.join(str(x) for x in (port.description, port.manufacturer,
                                         port.hwid, port.product)).lower()
        likely = (vid == FTDI_VID) or ('cedrus' in blob) or ('stimtracker' in blob)
        mark = ' <-- likely Cedrus' if likely else ''
        say(f"    {port.device:<8} {str(port.description)[:38]:<38} "
            f"vid:pid={vid:#06x}:{pid:#06x}" if vid and pid else
            f"    {port.device:<8} {str(port.description)[:38]:<38} vid:pid=?")
        say(f"             hwid={port.hwid}{mark}")
        if likely:
            candidates.append(port.device)

    if not candidates:
        say("")
        say("Nothing matched the Cedrus/FTDI signature. That does not rule the box")
        say("out -- a generic 'USB Serial Device' entry can still be it -- but if")
        say("Device Manager shows no new port appearing when you unplug and replug")
        say("the StimTracker, the driver is the problem, not Python.")
    return candidates


# ---- 3. can we even open it ------------------------------------------------- #
def open_test(say, serial_mod, port, baud=115200):
    """Open and immediately close. Separates ownership problems from silence."""
    import serial
    try:
        handle = serial.Serial(port, baud, timeout=0.3)
    except serial.SerialException as exc:
        text = str(exc)
        say(f"    {port}: FAILED to open -> {text}")
        if 'access is denied' in text.lower() or 'permission' in text.lower():
            say("           ^ the port is owned by another process. Close the")
            say("             cbgPARADIGM control panel, any Cedrus utility, and")
            say("             any leftover python.exe, then run this again.")
        return False
    except Exception as exc:
        say(f"    {port}: FAILED to open -> {type(exc).__name__}: {exc}")
        return False
    else:
        handle.close()
        say(f"    {port}: opens cleanly at {baud} baud")
        return True


# ---- 4. does anything answer XID -------------------------------------------- #
def xid_identify(say, port, bauds, settle=0.15, timeout=0.4):
    """Send the XID identify query at each baud rate; report every reply."""
    import serial

    answered_at = None
    for baud in bauds:
        try:
            handle = serial.Serial(port, baud, timeout=timeout)
        except Exception as exc:
            say(f"    {baud:>6} baud: cannot open ({exc})")
            continue

        try:
            time.sleep(settle)                  # the box needs a moment after open
            handle.reset_input_buffer()
            handle.write(XID_IDENTIFY)
            handle.flush()
            reply = handle.read(16)
            if reply:
                say(f"    {baud:>6} baud: REPLY {reply!r}")
                if answered_at is None:
                    answered_at = baud
                for query in XID_EXTRA_QUERIES:
                    handle.reset_input_buffer()
                    handle.write(query)
                    handle.flush()
                    extra = handle.read(16)
                    say(f"                 {query.decode():<4} -> {extra!r}"
                        f"{'  (no reply)' if not extra else ''}")
            else:
                say(f"    {baud:>6} baud: silence")
        except Exception as exc:
            say(f"    {baud:>6} baud: error during exchange -> "
                f"{type(exc).__name__}: {exc}")
        finally:
            try:
                handle.close()
            except Exception:
                pass

    return answered_at


# ---- 5. unprompted traffic --------------------------------------------------- #
def listen(say, port, baud, seconds):
    """Dump whatever the device sends on its own.

    A StimTracker in XID mode emits a packet when its light or audio sensor
    fires, so this is the quickest way to prove the sensor path works even if
    the command path does not: start this, then flash something at the sensor.
    """
    import serial
    try:
        handle = serial.Serial(port, baud, timeout=0.2)
    except Exception as exc:
        say(f"    cannot open {port} at {baud}: {exc}")
        return

    say(f"    listening on {port} at {baud} for {seconds}s -- trigger the light or")
    say("    audio sensor now (wave a phone torch at it, play a sound)...")
    deadline = time.time() + seconds
    total = 0
    try:
        while time.time() < deadline:
            chunk = handle.read(64)
            if chunk:
                total += len(chunk)
                say(f"    +{time.time() - (deadline - seconds):6.2f}s  {chunk!r}")
    except Exception as exc:
        say(f"    error while listening -> {type(exc).__name__}: {exc}")
    finally:
        try:
            handle.close()
        except Exception:
            pass
    say(f"    {total} byte(s) received")


# ---- 6. pyxid2's own view ---------------------------------------------------- #
def pyxid2_scan(say, pyxid2_mod):
    """Run the scan twice: the first call after a plug-in often returns nothing."""
    devices = []
    for attempt in (1, 2):
        try:
            devices = pyxid2_mod.get_xid_devices()
        except Exception as exc:
            say(f"    attempt {attempt}: get_xid_devices() raised "
                f"{type(exc).__name__}: {exc}")
            devices = []
        else:
            say(f"    attempt {attempt}: {len(devices)} device(s)")
        if devices:
            break
        time.sleep(0.5)

    for index, dev in enumerate(devices):
        say(f"    [{index}] {dev!r}")
        for attr in ('device_name', 'product_id', 'model_id', 'major_fw_version'):
            if hasattr(dev, attr):
                try:
                    say(f"         {attr:<18}= {getattr(dev, attr)}")
                except Exception as exc:
                    say(f"         {attr:<18}= <unreadable: {exc}>")
    if len(devices) > 1:
        say("    NOTE: more than one XID device. paradigm_utils._init_ttl() takes")
        say("    devices[0], and that order is not guaranteed between boots -- if")
        say("    one of these is a response box, that alone explains markers that")
        say("    sometimes went nowhere.")
    return devices


# ---- 7. fire something ------------------------------------------------------- #
def pulse_test(say, dev, bitmask, pulse_ms, count, interval, assume_yes):
    """Raise an output line a few times so the recorders can be watched."""
    say(f"    device        : {dev!r}")
    say(f"    bitmask       : {bitmask} (line {bitmask.bit_length()} if a single bit)")
    say(f"    pulse duration: {pulse_ms} ms")
    say(f"    pulses        : {count}, {interval}s apart")
    if not assume_yes:
        try:
            answer = input("    fire them? [y/N] ").strip().lower()
        except EOFError:
            answer = 'n'
        if answer not in ('y', 'yes'):
            say("    skipped.")
            return

    # Some pyxid/pyxid2 builds need the connection told it is driving a
    # StimTracker before the output lines respond. Harmless where absent.
    for setup in ('set_using_stim_tracker',):
        target = getattr(dev, 'con', None)
        if target is not None and hasattr(target, setup):
            try:
                getattr(target, setup)(True)
                say(f"    con.{setup}(True) ok")
            except Exception as exc:
                say(f"    con.{setup}(True) failed -> {exc}")

    if hasattr(dev, 'reset_base_timer'):
        try:
            dev.reset_base_timer()
        except Exception as exc:
            say(f"    reset_base_timer() failed -> {exc}")

    try:
        dev.set_pulse_duration(pulse_ms)
        say(f"    set_pulse_duration({pulse_ms}) ok")
    except Exception as exc:
        say(f"    set_pulse_duration({pulse_ms}) FAILED -> "
            f"{type(exc).__name__}: {exc}")

    for i in range(1, count + 1):
        stamp = time.perf_counter()
        try:
            dev.activate_line(bitmask=bitmask)
            say(f"    pulse {i}/{count} sent at t={stamp:.4f}")
        except Exception as exc:
            say(f"    pulse {i}/{count} FAILED -> {type(exc).__name__}: {exc}")
        if i < count:
            time.sleep(interval)

    say("")
    say("    Now check: did the box's output LED blink, and did Aurora /")
    say("    g.Recorder record that many markers? A send that raises no")
    say("    exception but produces no marker means the command path is fine")
    say("    and the wiring or the recorder's trigger input is not.")


# ---- main -------------------------------------------------------------------- #
def main():
    parser = argparse.ArgumentParser(
        description="Probe a Cedrus StimTracker: driver, port, baud, XID, pyxid2.")
    parser.add_argument('--port', help="test only this port (e.g. COM3)")
    parser.add_argument('--baud', type=int,
                        help="test only this baud rate instead of the usual five")
    parser.add_argument('--listen', type=float, metavar='SECONDS',
                        help="after identifying, dump unprompted traffic for N "
                             "seconds (use to test the light / audio sensor)")
    parser.add_argument('--pulse', action='store_true',
                        help="offer to fire test pulses through pyxid2")
    parser.add_argument('--bitmask', type=int, default=8,
                        help="output line bitmask for --pulse (default 8, the "
                             "value the paradigms use)")
    parser.add_argument('--pulse-ms', type=int, default=200,
                        help="pulse width in ms for --pulse (default 200)")
    parser.add_argument('--count', type=int, default=5,
                        help="how many pulses for --pulse (default 5)")
    parser.add_argument('--interval', type=float, default=1.0,
                        help="seconds between pulses (default 1.0)")
    parser.add_argument('--yes', action='store_true',
                        help="do not ask before firing pulses")
    parser.add_argument('--no-log', action='store_true',
                        help="do not write a log file")
    args = parser.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    log_path = os.path.join(
        here, f"stimtracker_probe_{datetime.datetime.now():%Y%m%d_%H%M%S}.log")
    say = Tee(None if args.no_log else log_path)

    try:
        say("StimTracker probe -- run this with the control panel closed.")

        header(say, 1, "environment")
        serial_mod, pyxid2_mod = check_environment(say)
        if serial_mod is None:
            say("\nWithout pyserial nothing else can run. Stopping.")
            return 2

        header(say, 2, "serial ports")
        if args.port:
            candidates = [args.port]
            say(f"scan skipped; testing {args.port} only (--port)")
        else:
            candidates = list_ports(say, serial_mod)
        if not candidates:
            say("\nNo candidate ports to test. Stopping.")
            return 1

        header(say, 3, "can the port be opened")
        openable = [p for p in candidates if open_test(say, serial_mod, p)]
        if not openable:
            say("\nEvery candidate port refused to open. This is an ownership or")
            say("driver problem, not an XID problem -- fix that first.")
            return 1

        header(say, 4, "does anything answer the XID identify query")
        bauds = [args.baud] if args.baud else BAUD_CANDIDATES
        answering = {}
        for port in openable:
            say(f"  {port}:")
            baud = xid_identify(say, port, bauds)
            if baud:
                answering[port] = baud

        if args.listen:
            header(say, 5, "unprompted traffic")
            for port in openable:
                baud = answering.get(port, args.baud or BAUD_CANDIDATES[0])
                listen(say, port, baud, args.listen)

        devices = []
        if pyxid2_mod is not None:
            header(say, 6, "pyxid2 device scan")
            devices = pyxid2_scan(say, pyxid2_mod)

        if args.pulse:
            header(say, 7, "pulse test")
            if not devices:
                say("    pyxid2 found no device, so there is nothing to pulse.")
            else:
                pulse_test(say, devices[0], args.bitmask, args.pulse_ms,
                           args.count, args.interval, args.yes)

        # ---- verdict ---------------------------------------------------- #
        header(say, 8, "verdict")
        if answering and devices:
            say("The box answers XID and pyxid2 can see it. The connection layer is")
            say("fine; anything still missing downstream is wiring, the recorder's")
            say("trigger input, or pulse width.")
        elif answering and not devices:
            say("The box answers raw XID but pyxid2 does not list it. That is a")
            say("library-side problem: update pyxid2, and note the baud rate that")
            say(f"worked ({sorted(set(answering.values()))}) -- if it is not 115200,")
            say("pyxid2's scanner may simply never try it.")
        elif openable and not answering:
            say("The port opens but nothing answers at any baud. The box is not in")
            say("XID mode, or the port is not the box. Check the mode with Cedrus's")
            say("own configuration utility; if that cannot see it either, Python was")
            say("never the problem.")
        else:
            say("Nothing reachable. Work down the list: cable, power, Device")
            say("Manager, driver, then port ownership.")

        if not args.no_log and say.path:
            say("")
            say(f"log written to {say.path}")
        return 0
    finally:
        say.close()


if __name__ == '__main__':
    sys.exit(main())
