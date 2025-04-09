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
import re
import argparse
from pathlib import Path

# Window name constant
WINDOW_NAME = "Working Memory Task"
SAVE_PATH   = r"C:\Projects"
# Define experiment profiles
EXPERIMENT_PROFILES = {
    "TBI_letter": {
        "stim_type": "letter_stimulus.csv",
        "rest_period": 1,
        "rest_states": ["open"],
    },
    "NRA_letter": {
        "stim_type": "letter_stimulus.csv",
        "rest_period": 60000,
        "rest_states": ["open"],
    },
    "NRA_number": {
        "stim_type": "number_stimulus.csv",
        "rest_period": 60000,
        "rest_states": ["open"],
    },
    "SCog_letter": {
        "stim_type": "letter_stimulus.csv",
        "rest_period": 300000,
        "rest_states": ["closed", "open"],
    }
}

# Common message constants
MSG_INTRO = ['WORKING MEMORY EXERCISE','PLEASE GET COMFORTABLE BEFORE WE', 
             'PERFORM BASELINE MEASUREMENTS','READY?']

MSG_INSTR = [['Any time you see','W','press', '[ Spacebar ]'],
             ['Any time you see','the same letter back to back',
                                     'press', '[ Spacebar ]'],
             ['Any time you see','W','press', '[ Spacebar ]'],
             ['Any time you see','a letter that matches the second to last,',
              'letter that you saw', 'press', '[ Spacebar ]']]

# Rest state messages

MSG_REST_CLOSED = ['Please close your eyes',
                  'keep them closed until stated otherwise',
                  'Relax for the duration given']

MSG_REST_OPEN = ['Please keep your eyes open',
                'and focus on the + symbol',
                'Relax for the duration given']

MSG_CLOSE = ['You have completed the', 'memory exercise.','Please stand by.']

# Timing constants
CLC_INSTR = 10000  # 10 seconds
CLC_CLOSE = 10000  # 10 seconds
CLC_STIMU = 500    # 0.5 seconds
CLC_INTER = 1500   # 1.5 seconds

# Screen dimensions
width_screen = 1920
height_screen = 1080

# Set up pygame
def init_game():
    pygame.init()
    pygame.display.set_caption(WINDOW_NAME)

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
    except Exception as e:
        print(f"Error updating progress: {e}")
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
    """Unified function to send keystroke events to all possible devices"""
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
        PostMessage(oEEG_hwnd, win32con.WM_KEYUP, win32con.VK_F8, 0)
    else:
        print(f"{oEEG} window not found")

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

def display_message(screen, font, message, wait=0, custom_font_size=None, progress_file=None, status=None, progress_start=None, progress_end=None):
    """Display message with optional progress updates during wait period"""
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
            # Update progress frequently during wait periods if progress file is provided
            if progress_file and status and progress_start is not None and progress_end is not None:
                elapsed = pygame.time.get_ticks() - start_time
                progress_percent = round(progress_start + (elapsed / wait) * (progress_end - progress_start), 2)
                update_progress(progress_file, progress_percent, status)
                
            # Check for quit events
            if check_for_quit():
                return True
                
            # Small delay to prevent high CPU usage but update frequently
            pygame.time.wait(50)  # Update every 50ms like fingertapping
    return False

