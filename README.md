# `ai/` — Agent tooling for Drupal Context

This folder is the **source of truth** for the agent tooling that turns Drupal
modules into AI-consumable documentation and agent skills. Everything else in
the workspace (`.claude/`, `.agents/`) only symlinks back here.

## Layout

| Path | What it is |
| --- | --- |
| `skills/discover-drupal-module/` | Discover a **contrib** module → category docs + `metadata.json`. Bundles its own downloader (`scripts/download.py`) and verifier (`scripts/verify.py`). |
| `skills/discover-drupal-core-module/` | Same for **core** modules (sparse-downloads only the module subtree). Keeps its own copies of the scripts. |
| `skills/discover-drupal-core-library/` | Document a framework library below `core/lib/Drupal` → stable summary/architecture/API/usage docs, optional source-driven topics, and search-oriented `metadata.json`. Uses direct exploration for small libraries and survey/research/synthesis waves for large ones. |
| `skills/generate-module-skill/` / `generate-core-module-skill/` | Turn discovered docs into an installable `dc-<module-name>` agent skill. Bundles its own verifier (`scripts/verify.py`) that checks the generated skill's structure and grounds every identifier in it against the discover docs; the core variant reuses the contrib copy. |
| `skills/update-module-docs/` | Version-bump maintenance for a documented module (small delta: retag in place + release.json). Hosts the shared release-maintenance references (`docs-impact.md`, `output-contract.md`, …). |
| `skills/upgrade-module-docs/` | Version-bump maintenance for real but contained deltas (new doc set alongside + release.json; explorer-regenerated categories). |
| `skills/boost-*/` | Legacy generated skills (the pipeline's *product*, not tools — being replaced by `dc-*` naming). |
| `agents/drupal-module-explorer.md` | The category worker agent the discover skills orchestrate. Exploration methodology, category contracts, and the shared output contract live here. |
| `agents/drupal-submodule-explorer.md` | The submodule worker agent — documents submodules in condensed `submodules/*.md` files, **grounded in the already-written category docs** for parent symbols. Runs after wave 1, in batches of ≤8 submodules. |
| `agents/drupal-core-library-explorer.md` | Multi-mode worker for core libraries: surveys source topology, writes per-workstream evidence notes, and synthesizes the stable library documentation without imposing module categories. |
| `skills/audit-discover-docs/` | Deep, read-only quality audit of generated discover docs — verifies claims against the module source and delivers a `path:line`-evidenced report. |
| `skills/migrate-discover-docs/` | Migrate legacy `storage/…/discover` docs (old 6-line-header format) into the current format under `~/.drupal-context/`, then audit-and-fix the content against the module source. Bundles the mechanical converter (`scripts/migrate.py`). |
| `ROADMAP.md` | Deferred improvement ideas, with date + context. |
| `IMPROVEMENT-HISTORY.md` | The distilled record of past improvement rounds — **read it before changing the discover skills or the explorer agent.** |

## Running the pipeline

Everything is invoked as Claude Code skills (or the equivalent in any agent
runner that loads `SKILL.md` files):

```text
/discover-drupal-module <machine_name> [<version>]     # e.g. flag 5.0.3 — version optional, defaults to latest stable
/discover-drupal-module eca without submodules         # root-only scope: huge ecosystems, submodules deferred
/discover-drupal-module eca only submodules            # completion pass over an existing root-only run (fresh context)
/discover-drupal-core-module <machine_name> [<core_version>]
/discover-drupal-core-library Core/Ajax [<project-or-drupal-root>]
/generate-module-skill <machine_name> [<version>]      # run after discover
/audit-discover-docs <machine_name> [<version>]        # deep QA of a discover run (read-only)
/migrate-discover-docs <machine_name> [<version>]      # legacy storage/…/discover docs → current format + audit-fix
```

What a discover run does, in order:

1. **Download + GATE** — the bundled script fetches the source into a per-user
   temp cache and prints a machine-parseable `GATE OK` block (paths, version,
   submodules). No gate, no explorers.
2. **Wave 1** — explorers A (metadata/UI) and B (code/API) run in parallel
   and write the factual root category files.
3. **Submodule wave** — when the module ships submodules (and the scope
   includes them), `drupal-submodule-explorer` batches (≤8 submodules each,
   in parallel) write `submodules/*.md`, **grounded in wave 1's files** for
   parent symbols. The user can scope a run "without submodules" (root-only;
   the skipped list is recorded in `metadata.json`) and complete it later
   with an "only submodules" pass that runs just this wave.
4. **Synthesis wave** — explorer C writes `extension-points.md` and
   `ai-integration.md` **grounded in every file written before it**, reading
   source only for what they don't cover. Both grounded waves report any
   conflict they verified via a `DISCREPANCIES` block (the orchestrator then
   re-checks the disputed file).
5. The orchestrator writes `summary.md` + `metadata.json` and runs the
   verifier.

Output lands in `~/.drupal-context/modules/<module>/<version>/` (contrib) or
`~/.drupal-context/core/<version>/<module>/` (core). Source cache lives in
`${TMPDIR}/drupal-context-<user>/…` and is disposable.

Core-library discovery is a separate source-local flow. It reads an installed
Drupal checkout at `core/lib/Drupal`, resolves the version from
`Drupal::VERSION`, and writes to
`~/.drupal-context/core-libraries/<version>/<Core-or-Component>/<library>/`.
The four stable files are `summary.md`, `architecture.md`, `api.md`, and
`usage.md`; large libraries may add independently retrievable `topics/*.md`
entries. `metadata.json` records a source digest and assigns every target PHP
file to exactly one documentation entry for mechanical coverage verification.

**Model/effort tip**: Sonnet at high effort is the validated operating point
for discover runs; reserve Opus or max effort for exceptionally API-dense
modules. (See `IMPROVEMENT-HISTORY.md` for the data behind this.)

## Release maintenance: which skill when

When a documented module ships a new release, **you** pick the skill — there
is no router skill. The Drupal.org release page usually tells you everything
you need: breaking changes announced? core support changed? or just fixes?
Both skills also **generate the release's `release.json`** (notes,
classification, issue links — authored from commits/MRs when the d.o page is
thin) into the version's doc-set directory, where the manual copy to the
site's `content/modules/` carries it along (staging is deliberately outside
both skills' scope).

