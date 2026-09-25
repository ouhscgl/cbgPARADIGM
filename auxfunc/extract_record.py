#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import re
import shutil
import sys
import argparse
import json
from datetime import datetime

try:
    from auxfunc.config import load_config
except ImportError:          # run directly from inside auxfunc/
    from config import load_config

class ExportResults:
    def __init__(self):
        self.results = {
            'subject_id': '',
            'files': {
                'fnirs_nback': {'status': 'not_found', 'message': '', 'path': '', 'source': ''},
                'fnirs_fingertapping': {'status': 'not_found', 'message': '', 'path': '', 'source': ''},
                'eeg_data': {'status': 'not_found', 'message': '', 'path': '', 'source': ''},
                'eeg_markers': {'status': 'not_found', 'message': '', 'path': '', 'source': ''}
            }
        }
    
    def set_subject_id(self, subject_id):
        self.results['subject_id'] = subject_id
    
    def set_file_result(self, file_type, status, message='', path='', source=''):
        if file_type in self.results['files']:
            self.results['files'][file_type] = {
                'status': status,
                'message': message,
                'path': path,
                'source': source,
            }
    
    def write_log(self, log_path):
        """Write results to log file"""
        try:
            folder = os.path.dirname(os.path.abspath(log_path))
            if folder:
                os.makedirs(folder, exist_ok=True)
            with open(log_path, 'w', encoding='utf-8') as f:
                f.write(f"=== EXPORT LOG - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
                f.write(f"Subject ID: {self.results['subject_id']}\n\n")
                
                for file_type, info in self.results['files'].items():
                    f.write(f"{file_type.upper()}:\n")
                    f.write(f"  Status: {info['status']}\n")
                    f.write(f"  Message: {info['message']}\n")
                    f.write(f"  Source: {info.get('source', '')}\n")
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


def _tree_size(path):
    """(file count, total bytes) for a file or a folder."""
    if os.path.isfile(path):
        return 1, os.path.getsize(path)
    count = total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
                count += 1
            except OSError:
                pass
    return count, total


def copy_folder(source, destination, overwrite=False):
    """Copy a session folder, staged and verified.

    The old version did rmtree(destination) and then copytree. A dropped
    network drive half way through that leaves you with neither the previous
    export nor a complete new one. This copies to a temporary name beside the
    destination first, checks the file count and byte total against the source,
    and only then replaces what was there.
    """
    if os.path.exists(destination) and not overwrite:
        return {'status': 'exists', 'message': 'Folder already exists'}

    staging = f"{destination}.incoming-{os.getpid()}"
    try:
        if os.path.exists(staging):
            shutil.rmtree(staging)
        shutil.copytree(source, staging)

        want = _tree_size(source)
        got  = _tree_size(staging)
        if got != want:
            shutil.rmtree(staging, ignore_errors=True)
            return {'status': 'error',
                    'message': f'Incomplete copy: {got[0]} files/{got[1]} bytes '
                               f'vs {want[0]}/{want[1]} at source'}

        replaced = os.path.exists(destination)
        if replaced:
            shutil.rmtree(destination)       # only now, with a verified copy ready
        os.rename(staging, destination)
        return {'status': 'success',
                'message': (f'Folder copied ({want[0]} files'
                            + (', overwritten)' if replaced else ')'))}
    except Exception as e:
        shutil.rmtree(staging, ignore_errors=True)
        return {'status': 'error', 'message': f'Copy error: {str(e)}'}


def copy_file(source, destination, overwrite=False):
    """Copy a file, staged and verified, same reasoning as copy_folder."""
    if os.path.exists(destination) and not overwrite:
        return {'status': 'exists', 'message': 'File already exists'}

    staging = f"{destination}.incoming-{os.getpid()}"
    try:
        shutil.copyfile(source, staging)
        want = os.path.getsize(source)
        got  = os.path.getsize(staging)
        if got != want:
            os.remove(staging)
            return {'status': 'error',
                    'message': f'Incomplete copy: {got} of {want} bytes'}
        replaced = os.path.exists(destination)
        os.replace(staging, destination)     # atomic on the same filesystem
        return {'status': 'success',
                'message': f'File copied ({want} bytes'
                           + (', overwritten)' if replaced else ')')}
    except Exception as e:
        if os.path.exists(staging):
            try:
                os.remove(staging)
            except OSError:
                pass
        return {'status': 'error', 'message': f'Copy error: {str(e)}'}


def parse_inf(path):
    """NIRStar .inf as {lowercased key: value}, quotes stripped."""
    fields = {}
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as handle:
            text = handle.read()
    except Exception:
        return fields, ''
    for line in text.splitlines():
        if '=' not in line:
            continue
        key, _, value = line.partition('=')
        fields[key.strip().lower()] = value.strip().strip('"').strip("'")
    return fields, text


def subject_matches(fields, body, subject):
    """Exact match on a subject field, else a whole-word match in the body.

    The old test was `subject in content`, which happily matched LTIA014's
    recording when exporting LTIA01 -- and did it silently.
    """
    wanted = subject.strip().lower()
    for key in ('subject', 'subjectid', 'subject_id', 'name', 'patient'):
        if key in fields:
            return fields[key].strip().lower() == wanted
    # No subject field: fall back to a word-boundary search, never a substring.
    return re.search(rf'(?<![A-Za-z0-9_]){re.escape(subject)}(?![A-Za-z0-9_])',
                     body) is not None


def paradigm_of(fields, body):
    """'nback', 'fingertapping' or None, from the recording comment."""
    haystack = (fields.get('comment', '') + ' ' + body).lower()
    if re.search(r'n[\s_-]?back', haystack):
        return 'nback'
    if re.search(r'finger[\s_-]?tapping', haystack):
        return 'fingertapping'
    return None


def find_fnirs_sessions(subject_id, nirx_path):
    """Every session folder belonging to this subject, newest first."""
    sessions = []
    for root, _dirs, files in os.walk(nirx_path):
        for inf_file in [f for f in files if f.lower().endswith('.inf')]:
            full_path = os.path.join(root, inf_file)
            fields, body = parse_inf(full_path)
            if not subject_matches(fields, body, subject_id):
                continue
            try:
                when = os.path.getmtime(root)
            except OSError:
                when = 0
            sessions.append({'folder': root, 'inf': full_path, 'when': when,
                             'paradigm': paradigm_of(fields, body)})
    sessions.sort(key=lambda item: item['when'], reverse=True)
    return sessions


def export_fnirs_data(subject_id, nirx_path, dest_root, results, overwrite=False):
    """Find and export fNIRS folders based on subject ID and experiment type"""
    if not nirx_path or not os.path.exists(nirx_path):
        results.set_file_result('fnirs_nback', 'error', 'NIRx data path not found')
        results.set_file_result('fnirs_fingertapping', 'error', 'NIRx data path not found')
        return

    try:
        sessions = find_fnirs_sessions(subject_id, nirx_path)
    except Exception as e:
        error_msg = f"fNIRS search error: {str(e)}"
        results.set_file_result('fnirs_nback', 'error', error_msg)
        results.set_file_result('fnirs_fingertapping', 'error', error_msg)
        return

    unlabelled = [x for x in sessions if x['paradigm'] is None]

    for paradigm, key, suffix in (('nback', 'fnirs_nback', 'NBK'),
                                  ('fingertapping', 'fnirs_fingertapping', 'FTP')):
        matching = [x for x in sessions if x['paradigm'] == paradigm]
        if not matching:
            # Say whether nothing was found at all, or found but unlabelled --
            # a recording whose comment never mentioned the paradigm used to be
            # indistinguishable from no recording.
            if unlabelled:
                message = (f'No {paradigm} session; {len(unlabelled)} session(s) '
                           f'for this subject have no paradigm in their comment')
            elif sessions:
                message = f'No {paradigm} session among {len(sessions)} for this subject'
            else:
                message = f'No session found for {subject_id}'
            results.set_file_result(key, 'not_found', message)
            continue

        chosen = matching[0]                  # newest by folder mtime
        stamp = datetime.fromtimestamp(chosen['when']).strftime('%Y-%m-%d %H:%M')
        note = (f'newest of {len(matching)}, {stamp}' if len(matching) > 1
                else f'recorded {stamp}')

        dest_folder = os.path.join(dest_root, 'NIR_DAT', f'{subject_id}_NIR_{suffix}')
        os.makedirs(os.path.dirname(dest_folder), exist_ok=True)
        status = copy_folder(chosen['folder'], dest_folder, overwrite)
        results.set_file_result(key, status['status'],
                                f"{status['message']} [{note}]",
                                dest_folder, chosen['folder'])


def find_eeg_files(subject_id, eeg_path, pattern):
    """Matching files, newest first. Anchored on the subject, not a prefix."""
    anchor = re.compile(rf'^{re.escape(subject_id)}_EPOCX', re.IGNORECASE)
    found = []
    for name in os.listdir(eeg_path):
        if not anchor.match(name) or not pattern.search(name):
            continue
        full = os.path.join(eeg_path, name)
        try:
            found.append((os.path.getmtime(full), full))
        except OSError:
            continue
    found.sort(reverse=True)
    return [full for _when, full in found]


def export_eeg_data(subject_id, eeg_path, dest_root, results, overwrite=False):
    """Find and export EEG files"""
    if not eeg_path or not os.path.exists(eeg_path):
        results.set_file_result('eeg_data', 'error', 'EEG data path not found')
        results.set_file_result('eeg_markers', 'error', 'EEG data path not found')
        return

    try:
        # Any session index, not just 00: a second recording is ...01.edf and
        # used to be invisible to the export.
        wanted = (('eeg_data',    re.compile(r'\.edf$', re.IGNORECASE),
                   'EEG_NBK_DAT.edf', 'EEG data file'),
                  ('eeg_markers', re.compile(r'_intervalMarker\.csv$', re.IGNORECASE),
                   'EEG_NBK_MRK.csv', 'EEG markers file'))

        for key, pattern, dest_name, label in wanted:
            candidates = find_eeg_files(subject_id, eeg_path, pattern)
            if not candidates:
                results.set_file_result(key, 'not_found', f'No {label} found')
                continue

            chosen = candidates[0]
            stamp = datetime.fromtimestamp(os.path.getmtime(chosen)).strftime('%Y-%m-%d %H:%M')
            note = (f'newest of {len(candidates)}, {stamp}' if len(candidates) > 1
                    else f'recorded {stamp}')

            dest_path = os.path.join(dest_root, 'EEG_DAT', f'{subject_id}_{dest_name}')
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            status = copy_file(chosen, dest_path, overwrite)
            results.set_file_result(key, status['status'],
                                    f"{status['message']} [{note}]",
                                    dest_path, chosen)

    except Exception as e:
        error_msg = f"EEG search error: {str(e)}"
        results.set_file_result('eeg_data', 'error', error_msg)
        results.set_file_result('eeg_markers', 'error', error_msg)


def destination_root(subject_id, project_root):
    """<project_root>/<leading letters of the subject id>."""
    match = re.match(r'^([A-Za-z]+)', subject_id)
    subject_prefix = match.group(1) if match else subject_id
    return os.path.join(project_root, subject_prefix)


def export_data(subject_id, project_root, nirx_path, eeg_path, overwrite=False):
    """Main export function"""
    results = ExportResults()
    results.set_subject_id(subject_id)

    dest_root = destination_root(subject_id, project_root)
    
    # EEG_DAT / NIR_DAT are created by whichever export actually has
    # something to write, so a failed export no longer leaves empty shells.

    # Export data
    export_fnirs_data(subject_id, nirx_path, dest_root, results, overwrite)
    export_eeg_data(subject_id, eeg_path, dest_root, results, overwrite)
    
    return results


# ---- survey -------------------------------------------------------------- #
# The exporter was written around NIRStar and EmotivPRO. Aurora and g.Recorder
# lay their data out differently, and guessing at those layouts is how you get
# an exporter that silently finds nothing. This prints what is actually on
# disk so the matching rules can be written against real structure.
SURVEY_MAX_ENTRIES = 12
SURVEY_MAX_DEPTH   = 3


def _summarise_dir(path, depth=0, printed=None):
    printed = printed if printed is not None else [0]
    try:
        entries = sorted(os.listdir(path))
    except OSError as exc:
        print(f"{'    ' * (depth + 1)}<cannot list: {exc}>")
        return

    folders = [e for e in entries if os.path.isdir(os.path.join(path, e))]
    files   = [e for e in entries if not os.path.isdir(os.path.join(path, e))]

    indent = '    ' * (depth + 1)
    for name in folders[:SURVEY_MAX_ENTRIES]:
        print(f"{indent}{name}/")
        if depth + 1 < SURVEY_MAX_DEPTH:
            _summarise_dir(os.path.join(path, name), depth + 1, printed)
    if len(folders) > SURVEY_MAX_ENTRIES:
        print(f"{indent}... and {len(folders) - SURVEY_MAX_ENTRIES} more folders")

    # Files by extension, with one example each: enough to see the naming
    # convention without printing a thousand names.
    by_extension = {}
    for name in files:
        by_extension.setdefault(os.path.splitext(name)[1].lower() or '<none>',
                                []).append(name)
    for extension, names in sorted(by_extension.items()):
        print(f"{indent}{len(names):>4} x {extension:<8} e.g. {names[0]}")


def _survey_inf(path):
    """Field names in a NIRStar .inf, values truncated."""
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as handle:
            lines = [line.rstrip() for line in handle][:40]
    except Exception as exc:
        print(f"      <cannot read: {exc}>")
        return
    print(f"      {path}")
    for line in lines:
        if not line.strip():
            continue
        if '=' in line:
            key, _, value = line.partition('=')
            value = value.strip()
            if len(value) > 40:
                value = value[:40] + '...'
            print(f"        {key.strip():<24} = {value}")
        else:
            print(f"        {line[:70]}")


def run_survey(settings):
    """Show what each configured data folder actually contains."""
    paths = (settings or {}).get('paths', {})
    interesting = [(key, paths.get(key, '')) for key in
                   ('nirx_data', 'emotiv_data', 'aurora_data', 'gtec_data',
                    'project_root')]

    for key, path in interesting:
        print("=" * 70)
        print(f"{key} = {path or '(not configured)'}")
        if not path:
            continue
        if not os.path.exists(path):
            print("    <does not exist on this machine>")
            continue
        _summarise_dir(path)

        # NIRStar describes a recording in a .inf; show its fields once.
        for root, _dirs, files in os.walk(path):
            inf = [f for f in files if f.lower().endswith('.inf')]
            if inf:
                print("\n    first .inf found, field names only:")
                _survey_inf(os.path.join(root, inf[0]))
                break
    print("=" * 70)
    print("Paste this back. Subject IDs appear in folder names -- redact if needed.")


def load_settings():
    """Load settings.json plus this machine's settings.local.json overlay"""
    try:
        return load_config('settings.json')
    except FileNotFoundError:
        print("Error: configs/settings.json not found")
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
    
    # Write the log beside the exported data rather than into the repo folder,
    # so it travels with the export and the repo stays clean.
    log_path = os.path.join(destination_root(subject_id, project_root),
                            f'{subject_id}_export_log.txt')
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
    
    # Write log file beside the exported data (not in the repo folder)
    log_path = os.path.join(destination_root(args.subject_id, args.project_root),
                            f'{args.subject_id}_export_log.txt')
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
    parser.add_argument('--survey', action='store_true',
                        help='Show what the configured data folders actually '
                             'contain, and stop. Changes nothing.')
    
    args = parser.parse_args()
    
    if args.survey:
        run_survey(load_settings())
        sys.exit(0)

    try:
        # If all required args provided, run with args; otherwise interactive
        if args.subject_id and args.project_root and args.nirx_data and args.eeg_data:
            results = run_with_args(args)
        else:
            results = run_interactive()
        
        # Exit code: anything that errored is a failure. 'not_found' is not --
        # a fingertapping-only session legitimately has no n-back data.
        errored = any(info['status'] == 'error'
                      for info in results.results['files'].values())
        sys.exit(1 if errored else 0)
        
    except KeyboardInterrupt:
        print('\nExport cancelled.')
        sys.exit(1)
    except Exception as e:
        print(f'Error: {str(e)}')
        sys.exit(1)