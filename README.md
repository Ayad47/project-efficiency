# Project Efficiency

A reusable Codex skill and agent package that reduces repeated exploration through focused retrieval and persistent project knowledge. Built from the supplied architecture description and usage efficiency policy.

## Install in any local project

Requires Python 3.11+; Git on PATH enables automatic change detection. No external Python packages, API keys, paid services, or network access are needed to run the package.

Extract the package, then run from its folder:

Download the packaged installer from [GitHub Releases](https://github.com/Ayad47/project-efficiency/releases/latest), or get the source:

```sh
git clone https://github.com/Ayad47/project-efficiency.git
cd project-efficiency
```

```sh
python install.py --project "/path/to/your/project" --dry-run
python install.py --project "/path/to/your/project"
```

On Windows, use `py -3` instead of `python` if that is your interpreter command, and quote project paths containing spaces. Codex can also run the installer when you provide this package and the target project.

Then open that project in Codex and say:

> Use $project-efficiency to initialize this project's knowledge index. Inspect only enough source to establish its purpose and main entry points, then maintain the index during future tasks.

This requests the initial structural inventory. Installation itself does not scan application code. The always-loaded project policy guides future tasks; the skill supplies the detailed workflow. Start a new chat or restart Codex if the installed skill or agent is not discovered. Existing chats do not necessarily refresh project instructions mid-session.

For an explicitly delegated knowledge task:

> Use the efficiency-steward agent to identify the files and source-backed notes relevant to fixing the mobile menu. Return a concise context packet; do not edit application code.

Ordinary edits should use the main agent and skill directly. The custom agent is available for bounded delegated work and does not run continuously.

## What gets installed

| Location in your project | Purpose |
| --- | --- |
| `AGENTS.md` managed section | Short, persistent usage policy; preserves existing instructions |
| `.agents/skills/project-efficiency/` | Skill, reference, UI metadata, and local indexing helper |
| `.codex/agents/efficiency-steward.toml` | Named Codex agent; inherits model and permissions |
| `.project-efficiency/install.json` | Ownership record for safe upgrades and removal |
| `.gitignore` managed section | Keeps generated knowledge local |
| `.project-efficiency/knowledge.sqlite3` | Created by initialization; paths, relationships, notes, provenance |
| `.project-efficiency/runs/` | Timed skill invocations and brief reports; latest 20 completed records |

## Efficiency reports (v1.1)

Every skill invocation now announces that Project Efficiency is active and ends with a short report. First setup reports the actual index size, initialization source bytes read, knowledge created, and workflow improvements. Later tasks report the optimizations actually applied and measured elapsed wall time, including waits and verification.

The speed field is always shown. It reports an observed time comparison only when a comparable measured without-skill baseline and evidence are supplied. Otherwise it says: **Speedup: not yet measurable — no comparable baseline.** It reports slower outcomes honestly and does not convert file counts into invented time savings. Timing failures show unavailable timing. See [reporting commands and examples](project-efficiency/references/reporting.md).

Use the existing `--upgrade` command to add this feature to a previously installed project. Existing knowledge databases are preserved; there is no schema migration.

Installation refuses conflicting files or modified managed sections, supports `--dry-run`, and is repeatable without duplicating instructions. `--upgrade` replaces only unmodified installer-owned files. `--uninstall` removes those files and managed blocks, preserving surrounding text and the knowledge database. The installer rolls back ordinary write failures; multi-file installation is not crash-atomic. Avoid concurrent installs. If a managed file was customized, preserve it and reconcile it manually before upgrading or uninstalling; there is deliberately no blind overwrite option.

```sh
python install.py --project "/path/to/project" --upgrade
python install.py --project "/path/to/project" --uninstall
```

The supplied folder is the distributable package; installing it globally is unnecessary. Repeat the installation command for each project. It does not change your global Codex configuration.

## Architecture improvements

- **One sparse cache:** SQLite replaces a compulsory forest of documents. Domain, subsystem, component, file, and dependency relationships still exist, but only useful semantic notes are added.
- **Cheap initialization:** inventory paths and metadata first; inspect selected source only when needed. Generated labels are inferred, never asserted as verified architecture.
- **Bounded retrieval:** ranked task terms, optional domain filtering, result and output limits, source freshness checks, no bulk context dump.
- **Incremental maintenance:** explicit changed paths or Git checkpoints; unchanged content is not reparsed. Renames, deletions, reverts, and branch changes are accounted for.
- **Provenance and invalidation:** notes retain source hashes and evidence; changed dependencies invalidate notes through known reverse relationships.
- **Low operational overhead:** no mandatory agent spawning, task diaries, duplicate audits, model switching, or background services.

See [the skill](project-efficiency/SKILL.md) for task behavior and [operations](project-efficiency/references/operations.md) for commands, cache schema, exclusions, and recovery.

## Practical limits

This is a working local index plus agent instructions, not a hard usage limiter. It cannot guarantee instruction compliance, prevent every broad read, change an already-running model's reasoning setting, or measure actual token savings. The timer measures elapsed wall time and computes comparisons from supplied baseline evidence; it cannot independently prove that the skill caused the difference. Measure Codex usage on comparable real tasks to assess token savings.

Discovery works with any file-based project, but import hints currently cover basic JS/TS and Python syntax only. Dynamic/framework relationships require source inspection and curated notes. Search is lexical, not semantic; use component names or record domain notes when user vocabulary differs from filenames. Non-Git folders need explicit change paths or a justified inventory reconciliation for unknown changes. Git submodules are separate projects. Default exclusions are conservative; adjust `.efficiencyignore` for your project, then reconcile explicitly.

The policy is an instruction layer, not a background process. The agent must invoke maintenance during work. Installation and tests do not prove that every future Codex client will load the agent correctly; confirm discovery in the target client.

## Verification

```sh
python -m unittest discover -s tests -v
```

Tests use isolated temporary projects. They exercise cache updates, source-backed note invalidation, Git history/worktree changes, bounded retrieval, exclusions, installation conflicts, repeat installation, and preservation of existing project files. No application builds or external services are needed.

## Format references

Installation locations and agent format checked against official documentation on October 7, 2026:

- [Build skills](https://learn.chatgpt.com/docs/build-skills)
- [Custom agents](https://learn.chatgpt.com/docs/agent-configuration/subagents)
- [Project instructions with AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)

The skill uses `.agents/skills`, and the named agent uses a standalone `.codex/agents/*.toml` file. These are separate from `agents/openai.yaml`, which describes only the skill's UI metadata.
