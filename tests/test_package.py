import importlib.util
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

PACKAGE = Path(__file__).resolve().parents[1]
SCRIPT = PACKAGE / 'project-efficiency/scripts/knowledge.py'
sys.path.insert(0, str(SCRIPT.parent))
import knowledge

spec = importlib.util.spec_from_file_location('installer', PACKAGE / 'install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class Project(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, path, text):
        file = self.root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text, encoding='utf-8')
        return file

    def cli(self, *args, good=True):
        result = subprocess.run([sys.executable, str(SCRIPT), '--root', str(self.root), *args],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0 if good else 1, result.stderr)
        return json.loads(result.stdout if good else result.stderr)

    def note(self, name, path):
        return self.cli('note', '--id', name, '--domain', 'frontend', '--component', name,
                        '--summary', name + ' behavior', '--sources', path, '--status', 'verified')

    def data(self, table):
        with closing(sqlite3.connect(self.root / '.project-efficiency/knowledge.sqlite3')) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute('SELECT * FROM ' + table)]

    def test_inventory_is_metadata_only_and_query_is_bounded(self):
        for i in range(30):
            self.write(f'src/MobileMenu{i}.tsx', 'export function Menu() { return null; }')
        result = self.cli('init')
        self.assertEqual(result['source_bytes_read'], 0)
        self.assertTrue(all(r['hash'] is None for r in self.data('files')))
        output = self.cli('query', 'mobile menu', '--limit', '3', '--budget', '1800')
        self.assertLessEqual(len(knowledge.dump(output)), 1800)
        self.assertTrue(output['truncated'])
        self.assertGreater(len(output['results']), 0)
        self.assertEqual(sum(r['hash'] is not None for r in self.data('files')), 3)

    def test_targeted_change_same_size_and_deletion(self):
        self.write('src/menu.py', 'value = 1\n')
        self.write('src/other.py', 'value = 0\n')
        self.cli('init')
        self.note('menu', 'src/menu.py')
        file = self.root / 'src/menu.py'
        stamp = file.stat()
        file.write_text('value = 2\n')
        os.utime(file, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        self.cli('update', '--paths', 'src/menu.py')
        self.assertEqual(self.data('notes')[0]['status'], 'outdated')
        other = next(r for r in self.data('files') if r['path'] == 'src/other.py')
        self.assertIsNone(other['hash'])
        file.unlink()
        self.cli('update', '--paths', 'src/menu.py')
        self.assertNotIn('src/menu.py', [r['path'] for r in self.data('files')])

    def test_transitive_dependency_invalidation(self):
        self.write('src/App.tsx', "import Header from './Header';")
        self.write('src/Header.tsx', "import Menu from './Menu';")
        self.write('src/Menu.tsx', 'export function Menu() { return 1; }')
        self.cli('init')
        self.cli('update', '--paths', 'src/App.tsx', 'src/Header.tsx', 'src/Menu.tsx')
        self.note('application', 'src/App.tsx')
        self.write('src/Menu.tsx', 'export function Menu() { return 2; }')
        self.cli('update', '--paths', 'src/Menu.tsx')
        self.assertEqual(self.data('notes')[0]['status'], 'outdated')

    def test_python_relative_import_edges(self):
        self.write('pkg/main.py', 'from . import helpers\n')
        self.write('pkg/helpers.py', 'def action(): pass\n')
        self.cli('init')
        self.cli('update', '--paths', 'pkg/main.py')
        row = next(r for r in self.data('files') if r['path'] == 'pkg/main.py')
        self.assertEqual(json.loads(row['dependencies']), ['pkg/helpers.py'])

    def test_retrieval_refreshes_note_sources(self):
        self.write('src/state.py', 'open = True\n')
        self.cli('init')
        self.note('navigation', 'src/state.py')
        self.write('src/state.py', 'open = False\n')
        result = self.cli('query', 'navigation', '--no-sync')
        self.assertEqual(result['results'][0]['status'], 'outdated')

    def test_exclusions_size_and_ignore_reconciliation(self):
        for path in ('.env', 'keys/token.pem', 'node_modules/x.js', 'private/data.py'):
            self.write(path, 'secret')
        self.write('.efficiencyignore', 'private/\n')
        self.write('src/large.py', 'x' * (knowledge.MAX_TEXT + 10))
        self.write('src/visible.py', 'x=1')
        self.cli('init')
        paths = [r['path'] for r in self.data('files')]
        self.assertNotIn('.env', paths)
        self.assertNotIn('keys/token.pem', paths)
        self.assertNotIn('private/data.py', paths)
        self.assertNotIn('node_modules/x.js', paths)
        result = self.cli('update', '--paths', 'src/large.py')
        self.assertEqual(result['source_bytes_read'], 0)
        self.write('.efficiencyignore', 'private/\nsrc/visible.py\n')
        self.cli('reconcile')
        self.assertNotIn('src/visible.py', [r['path'] for r in self.data('files')])

    def test_path_traversal_is_rejected(self):
        self.cli('init')
        self.assertIn('error', self.cli('update', '--paths', '../outside.py', good=False))

    def test_symlinks_are_not_followed(self):
        target = self.write('actual.py', 'value=1')
        try:
            (self.root / 'alias.py').symlink_to(target)
        except OSError:
            self.skipTest('Host does not permit creating symlinks')
        self.cli('init')
        self.assertNotIn('alias.py', [r['path'] for r in self.data('files')])

    def test_idempotent_init_validation_and_rebuild_backup(self):
        self.write('src/code.py', 'x=1')
        self.cli('init')
        self.note('code', 'src/code.py')
        self.assertTrue(self.cli('init')['unchanged'])
        self.assertEqual(self.cli('validate')['notes'], 1)
        result = self.cli('rebuild')
        self.assertTrue(Path(result['backup']).exists())
        self.assertEqual(self.cli('validate')['notes'], 0)
        with closing(sqlite3.connect(result['backup'])) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM notes').fetchone()[0], 1)

    def test_corrupt_cache_is_preserved(self):
        self.write('.project-efficiency/knowledge.sqlite3', 'not sqlite')
        self.cli('query', 'menu', good=False)
        self.assertEqual((self.root / '.project-efficiency/knowledge.sqlite3').read_text(), 'not sqlite')

    def test_install_repeat_uninstall_preserves_user_text(self):
        agents = b'# Existing policy\r\nKeep tests.\r\n'
        ignore = b'custom-output/'
        (self.root / 'AGENTS.md').write_bytes(agents)
        (self.root / '.gitignore').write_bytes(ignore)
        preview = installer.run(self.root, dry_run=True)
        self.assertIn('AGENTS.md', preview['changed_files'])
        self.assertFalse((self.root / '.agents').exists())
        installer.run(self.root)
        self.assertEqual(installer.run(self.root)['changed_files'], [])
        self.assertTrue((self.root / '.codex/agents/efficiency-steward.toml').exists())
        self.write('.project-efficiency/keep.txt', 'retained cache')
        installer.run(self.root, uninstall=True)
        self.assertEqual((self.root / 'AGENTS.md').read_bytes(), agents)
        self.assertEqual((self.root / '.gitignore').read_bytes(), ignore)
        self.assertTrue((self.root / '.project-efficiency/keep.txt').exists())

    def test_install_conflict_fails_before_policy_write(self):
        self.write('.codex/agents/efficiency-steward.toml', 'custom')
        with self.assertRaises(ValueError):
            installer.run(self.root)
        self.assertFalse((self.root / 'AGENTS.md').exists())
        self.assertFalse((self.root / '.agents').exists())

    def test_modified_managed_file_is_preserved(self):
        installer.run(self.root)
        custom = self.write('.agents/skills/project-efficiency/SKILL.md', 'customized')
        for mode in ({'upgrade': True}, {'uninstall': True}):
            with self.assertRaises(ValueError):
                installer.run(self.root, **mode)
            self.assertEqual(custom.read_text(), 'customized')

    def test_upgrade_preserves_unmanaged_text(self):
        self.write('AGENTS.md', 'Original policy\n')
        installer.run(self.root)
        file = self.root / 'AGENTS.md'
        file.write_text(file.read_text(encoding='utf-8') + '\nNew user policy\n', encoding='utf-8')
        updated = installer.sources()
        path = '.agents/skills/project-efficiency/SKILL.md'
        updated[path] += b'\nAdditional package instruction.\n'
        with patch.object(installer, 'sources', return_value=updated):
            with self.assertRaises(ValueError):
                installer.run(self.root)
            installer.run(self.root, upgrade=True)
        self.assertEqual((self.root / path).read_bytes(), updated[path])
        self.assertIn('New user policy', file.read_text())
        installer.run(self.root, uninstall=True)
        self.assertIn('Original policy', file.read_text())
        self.assertIn('New user policy', file.read_text())

    def test_install_rolls_back_write_failure(self):
        self.write('AGENTS.md', 'Original policy\n')
        original_write = installer.write_atomic
        def fail_policy(path, data):
            if path.name == 'AGENTS.md':
                raise OSError('Simulated failed write')
            original_write(path, data)
        with patch.object(installer, 'write_atomic', side_effect=fail_policy):
            with self.assertRaises(OSError):
                installer.run(self.root)
        self.assertEqual((self.root / 'AGENTS.md').read_text(), 'Original policy\n')
        self.assertFalse((self.root / '.codex/agents/efficiency-steward.toml').exists())

    def test_conflicting_cache_writer_fails_without_loss(self):
        self.write('src/code.py', 'x=1')
        self.cli('init')
        with closing(sqlite3.connect(self.root / '.project-efficiency/knowledge.sqlite3')) as db:
            db.execute('BEGIN IMMEDIATE')
            self.cli('update', '--paths', 'src/code.py', good=False)
            db.rollback()
        self.assertTrue(self.cli('validate')['valid'])


@unittest.skipUnless(shutil.which('git'), 'Git not available')
class GitProject(Project):
    def setUp(self):
        super().setUp()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Local fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.write('.gitignore', '.project-efficiency/\n')

    def git(self, *args):
        result = subprocess.run(['git', '-C', str(self.root), *args], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def commit(self):
        self.git('add', '.')
        self.git('commit', '-qm', 'fixture')

    def test_committed_changes_rename_untracked_and_revert(self):
        self.write('src/menu.py', 'x=1')
        self.commit()
        self.cli('init')
        self.note('menu', 'src/menu.py')
        self.write('src/menu.py', 'x=2')
        self.cli('sync')
        changed_hash = next(r['hash'] for r in self.data('files') if r['path'] == 'src/menu.py')
        self.git('restore', 'src/menu.py')
        self.cli('sync')
        reverted_hash = next(r['hash'] for r in self.data('files') if r['path'] == 'src/menu.py')
        self.assertNotEqual(changed_hash, reverted_hash)
        self.git('mv', 'src/menu.py', 'src/navigation.py')
        self.commit()
        self.write('src/new.py', 'x=3')
        self.cli('sync')
        paths = {r['path'] for r in self.data('files')}
        self.assertIn('src/navigation.py', paths)
        self.assertIn('src/new.py', paths)
        self.assertNotIn('src/menu.py', paths)

    def test_branch_switch_and_staged_changes(self):
        self.write('src/base.py', 'x=1')
        self.commit()
        base = self.git('rev-parse', 'HEAD')
        self.cli('init')
        self.write('src/feature.py', 'x=2')
        self.commit()
        self.cli('sync')
        self.git('checkout', '--detach', base)
        self.cli('sync')
        self.assertNotIn('src/feature.py', {r['path'] for r in self.data('files')})
        self.write('src/staged.py', 'x=3')
        self.git('add', 'src/staged.py')
        self.cli('sync')
        self.assertIn('src/staged.py', {r['path'] for r in self.data('files')})

    def test_git_ignore_including_tracked_files(self):
        self.write('private/data.py', 'secret=1')
        self.commit()
        self.write('.gitignore', '.project-efficiency/\nprivate/\n')
        self.cli('init')
        self.assertNotIn('private/data.py', {r['path'] for r in self.data('files')})


if __name__ == '__main__':
    unittest.main()
