---
name: retag-docs
description: >-
  The routine version-bump skill for a documented Drupal contrib module, for
  *small* release deltas in the same release line: retag the existing doc set
  in place to the target version (no clone, no second doc set — at most
  mechanical, diff-derived fact edits) AND generate the target release's
  notes as `release.json` in the same directory. The "dev updates the module
  and nothing, or almost nothing, changes" case — check the Drupal.org
  release page: no breaking changes announced, same core support. Verifies
  the result against the target source and refuses anything needing prose
  work, pointing to add-release. Requires the document-module
  skill installed alongside (download/verify scripts). Use when a documented
  module got a patch/minor release with no meaningful change to its
  documented surface.
---

# Retag docs (small delta: retag in place + release notes)

You move `~/.drop-context/docs/modules/<module>/<current>/` forward so it
becomes the doc set for `<target>` — the same docs, retagged, with at most a
handful of **mechanical** fact corrections derived from the source diff — and
you write the target release's `release.json` into that directory. One doc
set in the line before, one after. This is the cheap path for routine version
bumps; its whole value is refusing to be anything more.

This is the pipeline's one remaining networked skill: it diffs two tags of an
already-documented module, which needs both tags' source downloaded (an
installed repo only ever holds one checked-out version).

**You choose this skill, it doesn't choose for you** — see `README.md`
("Release maintenance: which skill when"). Real content changes (new features,
removed surface, anything needing prose) → `/drop-context:add-release`. Rewrites /
new major lines → `/drop-context:document-module`. The gates below are the safety
net, not the router.

**Parameters:**

| Param | Example | Meaning |
|-------|---------|---------|
| `module` | `workflow` | Machine name |
| `current` | `2.1.10` | Documented version to move forward (defaults to the newest documented version in `target`'s release line that is older than `target`) |
| `target` | `2.1.11` | New version the docs will describe |

Docs resolution is the same as the generate skills: they live at a single,
fixed user-level location — nothing to search for. Honour `DROP_CONTEXT_HOME`
when set, else default to `~/.drop-context`; `$DOCS_BASE` in the steps below
is `$DROP_CONTEXT_HOME/docs/modules/$module` (i.e.
`~/.drop-context/docs/modules/$module` by default).

`target` may **skip intermediate tags** (e.g. `3.1.0` straight to `3.1.6`):
the gates and every diff apply to the *cumulative* `current → target` delta,
which carries the same information as chaining the hops — intermediate
releases get no doc set of their own. If the cumulative delta fails a gate,
the answer is `/drop-context:add-release` for the same jump, never hop-by-hop
updates. (The generated `release.json` describes `target`'s own release —
delta vs its immediately preceding tag — per the output contract.)

References:

- [docs-impact.md](references/docs-impact.md) — category map + coverage rule (**required**)
- [drupal-org-release-page.md](references/drupal-org-release-page.md) — reading the d.o release page
- [gitlab-compare.md](references/gitlab-compare.md) — GitLab enrichment for the notes
- [output-contract.md](references/output-contract.md) — `release.json` contract (**required**)
- `scripts/download.py` — downloader (bundled with this skill; the only network access in the pipeline)
- `../document-module/scripts/verify.py` — verifier (sibling skill)

## Hard gates (all must hold, or refuse the docs action)

1. `$DOCS_BASE/$current/metadata.json` exists. (`$DOCS_BASE/$target` already
   holding a `metadata.json` means the target is **already documented**: skip
   the retag entirely — steps 2–3 — and still do step 4, the release notes.)
2. `target` is newer than `current`, in the **same release line**.
3. A **complete local diff** of the two downloaded source trees is available.
   Download failure → refuse (`unknown` delta is never "small").
4. Every changed file is either in a no-impact bucket (tests, CI, style —
   per docs-impact.md, hunks actually read), or its only effect on the docs
   is a **mechanical fact substitution**: version string, core requirement
   line, a dependency constraint, a renamed file path. New/removed/renamed
   plugins, services, hooks, events, routes, permissions, entities, config
   schema keys, or submodules always fail this gate — that is prose work.
   Apply the docs-impact.md coverage rule: every diff group dispatched
   explicitly, no sampling.

A failed gate is a **successful run**: report which gate failed, what you
found, and which skill to use instead (`/drop-context:add-release` for real but
contained changes; `/drop-context:document-module` for rewrites/new lines). Change
nothing on disk in that case.

## Steps

1. **Resolve + gates.** Resolve `DROP_CONTEXT_HOME`/`DOCS_BASE` (fixed
   location, no search). List documented versions (`ls -1 "$DOCS_BASE"/*/metadata.json`),
   resolve `current`, download both tags with
   `python3 "<dir containing this SKILL.md>/scripts/download.py" <module> <ref>`
   (once per tag — its `MODULE_ROOT=` gate line is the extracted source path,
   `$SRC_CURRENT` / `$SRC_TARGET` below), `diff -rq`, read every non-bucketed
   hunk, apply the gates above.
2. **Retag in place.**

   ```bash
   mv "$DOCS_BASE/$current" "$DOCS_BASE/$target"
   rm -f "$DOCS_BASE/$target"/audit-*.md
   rm -f "$DOCS_BASE/$target"/release.json   # described $current — step 4 writes $target's
   ```

   Then, surgically: `metadata.json` → `version` = `$target`, `date` = now
   (`date +%s`, the generation-time convention); `summary.md` → the
   `**Version**:` line; plus **only** the mechanical substitutions the diff
   proved (e.g. the core-compatibility line when `.info.yml` changed). Every
   edit must be quotable against a diff hunk — no rewording, no additions.
3. **Verify.** Run the document verifier against the **target** source:

   ```bash
   python3 "<dir containing this SKILL.md>/../document-module/scripts/verify.py" \
     "$DOCS_BASE/$target" --module-root "$SRC_TARGET"
   ```

   Any `PROBLEM:` → roll back (`mv` the dir back, undo edits) and refuse:
   the delta was not as small as it looked.
4. **Release notes → `release.json`.** Write the target release's notes to
   `$DOCS_BASE/$target/release.json` per
   [output-contract.md](references/output-contract.md) — always, even when
   the retag was skipped as already-documented. (If a contract-valid
   `release.json` for `$target` already sits there, keep it and say so —
   never regenerate over it.) Sources, in order:
   - The d.o release page (mandatory to *attempt*; report a failed fetch) —
     [drupal-org-release-page.md](references/drupal-org-release-page.md).
   - The `previous_tag → target` delta (tag history, not our docs baseline)
     and GitLab MR/commit titles for enrichment —
     [gitlab-compare.md](references/gitlab-compare.md). When the page is
     thin, author the summary from these — factual, verbatim-sourced, never
     invented.
   - The diff you already ran feeds `change_level` /
     `core_version_requirement` (breaking changes should be absent here by
     definition of this skill's gates — a real one belongs to
     `/drop-context:add-release`).
5. **Report.** Versions moved, the diff evidence (file counts, which groups
   were bucketed how), every content edit made (quote the hunk that justified
   it), verify result, release.json path + notes quality.
