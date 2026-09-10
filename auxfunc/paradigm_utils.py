#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Utility functions for the GeroScience Lab paradigms.
Created by: zkaposzt @ OU
"""

import json, os, sys, time
import pygame

# Work whether this module is imported as `auxfunc.paradigm_utils` (how the
# paradigms do it) or as a bare `paradigm_utils` from inside auxfunc/.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from auxfunc import crashlog
    from auxfunc.marker_relay import MarkerRelayClient, lsl_clock
except ImportError:                                   # pragma: no cover
    import crashlog
    from marker_relay import MarkerRelayClient, lsl_clock

# Windows keypress imports
try:
    import win32gui
    import win32con
    from win32api import keybd_event
    import pyautogui
    _WIN32_AVAILABLE = True
except ImportError:
    _WIN32_AVAILABLE = False


# Run-control outcomes returned by display_message / wait_period / RunControl.
# CONTINUE is None so the historical `if display_message(...): return` idiom in
# nback_tutorial.py keeps working unchanged.
CONTINUE = None
QUIT     = 'quit'
SKIP     = 'skip'


def load_strings(language, paradigm):
    """Load the text table for `paradigm` in `language` from configs/strings.json.
    Always read as UTF-8 (Spanish accents / inverted punctuation). Any key that is
    missing or blank under the requested language falls back to English, so a
    half-translated table never crashes a session."""
    cfg = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..',
                       'configs', 'strings.json')
    try:
        with open(cfg, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"load_strings: could not read strings.json ({e}); paradigm will use built-in defaults")
        return {}
    lang = (language or 'en').lower()
    if lang not in data:
        print(f"load_strings: language '{lang}' not in strings.json; falling back to 'en'")
        lang = 'en'
    base = dict(data.get('en', {}).get(paradigm, {}))   # English baseline
    loc  = data.get(lang, {}).get(paradigm, {})
    base.update({k: v for k, v in loc.items() if v not in (None, "", [])})
    return base


VK_MAP = {
    'F1':  0x70, 'F2':  0x71, 'F3':  0x72, 'F4':  0x73,
    'F5':  0x74, 'F6':  0x75, 'F7':  0x76, 'F8':  0x77,
    'F9':  0x78, 'F10': 0x79, 'F11': 0x7A, 'F12': 0x7B,
    '0':   0x30, '1':   0x31, '2':   0x32, '3':   0x33, '4': 0x34,
    '5':   0x35, '6':   0x36, '7':   0x37, '8':   0x38, '9': 0x39,
}

# Global LSL outlet variable
_lsl_outlet = None

# ---- Font cache ------------------------------------------------------------ #
# run_trials used to call pygame.font.SysFont(None, 300) twice per frame, i.e.
# ~200 font loads a second for the whole cognitive block. Cache them instead;
# the cache is dropped whenever pygame shuts down so a restarted display does
# not hand out surfaces belonging to a dead video subsystem.
_FONT_CACHE = {}


def get_font(size, name=None):
    """Return a cached pygame font, creating it on first use."""
    key = (name, int(size))
    font = _FONT_CACHE.get(key)
    if font is None:
        font = pygame.font.SysFont(name, int(size))
        _FONT_CACHE[key] = font
    return font


def clear_font_cache():
    _FONT_CACHE.clear()


# ---- Win32 helpers (no-op on other platforms) ------------------------------ #
def _find_window_partial(partial_name):
    if not _WIN32_AVAILABLE:
        return None
    results = []
    def cb(hwnd, results):
        if partial_name in win32gui.GetWindowText(hwnd):
            results.append(hwnd)
        return True
    win32gui.EnumWindows(cb, results)
    return results[0] if results else None


def _ensure_focus(hwnd, max_attempts=20, delay_ms=50):
    if not _WIN32_AVAILABLE or hwnd is None:
        return False
    pyautogui.press("alt")  # Win32 focus-stealing workaround
    for _ in range(max_attempts):
        try:
            win32gui.SetForegroundWindow(hwnd)
            return True
        except Exception:
            time.sleep(delay_ms / 1000)
    return False

# ---- The manager ---------------------------------------------------------- #
class TriggerManager:
    """Fan a trigger out to every attached modality in a single send(), each on
    its own transport. Routing is per-program, not a single global method:
    LSL is used only where it registers reliably (e.g. NIRStar), simulated
    keypresses everywhere else. This restores the pre-v4.0 behavior.

    Each entry in `programs` may specify:
        window    : partial window title (keystroke / focus target)
        key       : key to press for keystroke transport (e.g. 'F8', '8')
        transport : 'keystroke' (default) | 'lsl' | 'ttl'
        value     : marker value for lsl/ttl (default: send()'s `value` arg)

    A program set to 'lsl'/'ttl' falls back to its `key` (keystroke) if that
    transport isn't available, mirroring the old `if use_lsl else keystroke`.

    LSL transport (changed 2026-09)
    -------------------------------
    When `marker_port` is given -- which it always is when the control panel
    launches the paradigm -- this class does NOT create an LSL outlet. It sends
    each marker to the control panel's permanent outlet over localhost UDP,
    stamped with lsl_clock() at the moment of the trigger. That removes the
    outlet handoff that used to leave several outlets sharing one source_id and
    made NIRStar bind to a stale one after a couple of runs.

    With no `marker_port` (paradigm started by hand, no control panel) the old
    behaviour applies and the paradigm owns its own outlet.
    """
    def __init__(self, use_lsl=True, programs=None, pulse_ms=50,
                 lsl_source_id='paradigm_triggers', marker_port=None,
                 logger=None):
        self.programs   = programs or []
        self._ttl_dev   = None
        self._lsl_out   = None
        self._relay     = None
        self._log       = logger or crashlog.get()
        self.sent_count = 0

        self._init_ttl(pulse_ms)
        if use_lsl:
            if marker_port:
                self._init_relay(marker_port)
            else:
                self._log.log("TriggerManager: no --marker_port given; this "
                              "paradigm will own its LSL outlet (standalone run)")
                self._init_lsl(lsl_source_id)

        _targets = [(p.get('window'), p.get('transport', 'keystroke'))
                    for p in self.programs]
        self._log.log(f"TriggerManager: per-program routing "
                      f"(ttl={self._ttl_dev is not None}, "
                      f"lsl={self.lsl_available}, "
                      f"relay={self._relay is not None and self._relay.ok}, "
                      f"targets={_targets})")

    # ---- availability --------------------------------------------------- #
    @property
    def lsl_available(self):
        if self._lsl_out is not None:
            return True
        return self._relay is not None and self._relay.ok

    def _init_relay(self, marker_port):
        self._relay = MarkerRelayClient(marker_port, logger=self._log)
        if not self._relay.ok:
            # Deliberately NOT falling back to creating our own outlet: that is
            # exactly the duplicate-source_id situation this design removes.
            # Programs routed to 'lsl' demote to their keystroke fallback, and
            # the failure is loud in the log.
            self._log.error("TriggerManager: marker relay unavailable; LSL "
                            "programs will fall back to keystrokes")

    def _init_ttl(self, pulse_ms):
        try:
            import pyxid2
        except ImportError:
            self._log.log("TriggerManager: pyxid2 not installed; skipping TTL")
            return
        try:
            devices = pyxid2.get_xid_devices()
            if not devices:
                self._log.log("TriggerManager: no XID devices detected")
                return
            dev = devices[0]
            dev.reset_base_timer()
            dev.set_pulse_duration(pulse_ms)
            self._ttl_dev = dev
            self._log.log(f"TriggerManager: TTL ready -> {dev}")
        except Exception as e:
            self._log.warn(f"TriggerManager: TTL init failed -> {e}")
            self._ttl_dev = None

    def _init_lsl(self, source_id):
        try:
            import pylsl
        except ImportError:
            self._log.log("TriggerManager: pylsl not installed; skipping LSL")
            return
        try:
            info = pylsl.StreamInfo(
                name='TriggerStream', type='Markers',
                channel_count=1, nominal_srate=0,
                channel_format='int32', source_id=source_id,
            )
            self._lsl_out = pylsl.StreamOutlet(info)
            self._log.log("TriggerManager: LSL stream open (owned by this process)")
        except Exception as e:
            self._log.error(f"TriggerManager: LSL init failed -> {e}")
            self._lsl_out = None

    # ---- access point for the paradigm ---------------------------------- #
    def send(self, value=8, return_focus_to=None, label=None):
        """Fan the trigger out to every program on its own transport, in one
        call. Returns the set of transports that actually fired."""
        # Sample the clock once, before any transport work, so every modality
        # is stamped with the same instant rather than with its own latency.
        stamp = lsl_clock()
        fired = set()
        for prog in self.programs:
            transport = prog.get('transport', 'keystroke').lower()
            mval      = int(prog.get('value', value))

            # ttl -> lsl -> keystroke per-program fallback
            if transport == 'ttl':
                if self._ttl_dev is not None and self._send_ttl(mval):
                    fired.add('ttl');       continue
                transport = 'lsl'           # demote this program only
            if transport == 'lsl':
                if self._send_lsl(mval, stamp):
                    fired.add('lsl');       continue
                transport = 'keystroke'     # demote this program only
            if transport == 'keystroke':
                if self._send_keystroke_one(prog):
                    fired.add('keystroke')

        if return_focus_to:
            hwnd = _find_window_partial(return_focus_to)
            if hwnd is not None:
                _ensure_focus(hwnd)

        self.sent_count += 1
        self._log.event('trigger', value=value, label=label, t=stamp,
                        fired=sorted(fired) or ['none'], n=self.sent_count)
        return fired or {'none'}

    # ---- per-transport primitives --------------------------------------- #
    def _send_ttl(self, value):
        try:
            self._ttl_dev.activate_line(bitmask=int(value))
            return True
        except Exception as e:
            self._log.warn(f"TriggerManager: TTL send failed ({e}); falling back")
            return False

    def _send_lsl(self, value, stamp=None):
        if self._relay is not None:
            return self._relay.send(value, stamp)
        if self._lsl_out is None:
            return False
        try:
            if stamp is None:
                self._lsl_out.push_sample([int(value)])
            else:
                self._lsl_out.push_sample([int(value)], stamp)
            return True
        except Exception as e:
            self._log.warn(f"TriggerManager: LSL send failed ({e}); falling back")
            return False

    def _send_keystroke_one(self, prog):
        if not _WIN32_AVAILABLE:
            return False
        window = prog.get('window', '')
        key    = prog.get('key', 'F8')
        vk     = VK_MAP.get(key.upper())
        if vk is None:
            self._log.warn(f"TriggerManager: unknown key '{key}' for {window}")
            return False
        hwnd = _find_window_partial(window)
        if hwnd is None:
            self._log.warn(f"TriggerManager: window '{window}' not found")
            return False
        try:
            _ensure_focus(hwnd)
            keybd_event(vk, 0, 0, 0)
            time.sleep(0.01)
            keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
            return True
        except Exception as e:
            self._log.warn(f"TriggerManager: keystroke to {window} failed ({e})")
            return False

    # ---- introspection (for the future UI indicators) ------------------- #
    def _resolved_transport(self, prog):
        """What this program will actually use given current availability."""
        t = prog.get('transport', 'keystroke').lower()
        if t == 'ttl' and self._ttl_dev is None:
            t = 'lsl'
        if t == 'lsl' and not self.lsl_available:
            t = 'keystroke'
        return t

    def status(self):
        resolved = sorted({self._resolved_transport(p) for p in self.programs})
        return {
            'ttl_available':  self._ttl_dev is not None,
            'lsl_available':  self.lsl_available,
            'lsl_via_relay':  self._relay is not None and self._relay.ok,
            'active_method':  '+'.join(resolved) if resolved else 'none',
            'programs':       [(p.get('window'), self._resolved_transport(p))
                               for p in self.programs],
        }

    # ---- cleanup -------------------------------------------------------- #
    def close(self):
        if self._ttl_dev is not None:
            try:
                self._ttl_dev.con.close()
            except Exception as e:
                self._log.warn(f"TriggerManager: error closing TTL ({e})")
            self._ttl_dev = None
        if self._relay is not None:
            try:
                self._relay.close()
            except Exception as e:
                self._log.warn(f"TriggerManager: error closing relay ({e})")
            self._relay = None
        if self._lsl_out is not None:
            try:
                del self._lsl_out
            except Exception as e:
                self._log.warn(f"TriggerManager: error closing LSL ({e})")
            self._lsl_out = None
        self._method = 'none'

    def __del__(self):
        try:
            self.close()
        except Exception:
            # __del__ runs during interpreter teardown; never let it raise.
            pass


# ---- Run control: quit + fast-forward ------------------------------------- #
# Modifier keys must never be logged as an n-back response, and must never be
# mistaken for the skip chord on their own.
_MODIFIER_KEYS = frozenset((
    pygame.K_LSHIFT, pygame.K_RSHIFT, pygame.K_LCTRL, pygame.K_RCTRL,
    pygame.K_LALT, pygame.K_RALT, pygame.K_LMETA, pygame.K_RMETA,
    pygame.K_LSUPER, pygame.K_RSUPER, pygame.K_MODE, pygame.K_CAPSLOCK,
    pygame.K_NUMLOCK, pygame.K_SCROLLOCK,
))


def is_modifier_key(key):
    return key in _MODIFIER_KEYS


class RunControl:
    """Quit and fast-forward handling for a paradigm run.

    Two ways in, because the paradigm window grabs the foreground and the
    operator cannot reliably click the control panel while a block is running:

      * Ctrl + Right Arrow pressed in the paradigm window.
      * The control panel's "Skip >>" button, which bumps a counter in a small
        JSON command file that this class polls.

    One press ends the current *segment* -- the rest state you are in, or the
    current n-back block, or the current fingertapping phase -- and moves on.
    A short debounce stops one press from cascading through several segments.

    poll() returns CONTINUE / QUIT / SKIP and never raises.
    """

    def __init__(self, command_file=None, logger=None,
                 command_poll_ms=100, debounce_ms=1200,
                 allow_skip=True):
        self.command_file    = command_file
        self._log            = logger or crashlog.get()
        self.command_poll_ms = command_poll_ms
        self.debounce_ms     = debounce_ms
        self.allow_skip      = allow_skip

        self.quit_requested = False
        self.skips          = 0

        self._last_file_check = 0.0
        self._last_skip_at    = -1e9
        self._seen_skip_seq   = self._read_skip_seq()   # ignore anything stale

    # -- command file ----------------------------------------------------- #
    def _read_skip_seq(self):
        if not self.command_file:
            return 0
        try:
            with open(self.command_file, 'r') as handle:
                return int(json.load(handle).get('skip_seq', 0))
        except Exception:
            return 0

    def check_command_file(self):
        """Poll the control panel's command file (throttled)."""
        if not (self.allow_skip and self.command_file):
            return CONTINUE
        now = time.monotonic() * 1000.0
        if now - self._last_file_check < self.command_poll_ms:
            return CONTINUE
        self._last_file_check = now
        seq = self._read_skip_seq()
        if seq > self._seen_skip_seq:
            self._seen_skip_seq = seq
            return self._arm_skip('control panel button')
        return CONTINUE

    # -- pygame events ---------------------------------------------------- #
    def handle_event(self, event, escape_quits=True):
        """Classify one already-fetched pygame event.

        Returns QUIT, SKIP, or CONTINUE. A CONTINUE here means the caller is
        free to treat the event as a participant response.

        `escape_quits` is False inside the n-back stimulus loop, where a bare
        Escape has always counted as a participant response rather than an
        abort. Ctrl+C aborts everywhere.
        """
        if event.type == pygame.QUIT:
            return self._arm_quit('window closed')
        if event.type != pygame.KEYDOWN:
            return CONTINUE

        mods = pygame.key.get_mods()
        ctrl = bool(mods & pygame.KMOD_CTRL)

        if event.key == pygame.K_c and ctrl:
            return self._arm_quit('Ctrl+C')
        if event.key == pygame.K_ESCAPE and (escape_quits or ctrl):
            return self._arm_quit('Escape')
        if self.allow_skip and ctrl and event.key == pygame.K_RIGHT:
            return self._arm_skip('Ctrl+Right')
        return CONTINUE

    def poll(self, pump=True):
        """Pump the event queue and the command file. Quit wins over skip."""
        outcome = CONTINUE
        if pump:
            try:
                for event in pygame.event.get():
                    result = self.handle_event(event)
                    if result == QUIT:
                        return QUIT
                    if result == SKIP:
                        outcome = SKIP
            except Exception as exc:
                # A dead video subsystem raises here; treat it as a quit rather
                # than spinning forever on a display that no longer exists.
                self._log.warn(f"RunControl: event pump failed ({exc})")
                return self._arm_quit('event pump failure')
        if outcome == SKIP:
            return SKIP
        return self.check_command_file()

    # -- internals -------------------------------------------------------- #
    def _arm_quit(self, source):
        self.quit_requested = True
        self._log.event('quit_requested', source=source)
        return QUIT

    def _arm_skip(self, source):
        now = time.monotonic() * 1000.0
        if now - self._last_skip_at < self.debounce_ms:
            return CONTINUE                       # one press, one segment
        self._last_skip_at = now
        self.skips += 1
        self._log.event('skip_requested', source=source, n=self.skips)
        return SKIP


def write_skip_command(command_file, seq):
    """Control-panel side of the skip button."""
    if not command_file:
        return False
    try:
        with open(command_file, 'w') as handle:
            json.dump({'skip_seq': int(seq), 'ts': time.time()}, handle)
        return True
    except Exception as exc:
        print(f"write_skip_command: {exc}")
        return False


def resolve_display(requested_index, requested_width, requested_height):
    pygame.display.init()
    n_displays = pygame.display.get_num_displays()

    if requested_index < n_displays:
        return requested_index, requested_width, requested_height

    try:
        native_w, native_h = pygame.display.get_desktop_sizes()[0]
    except Exception:
        native_w, native_h = requested_width, requested_height
    print(f"resolve_display: requested display {requested_index} not available "
          f"({n_displays} present); using display 0 at {native_w}x{native_h}")
    return 0, native_w, native_h


# ---- Window focus --------------------------------------------------------- #
# Throttling state for ensure_window_focus. Module-level because run_trials
# calls it from inside the per-frame loop.
_focus_state = {'last_attempt': 0.0, 'last_warn': 0.0, 'suppressed': 0}


def ensure_window_focus(window_handle, max_attempts=3, delay_ms=20,
                        throttle_ms=1000, hard=False):
    """Attempt to set window focus with multiple retries.

    Rewritten 2026-09. The previous version pressed ALT and then retried
    SetForegroundWindow up to 20 times at 50 ms each, printing a line on every
    failed attempt -- and nback.run_trials calls this once per frame. On a
    machine where Windows refuses the foreground change (which it does whenever
    the calling thread does not own the foreground, and always when the handle
    is stale or 0) that was a full second of blocking plus ~20 log lines per
    frame. With the control panel holding an unread stdout PIPE, the ~4 KB
    Windows pipe buffer filled within a couple of frames and the paradigm
    blocked forever on write. That is the hang the operator sees as "it crashed
    right after the resting states", because run_trials is the first thing that
    calls this in a loop.

    Now: return immediately if we already are the foreground window, at most one
    attempt per `throttle_ms`, few short retries, and rate-limited warnings.
    Pass hard=True for the one-shot calls made between segments, where spending
    a second to grab focus is fine and worth it.
    """
    if not _WIN32_AVAILABLE or not window_handle:
        return False

    if hard:
        max_attempts, delay_ms, throttle_ms = 20, 50, 0

    try:
        if win32gui.GetForegroundWindow() == window_handle:
            return True                       # already ours: nothing to do
    except Exception:
        pass

    now = time.monotonic() * 1000.0
    if throttle_ms and (now - _focus_state['last_attempt']) < throttle_ms:
        _focus_state['suppressed'] += 1
        return False
    _focus_state['last_attempt'] = now

    try:
        pyautogui.press("alt")  # Win32 focus-stealing workaround
    except Exception:
        pass

    last_error = None
    for attempt in range(max_attempts):
        try:
            win32gui.SetForegroundWindow(window_handle)
            return True  # Success
        except Exception as e:
            last_error = e
            pygame.time.wait(delay_ms)

    # Rate-limited: at most one warning every 5 s, with a count of what we ate.
    if (now - _focus_state['last_warn']) > 5000:
        _focus_state['last_warn'] = now
        crashlog.get().warn(
            f"ensure_window_focus: could not focus window after {max_attempts} "
            f"attempts ({last_error}); {_focus_state['suppressed']} throttled "
            f"calls since the last warning")
        _focus_state['suppressed'] = 0
    return False


def update_progress(progress_file, progress, status):
    """Update progress file with current progress and status"""
    if not progress_file:
        return
    try:
        with open(progress_file, 'w') as f:
            json.dump({
                "progress": progress,
                "status": status
            }, f)
    except Exception as e:
        print(f"Error updating progress: {e}")
        pass

def find_window_with_partial_name(partial_name):
    """Find window by partial title"""
    def enum_windows_callback(hwnd, results):
        window_text = win32gui.GetWindowText(hwnd)
        if partial_name in window_text:
            results.append((hwnd, window_text))
        return True
   
    results = []
    win32gui.EnumWindows(enum_windows_callback, results)
    return results[0][0] if results else None

def check_for_quit():
    """Check if user is attempting to quit the application

    Legacy entry point, still used by nback_tutorial.py. The main paradigms use
    RunControl instead, which also reports fast-forward requests and leaves the
    display alive so a partially finished run can still be written out.
    """
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            clear_font_cache()
            pygame.quit()
            return True
        if event.type == pygame.KEYDOWN:
            # Check if ctrl+c is pressed (both windows and mac)
            if event.key == pygame.K_c and (pygame.key.get_mods() & pygame.KMOD_CTRL):
                clear_font_cache()
                pygame.quit()
                return True
            # Also exit on Escape key
            if event.key == pygame.K_ESCAPE:
                clear_font_cache()
                pygame.quit()
                return True
    return False


def _poll(control):
    """One tick of run control: RunControl if given, legacy check_for_quit if not."""
    if control is not None:
        return control.poll()
    return QUIT if check_for_quit() else CONTINUE


def display_message(screen, font, message, wait=0, custom_font_size=None, progress_file=None, 
                   status=None, progress_start=None, progress_end=None, image_path=None, 
                   position=None, width_screen=1920, height_screen=1080, control=None):
    """Draw `message` and optionally hold it for `wait` ms.

    Returns CONTINUE (None), QUIT or SKIP. Callers that predate run control can
    keep treating the result as a boolean: CONTINUE is falsy, QUIT is truthy.
    """
    bg_color = (0, 0, 0)
    font_color = (255, 255, 255)
    
    screen.fill(bg_color)
    text = []
    rect = []
    
    # Set default position to center if not specified
    if position is None:
        position = (width_screen // 2, height_screen // 2)
    
    # Load and display image if provided
    message_y_offset = 0
    if image_path and os.path.exists(image_path):
        try:
            image = pygame.image.load(image_path)
            # Resize image if needed
            max_img_height = height_screen // 3
            image_rect = image.get_rect()
            if image_rect.height > max_img_height:
                scale_factor = max_img_height / image_rect.height
                new_width = int(image_rect.width * scale_factor)
                image = pygame.transform.scale(image, (new_width, max_img_height))
            
            # Position the image above the text
            image_rect = image.get_rect(center=(position[0], height_screen // 4))
            screen.blit(image, image_rect)
            
            # Adjust message position to be below the image
            message_y_offset = image_rect.height // 2 + 20  # 20px spacing
        except Exception as e:
            print(f"Error loading image {image_path}: {e}")
    
    if not isinstance(message, list):
        # Single message - use custom font size if provided, otherwise larger font
        display_font = get_font(custom_font_size if custom_font_size else 300)
        text.append(display_font.render(str(message), True, font_color))
        rect.append(text[0].get_rect(center=(position[0], position[1] + message_y_offset)))
    else:
        # Multiple messages - use standard font size
        for i, line in enumerate(message):
            text.append(font.render(str(line), True, font_color))
            rect.append(text[i].get_rect(center=(position[0], position[1] + ((i-1)*120) + message_y_offset)))
    
    for line in range(len(text)):
        screen.blit(text[line], rect[line])  
    
    pygame.display.flip()
    
    if wait:
        start_time = pygame.time.get_ticks()
        while pygame.time.get_ticks() - start_time < wait:
            # Update progress frequently during wait periods if progress file is provided
            if progress_file and status and progress_start is not None and progress_end is not None:
                elapsed = pygame.time.get_ticks() - start_time
                progress_percent = round(progress_start + (elapsed / wait) * (progress_end - progress_start), 2)
                update_progress(progress_file, progress_percent, status)
                
            # Check for quit / fast-forward
            outcome = _poll(control)
            if outcome is not CONTINUE:
                return outcome
                
            # Small delay to prevent high CPU usage
            pygame.time.wait(50)
    return CONTINUE

def wait_period(screen, duration_ms, progress_file=None, status=None, progress_start=0, progress_end=0,
                control=None):
    """
    Wait for a specified duration with optional progress updates
    
    Parameters:
    - screen: pygame screen object
    - duration_ms: wait duration in milliseconds
    - progress_file: path to progress file
    - status: status message for progress updates
    - progress_start: starting progress percentage
    - progress_end: ending progress percentage
    - control: optional RunControl for quit / fast-forward handling
    
    Returns:
        CONTINUE, QUIT or SKIP
    """
    start_time = pygame.time.get_ticks()
    
    while pygame.time.get_ticks() - start_time < duration_ms:
        outcome = _poll(control)
        if outcome is not CONTINUE:
            return outcome
            
        # Update progress if needed
        if progress_file and status and progress_end > progress_start:
            elapsed = pygame.time.get_ticks() - start_time
            progress_percent = round(progress_start + (elapsed / duration_ms) * (progress_end - progress_start), 2)
            update_progress(progress_file, progress_percent, status)
            
        # Small delay to prevent high CPU usage
        pygame.time.wait(100)
        
    return CONTINUE

def play_audio(audio_file, control=None):
    """
    Play an audio file and wait for it to finish
    
    Parameters:
    - audio_file: path to audio file
    - control: optional RunControl for quit / fast-forward handling
    
    Returns:
        CONTINUE, QUIT or SKIP
    """
    try:
        if not pygame.mixer.get_init():
            # nback never called pygame.mixer.init() explicitly and pygame.init()
            # swallows a mixer failure, so the end-of-rest beep used to vanish
            # silently on machines with no default audio device.
            try:
                pygame.mixer.init()
            except Exception as e:
                print(f"play_audio: mixer unavailable ({e}); skipping {audio_file}")
                return CONTINUE

        pygame.mixer.music.load(str(audio_file))
        pygame.mixer.music.play()
        
        # Wait until the audio is finished playing
        while pygame.mixer.music.get_busy():
            outcome = _poll(control)
            if outcome is not CONTINUE:
                try:
                    pygame.mixer.music.stop()
                except Exception:
                    pass
                return outcome
            pygame.time.wait(100)
    except Exception as e:
        print(f"Error playing audio {audio_file}: {e}")
        
    return CONTINUE
