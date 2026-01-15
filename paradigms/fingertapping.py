#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import pygame, sys, os, time, json, argparse
from pathlib import Path

# Import shared utility functions
script_dir = Path(__file__).resolve().parent
parent_dir = script_dir.parent
sys.path.insert(0, str(parent_dir))
from auxfunc.paradigm_utils import (
    update_progress, send_keystroke, check_for_quit,
    display_message, play_audio, create_lsl_outlet
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

# -- messages
MSG_INTRO = ['SMALL MOTOR EXERCISE','','PLEASE GET COMFORTABLE BEFORE WE', 
             'PERFORM BASELINE MEASUREMENTS']

def parse_arguments():
    parser = argparse.ArgumentParser(description='Run fingertapping experiment')
    parser.add_argument('--subject_id', default="UNKNOWN", help='Subject ID for data collection')
    parser.add_argument('--progress_file', default=None, help='File path for progress tracking')
    parser.add_argument('--profile', default="fingertapping", 
                        help='Experiment profile to use')
    parser.add_argument('--use_lsl', action='store_true', 
                        help='Use LSL triggers for old NIRS device instead of keystrokes')
    parser.add_argument('--use_sound', action='store_true',
                        help='Enable beep sounds')
    return parser.parse_args()

def main():
    # Setup paradigm
    # -- get arguments from command line
    args = parse_arguments()
    settings, profile = load_config_profile(args.profile)
    
    # Get values from configs
    display_config = settings.get('display', {})
    width_screen = display_config.get('width', 1920)
    height_screen = display_config.get('height', 1080)
    
    window_name = profile.get('display_name', 'Fingertapping')
    task_duration = profile.get('task_duration', 10000)
    rest_duration = profile.get('rest_duration', 15000)
    resting_state = profile.get('resting_state', 60000)
    repetitions = profile.get('repetitions', ['left', 'right', 'left', 'right', 'left', 'right'])
    
    print(f"Debug: Using profile: {args.profile}")
    print(f"Debug: Subject ID: {args.subject_id}")
    print(f"Debug: Use LSL: {args.use_lsl}")
    
    # Initialize LSL
    lsl_initialized = create_lsl_outlet() if args.use_lsl else False
    
    # -- initialize pygame
    pygame.mixer.init()
    pygame.init()
    pygame.display.set_caption(window_name)
    
    # -- create display, initialize font and audio path
    audio_path = Path(os.path.dirname(os.path.abspath(__file__))) / '_resources'
    screen = pygame.display.set_mode((width_screen, height_screen), display=1)
    font = pygame.font.SysFont(None, 120)
    status = ''
    
    # Lobby 01: Welcome screen
    # -- display welcome message
    screen.fill((0, 0, 0))
    display_message(screen, font, MSG_INTRO, 
                   width_screen=width_screen, height_screen=height_screen)
    pygame.display.flip()
    
    # -- update progress file
    if args.progress_file:
        lsl_status = " (LSL enabled)" if lsl_initialized else ""
        update_progress(args.progress_file, 0, f"Setup complete{lsl_status}. Press 'W' to continue...")

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
    
    # Resting state
    # -- display resting message
    screen.fill((0, 0, 0))
    display_message(screen, font, "+", width_screen=width_screen, height_screen=height_screen)
    pygame.display.flip()
    send_keystroke(window_name, use_lsl=args.use_lsl)
    
    # -- update progress file
    if args.progress_file:
        update_progress(args.progress_file, 5, "Initial resting state.")
    
    # -- wait for the resting period
    if display_message(screen, font, "+", resting_state, custom_font_size=300,
                    progress_file=args.progress_file,
                    status="Initial resting state.",
                    progress_start=0,
                    progress_end=99,
                    width_screen=width_screen,
                    height_screen=height_screen):
        return

    send_keystroke(window_name, use_lsl=args.use_lsl)
    
    # Initial 3-second countdown
    # -- display countdown message
    for i in range(3, 0, -1):
        # -- visual feedback
        screen.fill((0, 0, 0))
        display_message(screen, font, f"Starting in {i}...", 
                     width_screen=width_screen, height_screen=height_screen)
        pygame.display.flip()
        # -- audio feedback
        if play_audio(audio_path / f'countdown_{i}.mp3'):
            return
        # -- wait on condition
        pygame.time.wait(1000)
        if check_for_quit():
            return
    
    # --update progress file
    if args.progress_file:
        update_progress(args.progress_file, 10, "Beginning exercise sequence...")

    # -- clear screen
    screen.fill((0, 0, 0))
    pygame.display.flip()
    
    # Exercise sequence
    # -- persistent variable setup
    progress_per_rep = 99 / len(repetitions)
    progress_base    = 10
    # -- exercise loop 
    for rep_idx, direction in enumerate(repetitions):

        # ========== EXERCISE PHASE ==========
        base_progress = progress_base + (rep_idx * progress_per_rep)
        if args.progress_file:
            update_progress(args.progress_file, base_progress, 
                            f"Exercise {direction.upper()} ({rep_idx+1}/{len(repetitions)})")
        
        send_keystroke(window_name, use_lsl=args.use_lsl and lsl_initialized)
        
        if display_message(screen, font, direction.upper(), task_duration, custom_font_size=300,
                        progress_file=args.progress_file,
                        status=f"Fingertapping {direction.upper()} ({rep_idx+1}/{len(repetitions)})",
                        progress_start=base_progress,
                        progress_end=base_progress + (progress_per_rep * 0.5),
                        width_screen=width_screen,
                        height_screen=height_screen):
            return
        
        if play_audio(str(audio_path / f"{direction.upper()}.mp3")):
            return
        
        # ========== REST PHASE ==========
        rest_progress = base_progress + (progress_per_rep * 0.5)
        if args.progress_file:
            update_progress(args.progress_file, rest_progress, 
                            f"Resting after {direction.upper()} ({rep_idx+1}/{len(repetitions)})")
        
        send_keystroke(window_name, use_lsl=args.use_lsl and lsl_initialized)
        
        if display_message(screen, font, "", rest_duration, custom_font_size=300,
                        progress_file=args.progress_file,
                        status=f"Resting after {direction.upper()} ({rep_idx+1}/{len(repetitions)})",
                        progress_start=rest_progress,
                        progress_end=base_progress + progress_per_rep,
                        width_screen=width_screen,
                        height_screen=height_screen):
            return
        
        if play_audio(str(audio_path / "STOP.mp3")):
            return
    
    # Terminate
    if args.progress_file:
        update_progress(args.progress_file, 95, "Sequence complete")
    
    # -- display terminal instructions
    screen.fill((0, 0, 0))
    display_message(screen, font, "You have completed the exercise.", 
                 width_screen=width_screen, height_screen=height_screen)
    display_message(screen, font, "Please stand by.", 
                 position=(width_screen//2, height_screen//2 + 80),
                 width_screen=width_screen, height_screen=height_screen)
    pygame.display.flip()
    pygame.time.wait(task_duration)
    
    # -- update progress file
    if args.progress_file:
        lsl_status = " (LSL mode)" if args.use_lsl else ""
        update_progress(args.progress_file, 100, f"Complete{lsl_status}")
    
    # -- clear screen
    screen.fill((0, 0, 0))
    pygame.display.flip()
    
    # -- wait for Esc or Ctrl+C to exit
    while True:
        if check_for_quit():
            return

if __name__ == "__main__":
    main()