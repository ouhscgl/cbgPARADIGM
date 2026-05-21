import tkinter as tk
from tkinter import ttk, messagebox
import subprocess, sys, os, json, tempfile, gc, time


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

# LSL stream identity. Kept stable so NIRStar and other consumers reconnect
# automatically when the outlet hands off between control panel and paradigm.
LSL_STREAM_NAME      = 'TriggerStream'
LSL_STREAM_TYPE      = 'Markers'
LSL_SOURCE_ID        = 'paradigm_triggers'
LSL_HANDOFF_DELAY_S  = 0.2   # let liblsl tear down before the subprocess opens


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

        window_size = self.panel_config.get('window_size',    [400, 500])
        window_pos  = self.panel_config.get('window_position', [50, 450])
        self.root.geometry(f"{window_size[0]}x{window_size[1]}")
        self.root.geometry(f"+{window_pos[0]}+{window_pos[1]}")

        self.experiments = build_experiments_dict(self.profiles)

        # Probe capabilities and decide cascade-winning mode
        self.capabilities = probe_capabilities()
        self.active_mode  = determine_mode(self.capabilities)

        # LSL outlet handle: control panel owns this between paradigm runs so
        # NIRStar (and any other consumer that subscribes at its startup) has
        # something to bind to. It is yielded to the paradigm subprocess for
        # the duration of an experiment, then reclaimed.
        self._lsl_outlet = None

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

        self.percentage_label = ttk.Label(progress_frame, text="0%")
        self.percentage_label.pack(fill="x")

        # ---- Bottom: termination hint + capability indicators ----------- #
        self.termination_label = ttk.Label(
            main_frame,
            text="Press Ctrl + C to terminate the ongoing test.",
            font=("TkDefaultFont", 10, "italic"),
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

        # Process state
        self.process = None
        self.temp_file = None
        self.experiment_complete = False

        # Bring up the placeholder LSL outlet now that the UI exists
        if self.capabilities['lsl']:
            self._create_lsl_outlet(initial=True)
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

    # ---- LSL outlet lifecycle ------------------------------------------ #
    def _create_lsl_outlet(self, initial=False):
        """Bring up the placeholder LSL outlet owned by the control panel."""
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
            # Heartbeat / "control panel has the stream" marker. Harmless to
            # consumers that ignore it; useful as evidence the outlet is alive.
            try:
                self._lsl_outlet.push_sample([999])
            except Exception:
                pass
            self._set_lsl_dot(COLOR_OK)
            who = "boot" if initial else "post-experiment"
            print(f"ControlPanel: LSL outlet up ({who})")
        except Exception as e:
            self._lsl_outlet = None
            self._set_lsl_dot(COLOR_DEAD)
            print(f"ControlPanel: LSL outlet create failed -> {e}")

    def _yield_lsl_to_subprocess(self):
        """
        Release the LSL outlet so the paradigm subprocess can claim the same
        source_id. Forces GC + a brief grace period so liblsl actually tears
        down before the subprocess tries to create its replacement.
        """
        if self._lsl_outlet is None:
            return
        try:
            outlet = self._lsl_outlet
            self._lsl_outlet = None
            del outlet
            gc.collect()
            time.sleep(LSL_HANDOFF_DELAY_S)
            self._set_lsl_dot(COLOR_WARN)  # amber: handed off
            print("ControlPanel: LSL outlet yielded to paradigm subprocess")
        except Exception as e:
            print(f"ControlPanel: error yielding LSL outlet -> {e}")

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
            print(f"ControlPanel: error destroying LSL outlet -> {e}")

    # ---- Export -------------------------------------------------------- #
    def export_data(self):
        subject = self.validate_subject_id()
        if not subject:
            return
        script_dir = os.path.dirname(os.path.abspath(__file__))
        export_script = os.path.join(script_dir, "auxfunc", "extract_record.py")
        if not os.path.exists(export_script):
            messagebox.showerror("Error", f"Export script '{export_script}' not found!")
            return

        print(f"Exporting data for {subject}...")
        self.root.update()
        try:
            cmd_args = [sys.executable, export_script,
                        "--subject_id",   subject,
                        "--project_root", self.paths_config.get('project_root', ''),
                        "--nirx_data",    self.paths_config.get('nirx_data', ''),
                        "--eeg_data",     self.paths_config.get('emotiv_data', '')]
            process = subprocess.Popen(cmd_args, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True)
            stdout, stderr = process.communicate()
            export_results = self.parse_export_results(stdout)
            if export_results:
                ExportResultsWindow(self.root, export_results)
            elif process.returncode == 0:
                messagebox.showinfo("Export Complete", f"Data exported for {subject}")
            else:
                self._show_export_error(subject, f"Export failed (code {process.returncode})")
        except Exception as e:
            self._show_export_error(subject, str(e))

    def _show_export_error(self, subject, message):
        error_results = {
            'subject_id': subject,
            'files': {key: {'status': 'error', 'message': message, 'path': ''}
                      for key in ['fnirs_nback', 'fnirs_fingertapping', 'eeg_data', 'eeg_markers']}
        }
        ExportResultsWindow(self.root, error_results)
        print(f"Export error: {message}")

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
            print("Could not find JSON results markers in output")
            return None
        except json.JSONDecodeError as e:
            print(f"Failed to parse export results JSON: {e}")
            return None
        except Exception as e:
            print(f"Error parsing export results: {e}")
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
        try:
            subprocess.Popen([sys.executable, "paradigms/nback_tutorial.py"])
        except Exception as e:
            messagebox.showerror("Error", f"Could not start tutorial: {str(e)}")

    # ---- Experiment lifecycle ----------------------------------------- #
    def start_experiment(self):
        if self.process and self.process.poll() is None and not self.experiment_complete:
            messagebox.showerror("Error", "An experiment is already running")
            return

        self.experiment_complete = False
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

        script_dir = os.path.dirname(os.path.abspath(__file__))
        script_path = os.path.join(script_dir, 'paradigms', module_name)

        try:
            # Progress IPC
            self.temp_file = tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.json')
            temp_path = self.temp_file.name
            json.dump({"progress": 0, "status": f"Starting {experiment_name}..."},
                      self.temp_file)
            self.temp_file.flush()

            # Yield the LSL outlet to the subprocess BEFORE spawning it, so
            # the subprocess's TriggerManager can claim the source_id cleanly.
            self._yield_lsl_to_subprocess()

            # Unified flag-style args for both paradigm modules
            cmd_args = [sys.executable, script_path,
                        "--subject_id",    subject,
                        "--progress_file", temp_path,
                        "--profile",       profile_key,
                        "--use_lsl"]   # always; TriggerManager handles availability
            if self.use_beep_var.get():
                cmd_args.append("--use_sound")

            self.process = subprocess.Popen(
                cmd_args, stderr=subprocess.PIPE, stdout=subprocess.PIPE
            )
            print(f"Process started with PID: {self.process.pid}")

            self.start_button.state(['disabled'])
            self.experiment_dropdown.state(['disabled'])
            self.status_label.config(text=f"Experiment '{experiment_name}' started...")
            self.percentage_label.config(text="0%")
            self.progress_var.set(0)

        except Exception as e:
            messagebox.showerror("Error", f"Could not start experiment: {str(e)}")
            if self.temp_file:
                self.temp_file.close()
                try:
                    os.unlink(self.temp_file.name)
                except Exception:
                    pass
                self.temp_file = None
            # If we yielded the outlet but failed to launch, reclaim it
            if self.capabilities['lsl'] and self._lsl_outlet is None:
                self._create_lsl_outlet()

    def check_progress(self):
        """Poll the paradigm subprocess's progress file."""
        if self.process:
            returncode = self.process.poll()

            if returncode is not None:
                if not self.experiment_complete:
                    print(f"Process ended with code: {returncode}")
                    self.cleanup()
                    self.progress_var.set(100)
                    self.status_label.config(text="Completed (Window still open)")
                    self.percentage_label.config(text="100%")
                    self.start_button.state(['!disabled'])
                    self.experiment_dropdown.state(['!disabled'])
                    self.experiment_complete = True
                    # Subprocess has released its LSL outlet by exiting;
                    # bring our placeholder back up so NIRStar can latch on.
                    if self.capabilities['lsl']:
                        # Small additional grace period before reclaiming
                        self.root.after(int(LSL_HANDOFF_DELAY_S * 1000),
                                        self._create_lsl_outlet)
            else:
                try:
                    with open(self.temp_file.name, 'r') as f:
                        data = json.load(f)
                        progress = data.get("progress", 0)
                        status   = data.get("status", "Running...")

                        if progress >= 99.9:
                            self.progress_var.set(100)
                            self.status_label.config(text="Completed")
                            self.percentage_label.config(text="100%")
                            self.start_button.state(['!disabled'])
                            self.experiment_dropdown.state(['!disabled'])
                            self.experiment_complete = True
                        else:
                            self.progress_var.set(progress)
                            self.status_label.config(text=status)
                            self.percentage_label.config(text=f"{progress}%")
                except Exception:
                    # Progress-file write race / transient — ignore and retry
                    pass

        self.root.after(100, self.check_progress)

    # ---- Cleanup ------------------------------------------------------- #
    def cleanup(self):
        if self.temp_file:
            try:
                self.temp_file.close()
                os.unlink(self.temp_file.name)
            except Exception as e:
                print(f"Cleanup error: {str(e)}")
            self.temp_file = None

    def __del__(self):
        self.cleanup()
        self._destroy_lsl_outlet()
        if self.process and self.process.poll() is None:
            self.process.terminate()


# Main
# ----------------------------------------------------------------------------
def main():
    root = tk.Tk()
    app = ControlPanel(root)

    def on_closing():
        app.cleanup()
        app._destroy_lsl_outlet()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()