```text
/update-module-docs <module> [<current>] <target>  # tiny delta: retag docs in place + release notes
/upgrade-module-docs <module> [<current>] <target> # real but contained delta: new doc set alongside + release notes
/discover-drupal-module <module> <target>          # sweeping delta / new line / first discovery
```

| Situation | Skill | Result |
|-----------|-------|--------|
| Delta doesn't touch documented surface (fixes, tests, style; at most mechanical fact edits like a core-requirement line) — "the dev updates the module and nothing changes" | `update-module-docs` | The existing doc set is **retagged in place** to the target version (one doc set in the line, moved forward) + the target's `release.json` |
| Real changes but **contained** — features added, surface removed, breaking changes, architecture intact (e.g. eca `3.0.14 → 3.1.0`) | `upgrade-module-docs` | A **new doc set is created alongside** the current one (both versions stay documented); only diff-affected categories are regenerated (by scoped explorers), the rest copied forward + the target's `release.json` |
| **Sweeping** — near-rewrite or a new major line (e.g. eca `2.1.x → 3.0.x`: not worth grounding on the old docs), or the module was never documented, or the delta can't be diffed | `discover-drupal-module` | Full fresh discover (its `release.json`, if wanted, comes from a later `update-module-docs` run on the same version — the already-documented path) |

Skipping intermediate tags is the norm, not a shortcut: both skills diff the
*cumulative* `current → target` source delta (which carries the same
information as chaining every hop), so update `3.1.0 → 3.1.6` directly rather
than hop-by-hop — intermediate releases get no doc set of their own. If the
cumulative delta is too big for update, the answer is upgrade for the same
jump, never a chain of updates.

Both skills gate their own preconditions and refuse across the boundary
(update refuses prose work; upgrade refuses rewrites) — a refusal names the
right skill and changes nothing on disk. `update-module-docs` is the sanctioned
exception to "never hand-edit generated docs": its edits are limited to
mechanical, diff-quotable fact substitutions, and `verify.py` gates the result.

The design was validated on 6 independently audited runs (workflow 2.1.10/
2.2.2, eca 3.0.14→3.1.0→3.1.6: retag, notes-only, refusal→upgrade handoff,
removed- and added-submodule variants, importer round-trips) — the full
audit record lives at the workspace root in
`plans/workflow-release-skill-ground-truth.md`.

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
   directions, runs doc-only consistency checks (a stated count vs the
   enumeration it introduces; two files citing the same code with different
   line ranges), and grounds the docs in the source: every
   `Drupal\<module>\…` class reference resolves via PSR-4, every backticked
   module-prefixed id occurs in the source, a code span quoted next to a
   `path:line` citation is literally in those lines, a `Class::method()` +
   `path:line` pair really lands inside that method, every `Plugin ID` in a
   table is declared by a non-abstract class, and every `@deprecated` public
   symbol is documented; libraries and plugin ids nobody names are warned
   about. `VERIFY OK` plus the `*_CHECKED=n` counters is the pass signal. The
   discover skills also run it in `--partial` mode as a **wave-1 gate**,
   before the submodule and synthesis waves ground themselves in those files.

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
   directory. Confirmed errors are fixed by spawning a follow-up explorer
   scoped to the affected file (`drupal-module-explorer` for category files,
   `drupal-submodule-explorer` for `submodules/*.md`) — never by editing
   generated docs by hand.

## Improving the tooling

- Read `IMPROVEMENT-HISTORY.md` first — it records what was tried, what
  failed, the error taxonomy, and which mechanism covers each error class.
- Evaluate any change with the A/B protocol described there: same module,
  same model/effort, audit before and after, score errors by class.
- Commit the current state before changing skills/agent — rollback is free.
- Park non-urgent ideas in `ROADMAP.md` (with date + context) instead of
  widening the current task.
