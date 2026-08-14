# CLAUDE.md — working inside `ai/`

Guidance for agents editing the tooling in this folder. `README.md` (sibling)
explains what everything is and how to run it; this file is the rules.

## Editing rules

- **This folder is the source of truth.** `.claude/skills/`, `.agents/skills/`,
  and `.claude/agents/` contain only symlinks into here — never edit through
  the symlinks, and when adding a new *pipeline* skill, symlink it into
  **both** `.claude/skills/` and `.agents/skills/` or it won't load.
  `boost-*` / `dc-*` skills are generated products and are **not** symlinked.
- **`verify.py` exists in two copies** that must stay identical:
  `skills/discover-drupal-module/scripts/verify.py` (canonical) and
  `skills/discover-drupal-core-module/verify.py`. After editing the canonical
  one, `cp` it over the core copy.
- **Do not break the machine-parseable output contracts.** Orchestrating
  skills parse these mechanically: the `GATE OK` block (download scripts), the
  `VERIFY OK` / `PROBLEM:` lines (verify.py), and the explorer's
  `=== MANIFEST === / === KEY-FACTS === / === DISCREPANCIES === / === END ===`
  blocks. Any change to their shape must update every consumer in the same
  commit.
- Skills use the **agentskills.io `SKILL.md` format**; the `name` is
  kebab-case and must equal the directory name. Bundled scripts are
  **stdlib-only** (plain `python3` / bash) — no pip installs, they must run
  anywhere.

## Changing the discover skills or the explorer agent

1. **Read `IMPROVEMENT-HISTORY.md` first.** It records the error taxonomy,
   which mechanism covers each error class, and why the architecture is the
   way it is (two-wave synthesis grounding, FQCN verify, class sweep). Don't
   re-litigate settled decisions without new data.
2. **Commit the current state before changing anything** — rollback must stay
   free.
3. **Validate with the A/B protocol** (in the history doc): same module +
   model + effort before/after, audit both runs with
   `prompts/audit-discover-docs.md`, score errors by taxonomy class.
4. Prefer **promoting a check into a script** (verify.py) over adding prose
   rules when the check is mechanizable — deterministic beats instructed.
5. Every new "also inspect X" instruction needs an **owning category** that
   documents X, or it will fall through (this failure happened twice).
6. Non-urgent ideas go to `ROADMAP.md` with date + context — don't widen the
   current task.

## Auditing generated output

- Use `prompts/audit-discover-docs.md`. It is **read-only** over docs, skills,
  and agent; audit report files are saved **outside** the docs directory
  (`audit-*.md` inside an output dir would be flagged by verify.py, which
  ignores that prefix only defensively).
- Confirmed doc errors are fixed by spawning one follow-up
  `drupal-module-explorer` scoped to the affected category file — the
  orchestrator (or you) never hand-edits generated docs.
- When verifying a "does not exist" claim, apply the nonexistence rule:
  whole-module grep for declarations **plus** the inheritance chain (core base
  classes — `drupal-site/web/core` is available in this workspace), and
  beware truncated listings (`ls | head` has produced a false accusation
  before).

## Invariants worth re-reading

- **Never fabricate** — docs and skills are consumed by agents that cannot
  verify claims. Prefer omission, or an explicit "not verified" note.
- Generated output under `~/.drupal-context/…` is regenerable; rebuild rather
  than hand-edit.
- The version directory name (`<module>/<version>`) is the join key across
  discover docs, generated skills, and releases — keep it consistent.