def run_rest_states(screen, font, rest_states, rest_period, progress_file=None):
    """Run the appropriate rest states based on experiment profile"""
    # Rest states should take 0-30% of the total progress
    total_rest_progress = 30.0
    progress_per_state = total_rest_progress / len(rest_states) if rest_states else 0
    
    for enum, state in enumerate(rest_states):
        # Calculate start and end progress for this rest state
        progress_start = enum * progress_per_state
        progress_end = (enum + 1) * progress_per_state
        
        if progress_file:
            update_progress(progress_file, progress_start, f"Starting rest state {enum+1}/{len(rest_states)}...")
        
        if state == 'closed':
            # Show instructions (takes 20% of this state's progress)
            instr_progress_start = progress_start
            instr_progress_end = progress_start + (progress_per_state * 0.2)
            
            if display_message(screen, font, MSG_REST_CLOSED, CLC_INSTR, 
                              progress_file=progress_file, 
                              status=f"Rest state {enum+1}: instructions (eyes closed)", 
                              progress_start=instr_progress_start, 
                              progress_end=instr_progress_end):
                return True
                
            send_keystroke()
            
            # Rest period (takes remaining 80% of this state's progress)
            rest_progress_start = instr_progress_end
            rest_progress_end = progress_end
            
            if display_message(screen, font, "", rest_period, custom_font_size=300,
                              progress_file=progress_file, 
                              status=f"Rest state {enum+1}: in progress (eyes closed)",
                              progress_start=rest_progress_start, 
                              progress_end=rest_progress_end):
                return True
        
        elif state == 'open':
            # Show instructions (takes 20% of this state's progress)
            instr_progress_start = progress_start
            instr_progress_end = progress_start + (progress_per_state * 0.2)
            
            if display_message(screen, font, MSG_REST_OPEN, CLC_INSTR,
                              progress_file=progress_file, 
                              status=f"Rest state {enum+1}: instructions (eyes open)",
                              progress_start=instr_progress_start, 
                              progress_end=instr_progress_end):
                return True
                
            send_keystroke()
            
            # Rest period (takes remaining 80% of this state's progress)
            rest_progress_start = instr_progress_end
            rest_progress_end = progress_end
            
            if display_message(screen, font, "+", rest_period, custom_font_size=300,
                              progress_file=progress_file, 
                              status=f"Rest state {enum+1}: in progress (eyes open)",
                              progress_start=rest_progress_start, 
                              progress_end=rest_progress_end):
                return True
        
        elif state == 'none':
            pass
        
    if progress_file:
        update_progress(progress_file, 30, "Rest states complete. Proceeding to task.")
    return False

