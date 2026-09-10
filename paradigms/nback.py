# Import dependencies
import numpy as np
import pandas as pd
from pathlib import Path
import sys, pygame, json, os, random, re, argparse

try:
    import win32gui
except ImportError:      # non-Windows dev box; the paradigm still runs headless
    win32gui = None

# Import shared utilities and the unified trigger dispatcher
script_dir = Path(__file__).resolve().parent
parent_dir = script_dir.parent
sys.path.insert(0, str(parent_dir))

from auxfunc import crashlog
from auxfunc.paradigm_utils import (
    update_progress, check_for_quit, display_message, ensure_window_focus, play_audio, TriggerManager, resolve_display, load_strings,
    RunControl, get_font, clear_font_cache, is_modifier_key, CONTINUE, QUIT, SKIP
)


# Default keystroke fallback targets. Overridable per-paradigm via
# profiles.json -> "keystroke_programs" (added in next step).
DEFAULT_KEYSTROKE_PROGRAMS = [
    {'window': 'g.Recorder',   'key': '8'},
    {'window': 'Aurora fNIRS', 'key': 'F8'},
    {'window': 'NIRx NIRStar', 'key': 'F8', 'transport': 'lsl', 'value': 8},
    {'window': 'EmotivPRO',    'key': '8'},
]

LOG = crashlog.get()


def load_config_profile(profile_key: str):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_dir = os.path.join(script_dir, "..", "configs")

    with open(os.path.join(config_dir, "settings.json"), "r") as f:
        settings = json.load(f)
    with open(os.path.join(config_dir, "profiles.json"), "r") as f:
        profiles = json.load(f)
    if profile_key not in profiles:
        raise KeyError(f"profile '{profile_key}' is not in profiles.json "
                       f"(available: {', '.join(sorted(profiles))})")
    profile = profiles[profile_key]
    return settings, profile


# ---------------------------------------------------------------------------
# Built-in ENGLISH fallbacks. The live text comes from configs/strings.json
# (selected by --language); these are only used if that file is missing a key.
# ---------------------------------------------------------------------------
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
MSG_INTRO       = ['WORKING MEMORY EXERCISE', '', 'PLEASE GET COMFORTABLE BEFORE WE',
                   'PERFORM BASELINE MEASUREMENTS']
MSG_POSTREST    = ['RESTING STATE IS COMPLETE', 'ARE YOU READY?']

# Rest state messages
MSG_REST_CLOSED = ['Please close your eyes']
MSG_REST_OPEN   = ['Please keep your eyes open',
                   'focus on the [ + ] symbol']
MSG_CLOSE       = ['You have completed the', 'memory exercise.', 'Please stand by.']

# Active text table (populated in main() from configs/strings.json) with the
# constants above as the fallback catalog.
_FALLBACK = {
    'intro':                MSG_INTRO,
    'postrest':             MSG_POSTREST,
    'rest_closed':          MSG_REST_CLOSED,
    'rest_open':            MSG_REST_OPEN,
    'close':                MSG_CLOSE,
    'letter_instructions':  LETTER_INSTRUCTIONS,
    'number_instructions':  NUMBER_INSTRUCTIONS,
}
STRINGS = {}


def txt(key):
    """Return localized text for `key`, falling back to the built-in English."""
    return STRINGS.get(key, _FALLBACK.get(key))


def find_paradigm_window(window_name):
    """Resolve our own pygame window handle, falling back to a partial match.

    FindWindow needs the caption to match exactly; a profile whose display_name
    picks up a stray character (or a pygame build that decorates the title)
    returns 0, and the old code then fed that 0 to SetForegroundWindow once per
    frame. Returning None instead makes ensure_window_focus a cheap no-op.
    """
    if win32gui is None or not window_name:
        return None
    try:
        hwnd = win32gui.FindWindow(None, window_name)
        if hwnd:
            return hwnd
        matches = []

        def _cb(handle, acc):
            try:
                if window_name in win32gui.GetWindowText(handle):
                    acc.append(handle)
            except Exception:
                pass
            return True

        win32gui.EnumWindows(_cb, matches)
        if matches:
            LOG.warn(f"find_paradigm_window: exact title '{window_name}' not "
                     f"found; using partial match {matches[0]}")
            return matches[0]
    except Exception as exc:
        LOG.warn(f"find_paradigm_window: lookup failed ({exc})")
    LOG.warn(f"find_paradigm_window: no window titled '{window_name}'; "
             f"focus management disabled for this run")
    return None


