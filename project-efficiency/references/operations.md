# Index operations

Use `python` below for a Python 3.11+ interpreter (on Windows, `py -3` or an available absolute interpreter path also works). Commands run from the target project root after installation.

```sh
python .agents/skills/project-efficiency/scripts/knowledge.py --root . init
python .agents/skills/project-efficiency/scripts/knowledge.py --root . query "mobile navigation" --limit 5
python .agents/skills/project-efficiency/scripts/knowledge.py --root . update --paths src/Header.tsx src/menu.css
python .agents/skills/project-efficiency/scripts/knowledge.py --root . sync
python .agents/skills/project-efficiency/scripts/knowledge.py --root . validate
```

`init` inventories paths, sizes, and types without reading source contents. Repeating it preserves an existing index. Git inventory uses tracked and untracked nonignored paths; a non-Git inventory uses a filtered filesystem walk. Git must be available on PATH and the target must be its root; otherwise non-Git mode is explicit in output. Git commands never execute project scripts.

`query` scores path terms (including camelCase) and note text. `--domain` narrows records to a domain; `--limit` defaults to 5 (maximum 20), and `--budget` caps serialized result characters (default 12000). This is a context proxy, not a token or billing measurement. Results include truncation indicators; refine terms when no useful match appears. No semantic embedding service, network, or API key is required. `--no-sync` avoids Git-wide change detection; selected matches still get fingerprinted. Use this when unrelated repository changes are outside task scope.

`update --paths` accepts explicit relative file paths, including deleted paths. It does not enumerate the repository. Content hashes detect same-size changes; unchanged hashed files are not reparsed. Only eligible UTF-8 text up to 256 KiB is read for symbols and import hints. Other files retain metadata only. `sync` uses saved Git HEAD, changes since it, current dirty/untracked names, and previously dirty names (to detect reverts). It refreshes candidate files and advances the checkpoint. Inventory-only dirty files with unchanged size/time stay unread until selected; this is not proof that their content is unchanged. A branch switch invalidates only changed paths. If old history is unavailable, it requires explicit reconciliation instead of silently scanning everything.

For unknown changes outside Git, or after modifying ignore rules:

```sh
python .agents/skills/project-efficiency/scripts/knowledge.py --root . reconcile
```

This explicitly inventories all eligible paths, then fingerprints them; it is not routine task completion. `validate` checks cache structure/integrity without verifying source freshness. Use `update` for source checks. `rebuild` creates a timestamped backup of an existing database and initializes a new inventory; semantic notes stay in the backup and must be selectively reviewed before restoration. If a corrupt or locked database cannot be opened for an exclusive transaction, it is preserved and recovery stops. Close other writers; for corruption, move the damaged database aside before `init`. Do not rebuild on an ordinary empty query.

## Semantic knowledge

After inspecting sources, record a compact fact rather than source excerpts:

```sh
python .agents/skills/project-efficiency/scripts/knowledge.py --root . note --id navigation --domain frontend --subsystem layout --component header --summary "Header owns mobile menu state; menu.css controls the collapsed breakpoint." --sources src/Header.tsx src/menu.css --status verified --evidence source-code
```

Only choose `verified` after actual source review. Other statuses are `inferred`, `outdated`, and `requires-review`. Evidence types: `source-code`, `documentation`, `configuration`, `user-instruction`, `previous-task`. Source hashes and observation times are stored with each note. Run `note` with the same ID to replace it after review; `forget --id` removes an obsolete note only.

A changed/deleted file marks notes sourced from it or known transitive importers `outdated`. Query checks sources of returned notes. Import hints are deliberately incomplete: simple relative JS/TS imports and Python imports, with local resolution where possible. Aliases, dynamic imports, framework conventions, other languages, and runtime wiring can be missing. Verify actual dependencies; record important cross-file relationships by listing their sources together in a note. Missing edges are never proof of independence.

## Storage and exclusions

`.project-efficiency/knowledge.sqlite3` holds `files`, `notes`, and `state` tables in one transactionally updated database. Files store relative paths, classification, inferred hierarchy, metadata, optional SHA-256, symbols/import hints, and observation time. Notes hold semantic hierarchy and provenance separately. There are no source bodies, credentials, generated markdown forests, mandatory task logs, or background daemons.

Built-in exclusions cover common dependency/build/cache directories, `.git`, `.codex`, `.agents`, `.project-efficiency`, and credential-like paths. Symlinks and Windows junctions are not followed. Add project-specific patterns to `.efficiencyignore`: one case-sensitive project-relative glob or directory prefix per line, `#` comments allowed. Negation is unsupported and produces an error. In Git mode `.gitignore` is also honored, including for previously tracked files. Non-Git mode does not interpret `.gitignore`; use `.efficiencyignore` for custom exclusions. Unknown binary files receive metadata only, never text content.

Keep the cache local (the installer adds a managed `.gitignore` block); commit the skill, agent, and project policy if sharing with a team. Cache data can contain private architectural descriptions: handle it with the same care as source. Ignore changes require explicit `reconcile` to purge newly excluded records and invalidate affected notes.

Writes use SQLite transactions and a short lock timeout; a competing writer fails clearly. Retry after the first writer finishes. Do not delete a database or lock while another writer is active. Broken schema/JSON/SQLite yields a failure message and preserves existing data. No command edits application source.
