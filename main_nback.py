# Import dependencies
import pygame
import numpy as np
import pandas as pd
import sys
import json
import os
import win32gui
import random
import re
import argparse
import time
from pathlib import Path

# Import shared utility functions
from paradigm_utils import (
    update_progress, send_keystroke, check_for_quit,
    display_message, wait_period, find_window_with_partial_name,
    ensure_window_focus, create_lsl_outlet
)

# Window name constant
WINDOW_NAME = "Working Memory Task"
SAVE_PATH   = r"C:\Projects"

# Define experiment profiles
EXPERIMENT_PROFILES = {
    "TBI_letter": {
        "stim_type": "letter_stimulus.csv",
        "rest_period": 72000,
        "rest_states": ["open"],
        "appendix"   : "_NIR_EEG_COG"
    },
    "NRA_letter": {
        "stim_type": "letter_stimulus.csv",
        "rest_period": 60000,
        "rest_states": ["open"],
        "appendix"   : "_NIR_COG"
    },
    "NRA_number": {
        "stim_type": "number_stimulus.csv",
        "rest_period": 15000,
        "rest_states": ["open", "closed"],
        "appendix"   : "_EEG_COG"
    },
    "SCog_letter": {
        "stim_type": "letter_stimulus.csv",
        "rest_period": 300000,
        "rest_states": ["closed", "open"],
        "appendix"   : "_NIR_EEG_COG"
    },
    "PeterProtocol1": {
        "stim_type": "letter_stimulus.csv",
        "rest_period": 300000,
        "rest_states": ["closed", "open"],
        "appendix"   : "_NIR_EEG_COG"
    },
    "PeterProtocol2": {
        "stim_type": "number_stimulus.csv",
        "rest_period": 300000,
        "rest_states": ["closed", "open"],
        "appendix"   : "_NIR_EEG_COG"
    }
}

# Instructions for letter stimulus
LETTER_INSTRUCTIONS = [
    ['Any time you see', 'W', 'press', '[ Button ]'],
    ['Any time you see', 'the same letter back to back', 'press', '[ Button ]'],
    ['Any time you see', 'W', 'press', '[ Button ]'],
    ['Any time you see', 'a letter that matches the second to last,', 'letter that you saw', 'press [ Button ]']
]

# Instructions for number stimulus
NUMBER_INSTRUCTIONS = [
    ['Any time you see', '8', 'press', '[ Button ]'],
    ['Any time you see', 'the same number back to back', 'press', '[ Button ]'],
    ['Any time you see', '8', 'press', '[ Button ]'],
    ['Any time you see', 'a number that matches the second to last,', 'number that you saw', 'press [ Button ]']
]

# Common message constants
MSG_INTRO = ['WORKING MEMORY EXERCISE','','PLEASE GET COMFORTABLE BEFORE WE', 
             'PERFORM BASELINE MEASUREMENTS']
MSG_POSTREST = ['RESTING STATE IS COMPLETE','ARE YOU READY?']

# Rest state messages
MSG_REST_CLOSED = ['Please close your eyes']
MSG_REST_OPEN = ['Please keep your eyes open',
                'focus on the [ + ] symbol']
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

def get_instructions(stim_type):
    """Return the appropriate instructions based on stimulus type"""
    if "number" in stim_type.lower():
        return NUMBER_INSTRUCTIONS
    else:
        return LETTER_INSTRUCTIONS

