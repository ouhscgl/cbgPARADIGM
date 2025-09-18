#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import shutil
import sys
import argparse
import json

class ExportResults:
    def __init__(self):
        self.results = {
            'subject_id': '',
            'overall_success': False,
            'files': {
                'nir_nback': {
                    'status': 'not_found',  # 'success', 'not_found', 'exists', 'error'
                    'message': '',
                    'source_path': '',
                    'dest_path': '',
                    'experiment_type': 'NBK'
                },
                'nir_fingertapping': {
                    'status': 'not_found',
                    'message': '',
                    'source_path': '',
                    'dest_path': '',
                    'experiment_type': 'FTP'
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

def search_inf_files(search_text="NRAXXX_V3", config_path=None, overwrite_existing=False, results_tracker=None):
    '''
    Export Manager written for fNIRS Setup v2.0 / [2] PC
    2025.01.30 @ZBK
    Enhanced to handle multiple experiment types (fingertapping and nback)
    '''
    if config_path is None:
        print('Please provide a config file.')
        return False
    else:
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
        except Exception as e:
            print(f"Error accessing config file: {str(e)}")
            if results_tracker:
                results_tracker.set_file_status('nir_nback', 'error', f'Config error: {str(e)}')
                results_tracker.set_file_status('nir_fingertapping', 'error', f'Config error: {str(e)}')
                results_tracker.set_file_status('eeg_data', 'error', f'Config error: {str(e)}')
                results_tracker.set_file_status('eeg_markers', 'error', f'Config error: {str(e)}')
            return False

    dest_root = config['destination_base'].format(
        subject_prefix=search_text[:3])

    # Create destination directories if they don't exist
    os.makedirs(dest_root, exist_ok=True)
    os.makedirs(os.path.join(dest_root, 'EEG_DAT'), exist_ok=True)
    os.makedirs(os.path.join(dest_root, 'NIR_DAT'), exist_ok=True)

    # NIRx file search - Enhanced to handle multiple experiment types
    found_matches = []  # Track all matches found
    processed_folders = set()  # Track already processed source folders
    nir_nback_success = False
    nir_ftp_success = False
    
    try:
        search_path = config['search_paths']['nir']
        for root, dirs, files in os.walk(search_path):
            inf_files = [f for f in files if f.lower().endswith('.inf')]
            for file in inf_files:
                full_path = os.path.join(root, file)
                try:
                    with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()

                    if search_text in content:
                        source_folder = os.path.dirname(full_path)
                        
                        # Determine experiment types present in this file
                        experiment_types = []
                        if 'fingertapping' in content.lower():
                            experiment_types.append('FTP')
                        if 'nback' in content.lower():
                            experiment_types.append('NBK')
                        
                        # If no specific experiment type found, use default
                        if not experiment_types:
                            print(f'Stimulus uncertain in file {file}.')
                            experiment_types = ['DAT']

                        # Process each experiment type found
                        for exp_type in experiment_types:
                            folder_name = f"{search_text}_NIR_{exp_type}"
                            destination_folder = os.path.join(dest_root, 'NIR_DAT', folder_name)
                            
                            # Create a unique key for this source-destination pair
                            copy_key = f"{source_folder}->{destination_folder}"
                            
                            if copy_key not in processed_folders:
                                try:
                                    # Check if destination already exists
                                    if os.path.exists(destination_folder):
                                        if overwrite_existing:
                                            print(f'Overwriting existing folder: {destination_folder}')
                                            shutil.rmtree(destination_folder)
                                        else:
                                            print(f'Destination already exists (skipping): {destination_folder}')
                                            if results_tracker:
                                                if exp_type == 'NBK':
                                                    results_tracker.set_file_status('nir_nback', 'exists', 
                                                        'Folder already exists', source_folder, destination_folder)
                                                    nir_nback_success = True
                                                elif exp_type == 'FTP':
                                                    results_tracker.set_file_status('nir_fingertapping', 'exists', 
                                                        'Folder already exists', source_folder, destination_folder)
                                                    nir_ftp_success = True
                                            continue
                                    
                                    # Copy the folder
                                    shutil.copytree(source_folder, destination_folder)
                                    print(f'SUCCESS: {source_folder} >>> {destination_folder}')
                                    found_matches.append(full_path)
                                    processed_folders.add(copy_key)
                                    
                                    if results_tracker:
                                        if exp_type == 'NBK':
                                            results_tracker.set_file_status('nir_nback', 'success', 
                                                'Folder copied successfully', source_folder, destination_folder)
                                            nir_nback_success = True
                                        elif exp_type == 'FTP':
                                            results_tracker.set_file_status('nir_fingertapping', 'success', 
                                                'Folder copied successfully', source_folder, destination_folder)
                                            nir_ftp_success = True
                                    
                                except Exception as e:
                                    print(f'ERROR: Error copying folder {source_folder} to {destination_folder}: {str(e)}')
                                    if results_tracker:
                                        if exp_type == 'NBK':
                                            results_tracker.set_file_status('nir_nback', 'error', 
                                                f'Copy error: {str(e)}', source_folder, destination_folder)
                                        elif exp_type == 'FTP':
                                            results_tracker.set_file_status('nir_fingertapping', 'error', 
                                                f'Copy error: {str(e)}', source_folder, destination_folder)
                            else:
                                print(f'SKIP: Already processed {copy_key}')

                        print(f"Found match in: {full_path}")

                except Exception as e:
                    print(f"ERROR: Error reading {full_path}: {str(e)}")
                    continue

    except Exception as e:
        print(f"ERROR: Error accessing NIR directory: {str(e)}")
        if results_tracker:
            results_tracker.set_file_status('nir_nback', 'error', f'Directory access error: {str(e)}')
            results_tracker.set_file_status('nir_fingertapping', 'error', f'Directory access error: {str(e)}')

    if not found_matches:
        print(f"WARNING: No matching NIRx files found for {search_text}")
        if results_tracker and not nir_nback_success and not nir_ftp_success:
            results_tracker.set_file_status('nir_nback', 'not_found', 'No matching NIR files found')
            results_tracker.set_file_status('nir_fingertapping', 'not_found', 'No matching NIR files found')
    else:
        print(f"INFO: Found {len(found_matches)} NIR file matches")
    
    print('-' * 50)

    # EEG file search (enhanced with results tracking)
    eeg_success = False
    csv_success = False
    
    try:
        eeg_search_path = config['search_paths']['eeg']
        if not os.path.exists(eeg_search_path):
            print(f'WARNING: EEG search path does not exist: {eeg_search_path}')
            if results_tracker:
                results_tracker.set_file_status('eeg_data', 'error', 'EEG search path does not exist')
                results_tracker.set_file_status('eeg_markers', 'error', 'EEG search path does not exist')
            return len(found_matches) > 0
            
        files = os.listdir(eeg_search_path)
        edf_file = [f for f in files if f.startswith(f'{search_text}_EPOCX') and f.endswith('00.edf')]
        csv_file = [f for f in files if f.startswith(f'{search_text}_EPOCX') and f.endswith('_intervalMarker.csv')]

        if edf_file:
            edf_path = os.path.join(eeg_search_path, edf_file[0])
            eeg_dest_path = os.path.join(dest_root, 'EEG_DAT', 
                                         f'{search_text}_EEG_NBK_DAT.edf')
            try:
                if os.path.exists(eeg_dest_path) and not overwrite_existing:
                    print(f'WARNING: EEG data file already exists: {eeg_dest_path}')
                    if results_tracker:
                        results_tracker.set_file_status('eeg_data', 'exists', 
                            'File already exists', edf_path, eeg_dest_path)
                    eeg_success = True
                else:
                    shutil.copyfile(edf_path, eeg_dest_path)
                    print(f'SUCCESS: {edf_path} >>> {eeg_dest_path}')
                    if results_tracker:
                        results_tracker.set_file_status('eeg_data', 'success', 
                            'File copied successfully', edf_path, eeg_dest_path)
                    eeg_success = True
            except Exception as e:
                print(f'ERROR: Error copying EEG data file: {str(e)}')
                if results_tracker:
                    results_tracker.set_file_status('eeg_data', 'error', 
                        f'Copy error: {str(e)}', edf_path, eeg_dest_path)
        else:
            print(f"WARNING: No matching EEG .edf file found for {search_text}")
            if results_tracker:
                results_tracker.set_file_status('eeg_data', 'not_found', 'No matching EEG .edf file found')

        if csv_file:
            csv_path = os.path.join(eeg_search_path, csv_file[0])
            csv_dest_path = os.path.join(dest_root, 'EEG_DAT',
                                         f'{search_text}_EEG_NBK_MRK.csv')
            try:
                if os.path.exists(csv_dest_path) and not overwrite_existing:
                    print(f'WARNING: EEG markers file already exists: {csv_dest_path}')
                    if results_tracker:
                        results_tracker.set_file_status('eeg_markers', 'exists', 
                            'File already exists', csv_path, csv_dest_path)
                    csv_success = True
                else:
                    shutil.copyfile(csv_path, csv_dest_path)
                    print(f'SUCCESS: {csv_path} >>> {csv_dest_path}')
                    if results_tracker:
                        results_tracker.set_file_status('eeg_markers', 'success', 
                            'File copied successfully', csv_path, csv_dest_path)
                    csv_success = True
            except Exception as e:
                print(f'ERROR: Error copying EEG markers file: {str(e)}')
                if results_tracker:
                    results_tracker.set_file_status('eeg_markers', 'error', 
                        f'Copy error: {str(e)}', csv_path, csv_dest_path)
        else:
            print(f"WARNING: No matching EEG markers file found for {search_text}")
            if results_tracker:
                results_tracker.set_file_status('eeg_markers', 'not_found', 'No matching EEG markers file found')

    except Exception as e:
        print(f"ERROR: Error accessing EEG folder: {str(e)}")
        if results_tracker:
            results_tracker.set_file_status('eeg_data', 'error', f'Directory access error: {str(e)}')
            results_tracker.set_file_status('eeg_markers', 'error', f'Directory access error: {str(e)}')

    print('-' * 50)
    print(f'Export process completed for {search_text}')
    
    # Return True if any files were successfully processed
    return len(found_matches) > 0 or eeg_success or csv_success

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Extract and organize fNIRS/EEG data files')
    parser.add_argument('--config', required=True, help='Path to configuration JSON file')
    parser.add_argument('--overwrite', action='store_true', 
                       help='Overwrite existing files in destination')
    args, unknown = parser.parse_known_args()
    
    # Create results tracker
    results = ExportResults()
    
    try:
        user_input = input('Enter subject ID (e.g.: UTC001_V1): ')
        print('-'*50)
        
        results.set_subject_id(user_input)
        
        success = search_inf_files(search_text=user_input, 
                                 config_path=args.config,
                                 overwrite_existing=args.overwrite,
                                 results_tracker=results)
        
        # Output structured results for the control panel
        results.output_json()
        
        if success:
            print('Export process completed!')
            sys.exit(0)
        else:
            print('Export process completed - check results above.')
            sys.exit(1)
    except KeyboardInterrupt:
        print('\nExport cancelled by user.')
        results.set_subject_id('CANCELLED')
        for file_type in results.results['files']:
            results.set_file_status(file_type, 'error', 'Export cancelled by user')
        results.output_json()
        sys.exit(1)
    except Exception as e:
        print(f'Unexpected error: {str(e)}')
        results.set_subject_id('ERROR')
        for file_type in results.results['files']:
            results.set_file_status(file_type, 'error', f'Unexpected error: {str(e)}')
        results.output_json()
        sys.exit(1)