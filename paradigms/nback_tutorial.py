# Import dependencies
import pygame, random, string, os
import numpy as np
from pathlib import Path

# Import shared utility functions
from paradigm_utils import (
    check_for_quit, display_message
)

MSG_INTRO          = ['WORKING MEMORY TUTORIAL','PLEASE GET COMFORTABLE BEFORE WE', 
                     'BEGIN THE TUTORIAL','READY?']

MSG_INSTR          = [['Any time you see', 'W', 'press', '[ Button ]'],
                     ['Any time you see', 'the same letter back to back', 'press', '[ Button ]'],
                     ['Any time you see', 'a letter that matches the second to last,', 
                     'letter that you saw', 'press [ Button ]']]

MSG_CLOSE          = ['You have completed the', 'tutorial.','Please stand by.']

MSG_FALSE_POSITIVE = ['Incorrect Response!', 'You responded when you', "shouldn't have.", 'Restarting in 5 seconds...']
MSG_FALSE_NEGATIVE = ['Missed Response!', 'You should have responded.', 'Restarting in 5 seconds...']
MSG_CORRECT_TRIAL  = ['Well done!', 'Next exercise starting in 5 seconds...']

CLC_INSTR          = 10000
CLC_CLOSE          = 10000
CLC_STIMU          = 500
CLC_INTER          = 1500

width_screen       = 1920
height_screen      = 1080

# Set up pygame
def init_game():
    pygame.init()
    pygame.display.set_caption("Working Memory Tutorial")
    screen = pygame.display.set_mode((width_screen, height_screen), display=1)
    
    clock = pygame.time.Clock()
    font = pygame.font.SysFont(None, 120)
    return screen, clock, font

def generate_tutorial_sequence():
    
    def generate_0back_sequence():
        sequence, responses = [], []
        num_targets = random.randint(2, 3)
        target_positions = random.sample(range(8), num_targets)
        
        for i in range(8):
            if i in target_positions:
                sequence.append('W')
                responses.append(1)
            else:
                letter = random.choice(string.ascii_uppercase.replace('W', ''))
                sequence.append(letter)
                responses.append(0)
        return sequence, responses

    def generate_1back_sequence():
        sequence, responses = [], []
        num_matches = random.randint(2, 3)
        match_positions = random.sample(range(1, 8), num_matches)
        
        for i in range(8):
            if i == 0:
                letter = random.choice(string.ascii_uppercase)
                sequence.append(letter)
                responses.append(0)
            elif i in match_positions:
                sequence.append(sequence[-1])
                responses.append(1)
            else:
                new_letter = random.choice(string.ascii_uppercase)
                while new_letter == sequence[-1]:
                    new_letter = random.choice(string.ascii_uppercase)
                sequence.append(new_letter)
                responses.append(0)
        return sequence, responses

    def generate_2back_sequence():
        sequence, responses = [], []
        num_matches = random.randint(2, 3)
        match_positions = random.sample(range(2, 8), num_matches)

        for i in range(8):
            if i < 2:
                letter = random.choice(string.ascii_uppercase)
                if i == 1:
                    while letter == sequence[0]:
                        letter = random.choice(string.ascii_uppercase)
                sequence.append(letter)
                responses.append(0)
            elif i in match_positions:
                sequence.append(sequence[i-2])
                responses.append(1)
            else:
                new_letter = random.choice(string.ascii_uppercase)
                while new_letter == sequence[i-2] or new_letter == sequence[i-1]:
                    new_letter = random.choice(string.ascii_uppercase)
                sequence.append(new_letter)
                responses.append(0)
        
        return sequence, responses

    seq1, resp1 = generate_0back_sequence()
    seq2, resp2 = generate_1back_sequence()
    seq3, resp3 = generate_2back_sequence()
    return [seq1, seq2, seq3], [resp1, resp2, resp3]

def run_tutorial_trials(screen, font):
    trial_num = 0
    rect_size = height_screen // 2
    rectangle = pygame.Rect((width_screen - rect_size) // 2, (height_screen - rect_size) // 2, rect_size, rect_size)
    rectangle.center = (width_screen // 2, height_screen // 2)
    
    resource_path = Path(os.path.dirname(os.path.abspath(__file__))) / '_resources'
    task_instr = ['0a','1a','2a']

    while trial_num < 3:
        sequences, expected_responses = generate_tutorial_sequence()
        image_path = str(resource_path / 'images' / f"nback_{task_instr[trial_num]}_let.png")
        
        if display_message(screen, font, MSG_INSTR[trial_num], CLC_INSTR,
                         image_path=image_path,
                         width_screen=width_screen, height_screen=height_screen):
            return
        
        sequence = sequences[trial_num]
        responses = expected_responses[trial_num]
        restart_needed = False
                
        for idx, (stim, resp) in enumerate(zip(sequence, responses)):
            start_time = pygame.time.get_ticks()
            key_pressed = None
            timepressed = np.inf
            
            woodpecker = random.uniform(0.9, 1.1)
            total_duration = woodpecker * (CLC_STIMU + CLC_INTER)

            while pygame.time.get_ticks() - start_time < total_duration:
                current_time = pygame.time.get_ticks() - start_time
                is_stimulus_phase = current_time < CLC_STIMU
                
                screen.fill((0, 0, 0))
                pygame.draw.rect(screen, (255, 255, 255), rectangle, 2)
                
                if is_stimulus_phase:
                    stim_font = pygame.font.SysFont(None, 300)
                    text = stim_font.render(str(stim), True, (255, 255, 255))
                    rect = text.get_rect(center=(width_screen//2, height_screen//2))
                    screen.blit(text, rect)
                else:
                    pass
                
                pygame.display.flip()

                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        return
                    if event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_c and (pygame.key.get_mods() & pygame.KMOD_CTRL):
                            return
                        elif key_pressed is None:
                            key_pressed = event.key
                            timepressed = current_time / 1000
                pygame.time.wait(10)
            
            user_responded = 1 if key_pressed is not None else 0

            if (user_responded == 1 and resp == 0):
                if display_message(screen, font, MSG_FALSE_POSITIVE, 5000,
                                 width_screen=width_screen, height_screen=height_screen):
                    return
                restart_needed = True
                break
            elif (user_responded == 0 and resp == 1):
                if display_message(screen, font, MSG_FALSE_NEGATIVE, 5000,
                                 width_screen=width_screen, height_screen=height_screen):
                    return
                restart_needed = True
                break
            
            if idx == len(sequence) - 1:
                if display_message(screen, font, MSG_CORRECT_TRIAL, 5000,
                                 width_screen=width_screen, height_screen=height_screen):
                    return

        if not restart_needed:
            trial_num += 1
    return

def main():
    screen, clock, font = init_game()
    
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
        pygame.time.wait(50)
      
    run_tutorial_trials(screen, font)
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