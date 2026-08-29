---
name: discover-drupal-core-module
description: >-
  Produce a full, AI-consumable analysis of a Drupal *core* module (e.g. views,
  node, field), written as category Markdown files plus a metadata.json
  manifest under ~/.drupal-context/core/<version>/<module>/. Accepts an
  optional core version parameter (defaults to the latest stable core tag).
  Self-contained: it resolves and caches the core module's source itself
  (bundled script, sparse download into the user's temp dir — no manual
  download). Use when
  asked to "discover", "explore", "analyze", or "document" a Drupal core
  module. Orchestrates parallel drupal-module-explorer subagents that write
  the category files directly, then drupal-submodule-explorer subagents that
  document submodules grounded in those files.
tools: read, edit/createDirectory, edit/createFile, edit/editFiles, search
---

# Discover a Drupal core module

Same shape as `discover-drupal-module`, but the target is a **Drupal core**
module — one that ships inside `drupal` under `core/modules/<module>/`, not a
contrib project. Core modules have no standalone project on drupal.org, so this
skill **resolves and caches the module's source itself** via the bundled
`download-core-module.sh` script (it never downloads the whole ~50 MB core
archive — it fetches only the one module's subtree, ≈1 MB, into a per-user
temp cache).

You are the **orchestrator**. The `drupal-module-explorer` subagents do the
heavy source reading in their own isolated contexts and **write their assigned
category files directly into the output directory**; each returns only a
compact manifest of what it wrote. **You** write the two files only you can
write: `summary.md` and `metadata.json`. This is the **same
`drupal-module-explorer` agent** the contrib discover skill uses — it just
receives a path inside the core cache.

Inputs: a core module **machine name** (required, e.g. `views`) and an optional
**version** (a core tag, e.g. `11.1.0`). If the version is omitted, the script
selects the **latest stable** core tag.

Follow these steps in order.

## 1. Download & GATE — one script run

**This is a hard gate. Do not spawn any explorer until it passes.** The
bundled script does the whole preparation in one run: sparse-downloads the
core module's subtree (or reuses its per-user temp cache), validates
`<module>.info.yml`, creates the output directory, and enumerates submodules.
It lives next to this SKILL.md — resolve `SKILL_DIR` to the **absolute path
of the directory containing this SKILL.md** (you know it from where this
skill was loaded); never assume a fixed project-relative location. Substitute
the real module name and — if the user gave one — the real version; omit the
version argument entirely to let the script resolve the latest stable core
tag:

```bash
SKILL_DIR="<absolute path of the directory containing this SKILL.md>"
# <version> is optional — omit it for "latest stable".
bash "$SKILL_DIR/download-core-module.sh" <module> [<version>]
```

On success the output ends with `GATE OK` followed by the machine-parseable
block. Carry every value forward **verbatim** — every later step and every
explorer prompt uses these exact strings:

```
GATE OK
MODULE=<machine name>
VERSION=<resolved core version>
MODULE_ROOT=<absolute path to the cached dir containing the .info.yml>
OUTPUT_DIR=<~/.drupal-context/core/<version>/<module>>
DATE_EPOCH=<unix epoch seconds — used for metadata.json in step 7>
SUBMODULE=<machine name>|<dir relative to MODULE_ROOT>   (one line per submodule)
SUBMODULES=<count>
```

The source lands in a per-user temp cache
(`<tempdir>/drupal-context-<user>/core/<version>/<module>/`): it never
occupies the user's project or home directory, the OS reclaims it on its own
schedule, and re-running the same version/module is a cache hit.

If the script exits non-zero (unknown module name, non-existent version,
network failure, or `GATE FAILED`), **stop and report its error** — do not
spawn explorers, do not try to download by other means, and do not improvise
a different path or search elsewhere on the filesystem. The script's messages
already tell the user how to recover (e.g. pass an explicit version, or fix
the module name).

**Note the submodules.** Each `SUBMODULE=` line is a real submodule — its
**machine name** and its **directory** (relative to `MODULE_ROOT`). Core
modules rarely ship submodules, but some do — handle them the same way
contrib does. If `SUBMODULES=0`, skip the submodule wave (step 4) and the
`submodules/` output entirely, and the rest of this skill runs exactly as it
does for a single-module project.

## 2. Spawn wave 1 — Explorers A and B in parallel

**Only reach this step if the GATE in step 1 printed `GATE OK`.** If you do not
have a verified `MODULE_ROOT`, go back — do not spawn.

