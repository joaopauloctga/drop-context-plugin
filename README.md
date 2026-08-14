# `ai/` — Agent tooling for Drupal Context

This folder is the **source of truth** for the agent tooling that turns Drupal
modules into AI-consumable documentation and agent skills. Everything else in
the workspace (`.claude/`, `.agents/`) only symlinks back here.

## Layout

| Path | What it is |
| --- | --- |
| `skills/discover-drupal-module/` | Discover a **contrib** module → category docs + `metadata.json`. Bundles its own downloader (`scripts/download.py`) and verifier (`scripts/verify.py`). |
| `skills/discover-drupal-core-module/` | Same for **core** modules (sparse-downloads only the module subtree). Keeps its own copies of the scripts. |
| `skills/generate-module-skill/` / `generate-core-module-skill/` | Turn discovered docs into an installable `dc-<module-name>` agent skill. Bundles its own verifier (`scripts/verify.py`) that checks the generated skill's structure and grounds every identifier in it against the discover docs; the core variant reuses the contrib copy. |
| `skills/discover-module-release/` | Release-notes discovery for a module version. |
| `skills/boost-*/` | Legacy generated skills (the pipeline's *product*, not tools — being replaced by `dc-*` naming). |
| `agents/drupal-module-explorer.md` | The worker agent the discover skills orchestrate. All exploration methodology, category contracts, and output contracts live here. |
| `skills/audit-discover-docs/` | Deep, read-only quality audit of generated discover docs — verifies claims against the module source and delivers a `path:line`-evidenced report. |
| `ROADMAP.md` | Deferred improvement ideas, with date + context. |
| `IMPROVEMENT-HISTORY.md` | The distilled record of past improvement rounds — **read it before changing the discover skills or the explorer agent.** |

## Running the pipeline

Everything is invoked as Claude Code skills (or the equivalent in any agent
runner that loads `SKILL.md` files):

```text
/discover-drupal-module <machine_name> [<version>]     # e.g. flag 5.0.3 — version optional, defaults to latest stable
/discover-drupal-core-module <machine_name> [<core_version>]
/generate-module-skill <machine_name> [<version>]      # run after discover
/audit-discover-docs <machine_name> [<version>]        # deep QA of a discover run (read-only)
```

What a discover run does, in order:

1. **Download + GATE** — the bundled script fetches the source into a per-user
   temp cache and prints a machine-parseable `GATE OK` block (paths, version,
   submodules). No gate, no explorers.
2. **Wave 1** — explorers A (metadata/UI), B (code/API), and D (submodules,
   when present) run in parallel and write the factual category files.
3. **Wave 2** — explorer C writes the synthesis files (`extension-points.md`,
   `ai-integration.md`) **grounded in wave 1's files**, reading source only
   for what they don't cover, and reports any conflict it verified via a
   `DISCREPANCIES` block (the orchestrator then re-checks the disputed file).
4. The orchestrator writes `summary.md` + `metadata.json` and runs the
   verifier.

Output lands in `~/.drupal-context/modules/<module>/<version>/` (contrib) or
`~/.drupal-context/core/<version>/<module>/` (core). Source cache lives in
`${TMPDIR}/drupal-context-<user>/…` and is disposable.

**Model/effort tip**: Sonnet at high effort is the validated operating point
for discover runs; reserve Opus or max effort for exceptionally API-dense
modules. (See `IMPROVEMENT-HISTORY.md` for the data behind this.)

## Validating the output

Three layers, cheapest first:

1. **The bundled verifier** (runs automatically as the discover skill's last
   step; re-run it any time):

   ```bash
   python3 skills/discover-drupal-module/scripts/verify.py \
     ~/.drupal-context/modules/<module>/<version> \
     --submodules <N> \
     --module-root <path-to-cached-source>
   ```

   It cross-checks `metadata.json` against the files on disk in both
   directions **and validates every `Drupal\<module>\…` class reference in the
   docs against the source via PSR-4** — an invented class name fails the
   verify. `VERIFY OK` + `FQCN_CHECKED=n` is the pass signal.

2. **Quick manual smoke checks** — `services.md` must have its three sections
   (Container Services / Public PHP API / Procedural API); `events.md` must
   cite dispatch sites as `Class::method()`; any "N hooks/plugins" count
   should be recountable; submodule docs must not contain "presumably".

3. **Deep audit** — run `/audit-discover-docs <module> [<version>]` (it
   auto-detects contrib vs core and defaults to the newest discovered
   version). It encodes the full audit
   protocol: verify claims against source at the line level, the
   nonexistence rule (inheritance-aware — never trust a single grep), cross-
   file consistency, orphan/procedural completeness sweeps, and a report
   format that requires `path:line` evidence for every error. It is
   **read-only** by contract and saves any report file *outside* the docs
   directory. Confirmed errors are fixed by spawning a follow-up
   `drupal-module-explorer` scoped to the affected file — never by editing
   generated docs by hand.

## Improving the tooling

- Read `IMPROVEMENT-HISTORY.md` first — it records what was tried, what
  failed, the error taxonomy, and which mechanism covers each error class.
- Evaluate any change with the A/B protocol described there: same module,
  same model/effort, audit before and after, score errors by class.
- Commit the current state before changing skills/agent — rollback is free.
- Park non-urgent ideas in `ROADMAP.md` (with date + context) instead of
  widening the current task.
