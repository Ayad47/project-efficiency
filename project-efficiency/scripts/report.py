#!/usr/bin/env python3
"""Measure one skill invocation and produce a short, evidence-qualified report."""
import argparse
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import uuid

from knowledge import safe_path


def save(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.report-', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(record, stream, ensure_ascii=True, indent=2, allow_nan=False)
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def comparison(elapsed, baseline, evidence, comparable, outcome):
    if baseline is None and not evidence and not comparable:
        return {'status': 'unavailable', 'message': 'Speedup: not yet measurable — no comparable baseline.'}
    if baseline is None or not evidence or not evidence.strip() or not comparable:
        raise ValueError('Baseline seconds, evidence, and --comparable-baseline must be supplied together')
    if not math.isfinite(baseline) or baseline <= 0 or len(evidence) > 500:
        raise ValueError('Baseline must be positive and finite; evidence must be at most 500 characters')
    if outcome != 'completed' or elapsed is None or elapsed <= 0:
        return {'status': 'unavailable', 'message': 'Speedup: unavailable for incomplete work or invalid elapsed time.'}
    difference = baseline - elapsed
    percent = abs(difference) / baseline * 100
    direction = 'less' if difference >= 0 else 'more'
    return {'status': 'observed-baseline-comparison', 'baseline_seconds': baseline,
            'baseline_evidence': evidence, 'seconds_saved': round(difference, 3),
            'percent_time_reduction': round(difference / baseline * 100, 2),
            'message': f'Observed baseline comparison: {abs(difference):.1f}s {direction} elapsed time '
                       f'({percent:.1f}% {direction}); supplied baseline {baseline:g}s. Attribution is not proven.'}


def run(root, command, kind='task', run_id=None, optimizations=None, outcome='completed',
        baseline=None, evidence=None, comparable=False):
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError('Project root must exist')
    directory = safe_path(root, '.project-efficiency/runs')
    if command == 'start':
        identity = uuid.uuid4().hex
        record = {'run_id': identity, 'kind': kind, 'started_at_unix': time.time(),
                  'started_monotonic': time.monotonic(), 'outcome': 'active'}
        save(safe_path(root, f'.project-efficiency/runs/{identity}.json'), record)
        return record
    if not run_id or not re.fullmatch(r'[a-f0-9]{32}', run_id):
        raise ValueError('Use the run ID returned by start')
    path = safe_path(root, f'.project-efficiency/runs/{run_id}.json')
    record = json.loads(path.read_text(encoding='utf-8'))
    if record['outcome'] != 'active':
        return record
    observations = optimizations or []
    if not observations or len(observations) > 4 or any(not s.strip() or len(s) > 400 for s in observations):
        raise ValueError('Supply 1-4 factual optimization observations, each at most 400 characters')
    finished = time.time()
    elapsed = time.monotonic() - record['started_monotonic']
    # A reboot or material system clock discontinuity makes this interval unreliable.
    wall_elapsed = finished - record['started_at_unix']
    if elapsed < 0 or abs(wall_elapsed - elapsed) > 5:
        elapsed = None
    compared = comparison(elapsed, baseline, evidence, comparable, outcome)
    timing = 'Elapsed time unavailable.' if elapsed is None else f'Elapsed: {elapsed:.1f}s, including waits.'
    record.update(finished_at_unix=finished, outcome=outcome, optimizations=observations,
                  elapsed_seconds=round(elapsed, 3) if elapsed is not None else None,
                  comparison=compared,
                  brief_report=f'Project Efficiency ({record["kind"]}, {outcome}): ' + ' '.join(observations)
                  + '\n' + timing + ' ' + compared['message'])
    save(path, record)
    # Only prune completed, recognized run records in this helper's own directory.
    completed = []
    for candidate in directory.glob('*.json'):
        if not re.fullmatch(r'[a-f0-9]{32}\.json', candidate.name):
            continue
        candidate = safe_path(root, '.project-efficiency/runs/' + candidate.name)
        try:
            data = json.loads(candidate.read_text(encoding='utf-8'))
            if data.get('outcome') in ('completed', 'partial', 'failed') and 'finished_at_unix' in data:
                completed.append((data['finished_at_unix'], candidate))
        except (ValueError, OSError):
            continue
    for _, old in sorted(completed, key=lambda entry: entry[0], reverse=True)[20:]:
        old.unlink()
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('start').add_argument('--kind', choices=('setup', 'task'), default='task')
    finish = commands.add_parser('finish')
    finish.add_argument('--run-id', required=True)
    finish.add_argument('--optimization', action='append', required=True)
    finish.add_argument('--outcome', choices=('completed', 'partial', 'failed'), default='completed')
    finish.add_argument('--baseline-seconds', type=float)
    finish.add_argument('--baseline-evidence')
    finish.add_argument('--comparable-baseline', action='store_true')
    args = parser.parse_args()
    try:
        if args.command == 'start':
            result = run(args.root, 'start', kind=args.kind)
        else:
            result = run(args.root, 'finish', run_id=args.run_id, optimizations=args.optimization,
                         outcome=args.outcome, baseline=args.baseline_seconds,
                         evidence=args.baseline_evidence, comparable=args.comparable_baseline)
        print(json.dumps(result, ensure_ascii=True, allow_nan=False))
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({'error': str(error)}), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
