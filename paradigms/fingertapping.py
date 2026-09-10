#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import pygame, sys, os, json, argparse
from pathlib import Path

# Import shared utilities and the unified trigger dispatcher
script_dir = Path(__file__).resolve().parent
parent_dir = script_dir.parent
sys.path.insert(0, str(parent_dir))
from auxfunc import crashlog
from auxfunc.paradigm_utils import (
    update_progress, check_for_quit, display_message, play_audio, wait_period, TriggerManager, resolve_display, load_strings,
    RunControl, get_font, clear_font_cache, CONTINUE, QUIT, SKIP
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
# Built-in ENGLISH fallbacks; live text comes from configs/strings.json
# (selected by --language). Used only if a key is missing from that file.
# ---------------------------------------------------------------------------
MSG_INTRO     = ['SMALL MOTOR EXERCISE', '', 'PLEASE GET COMFORTABLE BEFORE WE',
                 'PERFORM BASELINE MEASUREMENTS']
MSG_COUNTDOWN = 'Starting in {n}...'
MSG_COMPLETE  = ['You have completed the exercise.', 'Please stand by.']

_FALLBACK = {
    'intro':     MSG_INTRO,
    'countdown': MSG_COUNTDOWN,
    'complete':  MSG_COMPLETE,
}
STRINGS = {}


def txt(key):
    """Return localized text for `key`, falling back to the built-in English."""
    return STRINGS.get(key, _FALLBACK.get(key))


def parse_arguments():
    parser = argparse.ArgumentParser(description='Run fingertapping experiment')
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
    parser.add_argument('--profile', default="fingertapping",
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
    # Setup paradigm
    args = parse_arguments()

    LOG = crashlog.install('fingertapping', path=args.log_file,
                           subject_id=args.subject_id, profile=args.profile)

    settings, profile = load_config_profile(args.profile)

    # Load the language pack for this run (overlays built-in English fallbacks)
    global STRINGS
    STRINGS = load_strings(args.language, 'fingertapping')

    # Get values from configs
    display_config = settings.get('display', {})
    display_idx, width_screen, height_screen = resolve_display(
        display_config.get('monitor_index', 1),
        display_config.get('width',  1920),
        display_config.get('height', 1080),
    )

    window_name        = profile.get('display_name', 'Fingertapping')
    task_duration      = profile.get('task_duration',  10000)
    rest_duration      = profile.get('rest_duration',  15000)
    resting_state      = profile.get('resting_state',  60000)
    standby_duration   = profile.get('standby_duration', task_duration)
    repetitions        = profile.get('repetitions',
                                     ['left', 'right', 'left', 'right', 'left', 'right'])
    keystroke_programs = profile.get('keystroke_programs', DEFAULT_KEYSTROKE_PROGRAMS)

    LOG.log(f"Debug: Using profile: {args.profile}")
    LOG.log(f"Debug: Subject ID: {args.subject_id}")
    LOG.log(f"Debug: Language: {args.language}")
    LOG.log(f"Debug: Marker relay port: {args.marker_port}")

    # Initialize unified trigger dispatcher (cascade: TTL -> LSL -> keystrokes)
    trigger = TriggerManager(use_lsl=args.use_lsl, programs=keystroke_programs,
                             marker_port=args.marker_port, logger=LOG)

    control = RunControl(command_file=args.command_file, logger=LOG)
    crashed = False

    try:
        # Initialize pygame
        try:
            pygame.mixer.init()
        except Exception as exc:
            LOG.warn(f"audio unavailable ({exc}); cues will be silent")
        pygame.init()
        pygame.display.set_caption(window_name)

        audio_path    = Path(os.path.dirname(os.path.abspath(__file__))) / '_resources'
        screen = pygame.display.set_mode((width_screen, height_screen), display=display_idx)
        # Re-apply after set_mode: SDL drops a caption set before the window
        # exists on some builds, and the trigger code finds this window by title.
        pygame.display.set_caption(window_name)
        font          = get_font(120)

        LOG.event('run_start', profile=args.profile, subject=args.subject_id,
                  repetitions=repetitions, trigger=trigger.status())

        # Lobby 01: Welcome screen
        screen.fill((0, 0, 0))
        display_message(screen, font, txt('intro'),
                        width_screen=width_screen, height_screen=height_screen)
        pygame.display.flip()

        if args.progress_file:
            active = trigger.status()['active_method'].upper()
            update_progress(args.progress_file, 0,
                            f"Setup complete ({active}). Press 'W' to continue...")

        # Enter waiting room
        waiting = True
        while waiting:
            outcome = control.poll()
            if outcome == QUIT:
                return
            if outcome == SKIP:
                LOG.event('segment_skipped', segment='waiting_room')
                waiting = False
                break
            if pygame.key.get_pressed()[pygame.K_w]:
                waiting = False
            pygame.time.wait(50)

        screen.fill((0, 0, 0))
        pygame.display.flip()

        # Resting state
        screen.fill((0, 0, 0))
        display_message(screen, font, "+",
                        width_screen=width_screen, height_screen=height_screen)
        pygame.display.flip()
        trigger.send(value=8, return_focus_to=window_name, label='resting_state_onset')

        if args.progress_file:
            update_progress(args.progress_file, 5, "Initial resting state.")
        LOG.event('segment_start', segment='resting_state', duration_ms=resting_state)

        outcome = display_message(screen, font, "+", resting_state, custom_font_size=300,
                                  progress_file=args.progress_file,
                                  status="Initial resting state.",
                                  progress_start=0,
                                  progress_end=99,
                                  width_screen=width_screen,
                                  height_screen=height_screen,
                                  control=control)
        if outcome == QUIT:
            return
        if outcome == SKIP:
            LOG.event('segment_skipped', segment='resting_state')
            if args.progress_file:
                update_progress(args.progress_file, 9,
                                "Initial resting state skipped by operator")

        trigger.send(value=8, return_focus_to=window_name, label='resting_state_offset')

        # Initial 3-second countdown
        for i in range(3, 0, -1):
            screen.fill((0, 0, 0))
            display_message(screen, font, txt('countdown').format(n=i),
                            width_screen=width_screen, height_screen=height_screen)
            pygame.display.flip()
            outcome = play_audio(audio_path / f'countdown_{i}.mp3', control=control)
            if outcome == QUIT:
                return
            if outcome == SKIP:
                LOG.event('segment_skipped', segment='countdown')
                break
            outcome = wait_period(screen, 1000, control=control)
            if outcome == QUIT:
                return
            if outcome == SKIP:
                LOG.event('segment_skipped', segment='countdown')
                break

        if args.progress_file:
            update_progress(args.progress_file, 10, "Beginning exercise sequence...")

        screen.fill((0, 0, 0))
        pygame.display.flip()

        # Exercise sequence
        progress_per_rep = 99 / len(repetitions)
        progress_base    = 10

        for rep_idx, direction in enumerate(repetitions):
            # ========== EXERCISE PHASE ==========
            base_progress = progress_base + (rep_idx * progress_per_rep)
            if args.progress_file:
                update_progress(args.progress_file, base_progress,
                                f"Exercise {direction.upper()} ({rep_idx+1}/{len(repetitions)})")

            trigger.send(value=8, return_focus_to=window_name,
                         label=f'tap_{rep_idx}_{direction}_onset')
            LOG.event('segment_start', segment='tap', index=rep_idx,
                      direction=direction, duration_ms=task_duration)

            # Refresh the screen to the cue, then fire the audio at the same moment
            # (mirrors the countdown block), and only THEN hold for the task period.
            display_message(screen, font, direction.upper(), custom_font_size=300,
                            width_screen=width_screen, height_screen=height_screen)
            outcome = play_audio(str(audio_path / f"{direction.upper()}.mp3"), control=control)
            if outcome == QUIT:
                return
            if outcome != SKIP:
                outcome = wait_period(screen, task_duration,
                                      progress_file=args.progress_file,
                                      status=f"Fingertapping {direction.upper()} ({rep_idx+1}/{len(repetitions)})",
                                      progress_start=base_progress,
                                      progress_end=base_progress + (progress_per_rep * 0.5),
                                      control=control)
                if outcome == QUIT:
                    return
            if outcome == SKIP:
                # One press ends this tapping phase; the rest phase after it is
                # its own segment and still runs.
                LOG.event('segment_skipped', segment='tap', index=rep_idx,
                          direction=direction)
                if args.progress_file:
                    update_progress(args.progress_file, base_progress,
                                    f"Tapping {direction.upper()} ({rep_idx+1}/"
                                    f"{len(repetitions)}) skipped by operator")

            # ========== REST PHASE ==========
            rest_progress = base_progress + (progress_per_rep * 0.5)
            if args.progress_file:
                update_progress(args.progress_file, rest_progress,
                                f"Resting after {direction.upper()} ({rep_idx+1}/{len(repetitions)})")

            trigger.send(value=8, return_focus_to=window_name,
                         label=f'tap_{rep_idx}_{direction}_offset')
            LOG.event('segment_start', segment='rest', index=rep_idx,
                      direction=direction, duration_ms=rest_duration)

            # Blank the screen and say STOP together, then hold for the rest period.
            display_message(screen, font, "", custom_font_size=300,
                            width_screen=width_screen, height_screen=height_screen)
            outcome = play_audio(str(audio_path / "STOP.mp3"), control=control)
            if outcome == QUIT:
                return
            if outcome != SKIP:
                outcome = wait_period(screen, rest_duration,
                                      progress_file=args.progress_file,
                                      status=f"Resting after {direction.upper()} ({rep_idx+1}/{len(repetitions)})",
                                      progress_start=rest_progress,
                                      progress_end=base_progress + progress_per_rep,
                                      control=control)
                if outcome == QUIT:
                    return
            if outcome == SKIP:
                LOG.event('segment_skipped', segment='rest', index=rep_idx,
                          direction=direction)
                if args.progress_file:
                    update_progress(args.progress_file, rest_progress,
                                    f"Rest after {direction.upper()} ({rep_idx+1}/"
                                    f"{len(repetitions)}) skipped by operator")

        # Terminate
        if args.progress_file:
            update_progress(args.progress_file, 95, "Sequence complete")

        screen.fill((0, 0, 0))
        _complete = txt('complete')
        display_message(screen, font, _complete[0],
                        width_screen=width_screen, height_screen=height_screen)
        display_message(screen, font, _complete[1] if len(_complete) > 1 else "",
                        position=(width_screen // 2, height_screen // 2 + 80),
                        width_screen=width_screen, height_screen=height_screen)
        pygame.display.flip()
        if wait_period(screen, standby_duration, control=control) == QUIT:
            return

        if args.progress_file:
            active = trigger.status()['active_method'].upper()
            update_progress(args.progress_file, 100, f"Complete ({active})")
        LOG.event('run_complete', skips=control.skips, triggers=trigger.sent_count)

        screen.fill((0, 0, 0))
        pygame.display.flip()

        while True:
            if control.poll() == QUIT:
                return
            pygame.time.wait(50)

    except Exception:
        crashed = True
        LOG.exception('fingertapping run aborted by an unhandled exception')
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
