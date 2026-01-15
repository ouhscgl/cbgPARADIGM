import tkinter as tk
from tkinter import ttk, messagebox
import subprocess, sys, os, json, tempfile


# Configuration Loading
# ----------------------------------------------------------------------------
def load_configuration(filename):
    try:
        script_dir  = os.path.dirname(os.path.abspath(__file__))
    except:
        script_dir  = os.curdir
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
        
        # Main results window
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
            icon = " ✓ "
            color = "green"
        elif status == 'exists':
            icon = "⚠"
            color = "orange"
        else:  # error
            icon = " ✗ "
            color = "red"
        
        # Create icon label with status color
        icon_label = tk.Label(row_frame, 
                            text=icon,
                            font=("Verdana", 10, "bold"),
                            foreground=color,
                            anchor="w")
        icon_label.pack(side="left")
        
        # Create text label with black color
        text_label = tk.Label(row_frame, 
                            text=f" {display_name}",
                            font=("Verdana", 8, "bold"),
                            foreground="black",
                            anchor="w")
        text_label.pack(side="left", fill="x", expand=True)
    
    def center_window(self, x_offset=17, y_offset=62):
        self.window.update_idletasks()
        parent = self.window.master
        parent_x = parent.winfo_x()
        parent_y = parent.winfo_y()
        
        new_x = parent_x + x_offset
        new_y = parent_y + y_offset
        self.window.geometry(f"+{new_x}+{new_y}")
    
    def close_window(self):
        self.window.destroy()


