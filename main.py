import tkinter as tk
from tkinter import ttk, messagebox
import subprocess, sys, os, json, tempfile, gc, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from auxfunc import crashlog
from auxfunc.marker_relay import MarkerRelayServer
from auxfunc.paradigm_utils import write_skip_command

# Comment
# Color palette for indicators
COLOR_OK   = "#2ecc71"   # green: available / connected / owned
COLOR_WARN = "#f39c12"   # amber: usable but not primary, or transferred
COLOR_BAD  = "#95a5a6"   # gray:  unavailable
COLOR_DEAD = "#e74c3c"   # red:   fallback active / error

# Mode -> color for the top-level mode indicator
MODE_COLORS = {
    'TTL': COLOR_OK,
    'LSL': COLOR_WARN,
    'KEY': COLOR_DEAD,
}

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
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
    except:
        script_dir = os.curdir
    config_path = os.path.join(script_dir, 'configs', filename)
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Warning: {config_path} not found")
        return {}
    except json.JSONDecodeError as e:
        print(f"Error parsing settings.json: {e}")
        return None


def build_experiments_dict(profiles):
    experiments = {}
    for profile_key, profile_data in profiles.items():
        display_name = profile_data.get('display_name', profile_key)
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


# Control Panel
# ----------------------------------------------------------------------------
class ControlPanel:
    def __init__(self, root):
        # Load configs
        self.settings = load_configuration('settings.json')
        self.profiles = load_configuration('profiles.json')
        if not self.settings or not self.profiles:
            messagebox.showerror("Error", "Failed to load settings / profiles.")
            sys.exit(1)

        # Window setup
        self.root = root
        self.root.title(self.settings['control_panel']['window_name'])

        self.display_config = self.settings.get('display',       {})
        self.paths_config   = self.settings.get('paths',         {})
        self.panel_config   = self.settings.get('control_panel', {})

        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.log_dir    = crashlog.resolve_log_dir(self.paths_config.get('log_dir'))
        self.log        = crashlog.install('control_panel', log_dir=self.log_dir)
        self.log.log(f"Log directory: {self.log_dir}")

        window_size = self.panel_config.get('window_size',    [400, 500])
        window_pos  = self.panel_config.get('window_position', [50, 450])
        self.root.geometry(f"{window_size[0]}x{window_size[1]}")
        self.root.geometry(f"+{window_pos[0]}+{window_pos[1]}")

        self.experiments = build_experiments_dict(self.profiles)

        # Probe capabilities and decide cascade-winning mode
        self.capabilities = probe_capabilities()
        self.active_mode  = determine_mode(self.capabilities)

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

        # ---- Recording Information --------------------------------------- #
        recording_frame = ttk.LabelFrame(main_frame, text="Recording Information", padding="10")
        recording_frame.pack(fill="x", padx=5, pady=5)

        ttk.Label(recording_frame, text="Subject ID:").pack(anchor="w")

        subject_frame = ttk.Frame(recording_frame)
        subject_frame.pack(fill="x", pady=5)
        self.subject_id = ttk.Entry(subject_frame)
        self.subject_id.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.export_button = ttk.Button(
            subject_frame, text="Export", command=self.export_data, width=6
        )
        self.export_button.pack(side="right")

        # Mode indicator (replaces old LSL checkbox area)
        mode_frame = ttk.Frame(recording_frame)
        mode_frame.pack(fill="x", pady=(4, 0))

        self.mode_dot = tk.Label(
            mode_frame, text="●",
            foreground=MODE_COLORS[self.active_mode],
            font=("TkDefaultFont", 14)
        )
        self.mode_dot.pack(side="left")
        self.mode_label = tk.Label(
            mode_frame, text=f"{self.active_mode} mode",
            font=("TkDefaultFont", 10, "bold")
        )
        self.mode_label.pack(side="left", padx=(2, 0))

        self.marker_label = tk.Label(
            mode_frame, text="", font=("TkDefaultFont", 9),
            foreground="#555555"
        )
        self.marker_label.pack(side="right")

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

        self.log_label = ttk.Label(
            main_frame, text=f"Logs: {self.log_dir}",
            font=("TkDefaultFont", 8), foreground="#777777"
        )
        self.log_label.pack(fill="x", pady=(4, 0))

        # Process state
        self.process           = None
        self.process_meta      = {}
        self.temp_file         = None
        self.command_file      = None
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

            # Unified flag-style args for both paradigm modules
            language_code = LANGUAGES.get(self.selected_language.get(), 'en')
            cmd_args = [sys.executable, "-u", script_path,
                        "--subject_id",    subject,
                        "--progress_file", temp_path,
                        "--command_file",  self.command_file,
                        "--log_file",      run_log_path,
                        "--profile",       profile_key,
                        "--language",      language_code,
                        "--use_lsl"]   # always; TriggerManager handles availability
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
            self.percentage_label.config(text="0%")
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
                        self.last_status = status

                        if progress < 0:
                            # The paradigm caught its own exception.
                            self.progress_var.set(0)
                            self.status_label.config(text=status)
                            self.percentage_label.config(text="—")
                        elif progress >= 99.9:
                            self.progress_var.set(100)
                            self.status_label.config(text="Completed (window still open)")
                            self.percentage_label.config(text="100%")
                            self.progress_complete = True
                        else:
                            self.progress_var.set(progress)
                            self.status_label.config(text=status)
                            self.percentage_label.config(text=f"{progress}%")
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
        self.percentage_label.config(text="100%" if completed else
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
    root = tk.Tk()
    app = ControlPanel(root)

    def on_closing():
        app.shutdown()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()
