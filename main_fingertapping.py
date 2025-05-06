#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import pygame
import sys
import json
from pathlib import Path
import time
import os
import pyautogui

# Import shared utility functions
from paradigm_utils import (
    update_progress, send_keystroke, check_for_quit,
    display_message, wait_period, play_audio
)

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

def main():
    # Setup paradigm
    # -- get subject ID and progress file from command window arguments
    subject_id = sys.argv[1] if len(sys.argv) > 1 else "UNKNOWN"
    progress_file = sys.argv[2] if len(sys.argv) > 2 else None
    print(f"Subject ID: {subject_id}")
    
    # -- initialize pygame
    pygame.mixer.init()
    pygame.init()
    pygame.display.set_caption(WINDOW_NAME)
    
    # -- create display, initialize font and audio path
    audio_path = Path(os.path.dirname(os.path.abspath(__file__))) / '_resources'
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT), display=1)
    font = pygame.font.SysFont(None, 120)
    status = ''
    
    # Lobby 01: Welcome screen
    # -- display welcome message
    screen.fill((0, 0, 0))
    display_message(screen, font, "The exercise will begin shortly", 
                   width_screen=SCREEN_WIDTH, height_screen=SCREEN_HEIGHT)
    display_message(screen, font, "Please get comfortable.", 
                   position=(SCREEN_WIDTH//2, SCREEN_HEIGHT//2 + 80),
                   width_screen=SCREEN_WIDTH, height_screen=SCREEN_HEIGHT)
    pygame.display.flip()
    
    # -- update progress file
    if progress_file:
        update_progress(progress_file, 0, "Setup complete. Press any key to continue...")

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
    display_message(screen, font, "+", width_screen=SCREEN_WIDTH, height_screen=SCREEN_HEIGHT)
    pygame.display.flip()
    send_keystroke(WINDOW_NAME)
    
    # -- update progress file
    if progress_file:
        status = "Initial resting state."
        update_progress(progress_file, 5, status)
    
    # -- wait for the resting period
    if wait_period(screen, RESTING_STATE, progress_file, status, 5, 10):
        return
    send_keystroke(WINDOW_NAME)
    
    # Initial 3-second countdown
    # -- display countdown message
    for i in range(3, 0, -1):
        # -- visual feedback
        screen.fill((0, 0, 0))
        display_message(screen, font, f"Starting in {i}...", 
                     width_screen=SCREEN_WIDTH, height_screen=SCREEN_HEIGHT)
        pygame.display.flip()
        # -- audio feedback
        if play_audio(audio_path / f'countdown_{i}.mp3'):
            return
        # -- wait on condition
        pygame.time.wait(1000)
        if check_for_quit():
            return
    
    # --update progress file
    if progress_file:
        update_progress(progress_file, 10, "Beginning exercise sequence...")

    # -- clear screen
    screen.fill((0, 0, 0))
    pygame.display.flip()
    
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
            send_keystroke(WINDOW_NAME)
            screen.fill((0, 0, 0))
            display_message(screen, font, f"{direction}", 
                         width_screen=SCREEN_WIDTH, height_screen=SCREEN_HEIGHT)
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
            send_keystroke(WINDOW_NAME)
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
    display_message(screen, font, "You have completed the exercise.", 
                 width_screen=SCREEN_WIDTH, height_screen=SCREEN_HEIGHT)
    display_message(screen, font, "Please stand by.", 
                 position=(SCREEN_WIDTH//2, SCREEN_HEIGHT//2 + 80),
                 width_screen=SCREEN_WIDTH, height_screen=SCREEN_HEIGHT)
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