# Set up pygame
def init_game(settings, profile):
    pygame.init()
    # pygame.init() reports a failed mixer in its return tuple instead of
    # raising, which is why the end-of-rest beep could silently do nothing.
    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init()
    except Exception as exc:
        LOG.warn(f"init_game: audio unavailable ({exc}); sounds will be skipped")

    display_config = settings.get('display', {})
    display_idx, width_screen, height_screen = resolve_display(
        display_config.get('monitor_index', 1),
        display_config.get('width',  1920),
        display_config.get('height', 1080),
    )

    window_name = profile.get('display_name', 'N-back Task')
    pygame.display.set_caption(window_name)
    screen = pygame.display.set_mode((width_screen, height_screen), display=display_idx)
    # Set the caption again now that a window actually exists -- SDL drops a
    # caption set before set_mode() on some builds, and the trigger code finds
    # this window by title.
    pygame.display.set_caption(window_name)
    clock  = pygame.time.Clock()
    font   = get_font(120)

    return screen, clock, font, width_screen, height_screen, window_name


def get_instructions(stim_type):
    """Return the appropriate instructions based on stimulus type"""
    if "number" in stim_type.lower():
        return txt('number_instructions')
    else:
        return txt('letter_instructions')


def wait_for_ready(screen, font, message, control, width_screen, height_screen,
                   progress_file=None, label=''):
    """Hold a screen until the operator presses 'W' (or fast-forwards past it).

    Returns CONTINUE or QUIT; SKIP is treated as 'W' because a waiting room has
    nothing after it to skip to.
    """
    clock = pygame.time.Clock()
    while True:
        clock.tick(60)
        display_message(screen, font, message,
                        width_screen=width_screen, height_screen=height_screen)

        if progress_file:
            update_progress(progress_file, 0, "Press 'W' to continue...")

        outcome = control.poll()
        if outcome == QUIT:
            return QUIT
        if outcome == SKIP:
            LOG.event('segment_skipped', segment='waiting_room', label=label)
            return CONTINUE

        if pygame.key.get_pressed()[pygame.K_w]:
            return CONTINUE

        pygame.time.wait(50)


