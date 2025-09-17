import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import subprocess
import sys
import os
import json
import tempfile
import re

class ExportResultsWindow:
    def __init__(self, parent, results_data):
        self.results = results_data
        
        # Create the popup window
        self.window = tk.Toplevel(parent)
        self.window.title("Export Results")
        self.window.geometry("500x400")
        self.window.resizable(False, False)
        
        # Center the window
        self.window.transient(parent)
        self.window.grab_set()
        
        # Main frame
        main_frame = ttk.Frame(self.window, padding="20")
        main_frame.pack(fill="both", expand=True)
        
        # Title
        title_label = ttk.Label(main_frame, 
                               text=f"Export Results for {results_data.get('subject_id', 'Unknown')}", 
                               font=("Arial", 14, "bold"))
        title_label.pack(pady=(0, 20))
        
        # Results frame with scrollbar
        canvas = tk.Canvas(main_frame)
        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # File results
        files = results_data.get('files', {})
        self.create_file_result_row(scrollable_frame, "NIR Data", files.get('nir_data', {}))
        self.create_file_result_row(scrollable_frame, "EEG Data", files.get('eeg_data', {}))
        self.create_file_result_row(scrollable_frame, "EEG Markers", files.get('eeg_markers', {}))
        
        canvas.pack(side="left", fill="both", expand=True, pady=(0, 20))
        scrollbar.pack(side="right", fill="y", pady=(0, 20))
        
        # Overall status
        overall_frame = ttk.Frame(main_frame)
        overall_frame.pack(fill="x", pady=(10, 0))
        
        overall_success = results_data.get('overall_success', False)
        overall_icon = "✓" if overall_success else "✗"
        overall_color = "green" if overall_success else "red"
        overall_text = "Export completed successfully!" if overall_success else "Export completed with issues"
        
        overall_label = ttk.Label(overall_frame, 
                                 text=f"{overall_icon} {overall_text}", 
                                 font=("Arial", 12, "bold"),
                                 foreground=overall_color)
        overall_label.pack()
        
        # Close button
        close_button = ttk.Button(main_frame, text="Close", command=self.close_window)
        close_button.pack(pady=(20, 0))
        
        # Center the window on parent
        self.center_window()
    
    def create_file_result_row(self, parent, file_type, file_info):
        """Create a row showing the result for one file type"""
        frame = ttk.LabelFrame(parent, text=file_type, padding="10")
        frame.pack(fill="x", pady=5, padx=5)
        
        status = file_info.get('status', 'unknown')
        message = file_info.get('message', 'No information')
        source_path = file_info.get('source_path', '')
        dest_path = file_info.get('dest_path', '')
        
        # Status icon and color
        if status == 'success':
            icon = "✓"
            color = "green"
            status_text = "Successfully exported"
        elif status == 'not_found':
            icon = "✗"
            color = "red"
            status_text = "Not found"
        elif status == 'exists':
            icon = "⚠"
            color = "orange"
            status_text = "Already exists"
        elif status == 'error':
            icon = "✗"
            color = "red"
            status_text = "Error occurred"
        else:
            icon = "?"
            color = "gray"
            status_text = "Unknown status"
        
        # Status row
        status_frame = ttk.Frame(frame)
        status_frame.pack(fill="x", pady=(0, 5))
        
        status_label = tk.Label(status_frame, 
                               text=f"{icon} {status_text}", 
                               font=("Arial", 11, "bold"),
                               foreground=color,
                               background=frame.cget('background'))
        status_label.pack(anchor="w")
        
        # Message
        if message:
            message_label = ttk.Label(frame, text=message, font=("Arial", 9))
            message_label.pack(anchor="w", pady=(0, 5))
        
        # Paths (if available)
        if source_path:
            source_label = ttk.Label(frame, 
                                   text=f"From: {self.truncate_path(source_path)}", 
                                   font=("Arial", 8),
                                   foreground="gray")
            source_label.pack(anchor="w")
        
        if dest_path:
            dest_label = ttk.Label(frame, 
                                 text=f"To: {self.truncate_path(dest_path)}", 
                                 font=("Arial", 8),
                                 foreground="gray")
            dest_label.pack(anchor="w")
            
        # Show experiment type for NIR data if available
        if file_type == "NIR Data" and 'experiment_type' in file_info:
            exp_type = file_info['experiment_type']
            exp_label = ttk.Label(frame, 
                                text=f"Experiment type: {exp_type}", 
                                font=("Arial", 8, "italic"),
                                foreground="blue")
            exp_label.pack(anchor="w")
    
    def truncate_path(self, path, max_length=60):
        """Truncate long paths for display"""
        if len(path) <= max_length:
            return path
        return "..." + path[-(max_length-3):]
    
    def center_window(self):
        """Center the window on the parent"""
        self.window.update_idletasks()
        x = (self.window.winfo_screenwidth() // 2) - (self.window.winfo_width() // 2)
        y = (self.window.winfo_screenheight() // 2) - (self.window.winfo_height() // 2)
        self.window.geometry(f"+{x}+{y}")
    
    def close_window(self):
        self.window.destroy()

class ControlPanel:
    def __init__(self, root):
        self.root = root
        self.root.title("Memory Task Control Panel")
        
        # Make window slightly taller to accommodate dropdown
        self.root.geometry("400x500")
        
        if sys.platform == "win32":
            from win32api import GetSystemMetrics
            left_screen_x = -GetSystemMetrics(0)
        else:
            left_screen_x = -1920
        x_pos = 50
        y_pos = 550
        self.root.geometry(f"+{x_pos}+{y_pos}")
        
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
            width=5
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
        
        # Store LSL outlet
        self.lsl_outlet = None
        
        # Initialize LSL stream if checkbox is checked
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
        
        # List of available experiments
        self.experiments = {
            "Nback (letters) TBI" : "TBI_letter",
            "Nback (letters) NRA" : "NRA_letter",
            "Nback (numbers) NRA" : "NRA_number",
            "Nback (SCog with extended rest)" : "SCog_letter",
            "Fingertapping" : "fingertapping"
        }
        
        # Create dropdown menu
        self.selected_experiment = tk.StringVar()
        self.experiment_dropdown = ttk.Combobox(
            button_frame, 
            textvariable=self.selected_experiment,
            state="readonly"
        )
        
        # Set dropdown values
        self.experiment_dropdown['values'] = list(self.experiments.keys())
        self.experiment_dropdown.current(0)  # Set default selection to first item
        self.experiment_dropdown.pack(fill="x", pady=5)
        
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
        self.status_label = ttk.Label(progress_frame, text="Ready to start")
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
        
        # Debug label to show process status
        self.debug_label = ttk.Label(main_frame, text="Process: Not started")
        self.debug_label.pack(fill="x", pady=5)
        
        # Store process and temp file
        self.process = None
        self.temp_file = None
        
        # Track if experiment is complete but window still open
        self.experiment_complete = False
        
        # Setup periodic progress check
        self.check_progress()
    
    def export_data(self):
        """Handle the export data button click"""
        subject = self.validate_subject_id()
        if not subject:
            return
        
        script_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(script_dir, 'export_config.json')
        
        try:
            # Run the export script with the subject ID and config file
            export_script = "extract_record.py"
            if not os.path.exists(export_script):
                messagebox.showerror("Error", f"Export script '{export_script}' not found!")
                return
            
            # Show a message indicating export is starting
            self.debug_label.config(text=f"Exporting data for {subject}...")
            self.root.update()  # Force GUI update
            
            # Run the export script in a separate process
            process = subprocess.Popen(
                [sys.executable, export_script, "--config", config_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Send the subject ID to the script's input prompt
            stdout, stderr = process.communicate(input=f"{subject}\n")
            
            # Parse the JSON results from stdout
            export_results = self.parse_export_results(stdout)
            
            if export_results:
                # Show the detailed results window
                ExportResultsWindow(self.root, export_results)
                self.debug_label.config(text="Export completed - see results window")
            else:
                # Fallback to simple message if JSON parsing failed
                if process.returncode == 0:
                    messagebox.showinfo("Export Complete", 
                                      f"Data export completed for {subject}\n\nCheck console output for details.")
                    self.debug_label.config(text="Export completed successfully")
                else:
                    error_msg = f"Export failed with return code {process.returncode}"
                    if stderr.strip():
                        error_msg += f"\n\nError details:\n{stderr[:500]}..."  # Truncate long errors
                    messagebox.showerror("Export Error", error_msg)
                    self.debug_label.config(text="Export failed")
                
            # Show console output for debugging
            if stdout.strip():
                print("Export stdout:")
                print(stdout)
            if stderr.strip():
                print("Export stderr:")
                print(stderr)
                
        except Exception as e:
            error_msg = f"Could not run export script: {str(e)}"
            messagebox.showerror("Error", error_msg)
            self.debug_label.config(text="Export error")
    
    def parse_export_results(self, stdout):
        """Parse the JSON results from the export script output"""
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
            
        video_path = r"C:\Users\biochemlab\Desktop\N-back instructions video.mov"
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
            subprocess.Popen([sys.executable, "test_stimulus.py"])
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
        profile = self.experiments.get(experiment_name)
        
        if not profile:
            messagebox.showerror("Error", "Please select an experiment")
            return
        
        # Handle fingertapping separately (still uses old script)
        if profile == "fingertapping":
            script_name = "main_fingertapping.py"
        else:
            script_name = "main_nback.py"
            
        try:
            # Create temporary file for progress communication
            self.temp_file = tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.json')
            temp_path = self.temp_file.name
            
            # Initialize progress file
            json.dump({"progress": 0, "status": f"Starting {experiment_name}..."}, self.temp_file)
            self.temp_file.flush()
            
            # Update debug label
            self.debug_label.config(text=f"Temp file created: {os.path.basename(temp_path)}")
            
            # Prepare command line arguments
            if profile == "fingertapping":
                # Old style for fingertapping with LSL flag
                cmd_args = [sys.executable, script_name, subject, temp_path]
                if self.use_lsl_var.get():
                    cmd_args.append("--use_lsl")
            else:
                # New style for unified script with profile argument and LSL flag
                cmd_args = [sys.executable, script_name, 
                           "--subject_id", subject, 
                           "--progress_file", temp_path,
                           "--profile", profile]
                if self.use_lsl_var.get():
                    cmd_args.append("--use_lsl")
            
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
            self.debug_label.config(text=f"Process started with PID: {self.process.pid}")
            
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
                # Process has finished (either just now or earlier)
                
                # If we haven't already marked it complete, do so now
                if not self.experiment_complete:
                    self.debug_label.config(text=f"Process ended with code: {returncode}")
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
                            self.debug_label.config(text=f"Process running: {progress}% - {status}")
                except Exception as e:
                    self.debug_label.config(text=f"Error reading progress: {str(e)}")
                
        # Schedule next check
        self.root.after(100, self.check_progress)
    
    # -- main cleanup funcion
    def cleanup(self):
        """Clean up temporary files"""
        if self.temp_file:
            try:
                self.temp_file.close()
                os.unlink(self.temp_file.name)
            except Exception as e:
                self.debug_label.config(text=f"Cleanup error: {str(e)}")
            self.temp_file = None
    # --  entry for cleanup function
    def __del__(self):
        """Ensure cleanup on exit"""
        self.cleanup()
        # Clean up LSL stream
        self.destroy_lsl_stream()
        # If there's a running process, terminate it
        if self.process and self.process.poll() is None:
            self.process.terminate()

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