#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Utility functions for the GeroScience Lab paradigms.
Created by: zkaposzt @ OU
"""

import pygame, json, time, os

# Windows keypress imports
try:
    import win32gui
    import win32con
    from win32api import keybd_event
    import pyautogui
    _WIN32_AVAILABLE = True
except ImportError:
    _WIN32_AVAILABLE = False

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
    """
    def __init__(self, use_lsl=True, programs=None, pulse_ms=50,
                 lsl_source_id='paradigm_triggers'):
        self.programs   = programs or []
        self._ttl_dev   = None
        self._lsl_out   = None

        self._init_ttl(pulse_ms)
        if use_lsl:
            self._init_lsl(lsl_source_id)

        _targets = [(p.get('window'), p.get('transport', 'keystroke'))
                    for p in self.programs]
        print(f"TriggerManager: per-program routing "
              f"(ttl={self._ttl_dev is not None}, "
              f"lsl={self._lsl_out is not None}, "
              f"targets={_targets})")

    def _init_ttl(self, pulse_ms):
        try:
            import pyxid2
        except ImportError:
            print("TriggerManager: pyxid2 not installed; skipping TTL")
            return
        try:
            devices = pyxid2.get_xid_devices()
            if not devices:
                print("TriggerManager: no XID devices detected")
                return
            dev = devices[0]
            dev.reset_base_timer()
            dev.set_pulse_duration(pulse_ms)
            self._ttl_dev = dev
            print(f"TriggerManager: TTL ready -> {dev}")
        except Exception as e:
            print(f"TriggerManager: TTL init failed -> {e}")
            self._ttl_dev = None

    def _init_lsl(self, source_id):
        try:
            import pylsl
        except ImportError:
            print("TriggerManager: pylsl not installed; skipping LSL")
            return
        try:
            info = pylsl.StreamInfo(
                name='TriggerStream', type='Markers',
                channel_count=1, nominal_srate=0,
                channel_format='int32', source_id=source_id,
            )
            self._lsl_out = pylsl.StreamOutlet(info)
            print("TriggerManager: LSL stream open")
        except Exception as e:
            print(f"TriggerManager: LSL init failed -> {e}")
            self._lsl_out = None

    # ---- access point for the paradigm ---------------------------------- #
    def send(self, value=8, return_focus_to=None):
        """Fan the trigger out to every program on its own transport, in one
        call. Returns the set of transports that actually fired."""
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
                if self._lsl_out is not None and self._send_lsl(mval):
                    fired.add('lsl');       continue
                transport = 'keystroke'     # demote this program only
            if transport == 'keystroke':
                if self._send_keystroke_one(prog):
                    fired.add('keystroke')

        if return_focus_to:
            hwnd = _find_window_partial(return_focus_to)
            if hwnd is not None:
                _ensure_focus(hwnd)

        return fired or {'none'}

    # ---- per-transport primitives --------------------------------------- #
    def _send_ttl(self, value):
        try:
            self._ttl_dev.activate_line(bitmask=int(value))
            return True
        except Exception as e:
            print(f"TriggerManager: TTL send failed ({e}); falling back")
            return False

    def _send_lsl(self, value):
        try:
            self._lsl_out.push_sample([int(value)])
            return True
        except Exception as e:
            print(f"TriggerManager: LSL send failed ({e}); falling back")
            return False

    def _send_keystroke_one(self, prog):
        if not _WIN32_AVAILABLE:
            return False
        window = prog.get('window', '')
        key    = prog.get('key', 'F8')
        vk     = VK_MAP.get(key.upper())
        if vk is None:
            print(f"TriggerManager: unknown key '{key}' for {window}")
            return False
        hwnd = _find_window_partial(window)
        if hwnd is None:
            print(f"TriggerManager: window '{window}' not found")
            return False
        try:
            _ensure_focus(hwnd)
            keybd_event(vk, 0, 0, 0)
            time.sleep(0.01)
            keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
            return True
        except Exception as e:
            print(f"TriggerManager: keystroke to {window} failed ({e})")
            return False

    # ---- introspection (for the future UI indicators) ------------------- #
    def _resolved_transport(self, prog):
        """What this program will actually use given current availability."""
        t = prog.get('transport', 'keystroke').lower()
        if t == 'ttl' and self._ttl_dev is None:
            t = 'lsl'
        if t == 'lsl' and self._lsl_out is None:
            t = 'keystroke'
        return t

    def status(self):
        resolved = sorted({self._resolved_transport(p) for p in self.programs})
        return {
            'ttl_available':  self._ttl_dev is not None,
            'lsl_available':  self._lsl_out is not None,
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
                print(f"TriggerManager: error closing TTL ({e})")
            self._ttl_dev = None
        if self._lsl_out is not None:
            try:
                del self._lsl_out
            except Exception as e:
                print(f"TriggerManager: error closing LSL ({e})")
            self._lsl_out = None
        self._method = 'none'

    def __del__(self):
        self.close()

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

def ensure_window_focus(window_handle, max_attempts=20, delay_ms=50):
    """Attempt to set window focus with multiple retries"""
    pyautogui.press("alt")
    for attempt in range(max_attempts):
        try:
            win32gui.SetForegroundWindow(window_handle)
            return True  # Success
        except Exception as e:
            print(f"Focus attempt {attempt+1}/{max_attempts} failed: {e}")
            pygame.time.wait(delay_ms)
    
    print(f"Failed to focus window after {max_attempts} attempts")
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
    """Check if user is attempting to quit the application"""
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            pygame.quit()
            return True
        if event.type == pygame.KEYDOWN:
            # Check if ctrl+c is pressed (both windows and mac)
            if event.key == pygame.K_c and (pygame.key.get_mods() & pygame.KMOD_CTRL):
                pygame.quit()
                return True
            # Also exit on Escape key
            if event.key == pygame.K_ESCAPE:
                pygame.quit()
                return True
    return False

def display_message(screen, font, message, wait=0, custom_font_size=None, progress_file=None, 
                   status=None, progress_start=None, progress_end=None, image_path=None, 
                   position=None, width_screen=1920, height_screen=1080):
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
        display_font = pygame.font.SysFont(None, custom_font_size if custom_font_size else 300)
        text.append(display_font.render(message, True, font_color))
        rect.append(text[0].get_rect(center=(position[0], position[1] + message_y_offset)))
    else:
        # Multiple messages - use standard font size
        for i, line in enumerate(message):
            text.append(font.render(line, True, font_color))
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
                
            # Check for quit events
            if check_for_quit():
                return True
                
            # Small delay to prevent high CPU usage
            pygame.time.wait(50)
    return False

def wait_period(screen, duration_ms, progress_file=None, status=None, progress_start=0, progress_end=0):
    """
    Wait for a specified duration with optional progress updates
    
    Parameters:
    - screen: pygame screen object
    - duration_ms: wait duration in milliseconds
    - progress_file: path to progress file
    - status: status message for progress updates
    - progress_start: starting progress percentage
    - progress_end: ending progress percentage
    
    Returns:
        bool: True if user quit during wait, False otherwise
    """
    start_time = pygame.time.get_ticks()
    
    while pygame.time.get_ticks() - start_time < duration_ms:
        if check_for_quit():
            return True
            
        # Update progress if needed
        if progress_file and status and progress_end > progress_start:
            elapsed = pygame.time.get_ticks() - start_time
            progress_percent = round(progress_start + (elapsed / duration_ms) * (progress_end - progress_start), 2)
            update_progress(progress_file, progress_percent, status)
            
        # Small delay to prevent high CPU usage
        pygame.time.wait(100)
        
    return False

def play_audio(audio_file):
    """
    Play an audio file and wait for it to finish
    
    Parameters:
    - audio_file: path to audio file
    
    Returns:
        bool: True if user quit during playback, False otherwise
    """
    try:
        pygame.mixer.music.load(audio_file)
        pygame.mixer.music.play()
        
        # Wait until the audio is finished playing
        while pygame.mixer.music.get_busy():
            if check_for_quit():
                return True
            pygame.time.wait(100)
    except Exception as e:
        print(f"Error playing audio {audio_file}: {e}")
        
    return False