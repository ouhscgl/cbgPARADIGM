# cbgPARADIGM

Manages paradigms utilized by the GeroScience Lab. Currently contains n-back and fingertapping.

Run `main.py` (or `main.bat`) to open the control panel; it launches the
paradigms in `paradigms/` as subprocesses and owns the LSL marker stream.

## Running a session

1. Enter the Subject ID, pick the profile and language, press **Start Experiment**.
2. The paradigm opens fullscreen on the stimulus display. Press **W** to move
   past each "get comfortable / are you ready" screen.
3. When a paradigm finishes it deliberately keeps a blank window open so the
   participant does not see the desktop. Its process is still alive; starting
   the next experiment asks whether to close it first.

### Fast-forward

One press ends the **current segment** and moves to the next one — a rest
state, an n-back block, or a fingertapping phase. Use it when something has to
be redone without rerunning the whole paradigm.

* **Ctrl + →** in the paradigm window, or
* **Skip segment ▶▶** in the control panel (works even though the paradigm
  window holds the foreground).

Repeated presses within ~1.2 s are ignored, so one press cannot cascade through
several segments. Every skip is recorded in the run log as a `segment_skipped`
event, and n-back stimuli that were never presented are written to the results
CSV with `Skipped = 1` (the block keeps its full row count, so analysis can
filter on that column). On an instruction screen a skip starts the block
immediately rather than skipping the block itself.

**Ctrl + C** or **Escape** still aborts the run. Inside the n-back stimulus loop
a bare Escape stays a participant response, as it always has — use Ctrl + C
there.

## Triggers and LSL

`TriggerManager` fans each trigger out per program (`keystroke_programs` in
`configs/profiles.json`), cascading TTL → LSL → simulated keystroke per program.

The control panel creates the `TriggerStream` LSL outlet **once at startup** and
holds it until the application quits, so NIRStar binds to it once and never
sees it disappear. Paradigm subprocesses do not create outlets; they send each
marker to the panel over localhost UDP (`auxfunc/marker_relay.py`), stamped with
`pylsl.local_clock()` at the instant of the trigger, and the panel pushes it
with that timestamp. The marker counter next to the mode indicator shows how
many have been relayed.

Started by hand instead of from the control panel (no `--marker_port`), a
paradigm falls back to owning its own outlet.

## Logs

Every launch writes a plain-text log to `logs/` (override with
`paths.log_dir` in `configs/settings.json`), named
`<timestamp>_<paradigm>_<subject>_<profile>.log`. It contains everything the
paradigm printed, a full traceback for any uncaught exception, a `faulthandler`
dump for a hard native crash, and greppable `[EVENT]` lines for triggers,
segment boundaries and skips.

Abnormal endings are also indexed one line each in `logs/crashes.log`:

```
timestamp <TAB> component <TAB> subject <TAB> profile <TAB> error <TAB> log file
```

If a paradigm crashes, the control panel says so, names the log file, and the
n-back writes whatever data it had collected to a `*_PARTIAL.csv`. If
`paths.project_root` cannot be written to, results are rescued to
`logs/rescued_data/` rather than lost.

## Paradigm arguments

Both paradigms accept: `--subject_id`, `--profile`, `--language`,
`--progress_file`, `--command_file`, `--log_file`, `--marker_port`,
`--use_lsl`, `--use_sound`.
