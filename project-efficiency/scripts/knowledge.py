#!/usr/bin/env python3
"""Local, bounded project knowledge cache. Python 3.11+, standard library only."""
import argparse
import ast
import fnmatch
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import subprocess
import sys
import time

VERSION = 1
MAX_TEXT = 256 * 1024
SKIP = {'.git', '.codex', '.agents', '.project-efficiency', 'node_modules', 'vendor',
        'dist', 'build', 'coverage', '.next', '.nuxt', '.venv', 'venv', '__pycache__',
        '.pytest_cache', '.mypy_cache', '.cache', 'target', '.aws', '.ssh', '.terraform'}
TEXT = {'.py', '.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs', '.json', '.toml', '.yaml',
        '.yml', '.md', '.txt', '.css', '.scss', '.html', '.vue', '.svelte', '.rs', '.go',
        '.java', '.kt', '.c', '.h', '.cpp', '.cs', '.rb', '.php', '.sh', '.ps1', '.sql'}
STATUSES = ('verified', 'inferred', 'outdated', 'requires-review')
SCHEMA = """
CREATE TABLE state(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE files(path TEXT PRIMARY KEY, kind TEXT NOT NULL, domain TEXT NOT NULL,
 subsystem TEXT NOT NULL, component TEXT NOT NULL, size INTEGER NOT NULL,
 mtime_ns INTEGER NOT NULL, hash TEXT, symbols TEXT NOT NULL, imports TEXT NOT NULL,
 dependencies TEXT NOT NULL, status TEXT NOT NULL, indexed_at TEXT NOT NULL);
CREATE TABLE notes(id TEXT PRIMARY KEY, domain TEXT NOT NULL, subsystem TEXT NOT NULL,
 component TEXT NOT NULL, summary TEXT NOT NULL, sources TEXT NOT NULL,
 status TEXT NOT NULL, evidence TEXT NOT NULL, indexed_at TEXT NOT NULL);
"""


def now():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def dump(value):
    return json.dumps(value, ensure_ascii=True, separators=(',', ':'))


def linked(path):
    return path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()) or (
        path.exists() and bool(getattr(path.lstat(), 'st_file_attributes', 0) & 0x400))


def safe_path(root, relative):
    rel = PurePosixPath(str(relative).replace('\\', '/'))
    if rel.is_absolute() or '..' in rel.parts or not rel.parts or ':' in str(rel):
        raise ValueError('Expected a project-relative path without traversal')
    current = root
    for part in rel.parts:
        current = current / part
        if linked(current):
            raise ValueError('Symlink or junction paths are not supported')
    if not current.resolve().is_relative_to(root):
        raise ValueError('Path escapes the project')
    return current


