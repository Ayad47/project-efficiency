# Verification record

Validated on Windows with Python 3.12 and Git on October 7, 2026.

- Version 1.1.0 automated suite: 44 test executions; 42 passed, 2 skipped, 0 failures.
- Reporting checks cover setup before index creation, measured elapsed time, absent/incomplete/invalid baselines, faster and slower observed comparisons, partial-task comparison suppression, idempotent finish, clock discontinuities, bounded completed-run retention, invalid run IDs, and CLI start/finish.
- The two skipped executions are symlink creation tests (Git and non-Git fixtures); this Windows host did not grant symlink creation rights. Symlink and junction exclusion logic is present but these host-level cases remain unverified.
- Tested initialization without source reads, bounded retrieval, selected-file fingerprinting, same-size edits with preserved timestamps, direct and transitive note invalidation, relative Python imports, deletion, exclusion reconciliation, large-file bounds, invalid paths, corrupt-cache preservation, cache writer contention, database rebuild and backup.
- Git cases include committed changes, dirty-file reverts, renames, untracked and staged files, branch changes, and ignore rules affecting tracked files.
- Installer cases include dry run, repeat installation, conflict preflight, local customization preservation, upgrade, Windows line-ending conversion, uninstall preserving surrounding text, and rollback after a simulated write failure.
- Agent TOML parsed using Python's standard TOML parser; required fields are present and model/reasoning/permission overrides are absent.
- The bundled skill-creator `quick_validate.py` was attempted but could not run because PyYAML is not installed in the available Python runtime. Skill frontmatter, linked references, and UI fields were manually reviewed. This package itself has no third-party runtime dependency.

These checks validate the local helpers and package structure, not future agent behavior. Live discovery of this custom agent in a new Codex project, reliable model adherence to the reporting instructions, behavior under every language/framework, and actual Codex token savings have not been measured. Baseline comparisons are tested with controlled timing fixtures, not evidence of real task speedups. No global installation or unrelated project modification was performed.
