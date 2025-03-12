# Import dependencies
import pygame
import numpy as np
import pandas as pd
import sys
import json
import os
import win32gui
import win32con
from win32api import PostMessage, keybd_event
import time
import random

# Defined constant variables
STIM_PATH = r"C:\Projects\TBI\_ext\letter_stimulus.csv"
SAVE_PATH = r"C:\Projects\TBI"

MSG_INTRO = ['WORKING MEMORY EXERCISE','PLEASE GET COMFORTABLE BEFORE WE', 
             'PERFORM BASELINE MEASUREMENTS','READY?']

MSG_INSTR = [['Any time you see','W','press', '[ Spacebar ]'],
             ['Any time you see','the same letter back to back',
                                     'press', '[ Spacebar ]'],
             ['Any time you see','W','press', '[ Spacebar ]'],
             ['Any time you see','a letter that matches the second to last,',
              'letter that you saw', 'press', '[ Spacebar ]']]

MSG_CLOSE = ['You have completed the', 'memory exercise.','Please stand by.']

CLC_INSTR = 10000
CLC_CLOSE = 10000
CLC_STIMU = 500
CLC_INTER = 1500
REST_PERIOD = 72000

width_screen = 1920
height_screen = 1080

# Set up pygame
def init_game():
    pygame.init()
    pygame.display.set_caption("Working Memory Task")

    screen = pygame.display.set_mode((width_screen, height_screen), display=1)
    
    clock = pygame.time.Clock()
    font = pygame.font.SysFont(None, 120)
    return screen, clock, font

def update_progress(progress_file, progress, status):
    """Update progress file with current progress and status"""
    try:
        with open(progress_file, 'w') as f:
            json.dump({
                "progress": progress,
                "status": status
            }, f)
    except:
        pass

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
    pygame_hwnd = win32gui.FindWindow(None, "Working Memory Task")
    # Handle Aurora fNIRS with PostMessage
    aurora_hwnd = win32gui.FindWindow(None, "Aurora fNIRS")
    if aurora_hwnd:
        PostMessage(aurora_hwnd, win32con.WM_KEYDOWN, win32con.VK_F8, 0)
        time.sleep(0.01)
        PostMessage(aurora_hwnd, win32con.WM_KEYUP, win32con.VK_F8, 0)
    else:
        print("Aurora fNIRS window not found")

    # Handle g.Recorder with keybd_event
    recorder_hwnd = find_window_with_partial_name("g.Recorder")
    if recorder_hwnd:
        win32gui.SetForegroundWindow(recorder_hwnd)
        time.sleep(0.05)
        keybd_event(0x38, 0, 0, 0)  # key down for '8'
        time.sleep(0.01)
        keybd_event(0x38, 0, win32con.KEYEVENTF_KEYUP, 0)
        win32gui.SetForegroundWindow(pygame_hwnd)
    else:
        print("g.Recorder window not found")
            
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
    return False