# Control Panel
# ---------------------------------------------------------------------------- #
class ControlPanel:
    def __init__(self, root):
        # Load setting
        self.settings = load_configuration('settings.json')
        self.profiles = load_configuration('profiles.json')
        if not self.settings or not self.profiles:
            messagebox.showerror("Error", "Failed to load settings / profiles.")
            sys.exit(1)
        
        # Window Setup
        self.root = root
        self.root.title(self.settings['control_panel']['window_name'])
        
        # Extract settings for easy access
        self.display_config = self.settings.get('display',       {})
        self.paths_config   = self.settings.get('paths',         {})
        self.panel_config   = self.settings.get('control_panel', {})
        
        # Apply window geometry from config (fallback to default)
        window_size = self.panel_config.get('window_size',    [400, 500])
        window_pos = self.panel_config.get('window_position', [50, 450])
        self.root.geometry(f"{window_size[0]}x{window_size[1]}")
        
        # Apply window position
        if sys.platform == "win32":
            from win32api import GetSystemMetrics
            left_screen_x = -GetSystemMetrics(0)
        else:
            left_screen_x = -self.display_config.get('width', 1920)
        
        x_pos, y_pos = window_pos
        self.root.geometry(f"+{x_pos}+{y_pos}")
        
        # Build experiments dictionary dynamically from profiles
        self.experiments = build_experiments_dict(self.profiles)
        
        # Main container frame
        main_frame = ttk.Frame(root, padding="10")
        main_frame.pack(fill="both", expand=True)
        
        # Recording Information frame
        recording_frame = ttk.LabelFrame(main_frame, text="Recording Information", padding="10")
        recording_frame.pack(fill="x", padx=5, pady=5)
        
        ttk.Label(recording_frame, text="Subject ID:").pack(anchor="w")
        
        # Create horizontal frame for subject ID entry and export button
        subject_frame = ttk.Frame(recording_frame)
        subject_frame.pack(fill="x", pady=5)
        
        # Subject ID entry field (takes most of the space)
        self.subject_id = ttk.Entry(subject_frame)
        self.subject_id.pack(side="left", fill="x", expand=True, padx=(0, 5))
        
        # Export data button (fixed size, right-aligned)
        self.export_button = ttk.Button(
            subject_frame,
            text="Export",
            command=self.export_data,
            width=6
        )
        self.export_button.pack(side="right")
        
        # LSL checkbox (default: on)
        lsl_frame = ttk.Frame(recording_frame)
        lsl_frame.pack(fill="x", pady=2)
        
        self.use_lsl_var = tk.BooleanVar(value=True)
        self.lsl_checkbox = ttk.Checkbutton(
            lsl_frame,
            text="Use LSL triggers",
            variable=self.use_lsl_var,
            command=self.on_lsl_toggle
        )
        self.lsl_checkbox.pack(side="left")
        
        self.lsl_status_label = ttk.Label(lsl_frame, text="- Creating stream...")
        self.lsl_status_label.pack(side="left", padx=(5, 0))
        
        self.lsl_outlet = None
        self.on_lsl_toggle()

        # Controls frame
        button_frame = ttk.LabelFrame(main_frame, text="Experiment Selection", padding="10")
        button_frame.pack(fill="x", padx=5, pady=5)
        
        ttk.Button(button_frame, 
                  text="Play Video Instructions",
                  command=self.play_video).pack(fill="x", pady=2)
        
        ttk.Button(button_frame, 
                  text="Run N-back Tutorial",
                  command=self.run_tutorial).pack(fill="x", pady=2)
        
        # Create dropdown menu
        dropdown_frame = ttk.Frame(button_frame)
        dropdown_frame.pack(fill="x", pady=5)

        # Create dropdown menu (takes most space on left)
        self.selected_experiment = tk.StringVar()
        self.experiment_dropdown = ttk.Combobox(
            dropdown_frame, 
            textvariable=self.selected_experiment,
            state="readonly"
        )

        # Set dropdown values from dynamically loaded experiments
        self.experiment_dropdown['values'] = list(self.experiments.keys())
        if self.experiments:
            self.experiment_dropdown.current(0)  # Set default selection to first item
        self.experiment_dropdown.pack(side="left", fill="x", expand=True, padx=(0, 5))

        # Sound checkbox (fixed size, right-aligned)
        self.use_beep_var = tk.BooleanVar(value=True)
        self.beep_checkbox = ttk.Checkbutton(
            dropdown_frame,
            text="Play sound",
            variable=self.use_beep_var
        )
        self.beep_checkbox.pack(side="right")
        
        # Start button
        self.start_button = ttk.Button(
            button_frame, 
            text="Start Experiment",
            command=self.start_experiment
        )
        self.start_button.pack(fill="x", pady=5)
        
        # Progress frame with more padding and visibility
        progress_frame = ttk.LabelFrame(main_frame, text="Experiment Progress", padding="10")
        progress_frame.pack(fill="x", padx=5, pady=5)
        
        # Status label above progress bar
        self.status_label = ttk.Label(progress_frame, text="Initialization complete. Select experiment to start...")
        self.status_label.pack(fill="x", pady=(0, 5))
        
        # Progress bar with explicit height
        self.progress_var = tk.DoubleVar(value=0)  # Initialize to 0
        self.progress_bar = ttk.Progressbar(
            progress_frame,
            variable=self.progress_var,
            maximum=100,
            length=300,  # Explicit length
            mode='determinate'
        )
        self.progress_bar.pack(fill="x", pady=5)
        
        # Progress percentage label
        self.percentage_label = ttk.Label(progress_frame, text="0%")
        self.percentage_label.pack(fill="x")
        
        # Termination instructions
        self.termination_label = ttk.Label(
            main_frame, 
            text="Press Ctrl + C to terminate the ongoing test.",
            font=("TkDefaultFont", 10, "italic"),
            foreground="gray"
        )
        self.termination_label.pack(fill="x", pady=(5, 0))

        # Store process and temp file
        self.process = None
        self.temp_file = None
        
        # Track if experiment is complete but window still open
        self.experiment_complete = False
        
        # Setup periodic progress check
        self.check_progress()
    
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
        self.root.update()  # Force GUI update
        try:
            cmd_args = [ sys.executable, export_script,
            "--subject_id",     subject,
            "--project_root",   self.paths_config.get('project_root', ''),
            "--nirx_data",      self.paths_config.get('nirx_data', ''),
            "--eeg_data",       self.paths_config.get('emotiv_data', '')
            ]

            process = subprocess.Popen(
                cmd_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
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
        """Parse the JSON results from the export script output - simplified version"""
        try:
            # Look for the JSON results section
            start_marker = "=== EXPORT_RESULTS_JSON ==="
            end_marker = "=== END_EXPORT_RESULTS_JSON ==="
            
            start_idx = stdout.find(start_marker)
            end_idx = stdout.find(end_marker)
            
            if start_idx != -1 and end_idx != -1:
                json_start = start_idx + len(start_marker)
                json_text = stdout[json_start:end_idx].strip()
                return json.loads(json_text)
            else:
                print("Could not find JSON results markers in output")
                return None
                
        except json.JSONDecodeError as e:
            print(f"Failed to parse export results JSON: {e}")
            return None
        except Exception as e:
            print(f"Error parsing export results: {e}")
            return None
    
    def on_lsl_toggle(self):
        """Handle LSL checkbox toggle"""
        if self.use_lsl_var.get():
            self.create_lsl_stream()
        else:
            self.destroy_lsl_stream()
    
    def create_lsl_stream(self):
        """Create LSL stream in control panel"""
        try:
            import pylsl
            print("Control Panel: Creating LSL trigger stream...")
            info = pylsl.StreamInfo(
                name='TriggerStream',
                type='Markers',
                channel_count=1,
                nominal_srate=0,
                channel_format='int32',
                source_id='paradigm_triggers'
            )
            self.lsl_outlet = pylsl.StreamOutlet(info)
            self.lsl_status_label.config(text="- Stream ready")
            self.lsl_outlet.push_sample([999])
            
        except ImportError:
            self.lsl_status_label.config(text=" - pylsl not installed")
            self.lsl_outlet = None
            messagebox.showerror("LSL Error", 
                               "pylsl module not found!\n"
                               "Please install it with: pip install pylsl")
        except Exception as e:
            self.lsl_status_label.config(text=f" - {str(e)}")
            self.lsl_outlet = None
            print(f"Control Panel: Error creating LSL stream: {e}")
    
    def destroy_lsl_stream(self):
        """Destroy LSL stream"""
        if self.lsl_outlet:
            try:
                del self.lsl_outlet
                self.lsl_outlet = None
                self.lsl_status_label.config(text="- Disabled")
                print("Control Panel: LSL stream destroyed")
            except Exception as e:
                print(f"Control Panel: Error destroying LSL stream: {e}")
        else:
            self.lsl_status_label.config(text="- Disabled")

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
        
        # Get video path from config
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

    def start_experiment(self):
        # Check if there's a current experiment running
        if self.process and self.process.poll() is None and not self.experiment_complete:
            messagebox.showerror("Error", "An experiment is already running")
            return
            
        # Reset experiment_complete flag for new experiment
        self.experiment_complete = False
        
        subject = self.validate_subject_id()
        if not subject:
            return
        
        # Get selected experiment profile
        experiment_name = self.selected_experiment.get()
        profile_key = self.experiments.get(experiment_name)
        
        if not profile_key:
            messagebox.showerror("Error", "Please select an experiment")
            return
        
        # Get the full profile configuration
        profile_config = self.profiles.get(profile_key, {})
        module_name = profile_config.get('module', '')
        
        if not module_name:
            messagebox.showerror("Error", f"No module defined for profile: {profile_key}")
            return
        
        # Determine script path (in paradigms folder)
        script_dir = os.path.dirname(os.path.abspath(__file__))
        script_path = os.path.join(script_dir, 'paradigms', module_name)
            
        try:
            # Create temporary file for progress communication
            self.temp_file = tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.json')
            temp_path = self.temp_file.name
            
            # Initialize progress file
            json.dump({"progress": 0, "status": f"Starting {experiment_name}..."}, self.temp_file)
            self.temp_file.flush()
            
            # Prepare command line arguments based on module type
            if 'fingertapping' in module_name.lower():
                # Fingertapping style arguments
                cmd_args = [sys.executable, script_path, subject, temp_path]
                if self.use_lsl_var.get():
                    cmd_args.append("--use_lsl")
                if self.use_beep_var.get():
                    cmd_args.append("--use_sound")
            else:
                # N-back style arguments with profile
                cmd_args = [sys.executable, script_path, 
                           "--subject_id", subject, 
                           "--progress_file", temp_path,
                           "--profile", profile_key]
                if self.use_lsl_var.get():
                    cmd_args.append("--use_lsl")
                if self.use_beep_var.get():
                    cmd_args.append("--use_sound")
            
            # Start the process
            self.process = subprocess.Popen(
                cmd_args,
                stderr=subprocess.PIPE,
                stdout=subprocess.PIPE
            )
            
            # If using LSL, temporarily destroy control panel stream 
            # so paradigm can create one with same source_id
            if self.use_lsl_var.get() and self.lsl_outlet:
                print("Control Panel: Temporarily destroying LSL stream for experiment")
                del self.lsl_outlet
                self.lsl_outlet = None
                self.lsl_status_label.config(text=" - Transferred")
            
            # Update debug label
            print(f"Process started with PID: {self.process.pid}")
            
            # Disable start button while experiment is running
            self.start_button.state(['disabled'])
            self.experiment_dropdown.state(['disabled'])
            
            # Update initial status
            self.status_label.config(text=f"Experiment '{experiment_name}' started...")
            self.percentage_label.config(text="0%")
            self.progress_var.set(0)
            
        except Exception as e:
            messagebox.showerror("Error", f"Could not start experiment: {str(e)}")
            if self.temp_file:
                self.temp_file.close()
                os.unlink(self.temp_file.name)
                self.temp_file = None

    def check_progress(self):
        """Check progress file and update progress bar"""
        if self.process:
            # Check if process is still running
            returncode = self.process.poll()
            
            if returncode is not None:                
                # If we haven't already marked it complete, do so now
                if not self.experiment_complete:
                    print(f"Process ended with code: {returncode}")
                    self.cleanup()
                    self.progress_var.set(100)
                    self.status_label.config(text="Completed (Window still open)")
                    self.percentage_label.config(text="100%")
                    self.start_button.state(['!disabled'])
                    self.experiment_dropdown.state(['!disabled'])
                    self.experiment_complete = True
                    
                    # Recreate LSL stream if it was enabled
                    if self.use_lsl_var.get() and not self.lsl_outlet:
                        print("Control Panel: Recreating LSL stream after experiment")
                        self.create_lsl_stream()
            else:
                # Process still running, check progress
                try:
                    with open(self.temp_file.name, 'r') as f:
                        data = json.load(f)
                        progress = data.get("progress", 0)
                        status = data.get("status", "Running...")
                        
                        # If progress is 100%, consider the experiment complete
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
                            print(f"Process running: {progress}% - {status}")
                except Exception as e:
                    print(f"Error reading progress: {str(e)}")
                
        # Schedule next check
        self.root.after(100, self.check_progress)
    
    # -- main cleanup function
    def cleanup(self):
        if self.temp_file:
            try:
                self.temp_file.close()
                os.unlink(self.temp_file.name)
            except Exception as e:
                print(f"Cleanup error: {str(e)}")
            self.temp_file = None
    
    # -- entry for cleanup function
    def __del__(self):
        """Ensure cleanup on exit"""
        self.cleanup()
        # Clean up LSL stream
        self.destroy_lsl_stream()
        # If there's a running process, terminate it
        if self.process and self.process.poll() is None:
            self.process.terminate()


# Main
# ---------------------------------------------------------------------------- #
def main():
    root = tk.Tk()
    app = ControlPanel(root)
    
    # Handle window close event to clean up LSL
    def on_closing():
        app.destroy_lsl_stream()
        root.destroy()
    
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()

if __name__ == "__main__":
    main()