def run_trials(screen, font, stimulus, stim_type, progress_file=None, subject_id=None):
    """Run the cognitive trials portion of the experiment"""
    # -- Initialize output storage variables
    temp_st, temp_sm, temp_er, temp_ar, temp_rt = [], [], [], [], []
    results_df = pd.DataFrame()  # Empty DataFrame to store results
    
    # Trials take 30-90% of the total progress (60% total)
    total_trials_progress = 60.0
    progress_per_trial_type = total_trials_progress / len(stim_type) if stim_type else 0
    
    # Create a white rectangle that's half the screen height
    rect_size = height_screen // 2  # Half of screen height
    rectangle = pygame.Rect((width_screen - rect_size) // 2, (height_screen - rect_size) // 2, rect_size, rect_size)
    rectangle.center = (width_screen // 2, height_screen // 2)  # Center on screen
    
    # -- Iterate through stimuli
    for enum, i in enumerate(stim_type):
        # Calculate progress percentage for this trial block
        progress_start = 30.0 + (enum * progress_per_trial_type)
        progress_end = 30.0 + ((enum + 1) * progress_per_trial_type)
        
        # Insert update
        if progress_file:
            update_progress(progress_file, progress_start, f"Starting trial block: {i}")
            
        # Display instruction screen (takes 10% of this trial type's progress)
        instr_progress_start = progress_start
        instr_progress_end = progress_start + (progress_per_trial_type * 0.1)
        
        if display_message(screen, font, MSG_INSTR[enum], CLC_INSTR,
                          progress_file=progress_file,
                          status=f"Instructions for {i}",
                          progress_start=instr_progress_start,
                          progress_end=instr_progress_end):
            return pd.DataFrame()  # Return empty DataFrame if quit
            
        # Set response
        response = stimulus.iloc[:, stimulus.columns.get_loc(i) + 1]
        # Insert markers
        send_keystroke()
        
        # Stimuli take remaining 90% of this trial type's progress
        stimuli_progress_start = instr_progress_end
        stimuli_progress_end = progress_end
        
        # Calculate progress increment per stimulus
        stim_count = len(stimulus[i])
        progress_per_stim = (stimuli_progress_end - stimuli_progress_start) / stim_count if stim_count > 0 else 0
        
        for idx, (stim, resp) in enumerate(zip(stimulus[i], response)):
            # Progress for this individual stimulus
            stim_progress_start = stimuli_progress_start + (idx * progress_per_stim)
            stim_progress_end = stimuli_progress_start + ((idx + 1) * progress_per_stim)
            
            # Update progress for each stimulus
            if progress_file:
                update_progress(progress_file, stim_progress_start, 
                               f"Processing stimulus {idx+1}/{stim_count} in {i}")
            
            start_time = pygame.time.get_ticks()
            key_pressed = None
            timepressed = np.inf
            
            # Progress tracking variables
            last_update_time = start_time
            update_interval = 50  # Update every 50ms
            
            woodpecker = random.uniform(0.9, 1.1)
            total_duration = woodpecker * (CLC_STIMU + CLC_INTER)
            
            while pygame.time.get_ticks() - start_time < total_duration:
                current_time = pygame.time.get_ticks() - start_time
                is_stimulus_phase = current_time < CLC_STIMU
                
                # Fill screen with black background
                screen.fill((0, 0, 0))
                
                # Draw the white rectangle
                pygame.draw.rect(screen, (255, 255, 255), rectangle, 2)
                
                if is_stimulus_phase:
                    # Display the stimulus letter/number in white 
                    stim_font = pygame.font.SysFont(None, 300)
                    text = stim_font.render(str(stim), True, (255, 255, 255))  # White text
                    rect = text.get_rect(center=(width_screen//2, height_screen//2))
                    screen.blit(text, rect)
                else:
                    # Empty fixation cross as requested (still showing the white rectangle)
                    fix_font = pygame.font.SysFont(None, 300)
                    text = fix_font.render("", True, (255, 255, 255))  # Empty text, black color
                    rect = text.get_rect(center=(width_screen//2, height_screen//2))
                    screen.blit(text, rect)
                
                pygame.display.flip()
                
                # Check for events
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        return results_df
                    if event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_c and (pygame.key.get_mods() & pygame.KMOD_CTRL):
                            return results_df
                        elif key_pressed is None:
                            key_pressed = event.key
                            timepressed = current_time / 1000
                
                # Update progress more frequently
                current_update_time = pygame.time.get_ticks()
                if progress_file and (current_update_time - last_update_time >= update_interval):
                    progress_percent = stim_progress_start + (current_time / total_duration) * (stim_progress_end - stim_progress_start)
                    phase_name = "Stimulus" if is_stimulus_phase else "Fixation"
                    update_progress(progress_file, progress_percent, 
                                   f"{phase_name} {idx+1}/{stim_count} in {i}")
                    last_update_time = current_update_time
                
                # Small delay to prevent high CPU usage
                pygame.time.wait(10)
                
            print(f"Key pressed: {key_pressed} @{timepressed}")
            temp_st.append(i)
            temp_sm.append(stim)
            temp_er.append(resp)
            temp_ar.append(key_pressed)
            temp_rt.append(timepressed)
            
            # Save data after each user input
            # Update the results DataFrame
            results_df = pd.DataFrame({
                'StimulusType'    : temp_st, 
                'Stimulus'        : temp_sm, 
                'ExpectedResponse': temp_er, 
                'ActualResponse'  : temp_ar, 
                'ReactionTime'    : temp_rt
            })
            
            # Save interim results if subject_id is provided
            if subject_id and subject_id != "UNKNOWN":
                save_results(results_df, Path(SAVE_PATH), subject_id, interim=True)
        
        # Update progress at end of trial block
        if progress_file:
            update_progress(progress_file, progress_end, f"Completed trial block: {i}")

    return results_df

def save_results(results, save_path, subject_id, interim=False):
    """Save results using the appropriate method for the experiment profile"""
    if results.empty or subject_id == "UNKNOWN":
        return False
        
    match = re.match(r'^([A-Za-z]+)', subject_id)
    if match:
        project = match.group(1)
        # Create project directory if it doesn't exist
        project_dir = os.path.join(save_path, project)
        os.makedirs(project_dir, exist_ok=True)
        
        # Add interim suffix if this is an interim save
        filename = f"{subject_id}_interim.csv" if interim else f"{subject_id}.csv"
        save_file = os.path.join(project_dir, filename)
        
        results.to_csv(save_file, index=False)
        return True
    
    return False

def parse_arguments():
    """Parse command line arguments with defaults"""
    parser = argparse.ArgumentParser(description='Run N-back experiment with different profiles')
    parser.add_argument('--subject_id', default="UNKNOWN", help='Subject ID for data collection')
    parser.add_argument('--progress_file', default=None, help='File path for progress tracking')
    parser.add_argument('--profile', default="TBI_letter", 
                        choices=EXPERIMENT_PROFILES.keys(),
                        help='Experiment profile to use')
    
    # Handle both direct argparse and old-style sys.argv
    if len(sys.argv) == 1:
        # No arguments provided, use defaults
        return parser.parse_args([])
    elif len(sys.argv) >= 2 and not sys.argv[1].startswith('--'):
        # Old style: first arg is subject_id
        subject_id = sys.argv[1]
        progress_file = sys.argv[2] if len(sys.argv) > 2 else None
        args = parser.parse_args([])
        args.subject_id = subject_id
        args.progress_file = progress_file
        return args
    else:
        # New style: parse normally
        return parser.parse_args()

def main():
    # Parse command line arguments
    args = parse_arguments()
    
    # Get the selected experiment profile
    profile = EXPERIMENT_PROFILES[args.profile]
    
    print(f"Debug: Using profile: {args.profile}")
    print(f"Debug: Subject ID: {args.subject_id}")
    print(f"Debug: Progress file: {args.progress_file}")
    
    # Initialize pygame and other resources
    screen, clock, font = init_game()
    stim_root = Path(os.path.dirname(os.path.abspath(__file__))) / '_resources'
    stimulus = pd.read_csv(stim_root / profile["stim_type"])
    stim_type = [col for col in stimulus.columns if not col.endswith('response')]
    
    if args.progress_file:
        # Test writing to progress file
        try:
            update_progress(args.progress_file, 0, "Starting up...")
            print("Debug: Successfully wrote to progress file")
        except Exception as e:
            print(f"Debug: Error writing to progress file: {e}")
    
    # Waiting room
    waiting = True
    while waiting:
        clock.tick(60)
        display_message(screen, font, MSG_INTRO)
        
        if check_for_quit():
            return
            
        keys = pygame.key.get_pressed()
        if keys[pygame.K_w]:
            waiting = False
            
        # Small delay to prevent high CPU usage
        pygame.time.wait(50)
    
    # Run the appropriate rest states based on profile
    if run_rest_states(screen, font, profile["rest_states"], profile["rest_period"], args.progress_file):
        return  # Early exit if user quits during rest states
    
    # Cognitive trial
    results = run_trials(screen, font, stimulus, stim_type, args.progress_file, args.subject_id)
    
    if args.progress_file:
        update_progress(progress_file=args.progress_file, progress=90, status="Saving final results...")
    
    # Save results using the appropriate method
    save_results(results, Path(SAVE_PATH), args.subject_id)
    
    if args.progress_file:
        update_progress(progress_file=args.progress_file, progress=95, status="Finishing up...")
    
    # Show closing message with progress updates
    if display_message(screen, font, MSG_CLOSE, CLC_CLOSE,
                      progress_file=args.progress_file,
                      status="Finishing up...",
                      progress_start=95,
                      progress_end=100):
        return
    
    if args.progress_file:
        update_progress(progress_file=args.progress_file, progress=100, status="Complete")
    
    # Keep the black screen until manual close or ctrl+c
    while True:
        if check_for_quit():
            return
        screen.fill((0,0,0))
        pygame.display.flip()
        pygame.time.wait(50)  # Small delay to prevent high CPU usage

if __name__ == "__main__":
    main()