def display_message(screen, font, message, wait=0, custom_font_size=None):
    bg_color = (0,0,0)
    font_color = (255,255,255)
    
    screen.fill(bg_color)
    text = []
    rect = []
    
    if not isinstance(message, list):
        # Single message - use custom font size if provided, otherwise larger font
        display_font = pygame.font.SysFont(None, custom_font_size if custom_font_size else 300)
        text.append(display_font.render(message, True, font_color))
        rect.append(text[0].get_rect(center=(width_screen//2, height_screen//2)))
    else:
        # Multiple messages - use standard font size
        for i, line in enumerate(message):
            text.append(font.render(line, True, font_color))
            rect.append(text[i].get_rect(center=(width_screen//2, height_screen//2 + ((i-1)*120))))
    
    for line in range(len(text)):
        screen.blit(text[line], rect[line])  
    
    pygame.display.flip()
    if wait:
        start_time = pygame.time.get_ticks()
        while pygame.time.get_ticks() - start_time < wait:
            if check_for_quit():
                return True
    return False

def run_trials(screen, font, stimulus, stim_type, progress_file= None):
    # -- Initialize output storage variables
    temp_st, temp_sm, temp_er, temp_ar, temp_rt = [], [], [], [], []
    # -- Iterate through stimuli
    for enum, i in enumerate(stim_type):
        # Insert update
        if progress_file:
            update_progress(progress_file, 40+10*enum, f"Performing {i}")
        # Display instruction screen    
        if display_message(screen, font, MSG_INSTR[enum], CLC_INSTR):
            return pd.DataFrame()  # Return empty DataFrame if quit
        # Set response
        response = stimulus.iloc[:, stimulus.columns.get_loc(i) + 1]
        # Insert markers
        send_keystroke()
        
        for stim, resp in zip(stimulus[i], response):
            start_time = pygame.time.get_ticks()
            key_pressed = None
            timepressed = np.inf
            
            woodpecker = random.uniform(0.9,1.1)
            while pygame.time.get_ticks() - start_time < woodpecker * (CLC_STIMU + CLC_INTER):
                current_time = pygame.time.get_ticks() - start_time
                display_message(screen, font, str(stim) if current_time < CLC_STIMU else "+")
                
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        return pd.DataFrame()
                    if event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_c and (pygame.key.get_mods() & pygame.KMOD_CTRL):
                            return pd.DataFrame()
                        elif key_pressed is None:
                            key_pressed = event.key
                            timepressed = current_time / 1000
                            
            print(f"Key pressed: {key_pressed} @{timepressed}")
            temp_st.append(i)
            temp_sm.append(stim)
            temp_er.append(resp)
            temp_ar.append(key_pressed)
            temp_rt.append(timepressed)

    return pd.DataFrame({'StimulusType'    : temp_st, 
                         'Stimulus'        : temp_sm, 
                         'ExpectedResponse': temp_er, 
                         'ActualResponse'  : temp_ar, 
                         'ReactionTime'    : temp_rt})

def main():
    # Variable setup
    print("Debug: System arguments:", sys.argv)
    subject_id = sys.argv[1] if len(sys.argv) > 1 else "UNKNOWN"
    progress_file = sys.argv[2] if len(sys.argv) > 2 else None
    screen, clock, font = init_game()
    stimulus = pd.read_csv(STIM_PATH)
    stim_type = [col for col in stimulus.columns if not col.endswith('response')]
    
    print(f"Debug: Subject ID: {subject_id}")
    print(f"Debug: Progress file: {progress_file}")
    
    if progress_file:
        # Test writing to progress file
        try:
            update_progress(progress_file, 0, "Starting up...")
            print("Debug: Successfully wrote to progress file")
        except Exception as e:
            print(f"Debug: Error writing to progress file: {e}")
    
    # Waiting room
    while True:
        clock.tick(60)
        display_message(screen, font, MSG_INTRO)
        
        if check_for_quit():
            return
            
        keys = pygame.key.get_pressed()
        if keys[pygame.K_w]:
            break
    
    if progress_file:
        update_progress(progress_file, 10, "Resting state in progress...")
    
    # Add 72-second resting period with large "+" symbol
    send_keystroke()
    if display_message(screen, font, "+", REST_PERIOD, custom_font_size=300):
        return
    send_keystroke()
    
    if progress_file:
        update_progress(progress_file, 30, "Rest state complete. Trials ready.")
    
    # Cognitive trial
    if progress_file:    
        results = run_trials(screen, font, stimulus, stim_type, progress_file)
    else:
        results = run_trials(screen, font, stimulus, stim_type)
    
    if progress_file:
        update_progress(progress_file, 90, "Saving results...")
    
    # Save results and quit
    if not results.empty:
        save_path = os.path.join(SAVE_PATH, f"{subject_id}.csv")
        results.to_csv(save_path, index=False)
    
    if progress_file:
        update_progress(progress_file, 95, "Finishing up...")
    
    display_message(screen, font, MSG_CLOSE)
    pygame.time.wait(CLC_CLOSE)
    
    if progress_file:
        update_progress(progress_file, 100, "Complete")
    
    # Keep the black screen until manual close or ctrl+c
    while True:
        if check_for_quit():
            return
        screen.fill((0,0,0))
        pygame.display.flip()

if __name__ == "__main__":
    main()