def run_rest_states(screen, font, rest_states, rest_period, progress_file=None, use_lsl=False):
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
                              progress_end=instr_progress_end,
                              width_screen=width_screen,
                              height_screen=height_screen):
                return True
                
            send_keystroke(WINDOW_NAME, use_lsl=use_lsl)
            
            # Rest period (takes remaining 80% of this state's progress)
            rest_progress_start = instr_progress_end
            rest_progress_end = progress_end
            
            if display_message(screen, font, "", rest_period, custom_font_size=300,
                              progress_file=progress_file, 
                              status=f"Rest state {enum+1}: in progress (eyes closed)",
                              progress_start=rest_progress_start, 
                              progress_end=rest_progress_end,
                              width_screen=width_screen,
                              height_screen=height_screen):
                return True
        
        elif state == 'open':
            # Show instructions (takes 20% of this state's progress)
            instr_progress_start = progress_start
            instr_progress_end = progress_start + (progress_per_state * 0.2)
            
            if display_message(screen, font, MSG_REST_OPEN, CLC_INSTR,
                              progress_file=progress_file, 
                              status=f"Rest state {enum+1}: instructions (eyes open)",
                              progress_start=instr_progress_start, 
                              progress_end=instr_progress_end,
                              width_screen=width_screen,
                              height_screen=height_screen):
                return True
                
            send_keystroke(WINDOW_NAME, use_lsl=use_lsl)
            
            # Rest period (takes remaining 80% of this state's progress)
            rest_progress_start = instr_progress_end
            rest_progress_end = progress_end
            
            if display_message(screen, font, "+", rest_period, custom_font_size=300,
                              progress_file=progress_file, 
                              status=f"Rest state {enum+1}: in progress (eyes open)",
                              progress_start=rest_progress_start, 
                              progress_end=rest_progress_end,
                              width_screen=width_screen,
                              height_screen=height_screen):
                return True
        
        elif state == 'none':
            pass
        
    if progress_file:
        update_progress(progress_file, 30, "Rest states complete. Proceeding to task.")
    return False

def run_trials(screen, font, stimulus, stim_type, progress_file=None, subject_id=None, profile=None, use_lsl=False):
    pygame_hwnd = win32gui.FindWindow(None, WINDOW_NAME)
    """Run the cognitive trials portion of the experiment"""
    # -- Initialize output storage variables
    temp_st, temp_sm, temp_er, temp_ar, temp_rt = [], [], [], [], []
    results_df = pd.DataFrame()  # Empty DataFrame to store results
    
    # Get the appropriate instructions based on the stimulus type
    instructions = get_instructions(profile["stim_type"])
    image_path_appendix = ''
    if "number" in profile["stim_type"].lower():
        image_path_appendix = 'num'
    else:
        image_path_appendix = 'let'
    
    # Get the instruction images path (located in _resources/images)
    resource_path = Path(os.path.dirname(os.path.abspath(__file__))) / '_resources'
    images_path = resource_path / 'images'
    
    # Ensure images directory exists
    os.makedirs(images_path, exist_ok=True)
    
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
        
        # Look for a task-specific image for this trial
        image_path = None
        possible_image_paths = [
            images_path / f"{i.lower()}_{image_path_appendix}.png",
            images_path / f"{i.lower()}_{image_path_appendix}.jpg",
            images_path / f"task_{enum+1}_{image_path_appendix}.png",
            images_path / f"task_{enum+1}_{image_path_appendix}.jpg"
        ]
        
        for path in possible_image_paths:
            if path.exists():
                image_path = str(path)
                break
                
        # Display instruction screen (takes 10% of this trial type's progress)
        instr_progress_start = progress_start
        instr_progress_end = progress_start + (progress_per_trial_type * 0.1)
        
        if display_message(screen, font, instructions[enum], CLC_INSTR,
                          progress_file=progress_file,
                          status=f"Instructions for {i}",
                          progress_start=instr_progress_start,
                          progress_end=instr_progress_end,
                          image_path=image_path,
                          width_screen=width_screen,
                          height_screen=height_screen):
            return pd.DataFrame()  # Return empty DataFrame if quit
            
        # Set response
        response = stimulus.iloc[:, stimulus.columns.get_loc(i) + 1]
        # Insert markers
        send_keystroke(WINDOW_NAME, use_lsl=use_lsl)
        
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
                # Try to ensure focus with our function
                ensure_window_focus(pygame_hwnd)
                
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
            if subject_id and subject_id != "UNKNOWN" and profile:
                save_results(results_df, Path(SAVE_PATH), subject_id, profile.get("appendix", ""), interim=True)
        
        # Update progress at end of trial block
        if progress_file:
            update_progress(progress_file, progress_end, f"Completed trial block: {i}")

    return results_df

