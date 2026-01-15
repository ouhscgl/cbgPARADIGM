# Import dependencies
import numpy as np
import pandas as pd
from pathlib import Path
import sys, pygame, json, os, win32gui, random, re, argparse, time

# Import shared utility functions
script_dir = Path(__file__).resolve().parent
parent_dir = script_dir.parent
sys.path.insert(0, str(parent_dir))

from auxfunc.paradigm_utils import (
    update_progress, send_keystroke, check_for_quit,
    display_message, ensure_window_focus, create_lsl_outlet, play_audio
)

def load_config_profile(profile_key: str):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_dir = os.path.join(script_dir, "..", "configs")

    with open(os.path.join(config_dir, "settings.json"), "r") as f:
        settings = json.load(f)
    with open(os.path.join(config_dir, "profiles.json"), "r") as f:
        profiles = json.load(f)
    profile = profiles[profile_key]
    return settings, profile

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
MSG_INTRO       = ['WORKING MEMORY EXERCISE','','PLEASE GET COMFORTABLE BEFORE WE', 
                   'PERFORM BASELINE MEASUREMENTS']
MSG_POSTREST    = ['RESTING STATE IS COMPLETE','ARE YOU READY?']

# Rest state messages
MSG_REST_CLOSED = ['Please close your eyes']
MSG_REST_OPEN   = ['Please keep your eyes open',
                   'focus on the [ + ] symbol']
MSG_CLOSE       = ['You have completed the', 'memory exercise.','Please stand by.']

# Set up pygame
def init_game(settings, profile):
    pygame.init()
    
    display_config = settings.get('display', {})
    width_screen = display_config.get('width', 1920)
    height_screen = display_config.get('height', 1080)
    monitor_index = display_config.get('monitor_index', 1)
    
    window_name = profile.get('display_name', 'N-back Task')
    pygame.display.set_caption(window_name)
    screen = pygame.display.set_mode((width_screen, height_screen), display=1)
    clock = pygame.time.Clock()
    font = pygame.font.SysFont(None, 120)
    
    return screen, clock, font, width_screen, height_screen, window_name

def get_instructions(stim_type):
    """Return the appropriate instructions based on stimulus type"""
    if "number" in stim_type.lower():
        return NUMBER_INSTRUCTIONS
    else:
        return LETTER_INSTRUCTIONS

def run_rest_states(screen, font, rest_states, rest_period, instruction_time, window_name, 
                   width_screen, height_screen, progress_file=None, use_lsl=False, use_sound=True):
    
    audio_path = Path(os.path.dirname(os.path.abspath(__file__))) / '_resources'

    for enum, state in enumerate(rest_states):
        if state == 'none':
            continue

        if progress_file:
            update_progress(progress_file, 0, f"Starting rest state {enum+1}/{len(rest_states)}...")
        
        instruction_msg = MSG_REST_CLOSED if state == 'closed' else MSG_REST_OPEN
        rest_display    = "" if state == 'closed' else "+"

        if display_message(screen, font, instruction_msg, instruction_time, 
                          progress_file=progress_file, 
                          status=f"Rest state {enum+1}/{len(rest_states)}: instructions (eyes {state})", 
                          progress_start=0, 
                          progress_end=20,
                          width_screen=width_screen,
                          height_screen=height_screen):
            return True
                
        send_keystroke(window_name, use_lsl=use_lsl)
            
        if display_message(screen, font, rest_display, rest_period, custom_font_size=300,
                          progress_file=progress_file, 
                          status=f"Rest state {enum+1}: in progress (eyes {state})",
                          progress_start=20, 
                          progress_end=99,
                          width_screen=width_screen,
                          height_screen=height_screen):
            return True
        
        if use_sound:
            play_audio(audio_path / 'beep.mp3')
        
    if progress_file:
        update_progress(progress_file, 0, "Rest states complete. Proceeding to task.")
    return False

