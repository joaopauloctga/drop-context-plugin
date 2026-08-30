---
name: add-release
description: >-
  Produce a new version's doc set for an already-documented Drupal contrib
  module by upgrading from the existing docs, AND generate that release's
  notes as `release.json` in the new set: keep the current version's doc set
  untouched, create the target version's alongside it (two doc sets coexist),
  copying forward categories the source diff proves unchanged and
  regenerating the affected ones with scoped explorer subagents against the
  target source. For real but *contained* deltas — features added, surface
  removed, breaking changes, structure intact (e.g. eca 3.0.x → 3.1.x); a
  near-rewrite or a new major line is document-module territory, not
  this skill's. Requires the retag-docs (shared references) and
  document-module (scripts, explorer contract) skills installed
  alongside. Use when a documented module's new release changed its
  documented surface too much for retag-docs — the Drupal.org release
  page announcing breaking changes is the usual tell.
---

# Add a release (new doc set alongside + release notes)

You create `~/.drop-context/docs/modules/<module>/<target>/` **next to**
`<current>/` — both versions stay documented (the per-release model: old docs
keep serving upgrade tasks) — and you write the target release's
`release.json` into the new set. The efficiency over a full document run: the
complete source diff tells you which category files the delta touches; only
those are regenerated (by explorer subagents, against the target source), the
rest are copied forward as proven-unchanged.

Like `retag-docs`, this skill downloads both tags (the pipeline's one
networked exception — diffing needs both tags' source, which an installed
repo cannot provide on its own).

**You choose this skill, it doesn't choose for you** — see `README.md`
("Release maintenance: which skill when"). Deltas with no prose impact →
`retag-docs`. What this skill refuses → `document-module`.
The gates below are the safety net, not the router.

**Parameters:**

| Param | Example | Meaning |
|-------|---------|---------|
| `module` | `eca` | Machine name |
| `current` | `3.0.14` | Documented version to ground on (defaults to the newest documented version in `target`'s line older than `target`; cross-line grounding is allowed only when the lines share their architecture — when in doubt, refuse) |
| `target` | `3.1.0` | New version to document |

Docs resolution is the same as the generate skills: they live at a single,
fixed user-level location — nothing to search for. Honour `DROP_CONTEXT_HOME`
when set, else default to `~/.drop-context`; `$DOCS_BASE` below is
`$DROP_CONTEXT_HOME/docs/modules/$module` (i.e.
`~/.drop-context/docs/modules/$module` by default).

References (require the sibling skills):

- `../retag-docs/references/docs-impact.md` — category map + coverage rule (**required**)
- `../retag-docs/references/output-contract.md` — `release.json` contract (**required**)
- `../retag-docs/references/drupal-org-release-page.md` — reading the d.o release page
- `../retag-docs/references/gitlab-compare.md` — GitLab enrichment for the notes
- `../document-module/SKILL.md` — explorer prompt templates, manifest contract, verify step
- `../retag-docs/scripts/download.py` — downloader (the only network access in the pipeline)
- `../document-module/scripts/verify.py`

## When to refuse (full document run instead)

Grounding on old docs only pays while the architecture they describe still
stands. Refuse and recommend `/drop-context:document-module <module> <target>` when
any of:

- The root architecture changed (entity model, plugin-type system, service
  layout reorganized) — e.g. **eca 2.1.x → 3.0.x**: effectively a rewrite,
  grounding buys nothing. (Contrast **eca 3.0.14 → 3.1.0**: 27 of 31
  category files affected, but on an intact architecture — this skill's home
  turf; a high affected count is a *cost note* for the report, never a
  refusal trigger by itself.)
- No complete local diff is available (delta `unknown` can't be scoped).

A refusal changes nothing on disk and is a successful run.

## Steps

1. **Resolve + scope.** Resolve `current`; download both tags with
   `python3 "<dir containing this SKILL.md>/../retag-docs/scripts/download.py" <module> <ref>`
   (once per tag; its `MODULE_ROOT=` gate line is the extracted source path);
   complete `diff -rq` + hunks; apply docs-impact.md's category map **and
   coverage rule** (every diff group dispatched — under-scoping here ships
   stale docs as if they were regenerated). Output of this step: the
   affected list —
   root categories, `submodules/<sub>.md` files, plus submodules **added**
   (need new docs) and **removed** (must not carry forward) in the diff.
   Then apply the refusal rules above.
2. **Seed the target set.** Create `$DOCS_BASE/$target/`. No `release.json`
   is required as input — this skill produces the target's own in step 6; if
   the dir pre-exists holding only a `release.json`, fill it and **preserve
   that file**. A pre-existing `metadata.json` there means the target is
   already documented → refuse, change nothing. Copy forward every category file and
   submodule doc the diff proved untouched (drop `audit-*.md`, drop docs of
   removed submodules); update copied files' mechanical facts only —
   the `**Version**:` line plus any fact line the diff proves changed
   (core-compatibility, a dependency constraint), each quotable against its
   hunk — nothing narrative.
3. **Regenerate the affected files with explorers** — never write category
   prose yourself. Spawn `drupal-module-explorer` for affected root
   categories and `drupal-submodule-explorer` for affected/new submodule
   docs, batched as in the document-module skill, with the **target** source as
   `MODULE_ROOT` and `$DOCS_BASE/$target` as the output dir. Grounding rules
   from the document-module skill apply unchanged — in particular, if any wave-1
   category (entities/plugins/services/hooks/events/…) was regenerated, the
   synthesis categories (`extension-points.md`, `ai-integration.md`) must be
   regenerated after them, grounded on the new files, even if their own
   source areas look untouched in the diff.
4. **Assemble.** Rebuild `metadata.json` for the target set, starting from
   the current set's (`name`, `human_name`, `type` stay — the importer keys
   the module on `name` and titles it from `human_name`): version =
   `$target`, date = now, `files[]` reflecting exactly what is on disk —
   copied and regenerated alike, each entry with `file`/`category`/`title`
   (the importer skips files missing from disk with a warning and reads
   those three keys per entry); carry `project` forward; prune removed
   submodules from `files[]`. Update `summary.md` via the same explorer
   pass or mechanical edits only.
5. **Verify.** `verify.py "$DOCS_BASE/$target" --module-root "$SRC_TARGET"`
   → must print `VERIFY OK`. Problems → fix via a scoped follow-up explorer
   (the document-module skill's protocol), never by hand-editing.
6. **Release notes → `release.json`.** Write the target release's notes to
   `$DOCS_BASE/$target/release.json` per the output contract — unless a
   contract-valid one already sits there (then keep it and say so). Sources:
   the d.o release page (mandatory to *attempt*; report a failed fetch —
   this is where the maintainer's own breaking-changes narrative lives),
   the `previous_tag → target` delta + GitLab MR/commit titles for
   enrichment, and the diff you already ran for `change_level` /
   `breaking_changes[]` / `core_version_requirement`. Include a
   `**Breaking changes:**` section in the summary when any are proven —
   factual, verbatim-sourced, never invented.
7. **Report.** Affected-vs-copied file lists with the diff evidence,
   removed/added submodules, explorer batches run, verify result,
   release.json path + notes quality. Both version dirs now coexist — say so
   explicitly.