def git(root, *args, optional=False):
    try:
        result = subprocess.run(['git', '-C', str(root), *args], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        if optional:
            return None
        raise ValueError('Git unavailable or timed out; use explicit paths or reconcile')
    if result.returncode:
        if optional:
            return None
        raise ValueError('Git query failed; use explicit paths or reconcile if history changed')
    return result.stdout.decode('utf-8', errors='surrogateescape')


def git_root(root):
    top = git(root, 'rev-parse', '--show-toplevel', optional=True)
    return bool(top and Path(top.strip()).resolve() == root)


def head(root):
    value = git(root, 'rev-parse', '--verify', 'HEAD', optional=True)
    return value.strip() if value else ''


def paths_from(value):
    return {p for p in value.split('\0') if p}


def dirty(root):
    return (paths_from(git(root, 'diff', '--name-only', '--no-renames', '-z')) |
            paths_from(git(root, 'diff', '--cached', '--name-only', '--no-renames', '-z')) |
            paths_from(git(root, 'ls-files', '--others', '--exclude-standard', '-z')))


def ignored_by_git(root, paths):
    if not paths:
        return set()
    result = subprocess.run(['git', '-C', str(root), 'check-ignore', '--no-index', '-z', '--stdin'],
                            input=('\0'.join(paths) + '\0').encode('utf-8', errors='surrogateescape'),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
    if result.returncode not in (0, 1):
        raise ValueError('Could not check Git ignore rules')
    return paths_from(result.stdout.decode('utf-8', errors='surrogateescape'))


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise ValueError('Project root must be an existing directory')
        self.db_path = safe_path(self.root, '.project-efficiency/knowledge.sqlite3')
        self.is_git = git_root(self.root)
        ignore = safe_path(self.root, '.efficiencyignore')
        self.patterns = []
        if ignore.exists():
            self.patterns = [s.strip() for s in ignore.read_text(encoding='utf-8').splitlines()
                             if s.strip() and not s.lstrip().startswith('#')]
            if any(p.startswith('!') for p in self.patterns):
                raise ValueError('.efficiencyignore does not support negation')
        self.db = None

    def eligible(self, path):
        parts = PurePosixPath(path).parts
        lower = [p.lower() for p in parts]
        if not parts or any(p in SKIP for p in lower):
            return False
        name = lower[-1]
        if (name.startswith('.env') or name in {'.npmrc', '.pypirc', 'credentials',
                'credentials.json', 'secrets.json', 'secrets.yaml', 'secrets.yml',
                'id_rsa', 'id_ed25519'} or name.endswith(('.pem', '.key', '.p12', '.pfx'))):
            return False
        if any(fnmatch.fnmatchcase(path, p.rstrip('/')) or
               path.startswith(p.rstrip('/') + '/') for p in self.patterns):
            return False
        try:
            safe_path(self.root, path)
        except ValueError:
            return False
        return True

    def inventory(self):
        if self.is_git:
            paths = paths_from(git(self.root, 'ls-files', '--cached', '--others',
                                   '--exclude-standard', '-z'))
            paths -= ignored_by_git(self.root, sorted(paths))
        else:
            paths = set()
            for directory, dirs, files in os.walk(self.root, followlinks=False):
                parent = Path(directory)
                dirs[:] = [d for d in dirs if self.eligible((parent / d).relative_to(self.root).as_posix())]
                paths.update((parent / f).relative_to(self.root).as_posix() for f in files)
        return {p for p in paths if self.eligible(p) and safe_path(self.root, p).is_file()}

    def connect(self, create=False):
        if not self.db_path.exists() and not create:
            raise ValueError('Index missing; initialize it with init')
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        for suffix in ('-journal', '-wal', '-shm'):
            safe_path(self.root, '.project-efficiency/knowledge.sqlite3' + suffix)
        self.db = sqlite3.connect(self.db_path, timeout=2)
        self.db.row_factory = sqlite3.Row
        if create:
            self.db.executescript(SCHEMA)
            self.set_state('schema', VERSION)
        elif self.state('schema') != VERSION:
            raise ValueError('Unsupported index schema; preserve the database and use rebuild')
        return self

    def state(self, key, default=None):
        row = self.db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_state(self, key, value):
        self.db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', (key, dump(value)))

    def rows(self):
        return {r['path']: dict(r) for r in self.db.execute('SELECT * FROM files')}

    def checkpoint(self):
        self.set_state('git_head', head(self.root) if self.is_git else '')
        self.set_state('dirty', sorted(dirty(self.root)) if self.is_git else [])
        self.set_state('mode', 'git' if self.is_git else 'explicit-paths')

    def inspect(self, path, old=None, content=True):
        source = safe_path(self.root, path)
        info = source.stat()
        suffix = source.suffix.lower()
        parts = PurePosixPath(path).parts
        kind = ('test' if any(x in path.lower() for x in ('/tests/', '/test_', '.test.', '.spec.'))
                or parts[0] == 'tests' else 'document' if suffix in {'.md', '.txt'}
                else 'configuration' if suffix in {'.json', '.toml', '.yaml', '.yml'}
                else 'source' if suffix in TEXT else 'asset')
        record = dict(path=path, kind=kind, domain=parts[0] if len(parts) > 1 else 'root',
                      subsystem='/'.join(parts[:-1]) or 'root', component=source.stem,
                      size=info.st_size, mtime_ns=info.st_mtime_ns, hash=None,
                      symbols='[]', imports='[]', dependencies='[]', status='inferred', indexed_at=now())
        if not content or suffix not in TEXT or info.st_size > MAX_TEXT:
            return record, 0
        # Bound the read even if the file grew between stat and open.
        with source.open('rb') as stream:
            raw = stream.read(MAX_TEXT + 1)
        if len(raw) > MAX_TEXT or b'\0' in raw:
            return record, len(raw)
        fingerprint = hashlib.sha256(raw).hexdigest()
        if old and old['hash'] == fingerprint:
            return dict(old, size=info.st_size, mtime_ns=info.st_mtime_ns), len(raw)
        record['hash'] = fingerprint
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            record['hash'] = None
            return record, len(raw)
        symbols, imports = set(), set()
        if suffix == '.py':
            try:
                tree = ast.parse(text)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                        symbols.add(node.name)
                    elif isinstance(node, ast.Import):
                        imports.update(n.name for n in node.names)
                    elif isinstance(node, ast.ImportFrom):
                        base = '.' * node.level + (node.module or '')
                        if node.module:
                            imports.add(base)
                        else:
                            imports.update(base + n.name for n in node.names)
            except SyntaxError:
                record['status'] = 'requires-review'
        elif suffix in {'.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs', '.vue', '.svelte'}:
            imports.update(re.findall(r'''(?:\bfrom\s*|\bimport\s*|\brequire\s*\(\s*)["']([^"']+)["']''', text))
            symbols.update(re.findall(r'\b(?:function|class|interface|type)\s+(\w+)', text))
        record['symbols'] = dump(sorted(symbols)[:100])
        record['imports'] = dump(sorted(imports)[:100])
        return record, len(raw)

    def write_file(self, row):
        self.db.execute('INSERT OR REPLACE INTO files VALUES (' + ','.join('?' * 13) + ')',
                        tuple(row[k] for k in ('path', 'kind', 'domain', 'subsystem', 'component',
                              'size', 'mtime_ns', 'hash', 'symbols', 'imports', 'dependencies', 'status', 'indexed_at')))

    def resolve_edges(self):
        rows = self.rows()
        for path, row in rows.items():
            dependencies = set()
            parent = PurePosixPath(path).parent
            for spec in json.loads(row['imports']):
                if path.endswith('.py'):
                    dots = len(spec) - len(spec.lstrip('.'))
                    base = parent
                    for _ in range(max(0, dots - 1)):
                        base = base.parent
                    stem = spec.lstrip('.').replace('.', '/')
                    bases = [str(base / stem)] if dots else [stem, str(parent / stem), 'src/' + stem]
                    candidates = [b + ending for b in bases for ending in ('.py', '/__init__.py')]
                elif spec.startswith('.'):
                    base = os.path.normpath(str(parent / spec)).replace('\\', '/')
                    candidates = [base] + [base + e for e in ('.ts', '.tsx', '.js', '.jsx', '.css',
                                  '/index.ts', '/index.tsx', '/index.js')]
                    if base.endswith('.js'):
                        candidates.extend([base[:-3] + '.ts', base[:-3] + '.tsx'])
                else:
                    candidates = []
                dependencies.update(c for c in candidates if c in rows and c != path)
            encoded = dump(sorted(dependencies))
            if encoded != row['dependencies']:
                self.db.execute('UPDATE files SET dependencies=? WHERE path=?', (encoded, path))

    def invalidate(self, changed, before):
        affected = set(changed)
        reverse = {}
        for path, row in before.items():
            for dep in json.loads(row['dependencies']):
                reverse.setdefault(dep, set()).add(path)
        pending = list(affected)
        while pending:
            for importer in reverse.get(pending.pop(), ()):
                if importer not in affected:
                    affected.add(importer)
                    pending.append(importer)
        count = 0
        for note in self.db.execute('SELECT id,sources,status FROM notes').fetchall():
            if affected.intersection(json.loads(note['sources'])) and note['status'] != 'outdated':
                self.db.execute("UPDATE notes SET status='outdated' WHERE id=?", (note['id'],))
                count += 1
        return count

    def refresh(self, paths, content=True):
        before = self.rows()
        changed, read_bytes = set(), 0
        normalized = set()
        for path in paths:
            relative = PurePosixPath(path.replace('\\', '/'))
            if relative.is_absolute() or '..' in relative.parts or ':' in str(relative) or not relative.parts:
                raise ValueError('Expected a project-relative path without traversal')
            normalized.add(relative.as_posix())
        ignored = ignored_by_git(self.root, sorted(normalized)) if self.is_git else set()
        for path in sorted(normalized):
            old = before.get(path)
            if path in ignored or not self.eligible(path) or not safe_path(self.root, path).is_file():
                if old:
                    self.db.execute('DELETE FROM files WHERE path=?', (path,))
                    changed.add(path)
                continue
            row, consumed = self.inspect(path, old, content)
            read_bytes += consumed
            if not old or (old['hash'] != row['hash'] if old['hash'] and row['hash'] else
                           (old['hash'], old['size'], old['mtime_ns']) != (row['hash'], row['size'], row['mtime_ns'])):
                changed.add(path)
            self.write_file(row)
        stale = self.invalidate(changed, before)
        self.resolve_edges()
        return dict(candidates=len(normalized), changed=len(changed), source_bytes_read=read_bytes,
                    notes_invalidated=stale)

    def sync(self):
        if not self.is_git:
            return {'mode': 'explicit-paths', 'notice': 'Unknown changes need explicit paths or reconcile'}
        previous, current = self.state('git_head', ''), head(self.root)
        paths = dirty(self.root) | set(self.state('dirty', []))
        committed = set()
        if previous != current:
            if previous and current:
                committed = paths_from(git(self.root, 'diff', '--name-only', '--no-renames', '-z', previous, current, '--'))
            elif current:
                committed = paths_from(git(self.root, 'ls-tree', '-r', '--name-only', '-z', current))
            else:
                raise ValueError('Git history changed to unborn HEAD; use reconcile')
        known = self.rows()
        paths |= committed
        paths = {p for p in paths if self.eligible(p) or p in known}
        # An initial inventory may include thousands of unchanged untracked files.
        # Leave their content unobserved until retrieval, rather than eagerly reading
        # them on the first query. Already-fingerprinted dirty files are still hashed.
        for path in list(paths - committed):
            old = known.get(path)
            if old and old['hash'] is None and self.eligible(path):
                source = safe_path(self.root, path)
                if source.is_file():
                    info = source.stat()
                    if (old['size'], old['mtime_ns']) == (info.st_size, info.st_mtime_ns):
                        paths.remove(path)
        result = self.refresh(paths)
        self.checkpoint()
        return result

    def query(self, terms, limit, domain, budget, no_sync):
        if not terms.strip() or len(terms) > 512:
            raise ValueError('Query must contain 1-512 characters')
        sync = {} if no_sync else self.sync()
        tokens = words(terms)
        candidates = []
        for row in self.db.execute('SELECT * FROM files'):
            row = dict(row)
            if domain and row['domain'] != domain:
                continue
            score = len(tokens & words(row['path'] + ' ' + row['symbols']))
            if score:
                candidates.append((score, 'file', row['path'], row))
        for row in self.db.execute('SELECT * FROM notes'):
            row = dict(row)
            if domain and row['domain'] != domain:
                continue
            score = len(tokens & words(' '.join(str(row[k]) for k in ('id', 'domain', 'subsystem', 'component', 'summary'))))
            if score:
                candidates.append((score, 'note', row['id'], row))
        candidates.sort(key=lambda c: (-c[0], c[1], c[2]))
        selected = candidates[:limit]
        paths = set()
        for _, kind, identity, row in selected:
            paths.update([identity] if kind == 'file' else json.loads(row['sources']))
        # A replaced source symlink must not be followed; remove it from cache and stale its notes.
        unsafe = {p for p in paths if not self.eligible(p)}
        if unsafe:
            self.invalidate(unsafe, self.rows())
            self.db.executemany('DELETE FROM files WHERE path=?', [(p,) for p in unsafe])
        refresh = self.refresh(paths - unsafe)
        output = dict(query=terms, inventory_files=self.db.execute('SELECT count(*) FROM files').fetchone()[0],
                      sync=sync, refresh=refresh, matches=len(candidates), results=[], truncated=False)
        for _, kind, identity, _ in selected:
            table, key = ('files', 'path') if kind == 'file' else ('notes', 'id')
            found = self.db.execute(f'SELECT * FROM {table} WHERE {key}=?', (identity,)).fetchone()
            if not found:
                continue
            row = dict(found)
            for field in ('symbols', 'imports', 'dependencies', 'sources'):
                if field in row:
                    row[field] = json.loads(row[field])
            row['record_type'] = kind
            if kind == 'file':
                row['freshness'] = 'fingerprinted' if row['hash'] else 'metadata-only'
            output['results'].append(row)
            if len(dump(output)) > budget - 30:
                output['results'].pop()
                output['truncated'] = True
                break
        output['truncated'] |= len(candidates) > limit
        return output


def words(text):
    text = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', text)
    return set(re.findall(r'[a-z0-9]+', text.lower()))


def execute(args):
    store = Store(args.root)
    try:
        if args.command == 'rebuild' and store.db_path.exists():
            backup = safe_path(store.root, '.project-efficiency/knowledge.backup-' + str(time.time_ns()) + '.sqlite3')
            # Acquire the writer lock, preserve the original bytes, and rebuild in
            # the same transaction. Avoid unlinking a database another process holds.
            store.db = sqlite3.connect(store.db_path, timeout=2)
            store.db.row_factory = sqlite3.Row
            try:
                store.db.execute('BEGIN EXCLUSIVE')
            except sqlite3.DatabaseError:
                # Corruption recovery must not guess whether a live writer exists.
                backup.write_bytes(store.db_path.read_bytes())
                raise ValueError('Cannot lock database; original preserved. Stop other writers, '
                                 'move the damaged database aside if corrupt, then run init. Backup: ' + str(backup))
            # Use a second reader for a consistent committed backup. BEGIN EXCLUSIVE
            # blocks that reader, so serialize this connection instead (Python 3.11+).
            backup.write_bytes(store.db.serialize())
            paths = store.inventory()
            with store.db:
                for table in ('files', 'notes', 'state'):
                    store.db.execute('DROP TABLE IF EXISTS ' + table)
                for statement in SCHEMA.split(';'):
                    if statement.strip():
                        store.db.execute(statement)
                store.set_state('schema', VERSION)
                result = store.refresh(paths, content=False)
                store.checkpoint()
            return dict(result, initialized=True, backup=str(backup))
        else:
            backup = None
        if args.command in ('init', 'rebuild'):
            if store.db_path.exists():
                store.connect()
                return {'initialized': True, 'unchanged': True}
            paths = store.inventory()
            store.connect(create=True)
            with store.db:
                result = store.refresh(paths, content=False)
                store.checkpoint()
            return dict(result, initialized=True, mode=store.state('mode'), backup=str(backup) if backup else None)
        store.connect()
        if args.command != 'validate':
            store.db.execute('BEGIN IMMEDIATE')
        with store.db:
            if args.command == 'update':
                return store.refresh(args.paths)
            if args.command == 'sync':
                return store.sync()
            if args.command == 'reconcile':
                result = store.refresh(store.inventory() | set(store.rows()))
                store.checkpoint()
                return result
            if args.command == 'query':
                return store.query(args.terms, args.limit, args.domain, args.budget, args.no_sync)
            if args.command == 'note':
                if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', args.id):
                    raise ValueError('Note ID must be 1-80 letters, numbers, underscores, or hyphens')
                if len(args.summary) > 1600 or len(args.sources) > 20:
                    raise ValueError('Keep notes under 1600 characters with at most 20 sources')
                if any(len(value) > 160 for value in (args.domain, args.subsystem, args.component)):
                    raise ValueError('Hierarchy labels must be at most 160 characters')
                store.refresh(args.sources)
                rows = store.rows()
                sources = {}
                for path in args.sources:
                    path = PurePosixPath(path.replace('\\', '/')).as_posix()
                    if path not in rows or not rows[path]['hash']:
                        raise ValueError('Note sources must be eligible, existing, bounded text files')
                    sources[path] = rows[path]['hash']
                store.db.execute('INSERT OR REPLACE INTO notes VALUES (?,?,?,?,?,?,?,?,?)',
                                 (args.id, args.domain, args.subsystem, args.component, args.summary,
                                  dump(sources), args.status, args.evidence, now()))
                return {'note': args.id, 'status': args.status, 'sources': len(sources)}
            if args.command == 'forget':
                removed = store.db.execute('DELETE FROM notes WHERE id=?', (args.id,)).rowcount
                return {'removed': removed}
            if args.command == 'validate':
                if store.db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('SQLite integrity check failed; use rebuild after preserving the database')
                rows = store.rows()
                for path, row in rows.items():
                    # Validation is structural; a deleted/replaced source is handled at retrieval.
                    if PurePosixPath(path).is_absolute() or '..' in PurePosixPath(path).parts:
                        raise ValueError('Invalid cached source path')
                    for field in ('symbols', 'imports', 'dependencies'):
                        if not isinstance(json.loads(row[field]), list):
                            raise ValueError('Invalid cached file record')
                notes = list(store.db.execute('SELECT * FROM notes'))
                for note in notes:
                    if note['status'] not in STATUSES or not isinstance(json.loads(note['sources']), dict):
                        raise ValueError('Invalid cached note')
                return {'valid': True, 'files': len(rows), 'notes': len(notes), 'source_freshness_checked': False}
    finally:
        if store.db:
            store.db.close()


def bounded_int(low, high):
    def parse(value):
        number = int(value)
        if not low <= number <= high:
            raise argparse.ArgumentTypeError(f'Expected {low}..{high}')
        return number
    return parse


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    for command in ('init', 'sync', 'reconcile', 'validate', 'rebuild'):
        commands.add_parser(command)
    update = commands.add_parser('update')
    update.add_argument('--paths', nargs='+', required=True)
    query = commands.add_parser('query')
    query.add_argument('terms')
    query.add_argument('--limit', type=bounded_int(1, 20), default=5)
    query.add_argument('--budget', type=bounded_int(1000, 50000), default=12000)
    query.add_argument('--domain')
    query.add_argument('--no-sync', action='store_true')
    note = commands.add_parser('note')
    note.add_argument('--id', required=True)
    note.add_argument('--domain', required=True)
    note.add_argument('--subsystem', default='')
    note.add_argument('--component', default='')
    note.add_argument('--summary', required=True)
    note.add_argument('--sources', nargs='+', required=True)
    note.add_argument('--status', choices=STATUSES, default='inferred')
    note.add_argument('--evidence', choices=('source-code', 'documentation', 'configuration',
                                           'user-instruction', 'previous-task'), default='source-code')
    commands.add_parser('forget').add_argument('--id', required=True)
    args = parser.parse_args()
    try:
        print(dump(execute(args)))
    except (OSError, ValueError, sqlite3.Error, subprocess.TimeoutExpired) as error:
        print(dump({'error': str(error)}), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
