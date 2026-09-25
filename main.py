import tkinter as tk
from tkinter import ttk, messagebox
import argparse, subprocess, sys, os, json, tempfile, gc, threading, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from auxfunc import crashlog
from auxfunc.marker_relay import MarkerRelayServer
from auxfunc.config import load_config, load_overlay, applied_overlays
from auxfunc import apps, fleet, updater, version
from auxfunc.perf_stream import default_path as perf_file_for
from auxfunc.paradigm_utils import write_skip_command

# Comment
# Color palette for indicators
COLOR_OK   = "#2ecc71"   # green: available / connected / owned
COLOR_WARN = "#f39c12"   # amber: usable but not primary, or transferred
COLOR_BAD  = "#95a5a6"   # gray:  unavailable
COLOR_DEAD = "#e74c3c"   # red:   fallback active / error

# Hard-coded NIRStar / Aurora recording comments. The control panel copies
# these to the clipboard so the operator can paste them into the acquisition
# software without retyping them for every run.
NBACK_COMMENT = (
    "PRFMOT16X16 with SDC at D17\n"
    "baseline, short nback with letters"
)
FINGERTAP_COMMENT = (
    "PRFMOT16X16 with SDC at D17\n"
    "baseline, fingertapping"
)

# Selectable UI languages -> code consumed by paradigms / configs/strings.json
LANGUAGES = {'English': 'en', 'Spanish': 'es'}


# LSL stream identity. Kept stable so NIRStar and other consumers reconnect
# automatically when the outlet hands off between control panel and paradigm.
#
# Changed 2026-09: there is no handoff any more. The control panel creates this
# outlet once at startup and keeps it until the application quits, and paradigm
# subprocesses relay their markers to it over localhost UDP (auxfunc/
# marker_relay.py). The old scheme tore the outlet down before every run and
# rebuilt it afterwards, except the rebuild never actually fired -- see
# check_progress() below -- and finished-but-still-open paradigms kept their own
# outlets alive, so several outlets ended up advertising the same source_id and
# NIRStar bound to whichever it happened to resolve first. That is why the third
# paradigm of a session lost its markers.
LSL_STREAM_NAME      = 'TriggerStream'
LSL_STREAM_TYPE      = 'Markers'
LSL_SOURCE_ID        = 'paradigm_triggers'


# Configuration Loading
# ----------------------------------------------------------------------------
def load_configuration(filename):
    """Shared config plus this machine's optional <name>.local.json overlay."""
    try:
        return load_config(filename)
    except FileNotFoundError:
        print(f"Warning: configs/{filename} not found")
        return {}
    except json.JSONDecodeError as e:
        print(f"Error parsing settings.json: {e}")
        return None


def build_experiments_dict(profiles, local_keys=()):
    """Display name -> profile key, for the dropdown.

    Profiles that this machine's profiles.local.json defines or overrides are
    marked, so nobody has to wonder which definition a run used. It also keeps
    a local profile from colliding with a shared one that happens to carry the
    same display_name.
    """
    experiments = {}
    for profile_key, profile_data in profiles.items():
        display_name = profile_data.get('display_name', profile_key)
        if profile_key in local_keys:
            display_name = f"{display_name}  [local]"
        experiments[display_name] = profile_key
    return experiments


# Capability Probing
# ----------------------------------------------------------------------------
def probe_capabilities():
    """
    Non-invasive probe: check for hardware/library presence without holding
    any handles open. The control panel will create its own LSL outlet
    separately once it knows pylsl is available.
    """
    caps = {'ttl': False, 'lsl': False, 'key': True}

    # TTL: enumerate Cedrus devices, release the port immediately
    try:
        import pyxid2
        devices = pyxid2.get_xid_devices()
        if devices:
            caps['ttl'] = True
        for d in devices:
            try:
                d.con.close()
            except Exception:
                pass
    except ImportError:
        print("probe: pyxid2 not installed (TTL unavailable)")
    except Exception as e:
        print(f"probe: TTL detection failed -> {e}")

    # LSL: just check importability — outlet creation is deferred
    try:
        import pylsl  # noqa: F401
        caps['lsl'] = True
    except ImportError:
        print("probe: pylsl not installed (LSL unavailable)")
    except Exception as e:
        print(f"probe: LSL check failed -> {e}")

    return caps


def determine_mode(caps):
    """Strict cascade: TTL > LSL > KEY."""
    if caps.get('ttl'):
        return 'TTL'
    if caps.get('lsl'):
        return 'LSL'
    return 'KEY'


# Export Results Window
# ----------------------------------------------------------------------------
class ExportResultsWindow:
    def __init__(self, parent, results_data):
        self.results = results_data

        self.window = tk.Toplevel(parent)
        self.window.title("Export Results")
        geom_x = self.window.master.winfo_width() - 33
        self.window.geometry(f"{geom_x}x100")
        self.window.resizable(False, False)
        self.window.transient(parent)
        self.window.grab_set()

        main_frame = ttk.Frame(self.window, padding="5")
        main_frame.pack(fill="both", expand=True)
        self.create_results_list(main_frame)
        self.center_window()

    def create_results_list(self, parent):
        files = self.results.get('files', {})
        display_names = {
            'fnirs_nback'           : 'fNIRS - N-back',
            'fnirs_fingertapping'   : 'fNIRS - Fingertapping',
            'eeg_data'              : 'EEG - Recording',
            'eeg_markers'           : 'EEG - Markers'
        }
        for file_type, info in files.items():
            status = info.get('status', 'unknown')
            display_name = display_names.get(file_type, file_type)
            self.create_result_row(parent, display_name, status)

    def create_result_row(self, parent, display_name, status):
        row_frame = ttk.Frame(parent)
        row_frame.pack(fill="x", pady=1)
        if status == 'success':
            icon, color = " ✓ ", "green"
        elif status == 'exists':
            icon, color = "⚠", "orange"
        else:
            icon, color = " ✗ ", "red"
        tk.Label(row_frame, text=icon, font=("Verdana", 10, "bold"),
                 foreground=color, anchor="w").pack(side="left")
        tk.Label(row_frame, text=f" {display_name}",
                 font=("Verdana", 8, "bold"),
                 foreground="black", anchor="w").pack(side="left", fill="x", expand=True)

    def center_window(self, x_offset=17, y_offset=62):
        self.window.update_idletasks()
        parent = self.window.master
        new_x = parent.winfo_x() + x_offset
        new_y = parent.winfo_y() + y_offset
        self.window.geometry(f"+{new_x}+{new_y}")

    def close_window(self):
        self.window.destroy()