def run_rest_states(screen, font, rest_states, rest_period, instruction_time, window_name,
                    width_screen, height_screen, trigger, progress_file=None, use_sound=True,
                    control=None):

    audio_path = Path(os.path.dirname(os.path.abspath(__file__))) / '_resources'

    # rest_period may be a single value (same length for every state) or a list
    # aligned positionally with rest_states (e.g. ["closed","open"] -> [180000, 90000]).
    if isinstance(rest_period, (list, tuple)):
        periods = list(rest_period) or [60000]
        if len(periods) < len(rest_states):
            LOG.warn(f"run_rest_states: rest_period has {len(periods)} entries for "
                     f"{len(rest_states)} rest states; reusing last value for the remainder")
            periods += [periods[-1]] * (len(rest_states) - len(periods))
    else:
        periods = [rest_period] * len(rest_states)

    for enum, state in enumerate(rest_states):
        if state == 'none':
            continue

        if progress_file:
            update_progress(progress_file, 0,
                            f"Starting rest state {enum+1}/{len(rest_states)}...")

        instruction_msg = txt('rest_closed') if state == 'closed' else txt('rest_open')
        rest_display    = "" if state == 'closed' else "+"

        LOG.event('segment_start', segment='rest', index=enum, eyes=state,
                  duration_ms=periods[enum])

        outcome = display_message(screen, font, instruction_msg, instruction_time,
                                  progress_file=progress_file,
                                  status=f"Rest state {enum+1}/{len(rest_states)}: instructions (eyes {state})",
                                  progress_start=0,
                                  progress_end=20,
                                  width_screen=width_screen,
                                  height_screen=height_screen,
                                  control=control)
        if outcome == QUIT:
            return QUIT
        # SKIP on the instruction screen only shortens the instructions; the
        # rest state itself still runs, and can be skipped separately.

        trigger.send(value=8, return_focus_to=window_name,
                     label=f'rest_{enum}_onset_{state}')

        outcome = display_message(screen, font, rest_display, periods[enum], custom_font_size=300,
                                  progress_file=progress_file,
                                  status=f"Rest state {enum+1}: in progress (eyes {state})",
                                  progress_start=20,
                                  progress_end=99,
                                  width_screen=width_screen,
                                  height_screen=height_screen,
                                  control=control)
        if outcome == QUIT:
            return QUIT
        if outcome == SKIP:
            LOG.event('segment_skipped', segment='rest', index=enum, eyes=state)
            if progress_file:
                update_progress(progress_file, 99,
                                f"Rest state {enum+1}/{len(rest_states)} skipped by operator")

        if use_sound:
            if play_audio(audio_path / 'beep.mp3', control=control) == QUIT:
                return QUIT

        LOG.event('segment_end', segment='rest', index=enum, eyes=state,
                  skipped=(outcome == SKIP))

    if progress_file:
        update_progress(progress_file, 0, "Rest states complete. Proceeding to task.")
    return CONTINUE


def _instructions_for_block(instructions, index):
    """Instruction screen for block `index`, tolerating a short catalogue.

    The stimulus CSV drives how many blocks there are; strings.json drives how
    many instruction screens exist. They have always matched at four, but a new
    stimulus file with a fifth column used to raise IndexError right here --
    immediately after the resting states, which is where the reported crash
    happens. Reuse the last screen and log it instead.
    """
    if not instructions:
        return ['']
    if index < len(instructions):
        return instructions[index]
    LOG.warn(f"run_trials: no instruction text for block {index+1}; "
             f"only {len(instructions)} defined. Reusing the last one.")
    return instructions[-1]


