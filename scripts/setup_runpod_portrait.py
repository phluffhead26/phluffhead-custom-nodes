#!/usr/bin/env python3
"""Back up/update Phluffhead nodes and add a separate portrait workflow.

Uses only the Python standard library. Does not queue work or restart ComfyUI.
Run from a checkout/archive containing this script and its sibling assets.
"""
import argparse
import ast
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import urllib.parse
import urllib.request

REPO = Path(__file__).resolve().parents[1]
WORKFLOW = 'Phluffhead_TwoPerson_Portrait_SeedVR2.json'


def request_json(base, path, user=None, data=None):
    headers = {'Content-Type': 'application/json'}
    if user:
        headers['comfy-user'] = user
    request = urllib.request.Request(base.rstrip('/') + path, headers=headers,
                                     data=None if data is None else json.dumps(data).encode())
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def find_root(explicit=None):
    def valid(path):
        return (path / 'main.py').is_file() and (path / 'folder_paths.py').is_file() and (path / 'custom_nodes').is_dir()
    if explicit:
        root = Path(explicit).expanduser().resolve()
        if valid(root):
            return root
        raise ValueError(f'Not a ComfyUI directory: {root}')
    candidates = set()
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        try:
            args = (process / 'cmdline').read_bytes().decode().split('\0')
            cwd = (process / 'cwd').resolve()
            for arg in args:
                if Path(arg).name == 'main.py':
                    parent = (cwd / arg).resolve().parent
                    if valid(parent):
                        candidates.add(parent)
        except (OSError, UnicodeError):
            continue
    if len(candidates) == 1:
        return candidates.pop()
    raise ValueError('Could not uniquely locate running ComfyUI. Rerun with --root /actual/path/to/ComfyUI.')


def find_package(root):
    matches = []
    for folder in (root / 'custom_nodes').iterdir():
        if not folder.is_dir() or folder.name.endswith('.disabled'):
            continue
        for package in (folder, folder / 'Phluffhead_Custom_Nodes'):
            source = package / 'nodes.py'
            init = package / '__init__.py'
            if not (source.is_file() and init.is_file()):
                continue
            if 'Phluffhead_PickFromBatch' not in init.read_text(errors='replace'):
                continue
            classes = {n.name for n in ast.parse(source.read_text()).body if isinstance(n, ast.ClassDef)}
            if not classes <= {'PickFromBatch', 'ReleaseModels'}:
                raise ValueError(f'{package} contains other node classes; stopped to preserve them.')
            matches.append(package)
    if len(matches) > 1:
        raise ValueError('Multiple installed Phluffhead copies found. Resolve duplicates before updating.')
    return matches[0] if matches else root / 'custom_nodes' / 'Phluffhead_Custom_Nodes'


def fields(info):
    return {**info['input'].get('required', {}), **info['input'].get('optional', {})}


def choices(info, key):
    spec = fields(info).get(key)
    if not spec:
        return []
    if isinstance(spec[0], list):
        return spec[0]
    return spec[1].get('options', []) if len(spec) > 1 else []