# Applications Window
# ----------------------------------------------------------------------------
class ApplicationsWindow:
    """Start and stop the acquisition programs listed in settings.

    Status is polled on a worker thread: finding a window is cheap, but the
    tasklist fallback for a process whose window has gone is not, and the
    control panel must not stutter every two seconds.
    """

    REFRESH_MS = 2000

    def __init__(self, parent, panel):
        self.panel    = panel
        self.registry = apps.registry(panel.settings)
        self.rows     = {}
        self._job     = None
        self._busy    = False

        self.window = tk.Toplevel(parent)
        self.window.title("Applications")
        self.window.transient(parent)
        self.window.resizable(False, False)
        self.window.protocol("WM_DELETE_WINDOW", self.close)

        frame = ttk.Frame(self.window, padding="10")
        frame.pack(fill="both", expand=True)

        if not self.registry:
            ttk.Label(frame, justify="left", text=(
                "No applications configured.\n\n"
                "Add them to configs/settings.local.json:\n\n"
                '  "applications": {\n'
                '      "NIRStar": {\n'
                '          "window": "NIRx NIRStar",\n'
                '          "exe":    "C:\\\\NIRx\\\\NIRStar.exe",\n'
                '          "image":  "NIRStar.exe"\n'
                "      }\n"
                "  }")).pack(anchor="w")
            ttk.Button(frame, text="Close", command=self.close).pack(anchor="e",
                                                                     pady=(10, 0))
            return

        for index, (name, spec) in enumerate(self.registry.items()):
            tk.Label(frame, text=name, font=("TkDefaultFont", 9, "bold"),
                     anchor="w").grid(row=index, column=0, sticky="w", pady=2)
            state = tk.Label(frame, text="…", font=("TkDefaultFont", 9),
                             foreground=COLOR_BAD, anchor="w", width=15)
            state.grid(row=index, column=1, sticky="w", padx=(10, 6))
            start = ttk.Button(frame, text="Launch", width=8,
                               command=lambda n=name: self.launch(n))
            start.grid(row=index, column=2, padx=2)
            stop = ttk.Button(frame, text="Kill", width=6,
                              command=lambda n=name: self.kill(n))
            stop.grid(row=index, column=3, padx=2)
            self.rows[name] = {'state': state, 'launch': start, 'kill': stop,
                               'spec': spec}

        footer = ttk.Frame(frame)
        footer.grid(row=len(self.registry), column=0, columnspan=4,
                    sticky="ew", pady=(10, 0))
        ttk.Button(footer, text="Launch all",
                   command=self.launch_all).pack(side="left")
        ttk.Button(footer, text="Close", command=self.close).pack(side="right")

        self.message = tk.Label(frame, text="", font=("TkDefaultFont", 8),
                                foreground="#555555", anchor="w",
                                wraplength=360, justify="left")
        self.message.grid(row=len(self.registry) + 1, column=0, columnspan=4,
                          sticky="w", pady=(6, 0))
        if not apps.kill_supported():
            self._say("Stopping programs only works on Windows; Launch still does.")

        self.refresh()
        self.center()

    # ---- plumbing ---------------------------------------------------------- #
    def center(self, x_offset=30, y_offset=90):
        self.window.update_idletasks()
        parent = self.window.master
        self.window.geometry(f"+{parent.winfo_x() + x_offset}"
                             f"+{parent.winfo_y() + y_offset}")

    def _say(self, text):
        if getattr(self, 'message', None) is not None:
            self.message.config(text=text)

    def _set_busy(self, busy):
        self._busy = busy
        state = 'disabled' if busy else '!disabled'
        for row in self.rows.values():
            row['launch'].state([state])
            row['kill'].state([state])

    def refresh(self):
        """Poll status off the UI thread, then paint the result on it."""
        if not self.rows:
            return

        def work():
            found = {name: apps.status(row['spec'])
                     for name, row in self.rows.items()}
            try:
                self.window.after(0, lambda: self._paint(found))
            except Exception:
                pass                      # window closed while we were looking

        threading.Thread(target=work, name='app-status', daemon=True).start()
        self._job = self.window.after(self.REFRESH_MS, self.refresh)

    def _paint(self, found):
        colors = {apps.RUNNING: COLOR_OK, apps.NOT_RESPONDING: COLOR_DEAD,
                  apps.NOT_RUNNING: COLOR_BAD}
        for name, info in found.items():
            row = self.rows.get(name)
            if row is None:
                continue
            row['state'].config(text=info['state'],
                                foreground=colors.get(info['state'], COLOR_BAD))
            if not self._busy:
                running = info['state'] != apps.NOT_RUNNING
                row['launch'].state(['disabled' if running else '!disabled'])
                row['kill'].state(['!disabled' if (running and apps.kill_supported())
                                   else 'disabled'])

    # ---- actions ------------------------------------------------------------ #
    def launch(self, name):
        ok, message = apps.launch(self.rows[name]['spec'])
        self.panel.log.log(f"Applications: launch {name} -> {message}")
        self._say(f"{name}: {message}")

    def launch_all(self):
        for name, row in self.rows.items():
            if apps.status(row['spec'])['state'] == apps.NOT_RUNNING:
                self.launch(name)
        self._say("Launched everything that was not already running.")

    def kill(self, name):
        if not messagebox.askyesno(
                "Stop program",
                f"Force {name} to close?\n\n"
                "Anything it is recording right now will be lost.",
                parent=self.window):
            return
        self._set_busy(True)
        self._say(f"Stopping {name}…")

        def work():
            ok, message = apps.kill(self.rows[name]['spec'])
            def done():
                self._set_busy(False)
                self.panel.log.log(f"Applications: kill {name} -> {message}")
                self._say(f"{name}: {message}")
            try:
                self.window.after(0, done)
            except Exception:
                pass

        threading.Thread(target=work, name='app-kill', daemon=True).start()

    def close(self):
        if self._job is not None:
            try:
                self.window.after_cancel(self._job)
            except Exception:
                pass
            self._job = None
        self.window.destroy()


