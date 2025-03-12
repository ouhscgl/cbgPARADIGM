# Import dependencies
import pygame
import random
import string
import os

# Defined constant variables
SAVE_PATH = r"C:\Users\biochemlab\Downloads"

MSG_INTRO = ['WORKING MEMORY TUTORIAL','']

MSG_INSTR = [['Any time you see','W','press', '[ Spacebar ]'],
             ['Any time you see','the same letter back to back',
                                     'press', '[ Spacebar ]'],
             ['Any time you see','a letter that matches the second to last,',
              'letter that you saw', 'press', '[ Spacebar ]']]

MSG_CLOSE = ['You have completed the', 'tutorial.','Please stand by.']

MSG_FALSE_POSITIVE = ['Incorrect Response!', 'You responded when you', "shouldn't have.", 'Restarting in 5 seconds...']
MSG_FALSE_NEGATIVE = ['Missed Response!', 'You should have responded.', 'Restarting in 5 seconds...']
MSG_CORRECT_TRIAL = ['Well done!', 'Next exercise starting in 5 seconds...']

CLC_INSTR = 10000
CLC_CLOSE = 1000
CLC_STIMU = 500
CLC_INTER = 1500

width_screen = 1920
height_screen = 1080

# Set up pygame
def init_game():
    pygame.init()
    pygame.display.set_caption("Working Memory Test")

    screen = pygame.display.set_mode((width_screen, height_screen), display=1)
    
    clock = pygame.time.Clock()
    font = pygame.font.SysFont(None, 120)
    return screen, clock, font

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

def display_message(screen, font, message, wait=0):
    bg_color = (0,0,0)
    font_color = (255,255,255)
    
    screen.fill(bg_color)
    text = []
    rect = []
    
    if not isinstance(message, list):
        # Single message - use larger font
        large_font = pygame.font.SysFont(None, 300)
        text.append(large_font.render(message, True, font_color))
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
        pygame.time.wait(wait)
        if check_for_quit():
            return True
    return False

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
    seq4, resp4 = generate_2back_sequence()

    return [seq1, seq2, seq4], [resp1, resp2, resp4]

def run_tutorial_trials(screen, font):
    trial_num = 0
    
    while trial_num < 3:
        sequences, expected_responses = generate_tutorial_sequence()
        if display_message(screen, font, MSG_INSTR[trial_num], CLC_INSTR):
            return
        
        sequence = sequences[trial_num]
        responses = expected_responses[trial_num]
        
        # Flag to track if we need to restart the sequence
        restart_needed = False
        
        for idx, (stim, resp) in enumerate(zip(sequence, responses)):
            start_time = pygame.time.get_ticks()
            key_pressed = None

            while pygame.time.get_ticks() - start_time < CLC_STIMU + CLC_INTER:
                current_time = pygame.time.get_ticks() - start_time
                display_message(screen, font, str(stim) if current_time < CLC_STIMU else "+")
                
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        return
                    if event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_c and (pygame.key.get_mods() & pygame.KMOD_CTRL):
                            return
                        elif key_pressed is None and event.key == pygame.K_SPACE:
                            key_pressed = 1
            
            if key_pressed is None:
                key_pressed = 0
            
            # Check for errors
            if (key_pressed == 1 and resp == 0):  # False Positive
                if display_message(screen, font, MSG_FALSE_POSITIVE, 5000):  # 5 second wait
                    return
                restart_needed = True
                break
            elif (key_pressed == 0 and resp == 1):  # False Negative
                if display_message(screen, font, MSG_FALSE_NEGATIVE, 5000):  # 5 second wait
                    return
                restart_needed = True
                break
            
            # If we've completed the sequence successfully
            if idx == len(sequence) - 1:
                if display_message(screen, font, MSG_CORRECT_TRIAL, 5000):  # 5 second wait
                    return

        if not restart_needed:
            trial_num += 1
    return

def main():
    # Variable setup
    screen, clock, font = init_game()
    
    # Waiting room
    while True:
        clock.tick(60)
        display_message(screen, font, MSG_INTRO)
        
        if check_for_quit():
            return
            
        keys = pygame.key.get_pressed()
        if keys[pygame.K_w]:
            break
    
    # Tutorial trials    
    run_tutorial_trials(screen, font)
    display_message(screen, font, MSG_CLOSE)
    pygame.time.wait(CLC_CLOSE)
    
    # Keep the black screen until manual close or ctrl+c
    while True:
        if check_for_quit():
            return
        screen.fill((0,0,0))
        pygame.display.flip()

if __name__ == "__main__":
    main()