def prepare_workflow(info):
    workflow = json.loads((REPO / 'examples' / WORKFLOW).read_text())
    local_types = {'Phluffhead_PickFromBatch', 'Phluffhead_ReleaseModels', 'Note'}
    missing = sorted({n['type'] for n in workflow['nodes']} - set(info) - local_types)
    if missing:
        raise ValueError('Missing node types: ' + ', '.join(missing))
    for node in workflow['nodes']:
        typ = node['type']
        values = node.get('widgets_values', [])
        if typ in ('UNETLoader', 'CLIPLoader', 'VAELoader', 'SeedVR2LoadDiTModel', 'SeedVR2LoadVAEModel'):
            key = {'UNETLoader': 'unet_name', 'CLIPLoader': 'clip_name', 'VAELoader': 'vae_name'}.get(typ, 'model')
            available = choices(info[typ], key)
            desired = values[0]
            if desired not in available:
                # Only accept the same file in a registered subdirectory. Never
                # substitute another generation model/precision without review.
                same_file = [v for v in available if Path(str(v)).name == desired]
                if len(same_file) != 1:
                    raise ValueError(f'{typ}: expected {desired} in the model menu. Select/check this model before setup.')
                values[0] = same_file[0]
        if typ == 'ResolutionSelector':
            ratios = [x for x in choices(info[typ], 'aspect_ratio') if str(x).startswith('4:3')]
            if not ratios:
                raise ValueError('ResolutionSelector has no 4:3 aspect-ratio option.')
            values[0] = ratios[0]
        if typ.startswith('SeedVR2'):
            expected = {x['name'] for x in node['inputs']}
            installed = set(fields(info[typ]))
            if installed != expected:
                raise ValueError(f'{typ} inputs differ from the checked version. Expected {sorted(expected)}, got {sorted(installed)}')
        # Resolve supported socket names against the active server, not a guessed
        # installed package version. Widget fields on core dynamic nodes are kept.
        if typ not in local_types:
            available = set(fields(info[typ]))
            for inp in node['inputs']:
                if inp.get('link') is not None and not inp.get('widget') and inp['name'] not in available:
                    raise ValueError(f'{typ}: missing connected input {inp["name"]}')
    return workflow


def install_package(root, destination):
    source = REPO / 'Phluffhead_Custom_Nodes'
    for relative in ('__init__.py', 'nodes.py', 'selector_state.py', 'web/pick_from_batch.js'):
        if not (source / relative).is_file():
            raise ValueError(f'Missing installer asset: {relative}')
    backup = None
    if destination.exists():
        stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
        backup = root / 'phluffhead-backups' / stamp / destination.name
        shutil.copytree(destination, backup, ignore=shutil.ignore_patterns('__pycache__', '.git'))
    destination.mkdir(parents=True, exist_ok=True)
    # Update only our files; retain unrelated files in the package directory.
    for relative in ('__init__.py', 'nodes.py', 'selector_state.py', 'web/pick_from_batch.js'):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + '.phluffhead-new')
        shutil.copy2(source / relative, temporary)
        temporary.replace(target)
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-url', default='http://127.0.0.1:3000')
    parser.add_argument('--root')
    parser.add_argument('--user', help='ComfyUI user ID, only for multi-user installations')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    root = find_root(args.root)
    info = request_json(args.api_url, '/object_info', args.user)
    users = request_json(args.api_url, '/users', args.user)
    if users.get('users') and not args.user:
        raise ValueError('Multi-user ComfyUI: rerun with --user and the intended ComfyUI user ID.')
    queue = request_json(args.api_url, '/queue', args.user)
    if queue.get('queue_running') or queue.get('queue_pending'):
        raise ValueError('A prompt is running or queued. Finish/cancel it before installing, then run this command again.')
    workflow = prepare_workflow(info)
    destination = find_package(root)
    print('ComfyUI:', root)
    print('Update package:', destination)
    if args.dry_run:
        print('Dry run passed. No changes made.')
        return
    backup = install_package(root, destination)
    if backup:
        print('Backup:', backup)
    # A fresh name preserves all existing workflows, including earlier test copies.
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    name = WORKFLOW.replace('.json', f'_{stamp}.json')
    path = '/userdata/' + urllib.parse.quote('workflows/' + name, safe='') + '?overwrite=false'
    try:
        request_json(args.api_url, path, args.user, workflow)
    except Exception:
        fallback = root / name
        fallback.write_text(json.dumps(workflow, indent=2))
        print('Picker files updated, but workflow upload failed. Workflow saved for manual import:', fallback)
        raise
    print('Workflow added:', name)
    print('Restart ComfyUI, refresh its browser page, and open this workflow from Workflows.')
    print('Choose two non-explicit portrait references in the Load Image nodes before queuing.')
    print('SeedVR2 may download its model weights on first use. No job has been queued by setup.')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('SETUP STOPPED:', str(error), file=sys.stderr)
        sys.exit(1)