def save_results(results, save_path, subject_id, profile_appendix="", interim=False):
    """Save results using the appropriate method for the experiment profile"""
    if results.empty or subject_id == "UNKNOWN":
        return False
        
    match = re.match(r'^([A-Za-z]+)', subject_id)
    if match:
        project = match.group(1)
        # Create project directory if it doesn't exist
        project_dir = os.path.join(save_path, project)
        os.makedirs(project_dir, exist_ok=True)
        
        # Add interim suffix if this is an interim save and include the profile appendix
        if interim:
            filename = f"{subject_id}_interim{profile_appendix}.csv"
        else:
            filename = f"{subject_id}{profile_appendix}.csv"
        
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
    parser.add_argument('--use_lsl', action='store_true', 
                        help='Use LSL triggers for old NIRS device instead of keystrokes')
    
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
        # Check for LSL flag in remaining arguments
        if "--use_lsl" in sys.argv:
            args.use_lsl = True
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
    print(f"Debug: Use LSL: {args.use_lsl}")
    
    # Initialize LSL if requested
    lsl_initialized = False
    if args.use_lsl:
        # Small delay to ensure control panel stream is destroyed
        time.sleep(1)
        lsl_initialized = create_lsl_outlet()
        if lsl_initialized:
            print("N-back: LSL stream created successfully")
        else:
            print("Warning: Failed to create LSL stream, falling back to keystrokes")
    
    # Initialize pygame and other resources
    screen, clock, font = init_game()
    stim_root = Path(os.path.dirname(os.path.abspath(__file__))) / '_resources'
    stimulus = pd.read_csv(stim_root / profile["stim_type"])
    stim_type = [col for col in stimulus.columns if not col.endswith('response')]
    pygame_hwnd = win32gui.FindWindow(None, WINDOW_NAME)
    
    if args.progress_file:
        # Test writing to progress file
        try:
            lsl_status = " (LSL enabled)" if args.use_lsl and lsl_initialized else ""
            update_progress(args.progress_file, 0, f"Starting up...{lsl_status}")
            print("Debug: Successfully wrote to progress file")
        except Exception as e:
            print(f"Debug: Error writing to progress file: {e}")
    
    # Waiting room
    ensure_window_focus(pygame_hwnd)
    waiting = True
    while waiting:
        clock.tick(60)
        display_message(screen, font, MSG_INTRO, 
                      width_screen=width_screen, height_screen=height_screen)
        
        if check_for_quit():
            return
            
        keys = pygame.key.get_pressed()
        if keys[pygame.K_w]:
            waiting = False
            
        # Small delay to prevent high CPU usage
        pygame.time.wait(50)
    
    # Run the appropriate rest states based on profile
    if run_rest_states(screen, font, profile["rest_states"], profile["rest_period"], 
                      args.progress_file, use_lsl=args.use_lsl and lsl_initialized):
        return  # Early exit if user quits during rest states
    
    # Waiting room
    ensure_window_focus(pygame_hwnd)
    waiting = True
    while waiting:
        clock.tick(60)
        display_message(screen, font, MSG_POSTREST, 
                     width_screen=width_screen, height_screen=height_screen)
        
        if check_for_quit():
            return
        keys = pygame.key.get_pressed()
        if keys[pygame.K_w]:
            waiting = False
        pygame.time.wait(50)
    
    # Cognitive trial
    results = run_trials(screen, font, stimulus, stim_type, args.progress_file, 
                        args.subject_id, profile, use_lsl=args.use_lsl and lsl_initialized)
    
    if args.progress_file:
        update_progress(args.progress_file, 90, "Saving final results...")
    
    # Save results using the appropriate method
    save_results(results, Path(SAVE_PATH), args.subject_id, profile.get("appendix", ""))
    
    if args.progress_file:
        update_progress(args.progress_file, 95, "Finishing up...")
    
    # Show closing message with progress updates
    if display_message(screen, font, MSG_CLOSE, CLC_CLOSE,
                      progress_file=args.progress_file,
                      status="Finishing up...",
                      progress_start=95,
                      progress_end=100,
                      width_screen=width_screen,
                      height_screen=height_screen):
        return
    
    if args.progress_file:
        lsl_status = " (LSL mode)" if args.use_lsl and lsl_initialized else ""
        update_progress(args.progress_file, 100, f"Complete{lsl_status}")
    
    # Keep the black screen until manual close or ctrl+c
    while True:
        if check_for_quit():
            return
        screen.fill((0,0,0))
        pygame.display.flip()
        pygame.time.wait(50)  # Small delay to prevent high CPU usage

if __name__ == "__main__":
    main()