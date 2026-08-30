# CONTRIBUTING — working on this plugin

Guidance for agents editing the tooling in this repo. `README.md` (sibling)
explains what everything is and how to run it, from the *end user*'s side;
this file is the rules for changing it.

## Editing rules

- **This repo is a Claude Code plugin.** `.claude-plugin/plugin.json` and
  `marketplace.json` declare it; `skills/` and `agents/` at the repo root are
  what it ships. If this repo is also symlinked into a separate workspace's
  own `.claude/skills/`, `.agents/skills/`, or `.claude/agents/` for local
  development, treat those as **read-only mirrors** — edit only through this
  repo, never through a symlink into it.
- **The document `verify.py` exists in two copies** that must stay identical:
  `skills/document-module/scripts/verify.py` (canonical) and
  `skills/document-core-module/verify.py`. After editing the canonical
  one, `cp` it over the core copy. (The **make** verifier,
  `skills/make-skill/scripts/verify.py`, is deliberately
  single-copy: `make-core-skill` requires the contrib skill
  alongside and runs the script from there — do not fork a core copy.)
  The core-library verifier, `skills/document-core-library/scripts/verify.py`,
  is a third, independent script (different output contract), not a copy.
- **Do not break the machine-parseable output contracts.** Orchestrating
  skills parse these mechanically: the `GATE OK` block (`resolve.py`,
  `prepare.py`, and `retag-docs/scripts/download.py`), the
  `VERIFY OK` / `PROBLEM:` lines (verify.py), and the explorers'
  `=== MANIFEST === / === KEY-FACTS === / === DISCREPANCIES === / === END ===`
  blocks (shared by `drupal-module-explorer` and `drupal-submodule-explorer`).
  Any change to their shape must update every consumer in the same commit.
- Skills use the **agentskills.io `SKILL.md` format**; the `name` is
  kebab-case and must equal the directory name. Bundled scripts are
  **stdlib-only** (plain `python3` / bash) — no pip installs, they must run
  anywhere.
- **Zero network in the document/make/audit skills.** Only
  `retag-docs` and `add-release` talk to the network (they
  diff two tags of an already-documented module, which needs both tags'
  source — something an installed repo cannot provide on its own). Every
  other skill reads only the Drupal repo it is run in.
- **A resolved `MODULE_ROOT`/`LIBRARY_ROOT`/`CORE_ROOT` is always the user's
  real, version-controlled source and is READ-ONLY.** Every write, in every
  skill and every worker agent, goes only under `OUTPUT_DIR`/`WORK_DIR`, which
  are always inside `~/.drop-context/docs/` — a single user-level location,
  independent of which repo you're standing in (override the base with
  `DROP_CONTEXT_HOME`).
- **Verified-but-unconfirmed plugin behavior** (Phase 0 items this refactor
  could not test without an actual plugin install): whether a plugin-installed
  agent's `subagent_type` needs namespacing (currently invoked by bare name,
  e.g. `drupal-module-explorer`) and whether sibling-skill paths like
  `$SKILL_DIR/../document-module/scripts/resolve.py` resolve correctly
  once this repo is loaded as an installed plugin rather than a plain
  directory. If either breaks, the fix is either namespacing the
  `subagent_type` values or copying (not referencing) the shared scripts
  into each dependent skill — verify against a real plugin install before
  assuming either is needed.

## Changing the document skills or the explorer agents

1. **Read `IMPROVEMENT-HISTORY.md` first.** It records the error taxonomy,
   which mechanism covers each error class, and why the architecture is the
   way it is (two-wave synthesis grounding, FQCN verify, class sweep). Don't
   re-litigate settled decisions without new data.
2. **Commit the current state before changing anything** — rollback must stay
   free.
3. **Validate with the A/B protocol** (in the history doc): same module +
   model + effort before/after, audit both runs with
   the `audit-docs` skill, score errors by taxonomy class.
4. Prefer **promoting a check into a script** (verify.py) over adding prose
   rules when the check is mechanizable — deterministic beats instructed.
5. Every new "also inspect X" instruction needs an **owning category** that
   documents X, or it will fall through (this failure happened twice).
6. Non-urgent ideas go to `ROADMAP.md` with date + context — don't widen the
   current task.

## Auditing generated output

- Use the `audit-docs` skill. It is **read-only** over docs, skills,
  and agent; audit report files are saved **outside** the docs directory
  (`audit-*.md` inside an output dir would be flagged by verify.py, which
  ignores that prefix only defensively).
- Confirmed doc errors are fixed by spawning one follow-up explorer scoped to
  the affected file — `drupal-module-explorer` for a category file,
  `drupal-submodule-explorer` for a `submodules/*.md` file — the orchestrator
  (or you) never hand-edits generated docs. **One sanctioned exception**:
  `retag-docs` retags a doc set across a tiny release delta and may
  apply mechanical, diff-quotable fact substitutions (version string,
  core-requirement line) directly — gated by its hard preconditions and a
  mandatory `verify.py` pass; anything narrative stays explorer-only
  (`add-release` spawns explorers for exactly that reason).
- When verifying a "does not exist" claim, apply the nonexistence rule:
  whole-module grep for declarations **plus** the inheritance chain (core base
  classes — the audit skill runs inside the same repo, so `core/` is always
  available there), and beware truncated listings (`ls | head` has produced a
  false accusation before).

## Invariants worth re-reading

- **Never fabricate** — docs and skills are consumed by agents that cannot
  verify claims. Prefer omission, or an explicit "not verified" note.
- Generated output under `~/.drop-context/docs/…` is regenerable; rebuild
  rather than hand-edit.
- The version directory name (`<module>/<version>`) is the join key across
  doc sets, generated skills, and releases — keep it consistent.
