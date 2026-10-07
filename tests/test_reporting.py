import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'project-efficiency/scripts/report.py'
sys.path.insert(0, str(SCRIPT.parent))
import report


class Reporting(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def start(self, kind='task'):
        with patch.object(report.time, 'time', return_value=1000), patch.object(report.time, 'monotonic', return_value=100):
            return report.run(self.root, 'start', kind=kind)['run_id']

    def finish(self, identity, **kwargs):
        with patch.object(report.time, 'time', return_value=1090), patch.object(report.time, 'monotonic', return_value=190):
            return report.run(self.root, 'finish', run_id=identity, optimizations=['Updated affected knowledge.'], **kwargs)

    def test_setup_measures_without_index_or_baseline(self):
        result = self.finish(self.start('setup'))
        self.assertEqual(result['kind'], 'setup')
        self.assertEqual(result['elapsed_seconds'], 90)
        self.assertEqual(result['comparison']['status'], 'unavailable')
        self.assertIn('no comparable baseline', result['brief_report'])
        self.assertFalse((self.root / '.project-efficiency/knowledge.sqlite3').exists())

    def test_positive_and_negative_comparisons(self):
        faster = self.finish(self.start(), baseline=120, evidence='Paired run, same model and checks', comparable=True)
        self.assertEqual(faster['comparison']['seconds_saved'], 30)
        self.assertEqual(faster['comparison']['percent_time_reduction'], 25)
        slower = self.finish(self.start(), baseline=60, evidence='Paired run', comparable=True)
        self.assertEqual(slower['comparison']['seconds_saved'], -30)
        self.assertIn('more elapsed time', slower['brief_report'])

    def test_incomplete_and_invalid_baselines(self):
        for kwargs in ({'baseline': 100}, {'evidence': 'run'}, {'comparable': True},
                       {'baseline': 0, 'evidence': 'run', 'comparable': True},
                       {'baseline': float('nan'), 'evidence': 'run', 'comparable': True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.finish(self.start(), **kwargs)

    def test_partial_task_is_not_compared(self):
        result = self.finish(self.start(), baseline=120, evidence='run', comparable=True, outcome='partial')
        self.assertEqual(result['comparison']['status'], 'unavailable')
        self.assertNotIn('seconds_saved', result['comparison'])

    def test_finish_is_idempotent(self):
        identity = self.start()
        first = self.finish(identity)
        second = report.run(self.root, 'finish', run_id=identity, optimizations=['Different observation'])
        self.assertEqual(first, second)

    def test_clock_discontinuity_does_not_invent_time(self):
        identity = self.start()
        with patch.object(report.time, 'time', return_value=5000), patch.object(report.time, 'monotonic', return_value=190):
            result = report.run(self.root, 'finish', run_id=identity, optimizations=['Refreshed notes.'])
        self.assertIsNone(result['elapsed_seconds'])
        self.assertIn('Elapsed time unavailable', result['brief_report'])

    def test_retention_preserves_active_run(self):
        active = self.start()
        for _ in range(22):
            self.finish(self.start())
        records = list((self.root / '.project-efficiency/runs').glob('*.json'))
        self.assertEqual(len(records), 21)
        self.assertTrue(any(p.stem == active for p in records))

    def test_invalid_run_id(self):
        with self.assertRaises(ValueError):
            self.finish('../outside')

    def test_cli_start_and_finish(self):
        command = [sys.executable, str(SCRIPT), '--root', str(self.root)]
        start = subprocess.run(command + ['start', '--kind', 'setup'], capture_output=True, text=True, check=True)
        identity = json.loads(start.stdout)['run_id']
        finish = subprocess.run(command + ['finish', '--run-id', identity, '--optimization', 'Initialized targeted retrieval.'],
                                capture_output=True, text=True, check=True)
        self.assertIn('brief_report', json.loads(finish.stdout))


if __name__ == '__main__':
    unittest.main()
