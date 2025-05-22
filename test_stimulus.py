# Import dependencies
import pygame
import random
import string
import os
import numpy as np

# Import shared utility functions
from paradigm_utils import (
    check_for_quit, display_message
)

# Defined constant variables - matching main_nback.py
MSG_INTRO = ['WORKING MEMORY TUTORIAL','PLEASE GET COMFORTABLE BEFORE WE', 
             'BEGIN THE TUTORIAL','READY?']

# Instructions matching the format from main_nback.py
MSG_INSTR = [['Any time you see', 'W', 'press', '[ Button ]'],
             ['Any time you see', 'the same letter back to back', 'press', '[ Button ]'],
             ['Any time you see', 'a letter that matches the second to last,', 
              'letter that you saw', 'press [ Button ]']]

MSG_CLOSE = ['You have completed the', 'tutorial.','Please stand by.']

MSG_FALSE_POSITIVE = ['Incorrect Response!', 'You responded when you', "shouldn't have.", 'Restarting in 5 seconds...']
MSG_FALSE_NEGATIVE = ['Missed Response!', 'You should have responded.', 'Restarting in 5 seconds...']
MSG_CORRECT_TRIAL = ['Well done!', 'Next exercise starting in 5 seconds...']

# Timing constants matching main_nback.py
CLC_INSTR = 10000  # 10 seconds
CLC_CLOSE = 10000  # 10 seconds  
CLC_STIMU = 500    # 0.5 seconds
CLC_INTER = 1500   # 1.5 seconds

# Screen dimensions matching main_nback.py
width_screen = 1920
height_screen = 1080

# Set up pygame
def init_game():
    pygame.init()
    pygame.display.set_caption("Working Memory Tutorial")  # Updated to match

    screen = pygame.display.set_mode((width_screen, height_screen), display=1)
    
    clock = pygame.time.Clock()
    font = pygame.font.SysFont(None, 120)
    return screen, clock, font

def generate_tutorial_sequence():
    
    def generate_0back_sequence():
        sequence = list(random.choice(string.ascii_uppercase.replace('W', '')) for _ in range(8))
        w_positions = random.sample(range(8), random.randint(2, 3))
        for pos in w_positions:
            sequence[pos] = 'W'
        responses = [1 if x == 'W' else 0 for x in sequence]
        return sequence, responses

    def generate_1back_sequence():
        sequence = []
        responses = [0] * 8
        repeat_positions = random.sample(range(7), random.randint(2, 3))  # One less because we need space for the repeat
        
        for i in range(8):
            if i in repeat_positions:
                if i == 0:
                    letter = random.choice(string.ascii_uppercase)
                    sequence.append(letter)
                    sequence.append(letter)
                    responses[i+1] = 1
                    i += 1
                else:
                    letter = random.choice(string.ascii_uppercase)
                    sequence.append(letter)
                    sequence.append(letter)
                    responses[i+1] = 1
            else:
                if i < len(sequence):
                    continue
                new_letter = random.choice(string.ascii_uppercase)
                while (sequence and new_letter == sequence[-1]):
                    new_letter = random.choice(string.ascii_uppercase)
                sequence.append(new_letter)
        return sequence[:8], responses

    def generate_2back_sequence():
        sequence = []
        responses = [0] * 8
        target_positions = random.sample(range(2, 8), random.randint(2, 3))  # Start from 2 because we need 2 letters before
        
        # Generate first two letters
        sequence.extend(random.sample(string.ascii_uppercase, 2))
        
        for i in range(2, 8):
            if i in target_positions:
                sequence.append(sequence[i-2])  # Match the second-to-last letter
                responses[i] = 1
            else:
                new_letter = random.choice(string.ascii_uppercase)
                while new_letter == sequence[i-2]:  # Ensure it's not accidentally matching
                    new_letter = random.choice(string.ascii_uppercase)
                sequence.append(new_letter)
        return sequence, responses

    # Generate all sequences
    seq1, resp1 = generate_0back_sequence()
    seq2, resp2 = generate_1back_sequence()
    seq3, resp3 = generate_2back_sequence()
    return [seq1, seq2, seq3], [resp1, resp2, resp3]

