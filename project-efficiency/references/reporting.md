# Brief efficiency reports

Use the timer once per skill invocation, not once per helper call. A task using several queries gets one report. Timers measure the interval from start to finish, including tool, model, user, and approval waits. They do not isolate active model work or billable usage. Start before setup/retrieval; finish after implementation, verification, and maintenance, just before the final answer.

From the project root (replace `python` with the available Python 3.11+ interpreter):

```sh
python .agents/skills/project-efficiency/scripts/report.py --root . start --kind setup
python .agents/skills/project-efficiency/scripts/report.py --root . finish --run-id RETURNED_ID --optimization "Indexed 120 eligible paths without reading source bodies; created 2 source-backed notes."
```

Use `--kind task` on subsequent invocations. Repeat `--optimization` for up to four short, factual observations. Use `--outcome partial` or `--outcome failed` when appropriate; never present incomplete work as a successful optimization. For the setup report use actual `init` and `note` outputs, not the example counts above. A failed setup can still finish its timer because reporting does not require a knowledge index.

Keep the returned run ID in conversation context. Resume an interrupted task with that ID; the full elapsed interval includes the interruption. Do not finish another task's timer. If no timer was started or its record is inaccessible, report timing unavailable. A main agent and delegated steward use one main task timer; the steward supplies observations without finishing the main timer.

## Comparing task time

A speedup needs an independently measured **without-skill** run with comparable scope, completion criteria, checks, model/reasoning settings, environment, and treatment of waits. Use existing benchmark evidence or a measurement supplied by the user; never generate an assumed baseline or rerun paid agent work just to obtain one. Similar task names or fewer files read are insufficient. Previous with-skill runs are historical timings, not evidence of the skill's benefit.

When evidence is available and comparability has been checked:

```sh
python .agents/skills/project-efficiency/scripts/report.py --root . finish --run-id RETURNED_ID --optimization "Retrieved navigation context and refreshed only affected records." --baseline-seconds 240 --baseline-evidence "User-provided paired benchmark, run B, same checks and model" --comparable-baseline
```

The tool requires all three baseline arguments together. It records evidence, but cannot independently verify the supplied measurement or comparability. It labels the result **observed baseline comparison**, not proven causal savings. It reports seconds less/more and percentage less/more elapsed time; slower work must be shown as slower. Failed/partial runs are not compared against completed-task baselines. Zero or invalid durations have no speed comparison.

Without a baseline, always keep the speed field visible: "Speedup: not yet measurable — no comparable baseline." Do not replace it with a fabricated estimate. File/byte counts may describe reduced retrieval scope, never a time-saving percentage.

## User-facing format

First setup (illustrative counts only):

> Efficiency setup: indexed 120 paths; initialization read 0 source bytes; created 2 verified notes.
> Optimizations: bounded retrieval and incremental maintenance configured. Application code unchanged.
> Elapsed: 42 seconds, including waits. Speedup: not yet measurable — no comparable baseline.

Subsequent task (illustrative counts only):

> Project Efficiency: retrieved 3 relevant records and refreshed 2 changed files.
> Elapsed: 90 seconds, including waits. Speedup: not yet measurable — no comparable baseline.

Use only facts established in that invocation. If application code changed, say what changed rather than reusing the setup example. For a valid comparison, replace the final speed field with the computed observed comparison and its evidence reference. Summarize the report in the final answer even if the raw tool output is collapsed.

## Local records

The helper stores small JSON records under `.project-efficiency/runs/`, excluded from Git by the existing installer. Each contains its ID, kind, start/finish timestamps, outcome, observations, timing, and optional baseline evidence. It stores no prompts or source bodies. It keeps the latest 20 completed records; active timers are retained. Finishing a run twice returns the saved report without extending elapsed time or changing its baseline. No knowledge schema migration is needed; upgrades preserve existing indexes.
