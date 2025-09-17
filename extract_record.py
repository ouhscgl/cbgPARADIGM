#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import shutil
import re
import sys
import argparse
import json
from pathlib import Path

class ExportResults:
    def __init__(self):
        self.results = {
            'subject_id': '',
            'overall_success': False,
            'files': {
                'nir_data': {
                    'status': 'not_found',  # 'success', 'not_found', 'exists', 'error'
                    'message': '',
                    'source_path': '',
                    'dest_path': '',
                    'experiment_type': ''
                },
                'eeg_data': {
                    'status': 'not_found',
                    'message': '',
                    'source_path': '',
                    'dest_path': ''
                },
                'eeg_markers': {
                    'status': 'not_found',
                    'message': '',
                    'source_path': '',
                    'dest_path': ''
                }
            }
        }
    
    def set_subject_id(self, subject_id):
        self.results['subject_id'] = subject_id
    
    def set_file_status(self, file_type, status, message='', source_path='', dest_path='', **kwargs):
        if file_type in self.results['files']:
            self.results['files'][file_type]['status'] = status
            self.results['files'][file_type]['message'] = message
            self.results['files'][file_type]['source_path'] = source_path
            self.results['files'][file_type]['dest_path'] = dest_path
            # Add any extra fields
            for key, value in kwargs.items():
                self.results['files'][file_type][key] = value
    
    def finalize(self):
        # Check if any files were successfully exported
        success_count = sum(1 for file_info in self.results['files'].values() 
                          if file_info['status'] == 'success')
        self.results['overall_success'] = success_count > 0
    
    def output_json(self):
        self.finalize()
        print("=== EXPORT_RESULTS_JSON ===")
        print(json.dumps(self.results, indent=2))
        print("=== END_EXPORT_RESULTS_JSON ===")

def check_file_exists(dest_path, overwrite=False):
    """Check if file exists and handle accordingly"""
    if os.path.exists(dest_path):
        if overwrite:
            return 'overwrite'
        else:
            return 'exists'
    return 'new'

