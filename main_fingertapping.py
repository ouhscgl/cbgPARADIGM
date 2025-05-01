#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import pygame
import sys
import json
from pathlib import Path
import win32gui
import win32con
from win32api import PostMessage, keybd_event
import time
import os

# User defined variables
# -- variable names, paths
WINDOW_NAME   = "Small Motor Task"
# -- constants
TASK_DURATION = 10000
REST_DURATION = 15000
RESTING_STATE = 60000
REPETITIONS   = 3 
# -- screen settings
SCREEN_WIDTH  = 1920
SCREEN_HEIGHT = 1080

def update_progress(progress_file, progress, status):
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

def check_for_quit():
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

def display_message(screen, font, message, position=(SCREEN_WIDTH//2, SCREEN_HEIGHT//2)):
    text = font.render(message, True, (255, 255, 255))
    rect = text.get_rect(center=position)
    screen.blit(text, rect)
    pygame.display.flip()

def wait_period(screen, duration_ms, progress_file=None, status=None, progress_start=0, progress_end=0):
    start_time = pygame.time.get_ticks()
    
    while pygame.time.get_ticks() - start_time < duration_ms:
        if check_for_quit():
            return True
            
        # Update progress if needed
        if progress_file and status and progress_end > progress_start:
            elapsed = pygame.time.get_ticks() - start_time
            progress_percent = round(progress_start + (elapsed / duration_ms) * (progress_end - progress_start), 2)
            update_progress(progress_file, progress_percent, status)
            
        # Ensure the screen stays black
        # screen.fill((0, 0, 0))
        # pygame.display.flip()
        
        # Small delay to prevent high CPU usage
        pygame.time.wait(100)
        
    return False

def play_audio(audio_file):
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

def find_window_with_partial_name(partial_name):
    def enum_windows_callback(hwnd, results):
        window_text = win32gui.GetWindowText(hwnd)
        if partial_name in window_text:
            results.append((hwnd, window_text))
        return True
   
    results = []
    win32gui.EnumWindows(enum_windows_callback, results)
    return results[0][0] if results else None

def send_keystroke():
    # -- store task window handle
    pygame_hwnd = win32gui.FindWindow(None, WINDOW_NAME)
    # -- new NIR input
    nNIR = "Aurora fNIRS"
    nNIR_hwnd = find_window_with_partial_name(nNIR)
    if nNIR_hwnd:
        PostMessage(nNIR_hwnd, win32con.WM_KEYDOWN, win32con.VK_F8, 0)
        time.sleep(0.01)
        PostMessage(nNIR_hwnd, win32con.WM_KEYUP, win32con.VK_F8, 0)
    else:
        print(f"{nNIR} window not found")
    # -- old NIR input
    oNIR = "NIRx NIRStar"
    oNIR_hwnd = find_window_with_partial_name(oNIR)
    if oNIR_hwnd:
        PostMessage(oNIR_hwnd, win32con.WM_KEYDOWN, win32con.VK_F8, 0)
        time.sleep(0.01)
        PostMessage(oNIR_hwnd, win32con.WM_KEYUP, win32con.VK_F8, 0)
    else:
        print(f"{oNIR} window not found")
    # -- new EEG input
    nEEG = 'g.Recorder'
    nEEG_hwnd = find_window_with_partial_name(nEEG)
    if nEEG_hwnd:
        win32gui.SetForegroundWindow(nEEG_hwnd)
        time.sleep(0.05)
        keybd_event(0x38, 0, 0, 0)  # key down for '8'
        time.sleep(0.01)
        keybd_event(0x38, 0, win32con.KEYEVENTF_KEYUP, 0)
        win32gui.SetForegroundWindow(pygame_hwnd)
    else:
        print(f"{nEEG} window not found")
    # -- old EEG input
    oEEG = "EmotivPRO"
    oEEG_hwnd = find_window_with_partial_name(oEEG)
    if oEEG_hwnd:
        PostMessage(oEEG_hwnd, win32con.WM_KEYDOWN, win32con.VK_F8, 0)
        time.sleep(0.01)
        PostMessage(oEEG_hwnd, win32con.WM_KEYUP, win32con.VK_F8, 0)  # Fixed: was using nNIR_hwnd
    else:
        print(f"{oEEG} window not found")

def main():
    # Command line arguments
    subject_id = sys.argv[1] if len(sys.argv) > 1 else "UNKNOWN"
    progress_file = sys.argv[2] if len(sys.argv) > 2 else None
    print(f"Subject ID: {subject_id}")
    
    # Initialize pygame
    pygame.mixer.init()
    pygame.init()
    pygame.display.set_caption(WINDOW_NAME)
    
    # Initial setup
    # -- create display, initialize font and audio path
    audio_path = Path(os.path.dirname(os.path.abspath(__file__))) / '_resources'
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT), display=1)
    font = pygame.font.SysFont(None, 120)
    status = ''
    # -- display initial instructions
    screen.fill((0, 0, 0))
    display_message(screen, font, "The exercise will begin shortly")  # Fixed spelling
    display_message(screen, font, "Please get comfortable.", (SCREEN_WIDTH//2, SCREEN_HEIGHT//2 + 80))
    pygame.display.flip()
    # -- update progress file
    if progress_file:
        update_progress(progress_file, 0, "Setup complete. Press any key to continue...")
    # Lobby
    # -- enter waiting room
    waiting = True
    while waiting:
        for event in pygame.event.get():
            # -- quit on quit
            if event.type == pygame.QUIT:
                pygame.quit()
                return
            if event.type == pygame.KEYDOWN:
                # -- continue to stimulus on [ W ]
                if event.key == pygame.K_w:
                    waiting = False
                # -- quit on Ctrl + C
                if event.key == pygame.K_c and (pygame.key.get_mods() & pygame.KMOD_CTRL):
                    pygame.quit()
                    return
    # -- clear screen
    screen.fill((0, 0, 0))
    pygame.display.flip()
    
    # Initial resting period with fixation cross
    screen.fill((0, 0, 0))
    display_message(screen, font, "+")
    pygame.display.flip()
    send_keystroke()
    # -- update progress file
    if progress_file:
        status = "Initial resting state."
        update_progress(progress_file, 5, status)
    # -- wait for the resting period (60 seconds)
    if wait_period(screen, RESTING_STATE, progress_file, status, 5, 10):
        return
    send_keystroke()
    
    # Initial 3-second countdown
    for i in range(3, 0, -1):
        # -- visual feedback
        screen.fill((0, 0, 0))
        display_message(screen, font, f"Starting in {i}...")
        pygame.display.flip()
        # -- audio feedback
        if play_audio(audio_path / f'countdown_{i}.mp3'):
            return
        # -- wait on condition
        pygame.time.wait(1000)
        if check_for_quit():
            return
    # -- clear screen
    screen.fill((0, 0, 0))
    pygame.display.flip()
    # --update progress file
    if progress_file:
        update_progress(progress_file, 10, "Beginning exercise sequence...")
    
    # Exercise sequence
    # -- persistent variable setup
    progress_per_segment = 90 / (REPETITIONS * 2)  # Each repetition has 2 sides (LEFT, RIGHT)
    progress_base = 10  # Starting from 10% after initial setup and resting
    directions = ["LEFT", "RIGHT"]
    # -- exercise loop 
    for rep in range(REPETITIONS):
        for side_idx, direction in enumerate(directions):
            current_progress = progress_base + (rep * 2 + side_idx) * progress_per_segment
            
            # Exercise phase
            # -- update progress file
            if progress_file:
                status = f"Exercise {direction} in repetition {rep+1}/{REPETITIONS}."
                update_progress(progress_file, current_progress, status)
            
            # -- play directional instruction (LEFT / RIGHT)
            send_keystroke()
            screen.fill((0, 0, 0))
            display_message(screen, font, f"{direction}")
            pygame.display.flip()
            audio_file = str(audio_path / f"{direction}.mp3")
            if play_audio(audio_file):
                return
            
            # -- update progress file
            if progress_file:
                status = f"Fingertapping {direction} in repetition {rep+1}/{REPETITIONS}."
                update_progress(progress_file, current_progress, status)
            
            # -- wait for task duration
            if wait_period(screen, TASK_DURATION, progress_file, status, 
                          current_progress, current_progress + progress_per_segment / 2):
                return
            
            # Rest phase
            # -- update progress file
            if progress_file:
                status = f"Stopping {direction} in repetition {rep+1}/{REPETITIONS}."
                update_progress(progress_file, current_progress + progress_per_segment / 2, status)
            
            # -- play rest instruction
            send_keystroke()
            screen.fill((0, 0, 0))
            pygame.display.flip()
            audio_file = str(audio_path / "STOP.mp3")
            if play_audio(audio_file):
                return
            
            # -- update progress file
            if progress_file:
                status = f"Resting {direction} in repetition {rep+1}/{REPETITIONS}."
                update_progress(progress_file, current_progress + progress_per_segment / 2, status)
            
            # -- wait for rest duration
            if wait_period(screen, REST_DURATION, progress_file, status, 
                          current_progress + progress_per_segment / 2, 
                          current_progress + progress_per_segment):
                return
    
    # Terminate
    # -- update progress file
    if progress_file:
        update_progress(progress_file, 95, "Sequence complete")
    
    # -- display terminal instructions
    screen.fill((0, 0, 0))
    display_message(screen, font, "You have completed the exercise.")
    display_message(screen, font, "Please stand by.", (SCREEN_WIDTH//2, SCREEN_HEIGHT//2 + 80))
    pygame.display.flip()
    pygame.time.wait(TASK_DURATION)
    
    # -- update progress file
    if progress_file:
        update_progress(progress_file, 100, "Complete")
    
    # -- clear screen
    screen.fill((0, 0, 0))
    pygame.display.flip()
    
    # -- wait for Esc or Ctrl+C to exit
    while True:
        if check_for_quit():
            return

if __name__ == "__main__":
    main()