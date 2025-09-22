#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import shutil
import sys
import argparse
import json
from datetime import datetime

class SimpleExportResults:
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
                'status': status,  # 'success', 'exists', 'error', 'not_found'
                'message': message,
                'path': path
            }
    
    def write_log(self, log_path):
        """Write results to log file (overwrites existing)"""
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

def export_data(subject_id, config_path, overwrite=False):
    """Simplified export function"""
    results = SimpleExportResults()
    results.set_subject_id(subject_id)
    
    # Load config
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
    except Exception as e:
        error_msg = f"Config error: {str(e)}"
        for file_type in results.results['files']:
            results.set_file_result(file_type, 'error', error_msg)
        return results
    
    # Create destination directories
    dest_root = config['destination_base'].format(subject_prefix=subject_id[:3])
    os.makedirs(os.path.join(dest_root, 'EEG_DAT'), exist_ok=True)
    os.makedirs(os.path.join(dest_root, 'NIR_DAT'), exist_ok=True)
    
    # Search for fNIRS folders
    export_fnirs_data(subject_id, config, dest_root, results, overwrite)
    
    # Search for EEG files  
    export_eeg_data(subject_id, config, dest_root, results, overwrite)
    
    return results

def export_fnirs_data(subject_id, config, dest_root, results, overwrite):
    """Find and export fNIRS folders based on subject ID and experiment type"""
    try:
        search_path = config['search_paths']['nir']
        found_nback = False
        found_fingertapping = False
        
        # Walk through NIR directory looking for .inf files
        for root, dirs, files in os.walk(search_path):
            inf_files = [f for f in files if f.lower().endswith('.inf')]
            
            for inf_file in inf_files:
                full_path = os.path.join(root, inf_file)
                try:
                    with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                    
                    # Check if this file contains our subject ID
                    if subject_id in content:
                        source_folder = os.path.dirname(full_path)
                        
                        # Determine experiment type and copy accordingly
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
                        
                        # Break early if we found both
                        if found_nback and found_fingertapping:
                            break
                            
                except Exception as e:
                    print(f"Error reading {full_path}: {e}")
                    continue
            
            if found_nback and found_fingertapping:
                break
        
        # Set not found messages for missing data
        if not found_nback:
            results.set_file_result('fnirs_nback', 'not_found', 'No nback fNIRS data found')
        if not found_fingertapping:
            results.set_file_result('fnirs_fingertapping', 'not_found', 'No fingertapping fNIRS data found')
            
    except Exception as e:
        error_msg = f"fNIRS search error: {str(e)}"
        results.set_file_result('fnirs_nback', 'error', error_msg)
        results.set_file_result('fnirs_fingertapping', 'error', error_msg)

def export_eeg_data(subject_id, config, dest_root, results, overwrite):
    """Find and export EEG files"""
    try:
        eeg_search_path = config['search_paths']['eeg']
        if not os.path.exists(eeg_search_path):
            error_msg = 'EEG search path does not exist'
            results.set_file_result('eeg_data', 'error', error_msg)
            results.set_file_result('eeg_markers', 'error', error_msg)
            return
        
        files = os.listdir(eeg_search_path)
        
        # Look for EEG data file (.edf)
        edf_files = [f for f in files if f.startswith(f'{subject_id}_EPOCX') and f.endswith('00.edf')]
        if edf_files:
            source_path = os.path.join(eeg_search_path, edf_files[0])
            dest_path = os.path.join(dest_root, 'EEG_DAT', f'{subject_id}_EEG_NBK_DAT.edf')
            status = copy_file(source_path, dest_path, overwrite)
            results.set_file_result('eeg_data', status['status'], status['message'], dest_path)
        else:
            results.set_file_result('eeg_data', 'not_found', 'No EEG data file found')
        
        # Look for EEG markers file (.csv)
        csv_files = [f for f in files if f.startswith(f'{subject_id}_EPOCX') and f.endswith('_intervalMarker.csv')]
        if csv_files:
            source_path = os.path.join(eeg_search_path, csv_files[0])
            dest_path = os.path.join(dest_root, 'EEG_DAT', f'{subject_id}_EEG_NBK_MRK.csv')
            status = copy_file(source_path, dest_path, overwrite)
            results.set_file_result('eeg_markers', status['status'], status['message'], dest_path)
        else:
            results.set_file_result('eeg_markers', 'not_found', 'No EEG markers file found')
            
    except Exception as e:
        error_msg = f"EEG search error: {str(e)}"
        results.set_file_result('eeg_data', 'error', error_msg)
        results.set_file_result('eeg_markers', 'error', error_msg)

def copy_folder(source, destination, overwrite):
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

def copy_file(source, destination, overwrite):
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

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Export fNIRS/EEG data files')
    parser.add_argument('--config', required=True, help='Path to configuration JSON file')
    parser.add_argument('--overwrite', action='store_true', help='Overwrite existing files')
    args, unknown = parser.parse_known_args()
    
    try:
        user_input = input('Enter subject ID (e.g.: UTC001_V1): ')
        print('-' * 50)
        
        results = export_data(user_input, args.config, args.overwrite)
        
        # Write log file
        script_dir = os.path.dirname(os.path.abspath(__file__))
        log_path = os.path.join(script_dir, 'export_log.txt')
        results.write_log(log_path)
        
        # Output JSON for control panel
        results.output_json()
        
        # Determine exit code
        any_success = any(info['status'] in ['success', 'exists'] for info in results.results['files'].values())
        sys.exit(0 if any_success else 1)
        
    except KeyboardInterrupt:
        print('\nExport cancelled by user.')
        sys.exit(1)
    except Exception as e:
        print(f'Unexpected error: {str(e)}')
        sys.exit(1)