def run_trials(screen, font, stimulus, stim_type, settings, profile, width_screen, height_screen,
               window_name, progress_file=None, subject_id=None, use_lsl=False):

    pygame_hwnd         = win32gui.FindWindow(None, window_name)
    instruction_time    = profile.get('instructions', 10000)
    stim_time           = profile.get('stim_presentation', 500)
    cooldown_time       = profile.get('stim_cooldown', 1500)
    project_root        = settings.get('paths', {}).get('project_root', '')

    # -- Initialize output storage variables
    temp_st, temp_sm, temp_er, temp_ar, temp_rt, temp_offset = [], [], [], [], [], []
    results_df = pd.DataFrame()
    
    # -- Get the appropriate instructions based on the stimulus type
    instructions = get_instructions(profile.get("stim_type", ""))
    image_path_appendix = 'num' if "number" in profile.get("stim_type", "").lower() else 'let'
    
    # -- Get the instruction images path (located in _resources/images)
    resource_path = Path(os.path.dirname(os.path.abspath(__file__))) / '_resources'
    images_path = resource_path / 'images'
    instruction_images = {}
    for idx in range(len(instructions)):
        image_filename = f"{image_path_appendix}{idx}.png"
        image_path = images_path / image_filename
        if image_path.exists():
            try:
                instruction_images[idx] = pygame.image.load(str(image_path))
            except Exception as e:
                print(f"Warning: Could not load instruction image {image_filename}: {e}")
    
    progress_per_trial_type = 98 / len(stim_type) if stim_type else 0
    
    # -- Stimulus container rectangle
    rect_size = height_screen // 2
    rectangle = pygame.Rect((width_screen - rect_size) // 2, (height_screen - rect_size) // 2, rect_size, rect_size)
    rectangle.center = (width_screen // 2, height_screen // 2)
    
    # -- Iterate through stimuli
    for i, trial_type in enumerate(stim_type):
        progress_start = i * progress_per_trial_type
        progress_end = (i + 1) * progress_per_trial_type
        trials_in_block = len(stimulus[trial_type])
        progress_per_trial = progress_per_trial_type / trials_in_block if trials_in_block else 0

        # Insert update
        if progress_file:
            update_progress(progress_file, progress_start, f"Starting trial block: {i+1}/{len(stim_type)}")
        
        # Look for a task-specific image for this trial
        trial_image_path = images_path / f"nback_{trial_type}_{image_path_appendix}.png"
        image_path = str(trial_image_path) if trial_image_path.exists() else None

        # Display instruction screen (takes 10% of this trial type's progress)
        instr_progress_start = progress_start
        instr_progress_end = progress_start + (progress_per_trial_type * 0.1)
        
        if display_message(screen, font, instructions[i], instruction_time,
                          progress_file=progress_file,
                          status=f"Instructions for {trial_type}",
                          progress_start=instr_progress_start,
                          progress_end=instr_progress_end,
                          image_path=image_path,
                          width_screen=width_screen,
                          height_screen=height_screen):
            return results_df
            
        # Set response
        response = stimulus[f"{trial_type}_response"]
        # Insert markers
        send_keystroke(window_name, use_lsl=use_lsl)
        
        # Stimuli take remaining 90% of this trial type's progress
        stimuli_progress_start = instr_progress_end
        stimuli_progress_end = progress_end
        
        # Calculate progress increment per stimulus
        stim_count = len(stimulus[trial_type])
        progress_per_stim = (stimuli_progress_end - stimuli_progress_start) / stim_count if stim_count > 0 else 0
        stim_offset = 0
        
        for idx, (stim, resp) in enumerate(zip(stimulus[trial_type], response)):
            # Progress for this individual stimulus
            stim_progress_start = stimuli_progress_start + (idx * progress_per_stim)
            stim_progress_end = stimuli_progress_start + ((idx + 1) * progress_per_stim)
            
            if progress_file:
                update_progress(progress_file, stim_progress_start, 
                               f"Processing stimulus {idx+1}/{stim_count} in {i}")
            
            start_time = pygame.time.get_ticks()
            key_pressed = None
            timepressed = np.inf
            
            # Progress tracking variables
            last_update_time = start_time
            update_interval = 50
            
            temp_offset.append(stim_offset)
            woodpecker = random.uniform(0.9, 1.1)
            total_duration = woodpecker * (stim_time + cooldown_time)
            stim_offset += total_duration

            while pygame.time.get_ticks() - start_time < total_duration:
                ensure_window_focus(pygame_hwnd)
                
                current_time = pygame.time.get_ticks() - start_time
                is_stimulus_phase = current_time < stim_time
                
                screen.fill((0, 0, 0))
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

            results_df = pd.DataFrame({
                'StimulusType'    : temp_st, 
                'Stimulus'        : temp_sm, 
                'ExpectedResponse': temp_er, 
                'ActualResponse'  : temp_ar, 
                'ReactionTime'    : temp_rt,
                'StimOffset'      : temp_offset
            })
            
            # Save interim results if subject_id is provided
            if subject_id and subject_id != "UNKNOWN" and profile:
                save_results(results_df, Path(project_root), subject_id, profile.get("appendix", ""), interim=True)
        
        # Update progress at end of trial block
        if progress_file:
            update_progress(progress_file, progress_end, f"Completed trial block: {i+1}/{len(stim_type)}")

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
                        help='Experiment profile to use')
    parser.add_argument('--use_lsl', action='store_true', 
                        help='Use LSL triggers for old NIRS device instead of keystrokes')
    parser.add_argument('--use_sound', action='store_true',
                        help='Enable beep sounds')
    
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
    # Parse command line arguments, load settings / profile
    args = parse_arguments()
    settings, profile = load_config_profile(args.profile)
    
    print(f"Debug: Using profile: {args.profile}")
    print(f"Debug: Subject ID: {args.subject_id}")
    print(f"Debug: Progress file: {args.progress_file}")
    print(f"Debug: Use LSL: {args.use_lsl}")
    print(f"Debug: Use sound: {args.use_sound}")
    
    # Initialize LSL
    lsl_initialized = create_lsl_outlet() if args.use_lsl else False
    
    # Initialize pygame
    screen, clock, font, width_screen, height_screen, window_name = init_game(settings, profile)
    
    stim_root = Path(os.path.dirname(os.path.abspath(__file__))) / '_resources'
    stimulus = pd.read_csv(stim_root / profile["stim_type"])
    stim_type = [col for col in stimulus.columns if not col.endswith('response')]
    pygame_hwnd = win32gui.FindWindow(None, window_name)
    
    # Initialize progress file
    if args.progress_file:
        try:
            lsl_status = " (LSL enabled)" if lsl_initialized else ""
            update_progress(args.progress_file, 0, f"Starting up {lsl_status} ...")
            print("Debug: Successfully wrote to progress file")
        except Exception as e:
            print(f"Debug: Error writing to progress file: {e}")
    
    # Enter waiting room #1
    ensure_window_focus(pygame_hwnd)
    waiting = True
    while waiting:
        clock.tick(60)
        display_message(screen, font, MSG_INTRO, 
                      width_screen=width_screen, height_screen=height_screen)
        
        if args.progress_file:
            update_progress(args.progress_file, 0, "Press 'W' to continue...")

        if check_for_quit():
            return
        
        keys = pygame.key.get_pressed()
        if keys[pygame.K_w]:
            waiting = False
        
        pygame.time.wait(50)
    
    # Enter rest state(s)
    if run_rest_states(screen, font, profile["rest_states"], profile["rest_period"], 
                      profile["instructions"], window_name, width_screen, height_screen,
                      args.progress_file, use_lsl=args.use_lsl and lsl_initialized, 
                      use_sound=args.use_sound):
        return
    
    # Enter waiting room #2
    ensure_window_focus(pygame_hwnd)
    waiting = True
    while waiting:
        clock.tick(60)
        display_message(screen, font, MSG_POSTREST, 
                     width_screen=width_screen, height_screen=height_screen)
        
        if args.progress_file:
            update_progress(args.progress_file, 0, "Press 'W' to continue...")
        
        if check_for_quit():
            return
        
        keys = pygame.key.get_pressed()
        if keys[pygame.K_w]:
            waiting = False
        
        pygame.time.wait(50)
    
    # Enter congitive trial
    results = run_trials(screen, font, stimulus, stim_type, settings, profile, 
                        width_screen, height_screen, window_name, 
                        args.progress_file, args.subject_id, 
                        use_lsl=args.use_lsl and lsl_initialized)
    
    # -- Save final results
    if args.progress_file:
        update_progress(args.progress_file, 98, "Saving final results...")
    output_root = settings.get('paths', {}).get('project_root', '')
    save_results(results, Path(output_root), args.subject_id, profile.get("appendix", ""))
    
    # -- Final clean up
    if args.progress_file:
        update_progress(args.progress_file, 99, "Finishing up...")
    if display_message(screen, font, MSG_CLOSE, profile.get('instructions', 10000),
                      progress_file=args.progress_file,
                      status="Finishing up...",
                      progress_start=99,
                      progress_end=100,
                      width_screen=width_screen,
                      height_screen=height_screen):
        return
    
    if args.progress_file:
        lsl_status = " (LSL mode)" if args.use_lsl and lsl_initialized else ""
        update_progress(args.progress_file, 100, f"Complete{lsl_status}")
    
    # Enter waiting room (blank)
    while True:
        if check_for_quit():
            return
        screen.fill((0,0,0))
        pygame.display.flip()
        pygame.time.wait(50)

if __name__ == "__main__":
    main()