def run_trials(screen, font, stimulus, stim_type, settings, profile, width_screen, height_screen,
               window_name, trigger, progress_file=None, subject_id=None, control=None,
               state=None):

    pygame_hwnd      = find_paradigm_window(window_name)
    instruction_time = profile.get('instructions',       10000)
    stim_time        = profile.get('stim_presentation',    500)
    cooldown_time    = profile.get('stim_cooldown',       1500)
    project_root     = settings.get('paths', {}).get('project_root', '')

    # -- Initialize output storage variables
    temp_st, temp_sm, temp_er, temp_ar, temp_rt, temp_offset, temp_sk = [], [], [], [], [], [], []
    results_df = pd.DataFrame()

    def _snapshot():
        """Rebuild the results frame and hand it to the caller's crash handler."""
        frame = pd.DataFrame({
            'StimulusType'    : temp_st,
            'Stimulus'        : temp_sm,
            'ExpectedResponse': temp_er,
            'ActualResponse'  : temp_ar,
            'ReactionTime'    : temp_rt,
            'StimOffset'      : temp_offset,
            'Skipped'         : temp_sk
        })
        if state is not None:
            state['results'] = frame
        return frame

    # -- Get the appropriate instructions based on the stimulus type
    instructions = get_instructions(profile.get("stim_type", ""))
    image_path_appendix = 'num' if "number" in profile.get("stim_type", "").lower() else 'let'

    # -- Get the instruction images path (located in _resources/images)
    resource_path = Path(os.path.dirname(os.path.abspath(__file__))) / '_resources'

    progress_per_trial_type = 98 / len(stim_type) if stim_type else 0

    # -- Stimulus container rectangle
    rect_size = height_screen // 2
    rectangle = pygame.Rect((width_screen - rect_size) // 2,
                            (height_screen - rect_size) // 2,
                            rect_size, rect_size)
    rectangle.center = (width_screen // 2, height_screen // 2)

    # Fonts are cached: run_trials used to build these twice per frame.
    stim_font = get_font(300)

    # -- Iterate through stimuli
    for i, trial_type in enumerate(stim_type):
        progress_start    = i * progress_per_trial_type
        progress_end      = (i + 1) * progress_per_trial_type
        trials_in_block   = len(stimulus[trial_type])
        progress_per_trial = progress_per_trial_type / trials_in_block if trials_in_block else 0

        if progress_file:
            update_progress(progress_file, progress_start,
                            f"Starting trial block: {i+1}/{len(stim_type)}")
        LOG.event('segment_start', segment='block', index=i, name=str(trial_type),
                  n_stimuli=trials_in_block)

        # Look for a task-specific image for this trial
        trial_image_path = resource_path / 'images' / f"{trial_type}_{image_path_appendix}.png"
        image_path = str(trial_image_path) if trial_image_path.exists() else None

        # Display instruction screen (takes 10% of this trial type's progress)
        instr_progress_start = progress_start
        instr_progress_end   = progress_start + (progress_per_trial_type * 0.1)

        outcome = display_message(screen, font, _instructions_for_block(instructions, i),
                                  instruction_time,
                                  progress_file=progress_file,
                                  status=f"Instructions for {trial_type}",
                                  progress_start=instr_progress_start,
                                  progress_end=instr_progress_end,
                                  image_path=image_path,
                                  width_screen=width_screen,
                                  height_screen=height_screen,
                                  control=control)
        if outcome == QUIT:
            return _snapshot()
        if outcome == SKIP:
            # Fast-forward on the instruction screen means "start this block
            # now", not "skip the block" -- the block is the next segment.
            LOG.event('segment_skipped', segment='block_instructions', index=i)

        # Set response
        response = stimulus[f"{trial_type}-response"]
        # Block-onset marker
        trigger.send(value=8, return_focus_to=window_name,
                     label=f'block_{i}_onset_{trial_type}')

        # Stimuli take remaining 90% of this trial type's progress
        stimuli_progress_start = instr_progress_end
        stimuli_progress_end   = progress_end

        stim_count        = len(stimulus[trial_type])
        progress_per_stim = (stimuli_progress_end - stimuli_progress_start) / stim_count if stim_count > 0 else 0
        stim_offset       = 0

        block_quit    = False
        block_skipped = False

        for idx, (stim, resp) in enumerate(zip(stimulus[trial_type], response)):
            if block_skipped:
                # Operator fast-forwarded: record the remaining stimuli as
                # never presented so the block keeps its full row count and
                # analysis can drop them with Skipped == 1.
                temp_st.append(i)
                temp_sm.append(stim)
                temp_er.append(resp)
                temp_ar.append(None)
                temp_rt.append(np.inf)
                temp_offset.append(np.nan)
                temp_sk.append(1)
                continue

            stim_progress_start = stimuli_progress_start + (idx       * progress_per_stim)
            stim_progress_end   = stimuli_progress_start + ((idx + 1) * progress_per_stim)

            if progress_file:
                update_progress(progress_file, stim_progress_start,
                                f"Processing stimulus {idx+1}/{stim_count} in {i}")

            start_time  = pygame.time.get_ticks()
            key_pressed = None
            timepressed = np.inf

            # Progress tracking variables
            last_update_time = start_time
            update_interval  = 50

            temp_offset.append(stim_offset)
            woodpecker     = random.uniform(0.9, 1.1)
            total_duration = woodpecker * (stim_time + cooldown_time)
            stim_offset   += total_duration

            while pygame.time.get_ticks() - start_time < total_duration:
                ensure_window_focus(pygame_hwnd)

                current_time      = pygame.time.get_ticks() - start_time
                is_stimulus_phase = current_time < stim_time

                screen.fill((0, 0, 0))
                pygame.draw.rect(screen, (255, 255, 255), rectangle, 2)

                if is_stimulus_phase:
                    text = stim_font.render(str(stim), True, (255, 255, 255))
                    rect = text.get_rect(center=(width_screen // 2, height_screen // 2))
                    screen.blit(text, rect)

                pygame.display.flip()

                # Check for events
                for event in pygame.event.get():
                    # escape_quits=False: a bare Escape stays a participant
                    # response here, as it always has. Ctrl+C / Ctrl+Escape abort.
                    verdict = (control.handle_event(event, escape_quits=False)
                               if control else CONTINUE)
                    if verdict == QUIT:
                        block_quit = True
                        break
                    if verdict == SKIP:
                        block_skipped = True
                        break
                    if event.type == pygame.QUIT:
                        block_quit = True
                        break
                    if event.type == pygame.KEYDOWN:
                        if is_modifier_key(event.key):
                            continue          # Ctrl/Shift are not a response
                        if key_pressed is None:
                            key_pressed = event.key
                            timepressed = current_time / 1000

                if block_quit or block_skipped:
                    break

                # The control panel's Skip button arrives through a file rather
                # than the event queue, so check it here too (self-throttled).
                if control is not None and control.check_command_file() == SKIP:
                    block_skipped = True
                    break

                # Update progress at most every 50ms
                current_update_time = pygame.time.get_ticks()
                if progress_file and (current_update_time - last_update_time >= update_interval):
                    progress_percent = stim_progress_start + (current_time / total_duration) * (stim_progress_end - stim_progress_start)
                    phase_name = "Stimulus" if is_stimulus_phase else "Fixation"
                    update_progress(progress_file, progress_percent,
                                    f"{phase_name} {idx+1}/{stim_count} in {i}")
                    last_update_time = current_update_time

                pygame.time.wait(10)

            LOG.log(f"Key pressed: {key_pressed} @{timepressed}")
            temp_st.append(i)
            temp_sm.append(stim)
            temp_er.append(resp)
            temp_ar.append(key_pressed)
            temp_rt.append(timepressed)
            temp_sk.append(0)

            results_df = _snapshot()

            # Save interim results if subject_id is provided
            if subject_id and subject_id != "UNKNOWN" and profile:
                save_results(results_df, Path(project_root), subject_id,
                             profile.get("appendix", ""), interim=True)

            if block_quit:
                return _snapshot()
            if block_skipped:
                remaining = stim_count - (idx + 1)
                LOG.event('segment_skipped', segment='block', index=i,
                          name=str(trial_type), stimuli_remaining=remaining)
                if progress_file:
                    update_progress(progress_file, progress_end,
                                    f"Block {i+1}/{len(stim_type)} skipped "
                                    f"({remaining} stimuli not presented)")

        results_df = _snapshot()

        if progress_file:
            update_progress(progress_file, progress_end,
                            f"Completed trial block: {i+1}/{len(stim_type)}")
        LOG.event('segment_end', segment='block', index=i, name=str(trial_type),
                  skipped=block_skipped)

    return _snapshot()


def _rescue_dir():
    """Somewhere local and writable to park data when project_root is not."""
    return os.path.join(crashlog.resolve_log_dir(), 'rescued_data')


def save_results(results, save_path, subject_id, profile_appendix="", interim=False):
    """Save results using the appropriate method for the experiment profile

    Never raises. This runs after every stimulus, and project_root is usually a
    mapped drive -- an OSError here used to take the whole session down mid
    block. On failure the data is written to logs/rescued_data instead so
    nothing is lost.
    """
    if results is None or results.empty or subject_id == "UNKNOWN":
        return False

    match = re.match(r'^([A-Za-z]+)', str(subject_id))
    project = match.group(1) if match else 'MISC'
    if not match:
        LOG.warn(f"save_results: subject '{subject_id}' has no leading letters; "
                 f"filing under '{project}'")

    if interim:
        filename = f"{subject_id}_interim{profile_appendix}.csv"
    else:
        filename = f"{subject_id}{profile_appendix}.csv"

    attempts = [os.path.join(str(save_path), project),
                os.path.join(_rescue_dir(), project)]
    last_error = None
    for attempt, project_dir in enumerate(attempts):
        try:
            os.makedirs(project_dir, exist_ok=True)
            save_file = os.path.join(project_dir, filename)
            results.to_csv(save_file, index=False)
            if attempt:
                LOG.error(f"save_results: could not write to {attempts[0]} "
                          f"({last_error}); rescued to {save_file}")
            return True
        except Exception as exc:
            last_error = exc

    LOG.exception(f"save_results: every destination failed for {filename}",
                  fatal=False)
    return False


def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description='Run N-back experiment with different profiles')
    parser.add_argument('--subject_id', default="UNKNOWN",
                        help='Subject ID for data collection')
    parser.add_argument('--progress_file', default=None,
                        help='File path for progress tracking')
    parser.add_argument('--command_file', default=None,
                        help="File the control panel writes fast-forward requests to")
    parser.add_argument('--log_file', default=None,
                        help='Log file this process is already writing stdout/stderr to')
    parser.add_argument('--marker_port', type=int, default=None,
                        help="UDP port of the control panel's LSL marker relay")
    parser.add_argument('--profile', default="TBI_letter",
                        help='Experiment profile to use')
    parser.add_argument('--use_lsl', action='store_true',
                        help='Open the LSL marker stream (used as fallback if TTL unavailable)')
    parser.add_argument('--use_sound', action='store_true',
                        help='Enable beep sounds')
    parser.add_argument('--language', default='en',
                        help="UI language code from configs/strings.json (e.g. 'en', 'es')")
    return parser.parse_args()


def main():
    global LOG
    # Parse command line arguments, load settings / profile
    args = parse_arguments()

    LOG = crashlog.install('nback', path=args.log_file,
                           subject_id=args.subject_id, profile=args.profile)

    settings, profile = load_config_profile(args.profile)

    # Load the language pack for this run (overlays the built-in English fallbacks)
    global STRINGS
    STRINGS = load_strings(args.language, 'nback')

    LOG.log(f"Debug: Using profile: {args.profile}")
    LOG.log(f"Debug: Subject ID: {args.subject_id}")
    LOG.log(f"Debug: Language: {args.language}")
    LOG.log(f"Debug: Progress file: {args.progress_file}")
    LOG.log(f"Debug: Command file: {args.command_file}")
    LOG.log(f"Debug: Marker relay port: {args.marker_port}")
    LOG.log(f"Debug: Use sound: {args.use_sound}")

    # Per-profile keystroke fallback targets (default if not in config)
    keystroke_programs = profile.get('keystroke_programs', DEFAULT_KEYSTROKE_PROGRAMS)

    # Initialize unified trigger dispatcher (cascade: TTL -> LSL -> keystrokes)
    trigger = TriggerManager(use_lsl=args.use_lsl, programs=keystroke_programs,
                             marker_port=args.marker_port, logger=LOG)

    control = RunControl(command_file=args.command_file, logger=LOG)
    state   = {'results': None}
    crashed = False

    try:
        # Initialize pygame
        screen, clock, font, width_screen, height_screen, window_name = init_game(settings, profile)

        stim_root   = Path(os.path.dirname(os.path.abspath(__file__))) / '_resources'
        # utf-8-sig: the stimulus CSVs carry a byte-order mark, which would
        # otherwise glue itself to the first column name.
        stimulus    = pd.read_csv(stim_root / profile["stim_type"], encoding='utf-8-sig')
        stimulus.columns = [str(c).strip() for c in stimulus.columns]
        stim_type   = [col for col in stimulus.columns if not col.endswith('response')]
        missing     = [c for c in stim_type if f"{c}-response" not in stimulus.columns]
        if missing:
            raise KeyError(f"{profile['stim_type']} has no response column for: "
                           f"{', '.join(missing)}")
        pygame_hwnd = find_paradigm_window(window_name)
        LOG.event('run_start', profile=args.profile, subject=args.subject_id,
                  blocks=stim_type, rest_states=profile.get('rest_states'),
                  trigger=trigger.status())

        # Initialize progress file
        if args.progress_file:
            active = trigger.status()['active_method'].upper()
            try:
                update_progress(args.progress_file, 0, f"Starting up ({active}) ...")
                LOG.log("Debug: Successfully wrote to progress file")
            except Exception as e:
                LOG.warn(f"Debug: Error writing to progress file: {e}")

        # Enter waiting room #1
        ensure_window_focus(pygame_hwnd, hard=True)
        if wait_for_ready(screen, font, txt('intro'), control,
                          width_screen, height_screen,
                          progress_file=args.progress_file,
                          label='intro') == QUIT:
            return

        # Enter rest state(s)
        if run_rest_states(screen, font, profile["rest_states"], profile["rest_period"],
                           profile["instructions"], window_name, width_screen, height_screen,
                           trigger, progress_file=args.progress_file, use_sound=args.use_sound,
                           control=control) == QUIT:
            return

        # Enter waiting room #2
        ensure_window_focus(pygame_hwnd, hard=True)
        if wait_for_ready(screen, font, txt('postrest'), control,
                          width_screen, height_screen,
                          progress_file=args.progress_file,
                          label='postrest') == QUIT:
            return

        # Enter cognitive trial
        results = run_trials(screen, font, stimulus, stim_type, settings, profile,
                             width_screen, height_screen, window_name, trigger,
                             progress_file=args.progress_file, subject_id=args.subject_id,
                             control=control, state=state)

        # -- Save final results
        if args.progress_file:
            update_progress(args.progress_file, 98, "Saving final results...")
        output_root = settings.get('paths', {}).get('project_root', '')
        save_results(results, Path(output_root), args.subject_id, profile.get("appendix", ""))

        # -- Final clean up
        if args.progress_file:
            update_progress(args.progress_file, 99, "Finishing up...")
        if display_message(screen, font, txt('close'), profile.get('instructions', 10000),
                           progress_file=args.progress_file,
                           status="Finishing up...",
                           progress_start=99,
                           progress_end=100,
                           width_screen=width_screen,
                           height_screen=height_screen,
                           control=control) == QUIT:
            return

        if args.progress_file:
            active = trigger.status()['active_method'].upper()
            update_progress(args.progress_file, 100, f"Complete ({active})")
        LOG.event('run_complete', skips=control.skips,
                  triggers=trigger.sent_count)

        # Enter waiting room (blank)
        while True:
            if control.poll() == QUIT:
                return
            screen.fill((0, 0, 0))
            pygame.display.flip()
            pygame.time.wait(50)

    except Exception:
        crashed = True
        LOG.exception('nback run aborted by an unhandled exception')
        # Whatever was collected before the failure is worth more than a clean
        # traceback, so write it out before anything else unwinds.
        try:
            partial = state.get('results')
            if partial is not None and not partial.empty:
                output_root = settings.get('paths', {}).get('project_root', '')
                if save_results(partial, Path(output_root), args.subject_id,
                                (profile.get('appendix', '') or '') + '_PARTIAL'):
                    LOG.log('nback: partial results written')
        except Exception:
            LOG.exception('nback: could not save partial results', fatal=False)
        if args.progress_file:
            update_progress(args.progress_file, -1,
                            f"CRASHED - see {os.path.basename(LOG.path or 'log')}")
    finally:
        trigger.close()
        try:
            clear_font_cache()
            pygame.quit()
        except Exception:
            pass
        LOG.close()

    if crashed:
        # Nonzero exit is how the control panel knows to tell the operator.
        sys.exit(1)


if __name__ == "__main__":
    main()
