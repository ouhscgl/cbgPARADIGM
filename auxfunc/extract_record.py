#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import re
import shutil
import sys
import argparse
import json
from datetime import datetime

class ExportResults:
    def __init__(self):
        self.results = {
            'subject_id': '',
            'files': {
                'fnirs_nback': {'status': 'not_found', 'message': '', 'path': ''},
                'fnirs_fingertapping': {'status': 'not_found', 'message': '', 'path': ''},
                'eeg_data': {'status': 'not_found', 'message': '', 'path': ''},
                'eeg_markers': {'status': 'not_found', 'message': '', 'path': ''}
            }
        }
    
    def set_subject_id(self, subject_id):
        self.results['subject_id'] = subject_id
    
    def set_file_result(self, file_type, status, message='', path=''):
        if file_type in self.results['files']:
            self.results['files'][file_type] = {
                'status': status,
                'message': message,
                'path': path
            }
    
    def write_log(self, log_path):
        """Write results to log file"""
        try:
            with open(log_path, 'w', encoding='utf-8') as f:
                f.write(f"=== EXPORT LOG - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
                f.write(f"Subject ID: {self.results['subject_id']}\n\n")
                
                for file_type, info in self.results['files'].items():
                    f.write(f"{file_type.upper()}:\n")
                    f.write(f"  Status: {info['status']}\n")
                    f.write(f"  Message: {info['message']}\n")
                    f.write(f"  Path: {info['path']}\n\n")
        except Exception as e:
            print(f"Warning: Could not write log file: {e}")
    
    def output_json(self):
        """Output JSON for control panel"""
        print("=== EXPORT_RESULTS_JSON ===")
        print(json.dumps(self.results, indent=2))
        print("=== END_EXPORT_RESULTS_JSON ===")
    
    def print_summary(self):
        """Print human-readable summary for manual runs"""
        print("\n" + "=" * 50)
        print(f"Export Results for {self.results['subject_id']}")
        print("=" * 50)
        
        status_icons = {'success': '✓', 'exists': '⚠', 'not_found': '–', 'error': '✗'}
        display_names = {
            'fnirs_nback': 'fNIRS N-back',
            'fnirs_fingertapping': 'fNIRS Fingertapping',
            'eeg_data': 'EEG Data',
            'eeg_markers': 'EEG Markers'
        }
        
        for file_type, info in self.results['files'].items():
            icon = status_icons.get(info['status'], '?')
            name = display_names.get(file_type, file_type)
            print(f"  {icon} {name}: {info['message'] or info['status']}")
        
        print("=" * 50 + "\n")


def copy_folder(source, destination, overwrite=False):
    """Copy folder with status return"""
    try:
        if os.path.exists(destination):
            if overwrite:
                shutil.rmtree(destination)
                shutil.copytree(source, destination)
                return {'status': 'success', 'message': 'Folder copied (overwritten)'}
            else:
                return {'status': 'exists', 'message': 'Folder already exists'}
        else:
            shutil.copytree(source, destination)
            return {'status': 'success', 'message': 'Folder copied successfully'}
    except Exception as e:
        return {'status': 'error', 'message': f'Copy error: {str(e)}'}


def copy_file(source, destination, overwrite=False):
    """Copy file with status return"""
    try:
        if os.path.exists(destination):
            if overwrite:
                shutil.copyfile(source, destination)
                return {'status': 'success', 'message': 'File copied (overwritten)'}
            else:
                return {'status': 'exists', 'message': 'File already exists'}
        else:
            shutil.copyfile(source, destination)
            return {'status': 'success', 'message': 'File copied successfully'}
    except Exception as e:
        return {'status': 'error', 'message': f'Copy error: {str(e)}'}


def export_fnirs_data(subject_id, nirx_path, dest_root, results, overwrite=False):
    """Find and export fNIRS folders based on subject ID and experiment type"""
    if not nirx_path or not os.path.exists(nirx_path):
        results.set_file_result('fnirs_nback', 'error', 'NIRx data path not found')
        results.set_file_result('fnirs_fingertapping', 'error', 'NIRx data path not found')
        return
    
    try:
        found_nback = False
        found_fingertapping = False
        
        for root, dirs, files in os.walk(nirx_path):
            inf_files = [f for f in files if f.lower().endswith('.inf')]
            
            for inf_file in inf_files:
                full_path = os.path.join(root, inf_file)
                try:
                    with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                    
                    if subject_id not in content:
                        continue
                    
                    source_folder = os.path.dirname(full_path)
                    
                    if 'nback' in content.lower() and not found_nback:
                        dest_folder = os.path.join(dest_root, 'NIR_DAT', f'{subject_id}_NIR_NBK')
                        status = copy_folder(source_folder, dest_folder, overwrite)
                        results.set_file_result('fnirs_nback', status['status'], status['message'], dest_folder)
                        found_nback = True
                    
                    if 'fingertapping' in content.lower() and not found_fingertapping:
                        dest_folder = os.path.join(dest_root, 'NIR_DAT', f'{subject_id}_NIR_FTP')
                        status = copy_folder(source_folder, dest_folder, overwrite)
                        results.set_file_result('fnirs_fingertapping', status['status'], status['message'], dest_folder)
                        found_fingertapping = True
                    
                    if found_nback and found_fingertapping:
                        break
                        
                except Exception as e:
                    print(f"Error reading {full_path}: {e}")
                    continue
            
            if found_nback and found_fingertapping:
                break
        
        if not found_nback:
            results.set_file_result('fnirs_nback', 'not_found', 'No nback fNIRS data found')
        if not found_fingertapping:
            results.set_file_result('fnirs_fingertapping', 'not_found', 'No fingertapping fNIRS data found')
            
    except Exception as e:
        error_msg = f"fNIRS search error: {str(e)}"
        results.set_file_result('fnirs_nback', 'error', error_msg)
        results.set_file_result('fnirs_fingertapping', 'error', error_msg)


def export_eeg_data(subject_id, eeg_path, dest_root, results, overwrite=False):
    """Find and export EEG files"""
    if not eeg_path or not os.path.exists(eeg_path):
        results.set_file_result('eeg_data', 'error', 'EEG data path not found')
        results.set_file_result('eeg_markers', 'error', 'EEG data path not found')
        return
    
    try:
        files = os.listdir(eeg_path)
        
        # Look for EEG data file (.edf)
        edf_files = [f for f in files if f.startswith(f'{subject_id}_EPOCX') and f.endswith('00.edf')]
        if edf_files:
            source_path = os.path.join(eeg_path, edf_files[0])
            dest_path = os.path.join(dest_root, 'EEG_DAT', f'{subject_id}_EEG_NBK_DAT.edf')
            status = copy_file(source_path, dest_path, overwrite)
            results.set_file_result('eeg_data', status['status'], status['message'], dest_path)
        else:
            results.set_file_result('eeg_data', 'not_found', 'No EEG data file found')
        
        # Look for EEG markers file (.csv)
        csv_files = [f for f in files if f.startswith(f'{subject_id}_EPOCX') and f.endswith('_intervalMarker.csv')]
        if csv_files:
            source_path = os.path.join(eeg_path, csv_files[0])
            dest_path = os.path.join(dest_root, 'EEG_DAT', f'{subject_id}_EEG_NBK_MRK.csv')
            status = copy_file(source_path, dest_path, overwrite)
            results.set_file_result('eeg_markers', status['status'], status['message'], dest_path)
        else:
            results.set_file_result('eeg_markers', 'not_found', 'No EEG markers file found')
            
    except Exception as e:
        error_msg = f"EEG search error: {str(e)}"
        results.set_file_result('eeg_data', 'error', error_msg)
        results.set_file_result('eeg_markers', 'error', error_msg)


def export_data(subject_id, project_root, nirx_path, eeg_path, overwrite=False):
    """Main export function"""
    results = ExportResults()
    results.set_subject_id(subject_id)
    
    match = re.match(r'^([A-Za-z]+)', subject_id)
    subject_prefix =     match.group(1) if match else subject_id
    dest_root = os.path.join(project_root, subject_prefix)
    
    # Create destination directories
    os.makedirs(os.path.join(dest_root, 'EEG_DAT'), exist_ok=True)
    os.makedirs(os.path.join(dest_root, 'NIR_DAT'), exist_ok=True)
    
    # Export data
    export_fnirs_data(subject_id, nirx_path, dest_root, results, overwrite)
    export_eeg_data(subject_id, eeg_path, dest_root, results, overwrite)
    
    return results


def load_settings():
    """Load settings.json from configs folder (relative to project root)"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # Go up one level from auxfunc to project root, then into configs
    config_path = os.path.join(script_dir, '..', 'configs', 'settings.json')
    
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: settings.json not found at {config_path}")
        return None
    except json.JSONDecodeError as e:
        print(f"Error parsing settings.json: {e}")
        return None


def run_interactive():
    """Run in interactive mode - load settings and prompt for subject ID"""
    settings = load_settings()
    if not settings:
        sys.exit(1)
    
    paths = settings.get('paths', {})
    project_root = paths.get('project_root', '')
    nirx_path = paths.get('nirx_data', '')
    eeg_path = paths.get('emotiv_data', '')
    
    print("=" * 50)
    print("Data Export Utility")
    print("=" * 50)
    print(f"Project root: {project_root}")
    print(f"NIRx data:    {nirx_path}")
    print(f"EEG data:     {eeg_path}")
    print("-" * 50)
    
    subject_id = input("Enter subject ID (e.g., UTC001_V1): ").strip()
    if not subject_id:
        print("No subject ID entered. Exiting.")
        sys.exit(1)
    
    overwrite = input("Overwrite existing files? (y/N): ").strip().lower() == 'y'
    
    results = export_data(
        subject_id=subject_id,
        project_root=project_root,
        nirx_path=nirx_path,
        eeg_path=eeg_path,
        overwrite=overwrite
    )
    
    # Write log and print summary
    script_dir = os.path.dirname(os.path.abspath(__file__))
    log_path = os.path.join(script_dir, '..', 'export_log.txt')
    results.write_log(log_path)
    results.print_summary()
    
    input("Press Enter to exit...")
    return results


def run_with_args(args):
    """Run with command line arguments (called from control_panel)"""
    results = export_data(
        subject_id=args.subject_id,
        project_root=args.project_root,
        nirx_path=args.nirx_data,
        eeg_path=args.eeg_data,
        overwrite=args.overwrite
    )
    
    # Write log file
    script_dir = os.path.dirname(os.path.abspath(__file__))
    log_path = os.path.join(script_dir, '..', 'export_log.txt')
    results.write_log(log_path)
    
    # Output JSON for control panel
    results.output_json()
    
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Export fNIRS/EEG data files')
    parser.add_argument('--subject_id', help='Subject ID (e.g., UTC001_V1)')
    parser.add_argument('--project_root', help='Project root directory')
    parser.add_argument('--nirx_data', help='NIRx data directory')
    parser.add_argument('--eeg_data', help='EEG data directory')
    parser.add_argument('--overwrite', action='store_true', help='Overwrite existing files')
    
    args = parser.parse_args()
    
    try:
        # If all required args provided, run with args; otherwise interactive
        if args.subject_id and args.project_root and args.nirx_data and args.eeg_data:
            results = run_with_args(args)
        else:
            results = run_interactive()
        
        # Exit code based on results
        any_success = any(
            info['status'] in ['success', 'exists'] 
            for info in results.results['files'].values()
        )
        sys.exit(0 if any_success else 1)
        
    except KeyboardInterrupt:
        print('\nExport cancelled.')
        sys.exit(1)
    except Exception as e:
        print(f'Error: {str(e)}')
        sys.exit(1)