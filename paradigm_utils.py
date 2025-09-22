#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Utility functions for the GeroScience Lab paradigms (n-back and fingertapping).
This module contains shared functionality to reduce code duplication.
"""

import pygame
import json
import time
import os
import win32gui
import win32con
from win32api import keybd_event
import pyautogui

# Global LSL outlet variable
_lsl_outlet = None

def create_lsl_outlet():
    """Create LSL outlet for sending triggers"""
    global _lsl_outlet
    try:
        import pylsl
        print("Creating LSL trigger stream...")
        info = pylsl.StreamInfo(
            name='TriggerStream',
            type='Markers',
            channel_count=1,
            nominal_srate=0,
            channel_format='int32',
            source_id='paradigm_triggers'  # Same source_id as control panel
        )
        _lsl_outlet = pylsl.StreamOutlet(info)
        print("LSL stream created successfully")
        return True
    except ImportError:
        print("Warning: pylsl not available - LSL triggers disabled")
        return False
    except Exception as e:
        print(f"Error creating LSL outlet: {e}")
        return False

def send_lsl_trigger(trigger_value):
    """Send LSL trigger"""
    global _lsl_outlet
    if _lsl_outlet:
        try:
            _lsl_outlet.push_sample([trigger_value])
            print(f"LSL trigger sent: {trigger_value}")
            return True
        except Exception as e:
            print(f"Error sending LSL trigger: {e}")
            return False
    return False

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

def send_keystroke(pygame_window_name=None, use_lsl=False):
    """
    Unified function to send keystroke events to all possible devices with robust error handling
    
    Args:
        pygame_window_name: Name of the pygame window to return focus to after sending keystrokes
        use_lsl: If True, send LSL triggers instead of keystrokes for old NIRS device
    
    Returns:
        bool: True if any keystroke/trigger was sent successfully
    """
    # Track if any keystroke was sent successfully
    success = False
    
    # -- new NIR input (always use keystrokes for new device)
    try:
        nNIR = "Aurora fNIRS"
        nNIR_hwnd = find_window_with_partial_name(nNIR)
        if nNIR_hwnd:
            ensure_window_focus(nNIR_hwnd)
            keybd_event(0x77, 0, 0, 0)  # key down for 'F8'
            time.sleep(0.01)
            keybd_event(0x77, 0, win32con.KEYEVENTF_KEYUP, 0)
            success = True
            print(f"Sent keystroke to {nNIR}")
        else:
            print(f"{nNIR} window not found")
    except Exception as e:
        print(f"Error sending keystroke to {nNIR}: {e}")
    
    # -- old NIR input (use LSL if enabled, otherwise keystrokes)
    try:
        oNIR = "NIRx NIRStar"
        if use_lsl:
            # Send LSL trigger instead of keystroke for old NIRS
            if send_lsl_trigger(8):  # Use trigger value 8 for old NIRS
                success = True
                print(f"Sent LSL trigger to {oNIR}")
            else:
                print(f"Failed to send LSL trigger to {oNIR}")
        else:
            # Traditional keystroke method
            oNIR_hwnd = win32gui.FindWindow(None, "NIRx NIRStar 15.3")
            if oNIR_hwnd: 
                # Still try to send message even if setting foreground failed
                ensure_window_focus(oNIR_hwnd) 
                time.sleep(0.01)
                keybd_event(0x77, 0, 0, 0)  # key down for 'F8'
                time.sleep(0.01)
                keybd_event(0x77, 0, win32con.KEYEVENTF_KEYUP, 0)
                success = True
                print(f"Sent keystroke to {oNIR}")
            else:
                print(f"{oNIR} window not found")
    except Exception as e:
        print(f"Error sending trigger/keystroke to {oNIR}: {e}")
        
    # -- new EEG input (always use keystrokes)
    try:
        nEEG = 'g.Recorder'
        nEEG_hwnd = find_window_with_partial_name(nEEG)
        if nEEG_hwnd:
            ensure_window_focus(nEEG_hwnd)  
            keybd_event(0x38, 0, 0, 0)  # key down for '8'
            time.sleep(0.03)
            keybd_event(0x38, 0, win32con.KEYEVENTF_KEYUP, 0)
            success = True
            print(f"Sent keystroke to {nEEG}")
        else:
            print(f"{nEEG} window not found")
    except Exception as e:
        print(f"Error sending keystroke to {nEEG}: {e}")
        
    # -- old EEG input (use LSL if enabled, otherwise keystrokes)
    try:
        oEEG = "EmotivPRO"
        if False:#use_lsl:
            # Send LSL trigger instead of keystroke for old EEG
            if send_lsl_trigger(8):  # Use trigger value 8 for old EEG
                success = True
                print(f"Sent LSL trigger to {oEEG}")
            else:
                print(f"Failed to send LSL trigger to {oEEG}")
        else:
            # Traditional keystroke method
            oEEG_hwnd = find_window_with_partial_name(oEEG)
            if oEEG_hwnd:
                ensure_window_focus(oEEG_hwnd)
                time.sleep(0.01)
                keybd_event(0x38, 0, 0, 0)  # key down for '8'
                time.sleep(0.01)
                keybd_event(0x38, 0, win32con.KEYEVENTF_KEYUP, 0)
                success = True
                print(f"Sent keystroke to {oEEG}")
            else:
                print(f"{oEEG} window not found")
    except Exception as e:
        print(f"Error sending trigger/keystroke to {oEEG}: {e}")
    
    # Try to return to pygame window
    if pygame_window_name:
        try:
            pygame_hwnd = win32gui.FindWindow(None, pygame_window_name)
            ensure_window_focus(pygame_hwnd)
        except Exception as e:
            print(f"Error returning to pygame window: {e}")
    
    # Return overall success status
    return success

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