# Control Panel
# ----------------------------------------------------------------------------
class ControlPanel:
    def __init__(self, root, dry_run=False, subject=None):
        # Load configs
        self.settings = load_configuration('settings.json')
        self.profiles = load_configuration('profiles.json')
        if not self.settings or not self.profiles:
            messagebox.showerror("Error", "Failed to load settings / profiles.")
            sys.exit(1)

        # Window setup
        self.root = root
        self.app_version = version.describe()
        window_title = self.settings['control_panel']['window_name']
        window_title += f"  ·  {self.app_version}"
        if dry_run:
            window_title += "  —  DRY RUN"
        self.root.title(window_title)

        self.display_config = self.settings.get('display',       {})
        self.paths_config   = self.settings.get('paths',         {})
        self.panel_config   = self.settings.get('control_panel', {})

        self.script_dir = os.path.dirname(os.path.abspath(__file__))

        # Dry run: a throwaway session for testing the software itself. Every
        # file this run produces -- panel log, run log, trial feed -- goes in
        # one folder under the OS temp directory, and no results are written
        # anywhere. Nothing lands beside the repo or in project_root.
        self.dry_run = bool(dry_run)
        if self.dry_run:
            self.log_dir = crashlog.resolve_log_dir(
                os.path.join(tempfile.gettempdir(),
                             f"cbgPARADIGM-dryrun-{time.strftime('%Y%m%d_%H%M%S')}"))
        else:
            self.log_dir = crashlog.resolve_log_dir(self.paths_config.get('log_dir'))
        self.log        = crashlog.install('control_panel', log_dir=self.log_dir)
        self.log.log(f"Log directory: {self.log_dir}")

        # Build identity, first thing in every log: a bug report that names a
        # version is worth ten that describe symptoms.
        build = version.details()
        self.log.log(f"cbgPARADIGM {build['version']} "
                     f"(branch {build['branch'] or '?'}, {build['source']})"
                     + ("  *** LOCAL EDITS ***" if build['dirty'] else ""))
        for overlay in applied_overlays():
            self.log.log(f"Config overlay applied: {overlay}")

        # Which protocols came from this machine rather than from the repo.
        profile_overlay     = load_overlay('profiles.json')
        self._local_profiles = {key for key, value in profile_overlay.items()
                                if value is not None}
        hidden = sorted(key for key, value in profile_overlay.items() if value is None)
        if profile_overlay:
            self.log.log(
                f"Profiles: {len(self.profiles)} available; local overlay defines "
                f"{', '.join(sorted(self._local_profiles)) or 'nothing'}"
                + (f"; hides {', '.join(hidden)}" if hidden else ""))

        # Tell the shared folder which build this machine is on. Background
        # thread: a mapped drive that has gone away must not delay startup.
        if not self.dry_run:
            fleet.report(fleet.resolve_fleet_dir(self.settings),
                         app='control_panel', logger=self.log,
                         extra={'log_dir': self.log_dir})

        window_size = list(self.panel_config.get('window_size',    [400, 500]))
        window_pos  = self.panel_config.get('window_position', [50, 450])
        if self.dry_run:
            window_size[1] += 40          # room for the dry-run banner
        self.root.geometry(f"{window_size[0]}x{window_size[1]}")
        self.root.geometry(f"+{window_pos[0]}+{window_pos[1]}")

        self.experiments = build_experiments_dict(self.profiles, self._local_profiles)

        # Probe capabilities and decide cascade-winning mode
        self.capabilities = probe_capabilities()
        self.active_mode  = determine_mode(self.capabilities)
        self.log.log(f"Marker mode: {self.active_mode} (capabilities: {self.capabilities})")

        # LSL outlet handle. The control panel owns this for the whole session:
        # it is created once, below, and destroyed only when the application
        # quits, so a consumer that binds to TriggerStream never sees it vanish.
        # Paradigms push into it through self._relay instead of making their own.
        self._lsl_outlet     = None
        self._relay          = None
        self._marker_port    = None
        self._outlet_broken  = False
        self._relayed_shown  = -1

        # Build UI
        main_frame = ttk.Frame(root, padding="10")
        main_frame.pack(fill="both", expand=True)

        if self.dry_run:
            tk.Label(main_frame,
                     text=f"DRY RUN — no results are saved.\nEverything goes to "
                          f"{self.log_dir}",
                     background=COLOR_WARN, foreground="#ffffff",
                     font=("TkDefaultFont", 9, "bold"), justify="left",
                     anchor="w", padx=6, pady=3,
                     wraplength=(window_size[0] - 40)).pack(fill="x", padx=5,
                                                            pady=(0, 6))

        # ---- Recording Information --------------------------------------- #
        recording_frame = ttk.LabelFrame(main_frame, text="Recording Information", padding="10")
        recording_frame.pack(fill="x", padx=5, pady=5)

        ttk.Label(recording_frame, text="Subject ID:").pack(anchor="w")

        subject_frame = ttk.Frame(recording_frame)
        subject_frame.pack(fill="x", pady=5)
        self.subject_id = ttk.Entry(subject_frame)
        self.subject_id.pack(side="left", fill="x", expand=True, padx=(0, 5))
        if subject:
            self.subject_id.insert(0, subject)
        elif self.dry_run:
            self.subject_id.insert(0, "DRYRUN")
        self.export_button = ttk.Button(
            subject_frame, text="Export", command=self.export_data, width=6
        )
        self.export_button.pack(side="right")

        # Recording comments. The marker mode used to be shown here; the
        # TTL / LSL / KEY indicators at the bottom of the panel already say
        # which one is active, so the space goes to the clipboard buttons.
        comment_frame = ttk.Frame(recording_frame)
        comment_frame.pack(fill="x", pady=(4, 0))

        self.nb_comment_button = ttk.Button(
            comment_frame, text="NB comment",
            command=lambda: self.copy_comment('nback')
        )
        self.nb_comment_button.pack(side="left", fill="x", expand=True, padx=(0, 3))

        self.ft_comment_button = ttk.Button(
            comment_frame, text="FT comment",
            command=lambda: self.copy_comment('fingertapping')
        )
        self.ft_comment_button.pack(side="left", fill="x", expand=True, padx=(3, 0))

        # ---- Experiment Selection --------------------------------------- #
        button_frame = ttk.LabelFrame(main_frame, text="Experiment Selection", padding="10")
        button_frame.pack(fill="x", padx=5, pady=5)

        ttk.Button(button_frame, text="Play Video Instructions",
                   command=self.play_video).pack(fill="x", pady=2)
        ttk.Button(button_frame, text="Run N-back Tutorial",
                   command=self.run_tutorial).pack(fill="x", pady=2)

        dropdown_frame = ttk.Frame(button_frame)
        dropdown_frame.pack(fill="x", pady=5)

        self.selected_experiment = tk.StringVar()
        self.experiment_dropdown = ttk.Combobox(
            dropdown_frame, textvariable=self.selected_experiment, state="readonly"
        )
        self.experiment_dropdown['values'] = list(self.experiments.keys())
        if self.experiments:
            self.experiment_dropdown.current(0)
        self.experiment_dropdown.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.experiment_dropdown.bind('<<ComboboxSelected>>', self.on_paradigm_change)

        self.use_beep_var = tk.BooleanVar(value=True)
        self.beep_checkbox = ttk.Checkbutton(
            dropdown_frame, text="Play sound", variable=self.use_beep_var
        )
        self.beep_checkbox.pack(side="right")

        # Language picker
        lang_frame = ttk.Frame(button_frame)
        lang_frame.pack(fill="x", pady=(0, 2))
        ttk.Label(lang_frame, text="Language:",
                  font=("TkDefaultFont", 9)).pack(side="left")
        self.selected_language = tk.StringVar(value="English")
        self.language_dropdown = ttk.Combobox(
            lang_frame, textvariable=self.selected_language,
            state="readonly", width=12
        )
        self.language_dropdown['values'] = list(LANGUAGES.keys())
        self.language_dropdown.current(0)
        self.language_dropdown.pack(side="left", padx=(4, 0))

        # Keep the panel above the paradigm window, which pulls itself to the
        # foreground on a timer while a run is in progress.
        self.always_on_top = tk.BooleanVar(
            value=bool(self.panel_config.get('always_on_top', False))
        )
        self.topmost_check = ttk.Checkbutton(
            lang_frame, text="On top", variable=self.always_on_top,
            command=self.toggle_always_on_top
        )
        self.topmost_check.pack(side="right")
        if self.always_on_top.get():
            self.toggle_always_on_top()

        # Programs indicator
        programs_frame = ttk.Frame(button_frame)
        programs_frame.pack(fill="x", pady=(0, 5))
        ttk.Label(programs_frame, text="Programs:",
                  font=("TkDefaultFont", 9)).pack(side="left")
        self.programs_label = ttk.Label(
            programs_frame, text="—",
            font=("TkDefaultFont", 9, "italic"),
            foreground="#555555"
        )
        self.programs_label.pack(side="left", padx=(4, 0))

        self.start_button = ttk.Button(
            button_frame, text="Start Experiment", command=self.start_experiment
        )
        self.start_button.pack(fill="x", pady=5)

        tools_frame = ttk.Frame(button_frame)
        tools_frame.pack(fill="x")
        self.apps_button = ttk.Button(
            tools_frame, text="Applications", command=self.open_applications
        )
        self.apps_button.pack(side="left", fill="x", expand=True, padx=(0, 3))
        self.update_button = ttk.Button(
            tools_frame, text="Check for updates", command=self.check_for_updates
        )
        self.update_button.pack(side="left", fill="x", expand=True, padx=(3, 0))

        self.on_paradigm_change()

        # ---- Progress --------------------------------------------------- #
        progress_frame = ttk.LabelFrame(main_frame, text="Experiment Progress", padding="10")
        progress_frame.pack(fill="x", padx=5, pady=5)

        self.status_label = ttk.Label(
            progress_frame,
            text="Initialization complete. Select experiment to start..."
        )
        self.status_label.pack(fill="x", pady=(0, 5))

        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(
            progress_frame, variable=self.progress_var,
            maximum=100, length=300, mode='determinate'
        )
        self.progress_bar.pack(fill="x", pady=5)

        pct_frame = ttk.Frame(progress_frame)
        pct_frame.pack(fill="x")
        self.percentage_label = ttk.Label(pct_frame, text="0%")
        self.percentage_label.pack(side="left")

        # Fast-forward. The paradigm window grabs the foreground continuously,
        # so this writes into a command file the paradigm polls rather than
        # relying on the operator being able to reach this window's keyboard
        # focus. Ctrl+Right in the paradigm window does the same thing.
        self.skip_button = ttk.Button(
            pct_frame, text="Skip segment ▶▶", command=self.skip_segment, width=17
        )
        self.skip_button.pack(side="right")
        self.skip_button.state(['disabled'])

        # Opens the live performance view in its own process. Read-only and
        # entirely optional: the paradigm writes the trial file either way.
        self.perf_button = ttk.Button(
            pct_frame, text="Monitor", command=self.open_perf_monitor, width=9
        )
        self.perf_button.pack(side="right", padx=(0, 4))

        # ---- Bottom: termination hint + capability indicators ----------- #
        self.termination_label = ttk.Label(
            main_frame,
            text="Ctrl + C terminates the test · Ctrl + → skips the current segment.",
            font=("TkDefaultFont", 9, "italic"),
            foreground="gray"
        )
        self.termination_label.pack(fill="x", pady=(5, 0))

        cap_frame = ttk.Frame(main_frame)
        cap_frame.pack(fill="x", pady=(2, 0))
        self._ttl_dot = self._make_cap_indicator(cap_frame, "TTL",
                                                 COLOR_OK if self.capabilities['ttl'] else COLOR_BAD)
        self._lsl_dot = self._make_cap_indicator(cap_frame, "LSL",
                                                 COLOR_BAD)  # set properly after outlet creation
        self._key_dot = self._make_cap_indicator(cap_frame, "KEY",
                                                 COLOR_OK if self.capabilities['key'] else COLOR_BAD)

        self.marker_label = tk.Label(
            cap_frame, text="", font=("TkDefaultFont", 9),
            foreground="#555555"
        )
        self.marker_label.pack(side="right")

        self.log_label = ttk.Label(
            main_frame, text=f"{self.app_version}  ·  Logs: {self.log_dir}",
            font=("TkDefaultFont", 8), foreground="#777777"
        )
        self.log_label.pack(fill="x", pady=(4, 0))

        # Process state
        self.process           = None
        self.process_meta      = {}
        self.temp_file         = None
        self.command_file      = None
        # Trial feed for the performance monitor. Kept after the run ends so
        # the button still opens the last run rather than an empty picker.
        self.perf_file         = None
        self._run_log_handle   = None
        self.progress_complete = False     # paradigm reported 100%
        self.last_status       = ""
        self.skip_seq          = 0

        # Bring up the session-long LSL outlet and the marker relay it feeds
        if self.capabilities['lsl']:
            self._create_lsl_outlet(initial=True)
            self._start_relay()
        else:
            self._set_lsl_dot(COLOR_BAD)

        # What the last update check found, if anything.
        self._update_info = None

        # Look for an update once, quietly, after the window is up. Never pulls:
        # it only relabels the button, so a machine three versions behind says
        # so without anyone having to think to ask.
        if not self.dry_run:
            self.root.after(1500, lambda: self._start_update_check(interactive=False))

        # Periodic poll
        self.check_progress()

    # ---- UI helpers ---------------------------------------------------- #
    def _make_cap_indicator(self, parent, label, color):
        frame = ttk.Frame(parent)
        frame.pack(side="left", padx=(0, 12))
        dot = tk.Label(frame, text="●", foreground=color,
                       font=("TkDefaultFont", 11))
        dot.pack(side="left")
        tk.Label(frame, text=label,
                 font=("TkDefaultFont", 9)).pack(side="left", padx=(2, 0))
        return dot

    def _set_lsl_dot(self, color):
        if hasattr(self, '_lsl_dot') and self._lsl_dot is not None:
            self._lsl_dot.config(foreground=color)

    @staticmethod
    def _format_progress(progress, segment_index=0, segment_total=0):
        """'43.21%' on its own, '43.21% · segment 3/6' while a run is in progress."""
        try:
            text = f"{float(progress):.2f}%"
        except (TypeError, ValueError):
            return "—"
        if segment_index and segment_total:
            text += f" · segment {segment_index}/{segment_total}"
        return text

    def toggle_always_on_top(self):
        """Pin / unpin the control panel above every other window."""
        on = bool(self.always_on_top.get())
        try:
            self.root.attributes('-topmost', on)
        except Exception as e:
            self.log.error(f"ControlPanel: could not set always-on-top -> {e}")
            self.always_on_top.set(not on)          # leave the box telling the truth
            return
        self.log.log(f"Always-on-top {'enabled' if on else 'disabled'}")

    def copy_comment(self, which):
        """Copy the hard-coded recording comment for `which` to the clipboard."""
        text, button = {
            'nback':         (NBACK_COMMENT,     self.nb_comment_button),
            'fingertapping': (FINGERTAP_COMMENT, self.ft_comment_button),
        }[which]
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            # Hand the selection over to the window manager right away, so the
            # text is pastable even if the panel is busy afterwards.
            self.root.update()
        except Exception as e:
            self.log.error(f"ControlPanel: clipboard copy failed -> {e}")
            messagebox.showerror("Copy failed",
                                 f"Could not copy the comment to the clipboard:\n{e}")
            return
        self.log.log(f"Copied {which} recording comment to clipboard")
        self._flash_button(button)

    def _flash_button(self, button, restore_after=1200):
        """Confirm on the button itself, then put its own label back."""
        original = getattr(button, '_flash_original', None) or button.cget('text')
        job = getattr(button, '_flash_job', None)
        if job:
            self.root.after_cancel(job)
        button._flash_original = original
        button.config(text="Copied ✓")

        def restore():
            button._flash_job = None
            button.config(text=button._flash_original)

        button._flash_job = self.root.after(restore_after, restore)

    def on_paradigm_change(self, event=None):
        """Refresh the programs label when the selected paradigm changes."""
        experiment_name = self.selected_experiment.get()
        profile_key = self.experiments.get(experiment_name)
        if not profile_key:
            self.programs_label.config(text="—")
            return
        profile = self.profiles.get(profile_key, {})
        programs = profile.get('keystroke_programs', [])
        if not programs:
            self.programs_label.config(text="(none configured)")
            return
        names = [p.get('window', '?') for p in programs]
        self.programs_label.config(text=", ".join(names))

    # ---- LSL outlet + marker relay ------------------------------------- #
    def _create_lsl_outlet(self, initial=False):
        """Bring up the LSL outlet this control panel owns for the session."""
        if self._lsl_outlet is not None:
            return
        try:
            import pylsl
            info = pylsl.StreamInfo(
                name=LSL_STREAM_NAME,
                type=LSL_STREAM_TYPE,
                channel_count=1,
                nominal_srate=0,
                channel_format='int32',
                source_id=LSL_SOURCE_ID,
            )
            self._lsl_outlet = pylsl.StreamOutlet(info)
            self._outlet_broken = False
            # Heartbeat / "control panel has the stream" marker. Harmless to
            # consumers that ignore it; useful as evidence the outlet is alive.
            try:
                self._lsl_outlet.push_sample([999])
            except Exception:
                pass
            self._set_lsl_dot(COLOR_OK)
            who = "boot" if initial else "recovery"
            self.log.log(f"ControlPanel: LSL outlet up ({who}), "
                         f"name={LSL_STREAM_NAME} source_id={LSL_SOURCE_ID}")
        except Exception as e:
            self._lsl_outlet = None
            self._set_lsl_dot(COLOR_DEAD)
            self.log.error(f"ControlPanel: LSL outlet create failed -> {e}")

    def _start_relay(self):
        """Listen for markers from paradigm subprocesses."""
        if self._relay is not None:
            return
        try:
            self._relay = MarkerRelayServer(self._push_marker, logger=self.log)
            self._marker_port = self._relay.start()
        except Exception as e:
            self._relay = None
            self._marker_port = None
            self.log.error(f"ControlPanel: marker relay failed to start -> {e}")
            messagebox.showwarning(
                "Marker relay unavailable",
                "Could not open the local marker relay socket.\n\n"
                "Paradigms will fall back to simulated keystrokes for any "
                "program routed to LSL.")

    def _push_marker(self, value, timestamp):
        """Called on the relay thread. Touches the outlet only -- never Tk."""
        outlet = self._lsl_outlet
        if outlet is None:
            self._outlet_broken = True
            raise RuntimeError("no LSL outlet")
        try:
            if timestamp is None:
                outlet.push_sample([int(value)])
            else:
                outlet.push_sample([int(value)], float(timestamp))
        except Exception:
            self._outlet_broken = True
            raise

    def _service_lsl(self):
        """Main-thread health check for the outlet, run from check_progress."""
        if not self.capabilities['lsl']:
            return
        if self._outlet_broken:
            self.log.error("ControlPanel: LSL outlet reported an error; rebuilding")
            self._destroy_lsl_outlet()
            self._outlet_broken = False
            self._create_lsl_outlet()
        elif self._lsl_outlet is None:
            self._create_lsl_outlet()

        if self._relay is not None and self._relay.markers_relayed != self._relayed_shown:
            self._relayed_shown = self._relay.markers_relayed
            self.marker_label.config(text=f"{self._relayed_shown} markers")

    def _destroy_lsl_outlet(self):
        """Final teardown on shutdown."""
        if self._lsl_outlet is None:
            return
        try:
            outlet = self._lsl_outlet
            self._lsl_outlet = None
            del outlet
            gc.collect()
        except Exception as e:
            self.log.warn(f"ControlPanel: error destroying LSL outlet -> {e}")

    # ---- Export -------------------------------------------------------- #
    def export_data(self):
        subject = self.validate_subject_id()
        if not subject:
            return
        export_script = os.path.join(self.script_dir, "auxfunc", "extract_record.py")
        if not os.path.exists(export_script):
            messagebox.showerror("Error", f"Export script '{export_script}' not found!")
            return

        self.log.log(f"Exporting data for {subject}...")
        self.root.update()
        try:
            cmd_args = [sys.executable, "-u", export_script,
                        "--subject_id",   subject,
                        "--project_root", self.paths_config.get('project_root', ''),
                        "--nirx_data",    self.paths_config.get('nirx_data', ''),
                        "--eeg_data",     self.paths_config.get('emotiv_data', '')]
            process = subprocess.Popen(cmd_args, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True,
                                       cwd=self.script_dir)
            # communicate() drains both pipes, so this one is safe to keep.
            stdout, stderr = process.communicate(timeout=300)
            if stderr:
                self.log.warn(f"export stderr:\n{stderr.strip()}")
            export_results = self.parse_export_results(stdout)
            if export_results:
                ExportResultsWindow(self.root, export_results)
            elif process.returncode == 0:
                messagebox.showinfo("Export Complete", f"Data exported for {subject}")
            else:
                self._show_export_error(subject, f"Export failed (code {process.returncode})")
        except subprocess.TimeoutExpired:
            process.kill()
            self._show_export_error(subject, "Export timed out after 5 minutes")
        except Exception as e:
            self.log.exception("export failed", fatal=False)
            self._show_export_error(subject, str(e))

    def _show_export_error(self, subject, message):
        error_results = {
            'subject_id': subject,
            'files': {key: {'status': 'error', 'message': message, 'path': ''}
                      for key in ['fnirs_nback', 'fnirs_fingertapping', 'eeg_data', 'eeg_markers']}
        }
        ExportResultsWindow(self.root, error_results)
        self.log.error(f"Export error: {message}")

    def parse_export_results(self, stdout):
        try:
            start_marker = "=== EXPORT_RESULTS_JSON ==="
            end_marker   = "=== END_EXPORT_RESULTS_JSON ==="
            start_idx = stdout.find(start_marker)
            end_idx   = stdout.find(end_marker)
            if start_idx != -1 and end_idx != -1:
                json_start = start_idx + len(start_marker)
                json_text = stdout[json_start:end_idx].strip()
                return json.loads(json_text)
            self.log.warn("Could not find JSON results markers in output")
            return None
        except json.JSONDecodeError as e:
            self.log.error(f"Failed to parse export results JSON: {e}")
            return None
        except Exception as e:
            self.log.error(f"Error parsing export results: {e}")
            return None

    # ---- Misc inputs --------------------------------------------------- #
    def validate_subject_id(self):
        subject = self.subject_id.get().strip()
        if not subject:
            messagebox.showerror("Error", "Please enter a Subject ID")
            return None
        return subject

    def play_video(self):
        subject = self.validate_subject_id()
        if not subject:
            return
        video_path = self.paths_config.get('video_instructions', '')
        if not video_path:
            messagebox.showerror("Error", "Video path not configured in settings.json")
            return
        try:
            if sys.platform == "win32":
                os.startfile(video_path)
            else:
                opener = "open" if sys.platform == "darwin" else "xdg-open"
                subprocess.call([opener, video_path])
        except Exception as e:
            messagebox.showerror("Error", f"Could not play video: {str(e)}")

    def run_tutorial(self):
        # Absolute path + explicit cwd: the old relative "paradigms/..." only
        # resolved when the panel happened to be started from the repo root,
        # which main.bat does not do.
        tutorial = os.path.join(self.script_dir, "paradigms", "nback_tutorial.py")
        try:
            log_path = crashlog.new_log_path('tutorial', configured_dir=self.log_dir)
            handle = open(log_path, 'a', buffering=1, encoding='utf-8', errors='replace')
            subprocess.Popen([sys.executable, "-u", tutorial],
                             stdout=handle, stderr=subprocess.STDOUT,
                             cwd=self.script_dir)
            self.log.log(f"Tutorial started; log -> {log_path}")
        except Exception as e:
            self.log.exception("could not start tutorial", fatal=False)
            messagebox.showerror("Error", f"Could not start tutorial: {str(e)}")

    # ---- Fast-forward -------------------------------------------------- #
    def open_applications(self):
        """Start / stop the acquisition programs listed in settings."""
        try:
            ApplicationsWindow(self.root, self)
        except Exception as e:
            self.log.exception("could not open the applications window", fatal=False)
            messagebox.showerror("Applications", str(e))

    # ---- updates ------------------------------------------------------- #
    def _start_update_check(self, interactive):
        """Fetch and compare on a worker thread; the UI never waits on git."""
        if interactive:
            self.update_button.state(['disabled'])
            self.update_button.config(text="Checking…")

        timeout = updater.MANUAL_TIMEOUT if interactive else updater.AUTO_TIMEOUT

        def work():
            try:
                info = updater.check(timeout=timeout)
            except Exception as exc:       # belt and braces: check() is no-raise
                info = {'ok': False, 'error': f"{type(exc).__name__}: {exc}",
                        'behind': 0, 'ahead': 0, 'incoming': [], 'target': None,
                        'upstream': None, 'branch': None, 'dirty': False}
            try:
                self.root.after(0, lambda: self._update_checked(info, interactive))
            except Exception:
                pass                       # panel closed mid-check

        threading.Thread(target=work, name='update-check', daemon=True).start()

    def _update_checked(self, info, interactive):
        try:
            self._apply_update_check(info, interactive)
        except tk.TclError:
            pass                           # panel is closing; nothing to update
        except Exception:
            self.log.exception("update check callback failed", fatal=False)

    def _apply_update_check(self, info, interactive):
        self.update_button.state(['!disabled'])
        self._update_info = info

        if not info['ok']:
            self.log.warn(f"Update check failed: {info['error']}")
            self.update_button.config(text="Check for updates")
            if interactive:
                messagebox.showwarning("Update check", info['error'])
            return

        if info['behind']:
            target = info['target'] or f"{info['behind']} commits"
            self.log.log(f"Update available: {target} "
                         f"({info['behind']} commit(s) behind {info['upstream']})")
            self.update_button.config(text=f"Update available: {target}")
            if interactive:
                self._offer_update()
        else:
            self.log.log(f"Up to date with {info['upstream']}"
                         + (f"; {info['ahead']} local commit(s) not pushed"
                            if info['ahead'] else ""))
            self.update_button.config(text="Check for updates")
            if interactive:
                messagebox.showinfo("Up to date",
                                    f"This machine matches {info['upstream']}.")

    def check_for_updates(self):
        info = self._update_info
        if info and info.get('ok') and info.get('behind'):
            self._offer_update()           # already know; go straight to the offer
        else:
            self._start_update_check(interactive=True)

    def _offer_update(self):
        info = self._update_info or {}
        if self.process and self.process.poll() is None:
            messagebox.showwarning(
                "Paradigm running",
                "A paradigm is still running.\n\nUpdating now would leave this "
                "control panel driving newer paradigm code. Finish the session "
                "first.")
            return

        listing = "\n".join(f"  {sha}  {subject}"
                             for sha, subject in info.get('incoming', [])[:10])
        if len(info.get('incoming', [])) > 10:
            listing += f"\n  … and {len(info['incoming']) - 10} more"

        warning = ""
        if info.get('dirty'):
            warning = ("\n\nNOTE: this copy has local edits. The update will "
                       "refuse rather than overwrite them.")

        if not messagebox.askyesno(
                "Update available",
                f"{info.get('behind', '?')} commit(s) behind "
                f"{info.get('upstream', 'the server')}"
                + (f", up to {info['target']}" if info.get('target') else "")
                + f":\n\n{listing}\n\n"
                  "The control panel will close and reopen once it is done."
                + warning):
            return

        self.update_button.state(['disabled'])
        self.update_button.config(text="Updating…")

        def work():
            ok, message = updater.apply_update()
            try:
                self.root.after(0, lambda: self._update_applied(ok, message))
            except Exception:
                pass

        threading.Thread(target=work, name='update-apply', daemon=True).start()

    def _update_applied(self, ok, message):
        self.update_button.state(['!disabled'])
        if not ok:
            self.update_button.config(text="Check for updates")
            self.log.warn(f"Update refused: {message}")
            messagebox.showerror("Update not applied", message)
            return

        self.log.log(f"Updated: {message}")
        self._update_info = None
        if messagebox.askyesno("Update installed",
                               f"{message}\n\nRestart the control panel now?"):
            self.restart()
        else:
            self.update_button.config(text="Restart to finish updating")

    def restart(self):
        """Relaunch this panel as a fresh process and let this one go.

        A running python process cannot adopt new source, so the only honest
        way to finish an update is to hand over to a new one. Detached, so the
        replacement does not die with us.
        """
        target = [sys.executable, os.path.join(self.script_dir, 'main.py')]
        if self.dry_run:
            target.append('--dry-run')
        subject = self.subject_id.get().strip()
        if subject:
            target += ['--subject', subject]

        options = {'cwd': self.script_dir, 'close_fds': True}
        if os.name == 'nt':
            options['creationflags'] = (subprocess.DETACHED_PROCESS
                                        | subprocess.CREATE_NEW_PROCESS_GROUP)
        else:
            options['start_new_session'] = True

        try:
            subprocess.Popen(target, **options)
        except Exception as e:
            self.log.error(f"restart failed -> {e}")
            messagebox.showerror("Restart failed",
                                 f"{e}\n\nClose and reopen the panel by hand.")
            return

        self.log.log("Restarting the control panel after an update")
        self.shutdown()
        self.root.destroy()

    def open_perf_monitor(self):
        """Launch the live performance view as its own process.

        Separate process on purpose: it only reads the trial file, so nothing
        it does -- redrawing, resizing, being closed -- can reach the paradigm.
        """
        script = os.path.join(self.script_dir, 'auxfunc', 'perf_monitor.py')
        if not os.path.exists(script):
            messagebox.showerror("Monitor not found", f"Missing:\n{script}")
            return

        args = [sys.executable, script]
        if self.perf_file and os.path.exists(self.perf_file):
            args += ["--file", self.perf_file]
        else:
            args += ["--start-dir", self.log_dir]

        # Park it immediately to the right of this window.
        try:
            self.root.update_idletasks()
            x = self.root.winfo_x() + self.root.winfo_width() + 12
            y = self.root.winfo_y()
            args += ["--geometry", f"460x300+{max(0, x)}+{max(0, y)}"]
        except Exception:
            pass

        try:
            subprocess.Popen(args, cwd=self.script_dir,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.log.log(f"Performance monitor launched: {' '.join(args[1:])}")
        except Exception as e:
            self.log.error(f"could not launch the performance monitor -> {e}")
            messagebox.showerror("Monitor failed to start", str(e))

    def skip_segment(self):
        """Ask the running paradigm to end its current segment."""
        if not (self.process and self.process.poll() is None):
            messagebox.showinfo("Nothing to skip",
                                "No experiment is currently running.")
            return
        self.skip_seq += 1
        if write_skip_command(self.command_file, self.skip_seq):
            self.log.event('skip_button', seq=self.skip_seq,
                           at_status=self.last_status)
            self.status_label.config(text=f"Skip requested ({self.skip_seq})...")
        else:
            messagebox.showwarning("Skip failed",
                                   "Could not write the skip command file.\n"
                                   "Use Ctrl + → in the paradigm window instead.")

    # ---- Experiment lifecycle ----------------------------------------- #
    def start_experiment(self):
        # A finished paradigm keeps its window open on purpose, but its process
        # is still alive and still holds the participant display. Launching over
        # the top of it used to orphan the old process silently.
        if self.process and self.process.poll() is None:
            if not messagebox.askyesno(
                    "Paradigm still running",
                    "The previous paradigm window is still open.\n\n"
                    "Close it and start the new experiment?"):
                return
            self._terminate_process("superseded by a new experiment")

        if self.process is not None:
            # Exited between check_progress ticks: reap it here so its progress
            # file, command file and log handle are closed before we make new
            # ones, and so a crash from the previous run is still reported.
            code = self.process.poll()
            if code is not None:
                self._on_process_exit(code)

        subject = self.validate_subject_id()
        if not subject:
            return

        experiment_name = self.selected_experiment.get()
        profile_key = self.experiments.get(experiment_name)
        if not profile_key:
            messagebox.showerror("Error", "Please select an experiment")
            return

        profile_config = self.profiles.get(profile_key, {})
        module_name = profile_config.get('module', '')
        if not module_name:
            messagebox.showerror("Error", f"No module defined for profile: {profile_key}")
            return

        script_path = os.path.join(self.script_dir, 'paradigms', module_name)
        if not os.path.exists(script_path):
            messagebox.showerror("Error", f"Paradigm module not found:\n{script_path}")
            return

        self.progress_complete = False
        self.last_status = ""

        try:
            # Progress IPC
            self.temp_file = tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.json')
            temp_path = self.temp_file.name
            json.dump({"progress": 0, "status": f"Starting {experiment_name}..."},
                      self.temp_file)
            self.temp_file.flush()

            # Fast-forward IPC. Separate file so a skip never races a progress
            # write, and reset per run so a stale request cannot fire.
            command_handle = tempfile.NamedTemporaryFile(mode='w+', delete=False,
                                                         suffix='.cmd.json')
            self.command_file = command_handle.name
            json.dump({"skip_seq": 0}, command_handle)
            command_handle.flush()
            command_handle.close()
            self.skip_seq = 0

            # One log file per run, written to directly by the subprocess.
            # NOT subprocess.PIPE: nothing here ever drained those pipes, so the
            # ~4 KB Windows pipe buffer filled up and the paradigm blocked
            # forever on its next print -- which is what "it crashed after the
            # resting states" actually was. run_trials is the first code that
            # logs on every frame, so the buffer filled the moment the
            # cognitive block started.
            run_log_path = crashlog.new_log_path(
                os.path.splitext(module_name)[0], subject, profile_key, self.log_dir)
            self._run_log_handle = open(run_log_path, 'a', buffering=1,
                                        encoding='utf-8', errors='replace')

            # Per-trial performance feed, beside the run log.
            self.perf_file = perf_file_for(run_log_path)

            # Unified flag-style args for both paradigm modules
            language_code = LANGUAGES.get(self.selected_language.get(), 'en')
            cmd_args = [sys.executable, "-u", script_path,
                        "--subject_id",    subject,
                        "--progress_file", temp_path,
                        "--command_file",  self.command_file,
                        "--log_file",      run_log_path,
                        "--profile",       profile_key,
                        "--language",      language_code,
                        "--perf_file",     self.perf_file,
                        "--use_lsl"]   # always; TriggerManager handles availability
            if self.dry_run:
                cmd_args.append("--dry_run")
            if self._marker_port:
                cmd_args += ["--marker_port", str(self._marker_port)]
            if self.use_beep_var.get():
                cmd_args.append("--use_sound")

            self.process = subprocess.Popen(
                cmd_args, stdout=self._run_log_handle, stderr=subprocess.STDOUT,
                cwd=self.script_dir
            )
            self.process_meta = {
                'subject': subject, 'profile': profile_key,
                'experiment': experiment_name, 'log': run_log_path,
                'started': time.time(),
            }
            self.log.log(f"Process started with PID: {self.process.pid}")
            self.log.event('experiment_started', pid=self.process.pid,
                           subject=subject, profile=profile_key,
                           marker_port=self._marker_port, log=run_log_path)

            self.start_button.state(['disabled'])
            self.experiment_dropdown.state(['disabled'])
            self.skip_button.state(['!disabled'])
            self.status_label.config(text=f"Experiment '{experiment_name}' started...")
            self.percentage_label.config(text=self._format_progress(0))
            self.progress_var.set(0)

        except Exception as e:
            self.log.exception("could not start experiment", fatal=False)
            messagebox.showerror("Error", f"Could not start experiment: {str(e)}")
            self.cleanup()

    def check_progress(self):
        """Poll the paradigm subprocess's progress file."""
        try:
            self._service_lsl()
        except Exception:
            self.log.exception("LSL service tick failed", fatal=False)

        if self.process:
            returncode = self.process.poll()

            if returncode is not None:
                # Runs unconditionally now. The old code guarded this whole
                # branch with `if not self.experiment_complete:`, and that flag
                # was already set the moment the paradigm reported 100% -- while
                # it was still sitting in its blank end screen. So for every run
                # that finished normally, the exit handler never ran: the temp
                # file was never removed and the outlet was never reclaimed.
                self._on_process_exit(returncode)
            else:
                try:
                    with open(self.temp_file.name, 'r') as f:
                        data = json.load(f)
                        progress = data.get("progress", 0)
                        status   = data.get("status", "Running...")
                        seg_index = data.get("segment_index", 0) or 0
                        seg_total = data.get("segment_total", 0) or 0

                        # Each segment now fills its own 0-100 bar, so reaching
                        # 100 no longer means the run is over -- the paradigm
                        # says so explicitly. A paradigm that predates the flag
                        # still means it when it reports 100.
                        if "done" in data:
                            done = bool(data["done"])
                        else:
                            done = progress >= 99.9 and not seg_total

                        self.last_status = status

                        if progress < 0:
                            # The paradigm caught its own exception.
                            self.progress_var.set(0)
                            self.status_label.config(text=status)
                            self.percentage_label.config(text="—")
                        elif done:
                            self.progress_var.set(100)
                            self.status_label.config(text="Completed (window still open)")
                            self.percentage_label.config(text=self._format_progress(100))
                            self.progress_complete = True
                        else:
                            self.progress_var.set(progress)
                            self.status_label.config(text=status)
                            self.percentage_label.config(
                                text=self._format_progress(progress, seg_index, seg_total))
                except Exception:
                    # Progress-file write race / transient — ignore and retry
                    pass

        self.root.after(100, self.check_progress)

    def _on_process_exit(self, returncode, deliberate=False):
        """Single exit path for a paradigm process.

        `deliberate` marks a process we terminated ourselves (operator started
        the next experiment, or closed the panel): those always report a
        nonzero code and must not be logged or announced as crashes.
        """
        meta = dict(self.process_meta)
        last_status = self.last_status
        completed = self.progress_complete

        self.log.log(f"Process ended with code: {returncode}"
                     f"{' (terminated by the control panel)' if deliberate else ''}")
        self.log.event('experiment_ended', code=returncode, deliberate=deliberate,
                       completed=completed, last_status=last_status, **meta)

        self.process = None
        self.process_meta = {}
        self.cleanup()

        self.progress_var.set(100 if completed else self.progress_var.get())
        self.percentage_label.config(text=self._format_progress(100) if completed else
                                     self.percentage_label.cget("text"))
        self.status_label.config(
            text="Completed" if completed else f"Ended early: {last_status or 'unknown'}")
        self.start_button.state(['!disabled'])
        self.experiment_dropdown.state(['!disabled'])
        self.skip_button.state(['disabled'])
        self.progress_complete = False

        if deliberate:
            self.status_label.config(
                text="Completed" if completed else "Stopped by operator")
        elif returncode != 0:
            description = (f"paradigm exited with code {returncode} "
                           f"(last status: {last_status or 'unknown'})")
            self.log.note_abnormal_exit(description)
            self.status_label.config(text=f"CRASHED — see {os.path.basename(meta.get('log', ''))}")
            messagebox.showerror(
                "Paradigm ended abnormally",
                f"The paradigm exited with code {returncode}.\n\n"
                f"Last reported step:\n  {last_status or 'unknown'}\n\n"
                f"Full traceback:\n  {meta.get('log', self.log_dir)}\n\n"
                f"A one-line summary was added to:\n  "
                f"{os.path.join(self.log_dir, crashlog.CRASH_INDEX)}")

    def _terminate_process(self, reason):
        if not (self.process and self.process.poll() is None):
            return
        self.log.log(f"Terminating paradigm PID {self.process.pid}: {reason}")
        try:
            self.process.terminate()
            self.process.wait(timeout=5)
        except Exception:
            try:
                self.process.kill()
                self.process.wait(timeout=5)
            except Exception as e:
                self.log.warn(f"could not kill paradigm process -> {e}")
        # Run the exit path here rather than waiting for the next
        # check_progress tick: start_experiment is about to replace
        # self.process, and the old handle -- along with its progress file, its
        # command file and its open log -- would otherwise never be cleaned up.
        code = self.process.poll() if self.process else None
        self._on_process_exit(code if code is not None else -1, deliberate=True)

    # ---- Cleanup ------------------------------------------------------- #
    def cleanup(self):
        for attr in ('temp_file',):
            handle = getattr(self, attr, None)
            if handle is not None:
                try:
                    handle.close()
                    os.unlink(handle.name)
                except Exception as e:
                    self.log.warn(f"Cleanup error: {str(e)}")
                setattr(self, attr, None)

        if self.command_file:
            try:
                os.unlink(self.command_file)
            except Exception:
                pass
            self.command_file = None

        if self._run_log_handle is not None:
            try:
                self._run_log_handle.close()
            except Exception:
                pass
            self._run_log_handle = None

    def shutdown(self):
        """Ordered teardown: paradigm, relay, outlet, temp files, log."""
        if self.process and self.process.poll() is None:
            if messagebox.askyesno(
                    "Paradigm still running",
                    "A paradigm window is still open.\n\n"
                    "Close it as well?\n\n"
                    "(Closing the control panel stops the LSL marker stream "
                    "either way.)"):
                self._terminate_process("control panel closing")
        if self._relay is not None:
            try:
                self._relay.stop()
            except Exception:
                pass
            self._relay = None
        self.cleanup()
        self._destroy_lsl_outlet()
        try:
            self.log.close()
        except Exception:
            pass


# Main
# ----------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="cbgPARADIGM control panel")
    parser.add_argument('--subject', default=None,
                        help="pre-fill the Subject ID field (used when the panel "
                             "restarts itself after an update)")
    parser.add_argument('--dry-run', '--dry_run', dest='dry_run', action='store_true',
                        help="Testing mode: logs and the trial feed go to a "
                             "throwaway folder in the OS temp directory and no "
                             "results are written. Nothing is created beside the "
                             "repo or in project_root.")
    args = parser.parse_args()

    root = tk.Tk()
    app = ControlPanel(root, dry_run=args.dry_run, subject=args.subject)

    def on_closing():
        app.shutdown()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()
