#!/usr/bin/env python3
"""Install the project-efficiency skill, agent, and policy into one project."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

PACKAGE = Path(__file__).resolve().parent
sys.path.insert(0, str(PACKAGE / 'project-efficiency' / 'scripts'))
from knowledge import safe_path

MANIFEST = '.project-efficiency/install.json'
BEGIN = '<!-- project-efficiency:begin -->'
END = '<!-- project-efficiency:end -->'
GIT_BEGIN = '# project-efficiency:begin'
GIT_END = '# project-efficiency:end'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.efficiency-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def owned_block(current, stored, relative):
    # Editors commonly convert line endings across the whole document.
    # Accept that conversion while refusing changes to managed policy text.
    normalized = stored.replace(b'\r\n', b'\n')
    variants = {stored, normalized, normalized.replace(b'\n', b'\r\n')}
    found = [value for value in variants if current.count(value) == 1]
    if len(found) != 1:
        raise ValueError(f'Managed block was modified: {relative}')
    return found[0]


def sources():
    result = {}
    for path in (PACKAGE / 'project-efficiency').rglob('*'):
        if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
            relative = path.relative_to(PACKAGE / 'project-efficiency').as_posix()
            result['.agents/skills/project-efficiency/' + relative] = path.read_bytes()
    result['.codex/agents/efficiency-steward.toml'] = (PACKAGE / 'agents/efficiency-steward.toml').read_bytes()
    return result


def run(project, dry_run=False, upgrade=False, uninstall=False):
    root = Path(project).resolve()
    if not root.is_dir():
        raise ValueError('Project must be an existing directory')
    manifest_path = safe_path(root, MANIFEST)
    previous = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else None
    if previous and previous.get('version') != 1:
        raise ValueError('Unsupported installation manifest')
    if uninstall and not previous:
        raise ValueError('No installation manifest; refusing to guess which files to remove')
    changes = {}
    files = {} if uninstall else sources()
    old_files = previous.get('files', {}) if previous else {}
    for relative in sorted(set(files) | set(old_files)):
        path = safe_path(root, relative)
        current = path.read_bytes() if path.exists() else None
        desired = files.get(relative)
        if current == desired:
            continue
        if current is not None:
            if relative not in old_files or digest(current) != old_files[relative]:
                raise ValueError(f'Local file conflicts with installation: {relative}')
            if not uninstall and not upgrade:
                raise ValueError('Package changed; rerun with --upgrade to replace unmodified managed files')
        changes[relative] = desired

    blocks = {}
    policy = (PACKAGE / 'templates/AGENTS.fragment.md').read_text(encoding='utf-8').strip()
    definitions = {'AGENTS.md': (BEGIN, END, policy), '.gitignore': (GIT_BEGIN, GIT_END,
                   GIT_BEGIN + '\n/.project-efficiency/\n' + GIT_END)}
    for relative, (begin, end, desired_text) in definitions.items():
        path = safe_path(root, relative)
        current = path.read_bytes() if path.exists() else b''
        old_block = (previous or {}).get('blocks', {}).get(relative)
        start = begin.encode()
        finish = end.encode()
        if uninstall:
            owned = owned_block(current, old_block['payload'].encode('utf-8'), relative)
            replacement = current.replace(owned, b'', 1)
            changes[relative] = replacement if replacement or old_block['existed'] else None
            continue
        desired = desired_text.encode('utf-8')
        if old_block:
            owned = owned_block(current, old_block['payload'].encode('utf-8'), relative)
            prefix = old_block['prefix'].encode('utf-8')
            prefix = prefix.replace(b'\r\n', b'\n')
            payload = prefix + desired + b'\n'
            if b'\r\n' in owned:
                payload = payload.replace(b'\n', b'\r\n')
                prefix = prefix.replace(b'\n', b'\r\n')
            if payload != owned:
                if not upgrade:
                    raise ValueError('Policy changed; rerun with --upgrade')
                changes[relative] = current.replace(owned, payload, 1)
            blocks[relative] = dict(payload=payload.decode(), prefix=prefix.decode(), existed=old_block['existed'])
        else:
            if start in current or finish in current:
                raise ValueError(f'Unowned or malformed managed block in {relative}')
            prefix = b'\n\n' if current and not current.endswith(b'\n') else b'\n' if current else b''
            payload = prefix + desired + b'\n'
            changes[relative] = current + payload
            blocks[relative] = dict(payload=payload.decode(), prefix=prefix.decode(), existed=path.exists())
    if uninstall:
        changes[MANIFEST] = None
    else:
        manifest = dict(version=1, files={p: digest(data) for p, data in files.items()}, blocks=blocks)
        data = (json.dumps(manifest, indent=2) + '\n').encode()
        if not manifest_path.exists() or manifest_path.read_bytes() != data:
            changes[MANIFEST] = data
    # Validate all destinations before writing any, including protected/symlinked parents.
    destinations = {relative: safe_path(root, relative) for relative in changes}
    result = {'operation': 'uninstall' if uninstall else 'install', 'dry_run': dry_run,
              'project': str(root), 'changed_files': sorted(changes)}
    if dry_run:
        return result
    originals = {relative: path.read_bytes() if path.exists() else None for relative, path in destinations.items()}
    applied = []
    try:
        for relative, content in changes.items():
            path = destinations[relative]
            # Detect concurrent edits since preflight instead of silently overwriting them.
            current = path.read_bytes() if path.exists() else None
            if current != originals[relative]:
                raise ValueError(f'File changed during installation: {relative}')
            if content is None:
                path.unlink(missing_ok=True)
            else:
                write_atomic(path, content)
            applied.append(relative)
    except Exception:
        for relative in reversed(applied):
            path = destinations[relative]
            current = path.read_bytes() if path.exists() else None
            if current != changes[relative]:
                continue  # Do not undo another writer's edit.
            if originals[relative] is None:
                path.unlink(missing_ok=True)
            else:
                write_atomic(path, originals[relative])
        raise
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    parser.add_argument('--dry-run', action='store_true')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--upgrade', action='store_true')
    modes.add_argument('--uninstall', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.project, args.dry_run, args.upgrade, args.uninstall), indent=2))
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