def search_inf_files(search_text="NRAXXX_V3", config_path=None, overwrite_existing=False):
    '''
    Export Manager written for fNIRS Setup v2.0 / [2] PC
    2025.01.30 @ZBK
    Enhanced version with structured feedback for GUI integration
    '''
    results = ExportResults()
    results.set_subject_id(search_text)
    
    if config_path is None:
        print('ERROR: Please provide a config file.')
        results.output_json()
        return False
    
    try:
        with open(config_path,'r') as f:
            config = json.load(f)
        print(f'SUCCESS: Loaded config file: {config_path}')
    except Exception as e:
        print(f"ERROR: Error accessing config file: {str(e)}")
        results.output_json()
        return False

    # Validate config structure
    required_keys = ['destination_base', 'search_paths']
    for key in required_keys:
        if key not in config:
            print(f'ERROR: Missing required key "{key}" in config file')
            results.output_json()
            return False
    
    if 'nir' not in config['search_paths'] or 'eeg' not in config['search_paths']:
        print('ERROR: Missing "nir" or "eeg" in search_paths configuration')
        results.output_json()
        return False

    dest_root = config['destination_base'].format(
        subject_prefix = search_text[:3])    
    
    print(f'INFO: Destination root: {dest_root}')

    # Create destination directories if they don't exist
    try:
        os.makedirs(dest_root, exist_ok=True)
        os.makedirs(os.path.join(dest_root, 'EEG_DAT'), exist_ok=True)
        os.makedirs(os.path.join(dest_root, 'NIR_DAT'), exist_ok=True)
        print('SUCCESS: Created destination directories')
    except Exception as e:
        print(f'ERROR: Failed to create directories: {str(e)}')
        results.output_json()
        return False

    # NIRx file search
    print('INFO: Searching for NIR files...')
    try:
        search_path = config['search_paths']['nir']
        if not os.path.exists(search_path):
            print(f'WARNING: NIR search path does not exist: {search_path}')
            results.set_file_status('nir_data', 'error', f'Search path does not exist: {search_path}')
        else:
            nir_found = False
            for root, dirs, files in os.walk(search_path):
                inf_files = [f for f in files if f.lower().endswith('.inf')]
                for file in inf_files:
                    full_path = os.path.join(root, file)
                    try:
                        with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                            
                        if search_text in content:
                            nir_found = True
                            source_folder = os.path.dirname(full_path)
                            folder_name = search_text + '_NIR_'
                            
                            # Determine experiment type
                            experiment_type = 'DAT'  # Default
                            if 'fingertapping' in content:
                                experiment_type = 'FTP'
                                folder_name += 'FTP'
                            elif 'nback' in content:
                                experiment_type = 'NBK'
                                folder_name += 'NBK'
                            else:
                                print(f'WARNING: Stimulus uncertain in file {file}.')
                                folder_name += 'DAT'
                            
                            destination_folder = os.path.join(dest_root, 'NIR_DAT', folder_name)
                            
                            # Check if destination already exists
                            exists_status = check_file_exists(destination_folder, overwrite_existing)
                            
                            if exists_status == 'exists':
                                results.set_file_status('nir_data', 'exists', 
                                                       'Directory already exists', 
                                                       source_folder, destination_folder,
                                                       experiment_type=experiment_type)
                                print(f'WARNING: Destination already exists: {destination_folder}')
                            else:
                                try:
                                    if exists_status == 'overwrite':
                                        shutil.rmtree(destination_folder)  # Remove existing
                                    shutil.copytree(source_folder, destination_folder)
                                    results.set_file_status('nir_data', 'success', 
                                                           'Successfully copied NIR data', 
                                                           source_folder, destination_folder,
                                                           experiment_type=experiment_type)
                                    print(f'SUCCESS: {source_folder} >>> {destination_folder}')
                                except Exception as e:
                                    results.set_file_status('nir_data', 'error', 
                                                           f'Copy failed: {str(e)}', 
                                                           source_folder, destination_folder,
                                                           experiment_type=experiment_type)
                                    print(f'ERROR: Error copying folder {source_folder}: {str(e)}')
                            
                            print(f"INFO: Found match in: {full_path}")
                            break
                            
                    except Exception as e:
                        print(f"ERROR: Error reading {full_path}: {str(e)}")
                        continue
                
                if nir_found:
                    break
            
            if not nir_found:
                results.set_file_status('nir_data', 'not_found', 
                                       f'No .inf files containing "{search_text}" found in {search_path}')
                print(f"WARNING: No matching NIRx files found for {search_text}")
    
    except Exception as e:
        results.set_file_status('nir_data', 'error', f'Search error: {str(e)}')
        print(f"ERROR: Error accessing NIR directory: {str(e)}")
    
    print('-'*50)
    
    # EEG file search
    print('INFO: Searching for EEG files...')
    try:
        eeg_search_path = config['search_paths']['eeg']
        if not os.path.exists(eeg_search_path):
            print(f'WARNING: EEG search path does not exist: {eeg_search_path}')
            results.set_file_status('eeg_data', 'error', f'Search path does not exist: {eeg_search_path}')
            results.set_file_status('eeg_markers', 'error', f'Search path does not exist: {eeg_search_path}')
        else:
            files = os.listdir(eeg_search_path)
            edf_file = [f for f in files if f.startswith(f'{search_text}_EPOCX') and f.endswith('00.edf')]
            csv_file = [f for f in files if f.startswith(f'{search_text}_EPOCX') and f.endswith('_intervalMarker.csv')]
            
            # Handle EDF file
            if edf_file:
                edf_path = os.path.join(eeg_search_path, edf_file[0])
                eeg_dest_path = os.path.join(dest_root, 'EEG_DAT', 
                                             f'{search_text}_EEG_NBK_DAT.edf')
                
                exists_status = check_file_exists(eeg_dest_path, overwrite_existing)
                
                if exists_status == 'exists':
                    results.set_file_status('eeg_data', 'exists', 
                                           'File already exists', 
                                           edf_path, eeg_dest_path)
                    print(f'WARNING: EEG data file already exists: {eeg_dest_path}')
                else:
                    try:
                        shutil.copyfile(edf_path, eeg_dest_path)
                        results.set_file_status('eeg_data', 'success', 
                                               'Successfully copied EEG data', 
                                               edf_path, eeg_dest_path)
                        print(f'SUCCESS: {edf_path} >>> {eeg_dest_path}')
                    except Exception as e:
                        results.set_file_status('eeg_data', 'error', 
                                               f'Copy failed: {str(e)}', 
                                               edf_path, eeg_dest_path)
                        print(f'ERROR: Error copying EEG data file: {str(e)}')
            else:
                results.set_file_status('eeg_data', 'not_found', 
                                       f'No EEG .edf file found for {search_text}')
                print(f"WARNING: No matching EEG .edf file found for {search_text}")
            
            # Handle CSV file
            if csv_file:
                csv_path = os.path.join(eeg_search_path, csv_file[0])
                csv_dest_path = os.path.join(dest_root, 'EEG_DAT',  
                                             f'{search_text}_EEG_NBK_MRK.csv')
                
                exists_status = check_file_exists(csv_dest_path, overwrite_existing)
                
                if exists_status == 'exists':
                    results.set_file_status('eeg_markers', 'exists', 
                                           'File already exists', 
                                           csv_path, csv_dest_path)
                    print(f'WARNING: EEG markers file already exists: {csv_dest_path}')
                else:
                    try:
                        shutil.copyfile(csv_path, csv_dest_path)
                        results.set_file_status('eeg_markers', 'success', 
                                               'Successfully copied EEG markers', 
                                               csv_path, csv_dest_path)
                        print(f'SUCCESS: {csv_path} >>> {csv_dest_path}')
                    except Exception as e:
                        results.set_file_status('eeg_markers', 'error', 
                                               f'Copy failed: {str(e)}', 
                                               csv_path, csv_dest_path)
                        print(f'ERROR: Error copying EEG markers file: {str(e)}')
            else:
                results.set_file_status('eeg_markers', 'not_found', 
                                       f'No EEG markers .csv file found for {search_text}')
                print(f"WARNING: No matching EEG markers file found for {search_text}")
                
    except Exception as e:
        results.set_file_status('eeg_data', 'error', f'Search error: {str(e)}')
        results.set_file_status('eeg_markers', 'error', f'Search error: {str(e)}')
        print(f"ERROR: Error accessing EEG folder: {str(e)}")
    
    print('-'*50)
    
    # Output structured results for GUI
    results.output_json()
    
    # Summary for console
    success_files = [name for name, info in results.results['files'].items() 
                    if info['status'] == 'success']
    
    if success_files:
        print(f'SUMMARY: Export completed for {search_text}')
        print(f'  Successfully exported: {", ".join(success_files)}')
        return True
    else:
        print(f'SUMMARY: No files were successfully exported for {search_text}')
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Extract and organize fNIRS/EEG data files')
    parser.add_argument('--config', required=True, help='Path to configuration JSON file')
    parser.add_argument('--overwrite', action='store_true', 
                       help='Overwrite existing files in destination')
    args = parser.parse_args()
    
    try:
        user_input = input('Enter subject ID (e.g.: UTC001_V1): ')
        print('-'*50)
        
        success = search_inf_files(search_text=user_input, 
                                 config_path=args.config,
                                 overwrite_existing=args.overwrite)
        
        if success:
            print('Export process completed!')
            sys.exit(0)
        else:
            print('Export process completed - check results above.')
            sys.exit(1)
    except KeyboardInterrupt:
        print('\nExport cancelled by user.')
        sys.exit(1)
    except Exception as e:
        print(f'Unexpected error: {str(e)}')
        sys.exit(1)