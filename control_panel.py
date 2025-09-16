import tkinter as tk
from tkinter import ttk, messagebox
import subprocess
import sys
import os
import json
import tempfile

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
        self.subject_id = ttk.Entry(recording_frame)
        self.subject_id.pack(fill="x", pady=5)
        
        # LSL checkbox (default: on)
        self.use_lsl_var = tk.BooleanVar(value=True)
        self.lsl_checkbox = ttk.Checkbutton(
            recording_frame,
            text="Use LSL triggers (old devices)",
            variable=self.use_lsl_var,
            command=self.on_lsl_toggle
        )
        self.lsl_checkbox.pack(anchor="w", pady=2)
        
        # LSL status label
        self.lsl_status_label = ttk.Label(recording_frame, text="LSL: Creating stream...")
        self.lsl_status_label.pack(anchor="w", pady=2)
        
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
            self.lsl_status_label.config(text="LSL: Stream ready for Aurora connection")
            print("Control Panel: LSL stream created successfully - Aurora can now connect")
            
            # Send initial test trigger
            self.lsl_outlet.push_sample([999])
            print("Control Panel: Sent initial test trigger (999)")
            
        except ImportError:
            self.lsl_status_label.config(text="LSL: Error - pylsl not installed")
            self.lsl_outlet = None
            messagebox.showerror("LSL Error", 
                               "pylsl module not found!\n"
                               "Please install it with: pip install pylsl")
        except Exception as e:
            self.lsl_status_label.config(text=f"LSL: Error - {str(e)}")
            self.lsl_outlet = None
            print(f"Control Panel: Error creating LSL stream: {e}")
    
    def destroy_lsl_stream(self):
        """Destroy LSL stream"""
        if self.lsl_outlet:
            try:
                del self.lsl_outlet
                self.lsl_outlet = None
                self.lsl_status_label.config(text="LSL: Disabled")
                print("Control Panel: LSL stream destroyed")
            except Exception as e:
                print(f"Control Panel: Error destroying LSL stream: {e}")
        else:
            self.lsl_status_label.config(text="LSL: Disabled")

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
                self.lsl_status_label.config(text="LSL: Transferred to experiment")
            
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