The explorer team runs in **sequenced waves**. Wave 1 covers the factual root
categories — Explorers A and B in parallel. When the GATE found submodules,
the **submodule wave** runs next (step 4): `drupal-submodule-explorer` batches
grounded in wave 1's files. Explorer C (the synthesis categories
`extension-points` and `ai-integration`) runs last (step 5), after every
earlier file is on disk, and uses them all as its verified fact base. That
sequencing is what keeps each later wave consistent with the facts the
earlier waves already wrote.

Launch **two** `drupal-module-explorer` subagents — A and B — **in a single
batch so they run concurrently**, each assigned a disjoint set of categories.
Give both the same `MODULE_ROOT` and `OUTPUT_DIR`, the machine name
(`MODULE`), and the version (`VERSION` — for a core module the "release" is
the core version); assign work as below.

- **Claude Code**: make two `Task` (Agent) calls with
  `subagent_type: drupal-module-explorer` in one turn.

Use this prompt template for each wave-1 category explorer (A/B) — **substitute the
real `MODULE_ROOT` and `OUTPUT_DIR` the gate printed, plus the real module
machine name and the version. Do not pass literal placeholder strings to the
explorer; they cannot resolve them and will get lost searching the
filesystem:**

> Explore the Drupal core module whose source is at the path `<MODULE_ROOT>` (machine name `<MODULE>`, release `<VERSION>`). That directory contains the module's `.info.yml`; read only files under it. Cover **only** these categories: **<assigned>**. Write one Markdown file per assigned category **directly into the output directory `<OUTPUT_DIR>`**, per your Output Contract — each file starts with its `# …` H1, no metadata header; write nothing anywhere else and never modify the module source. Then return your final message as the `=== MANIFEST ===` block (one JSON entry per file you wrote), ending with `=== END ===`. Nothing else.

For **Explorer A** append: *"You are also assigned `key-facts` — that is NOT a
file: return its fact sheet inline in a `=== KEY-FACTS ===` block between the
manifest and the END marker."*

| Explorer            | Assigned categories                                   |
| ------------------- | ----------------------------------------------------- |
| **A — metadata/UI** | `key-facts`, `configuration`, `permissions`, `routes` |
| **B — code/API**    | `entities`, `plugins`, `services`, `hooks`, `events`  |

(The submodule wave and Explorer C are **not** part of this batch — they run
in steps 4 and 5, after these files exist.)

## 3. Collect the wave-1 manifests

Each explorer's final message is a `=== MANIFEST ===` block holding a JSON
array — one entry per file it wrote, with `file`, `category`, `title`, and
`description` keys — and, for Explorer A only, a `=== KEY-FACTS ===` block
with the inline fact sheet. Parse the JSON arrays and keep the key-facts text.

If any explorer returned an `=== ERROR ===` block instead, report it and stop —
do not fabricate the missing categories. If an explorer's manifest is missing
some assigned category, spawn **one** follow-up explorer for just the missing
pieces before giving up.

### Wave-1 gate — verify these files before anything is grounded in them

The submodule wave and Explorer C copy facts from wave 1's files, so a wrong
fact here propagates into every later file by construction. Verify wave 1
**now**, in partial mode (it checks whatever exists and skips the
completeness checks — `summary.md`, the synthesis files and `metadata.json`
do not exist yet):

```bash
python3 "$SKILL_DIR/verify.py" "$OUTPUT_DIR" --partial --module <module> --module-root "$MODULE_ROOT"
```

Judge the output exactly as in step 8. Every `PROBLEM:` line names the file
and the defect (a miscount, an invented class or plugin id, a `path:line`
that sits in the wrong function, a synthesized code quotation): spawn **one**
follow-up `drupal-module-explorer` scoped to that category file, quoting the
verifier line verbatim, then re-run the gate. Do not start step 4 with a
`PROBLEM:` standing. `WARNING:` lines are judged per step 8 — fix the ones
that look invented, carry the rest into the final report.

## 4. Spawn the submodule wave — `drupal-submodule-explorer` batches

Run this step only when the GATE found submodules (`SUBMODULES` > 0);
otherwise skip to step 5.

This wave runs **after** wave 1's files are on disk because the
`drupal-submodule-explorer` agent is **grounded by design**: it reads the root
module's category files in `OUTPUT_DIR` as its verified fact base for
parent-module symbols, touches parent source only for what they don't cover,
and refuses to run without that fact base.

**Batch large sets**: split the submodules into batches of at most **8** and
launch one `drupal-submodule-explorer` subagent per batch (D1, D2, …), **all
in a single parallel batch**. The output files are disjoint
(`submodules/<sub_machine>.md`), so batches never conflict.

- **Claude Code**: one `Task` (Agent) call per batch with
  `subagent_type: drupal-submodule-explorer`, all in one turn.

Prompt template per batch — substitute the real values as before:

> Document the submodules of the Drupal core module whose source is at the path `<MODULE_ROOT>` (parent machine name `<MODULE>`, release `<VERSION>`). The parent's category docs are in `<OUTPUT_DIR>` — treat them as your verified fact base, per your grounding rules. For each submodule below, read that submodule's own subdirectory and write one condensed file `<OUTPUT_DIR>/submodules/<sub_machine>.md`, per your Output Contract — each file starts with its H1, no metadata header; write nothing anywhere else and never modify the module source. The submodules are: `<sub_machine_1>` at `<dir_1>`, `<sub_machine_2>` at `<dir_2>`, … Then return your final message as the `=== MANIFEST ===` block (one JSON entry per submodule file), plus a `=== DISCREPANCIES ===` block only if you verified that a fact in a root category doc contradicts the source, ending with `=== END ===`. Nothing else.

Collect each batch's manifest exactly like step 3 (submodule entries also
carry the `submodule` key). If a batch returned `=== ERROR ===`, report it and
stop; if a manifest is missing an assigned submodule, spawn **one** follow-up
batch for just the missing ones. **If any batch returned a non-empty
`=== DISCREPANCIES ===` block**, spawn one follow-up `drupal-module-explorer`
for the affected root category file(s), passing the disputed point(s)
verbatim — and resolve this **before step 5**, so Explorer C grounds itself
in corrected files.

## 5. Spawn Explorer C — the synthesis wave

Only after every earlier wave's manifests are collected and files are on disk
(wave 1 and, when it ran, the submodule wave), launch **one** more
`drupal-module-explorer` for the synthesis categories. Use this prompt
template — substitute the real values as before:

> Explore the Drupal core module whose source is at the path `<MODULE_ROOT>` (machine name `<MODULE>`, release `<VERSION>`). Cover **only** these categories: **extension-points, ai-integration**. These are synthesis categories — follow your "Synthesis categories (fact grounding)" rules: first read the category files already present in the output directory `<OUTPUT_DIR>` and treat them as your verified fact base; read the module source for the guidance layer and for anything they do not cover. Write one Markdown file per assigned category directly into `<OUTPUT_DIR>`, per your Output Contract — each file starts with its `# …` H1, no metadata header; write nothing anywhere else and never modify the module source. Then return your final message as the `=== MANIFEST ===` block (one JSON entry per file you wrote), plus a `=== DISCREPANCIES ===` block only if you verified that a fact in an existing category file contradicts the source, ending with `=== END ===`. Nothing else.

Collect its manifest like the others. **If it returned a non-empty
`=== DISCREPANCIES ===` block**, each entry is a disputed fact that Explorer C
verified against the source and found wrong in a wave-1 file (C's own files
already carry the source-verified version). Spawn **one** follow-up explorer
assigned to the affected category file(s), passing the disputed point(s)
verbatim, to re-check the source at the cited location and rewrite the affected
file(s) if the dispute is confirmed. Never resolve a dispute by editing a
category file yourself, and never ignore one silently — if it cannot be
resolved, call it out in your final report.

## 6. Build `summary.md` yourself

Explorers do not produce `summary.md`. Build it from Explorer A's key-facts and
include an index linking every file, then write it to `OUTPUT_DIR/summary.md`.
For a core module, the package is `Core` and the version is the core tag you
resolved. It starts directly with its H1 — no metadata header:

```markdown
# Core Module: {Human Name} (`{machine_name}`)

## Summary

{2–4 sentence description from key-facts.}

## Key Facts

- **Machine name**: `{machine_name}`
- **Package**: Core
- **Drupal core version**: {VERSION}
- **Dependencies**: {list — note core modules depend on other core modules}

## Analysis Files (core module)

- [Entities](entities.md)
- [Plugins](plugins.md)
- [Services](services.md)
- [Configuration](configuration.md)
- [Permissions](permissions.md)
- [Routes & Admin UI](routes.md)
- [Hooks](hooks.md)
- [Events](events.md)
- [Extension Points](extension-points.md)
- [AI Integration Notes](ai-integration.md)
```

**Add a `## Submodules` section only when the submodule wave ran (`SUBMODULES` > 0).**
It indexes the per-submodule files and, for each, gives a one-line description
of what the submodule adds to the parent — derive that line from the manifest
`description` (do not invent capabilities). Use relative links into the
`submodules/` folder:

```markdown
## Submodules (extensions to the core module)

- [{Sub Human Name}](submodules/{sub_machine}.md) — {one-line summary of what it adds}.
- …
```

## 7. Write `metadata.json`

All per-file metadata lives in a single `OUTPUT_DIR/metadata.json` — the doc
files themselves carry none. Assemble it from the gate values and the
explorers' manifests, **copying `category`/`title`/`description` verbatim** —
never invent or rewrite them:

```json
{
  "name": "{MODULE}",
  "human_name": "{Human Name from key-facts}",
  "type": "core",
  "version": "{VERSION}",
  "date": {DATE_EPOCH},
  "files": [
    {
      "file": "summary.md",
      "category": "Summary",
      "title": "{Human Name} — Summary",
      "description": "Overview, key facts, and index of the generated documentation."
    },
    { "file": "entities.md", "category": "Entities", "title": "…", "description": "…" },
    { "file": "submodules/{sub_machine}.md", "category": "Submodule", "submodule": "{sub_machine}", "title": "…", "description": "…" }
  ]
}
```

`files` must list **exactly** `summary.md` plus every file the explorers
reported (all 10 category files, and one `submodules/<sub_machine>.md` per
submodule when there are submodules). `date` is the `DATE_EPOCH` from the gate
(Unix epoch seconds). `version` is the resolved core tag.

## 8. Verify and report

Run the bundled verifier (it sits next to this SKILL.md) — it cross-checks
`metadata.json` against the disk in both directions (all 11 doc files
present, listed, and non-empty; no unlisted files; valid categories;
submodule count matching the GATE), runs the doc-only consistency checks,
and — via `--module-root` — grounds the docs in the source:

```bash
python3 "$SKILL_DIR/verify.py" "$OUTPUT_DIR" --submodules <SUBMODULES> --module-root "$MODULE_ROOT"
```

What it checks beyond structure — every line names the file and, where it
can, the doc line:

| Check | Line starts with | Fails? |
| --- | --- | --- |
| `Drupal\<module>\…` class reference resolves via PSR-4 | `unresolvable class reference` | yes |
| A stated count matches the enumeration it introduces ("declares 5 services: …", "N routes:" + table) | `states N … but … has M` | yes |
| A backticked code span next to a `path:line` citation is literally in those lines | `exists nowhere in that file` / `is not within cited lines` | yes / warning |
| `Class::method()` + `path:line` — the line lies inside that method | `that line is inside \`other()\`` | yes |
| A `Plugin ID` table id is declared by a non-abstract class | `plugin id … abstract` / `not declared by` / `no plugin attribute` | yes |
| Every `@deprecated` public symbol is named in some doc | `@deprecated public symbols in … appear in no doc file` | yes |
| A module-prefixed id string occurs in the source (negated mentions and runtime-interpolated ids are excluded) | `module-prefixed id … not found` | warning |
| Two citations of one file with overlapping, unequal ranges | `citation ranges diverge` | warning |
| Every `*.libraries.yml` entry is named in some doc | `library … mentioned in no doc file` | warning |
| Every non-abstract plugin id is named in some doc (recall) | `N of M \`Type\` plugin ids are mentioned in no doc` | warning |
| A bare module-named class (`<Module>FooSubscriber`) exists in the source | `no class of that name` | warning |

- **`VERIFY OK`** → done.
- **`VERIFY FAILED`** → fix what the `PROBLEM:` lines say. A *structural*
  problem (a file an explorer reported is missing, or one was written but not
  reported) → spawn one follow-up explorer for just that piece, update
  `metadata.json`, re-run. Every *content* problem (unresolvable class,
  miscount, synthesized span, wrong enclosing function, plugin id,
  deprecation gap) is a discrepancy: spawn **one** follow-up explorer scoped
  to the affected category file (`drupal-submodule-explorer` for a
  `submodules/*.md` file), **quoting the verifier line verbatim** so it knows
  exactly what to fix — never edit the file yourself — then re-run. A
  deprecation gap names the *source* file, not a doc: route it to the
  category that owns the symbol (`services` for PHP API, `ai-integration`'s
  Deprecations section). Call out anything still unresolved.
- **`WARNING:` lines do not fail the verify, but judge them before reporting.**
  A *module-prefixed id* warning means a doc names an id string
  (`<module>_…` / `<module>.…`) that occurs nowhere in the source — exactly
  how an identifier reconstructed from a class name looks; unless the id is
  legitimately derived at runtime or doc-composed notation, treat it like a
  discrepancy. A *citation divergence* means one of the two files cites the
  wrong lines — fix the one that does not match the source. A *library* or
  *plugin recall* gap is usually real (`extension-points` owns libraries;
  `plugins.md` may legitimately summarize a huge plugin set — say so). A
  *bare class name* warning is an invented or misspelled class until proven
  otherwise. Mention any warning you left standing in your final report.

Then report back concisely: the `OUTPUT_DIR` path, the resolved core
`VERSION`, the count of category and submodule files written, and a one-line
takeaway about the module. Do **not** paste the file contents into your reply —
the caller reads the files.