def run_tutorial_trials(screen, font):
    trial_num = 0
    rect_size = height_screen // 2
    rectangle = pygame.Rect((width_screen - rect_size) // 2, (height_screen - rect_size) // 2, rect_size, rect_size)
    rectangle.center = (width_screen // 2, height_screen // 2)
    
    while trial_num < 3:
        sequences, expected_responses = generate_tutorial_sequence()
        if display_message(screen, font, MSG_INSTR[trial_num], CLC_INSTR,
                         width_screen=width_screen, height_screen=height_screen):
            return
        
        sequence = sequences[trial_num]
        responses = expected_responses[trial_num]
        restart_needed = False
        
        for idx, (stim, resp) in enumerate(zip(sequence, responses)):
            start_time = pygame.time.get_ticks()
            key_pressed = None
            timepressed = np.inf
            
            # Add randomization matching main_nback.py
            woodpecker = random.uniform(0.9, 1.1)
            total_duration = woodpecker * (CLC_STIMU + CLC_INTER)

            while pygame.time.get_ticks() - start_time < total_duration:
                current_time = pygame.time.get_ticks() - start_time
                is_stimulus_phase = current_time < CLC_STIMU
                
                # Fill screen with black background
                screen.fill((0, 0, 0))
                
                # Draw the white rectangle matching main_nback.py
                pygame.draw.rect(screen, (255, 255, 255), rectangle, 2)
                
                if is_stimulus_phase:
                    # Display the stimulus letter in white matching main_nback.py
                    stim_font = pygame.font.SysFont(None, 300)
                    text = stim_font.render(str(stim), True, (255, 255, 255))  # White text
                    rect = text.get_rect(center=(width_screen//2, height_screen//2))
                    screen.blit(text, rect)
                else:
                    # Empty fixation cross (just the rectangle) matching main_nback.py
                    pass
                
                pygame.display.flip()
                
                # Check for events - matching main_nback.py response detection
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        return
                    if event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_c and (pygame.key.get_mods() & pygame.KMOD_CTRL):
                            return
                        elif key_pressed is None:  # Accept any key like main_nback.py
                            key_pressed = event.key
                            timepressed = current_time / 1000
                
                # Small delay to prevent high CPU usage
                pygame.time.wait(10)
            
            # Determine if response was given (any key press counts as response)
            user_responded = 1 if key_pressed is not None else 0
            
            print(f"Stimulus: {stim}, Expected: {resp}, User responded: {user_responded}, Key: {key_pressed}, Time: {timepressed}")
            
            # Check for errors
            if (user_responded == 1 and resp == 0):  # False Positive
                if display_message(screen, font, MSG_FALSE_POSITIVE, 5000,
                                 width_screen=width_screen, height_screen=height_screen):
                    return
                restart_needed = True
                break
            elif (user_responded == 0 and resp == 1):  # False Negative
                if display_message(screen, font, MSG_FALSE_NEGATIVE, 5000,
                                 width_screen=width_screen, height_screen=height_screen):
                    return
                restart_needed = True
                break
            
            # If we've completed the sequence successfully
            if idx == len(sequence) - 1:
                if display_message(screen, font, MSG_CORRECT_TRIAL, 5000,
                                 width_screen=width_screen, height_screen=height_screen):
                    return

        if not restart_needed:
            trial_num += 1
    return

def main():
    # Variable setup
    screen, clock, font = init_game()
    
    # Waiting room matching main_nback.py
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
    
    # Tutorial trials    
    run_tutorial_trials(screen, font)
    
    # Show closing message matching main_nback.py timing
    if display_message(screen, font, MSG_CLOSE, CLC_CLOSE,
                      width_screen=width_screen, height_screen=height_screen):
        return
    
    while True:
        if check_for_quit():
            return
        screen.fill((0,0,0))
        pygame.display.flip()
        pygame.time.wait(50)

if __name__ == "__main__":
    main()