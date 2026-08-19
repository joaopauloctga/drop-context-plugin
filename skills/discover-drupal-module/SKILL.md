---
name: discover-drupal-module
description: >-
  Produce a full, AI-consumable analysis of a Drupal contrib module, written as
  category Markdown files plus a metadata.json manifest under
  ~/.drupal-context/modules/<module>/<version>/. Accepts an optional
  version/tag parameter (defaults to the latest stable release).
  Self-contained: it downloads the module source itself via a bundled script
  (cached in the user's temp dir) — no project-specific setup required. Use
  when asked to "discover",
  "explore", "analyze", or "document" a Drupal module so other agents can
  build on it. Orchestrates parallel drupal-module-explorer subagents that
  write the category files directly, then drupal-submodule-explorer subagents
  that document submodules grounded in those files. Supports an optional
  submodule scope for huge ecosystems (e.g. eca, commerce): "without
  submodules" documents the root module only, and a later "only submodules"
  run — optionally naming a subset — completes the same output directory.
tools: read, edit/createDirectory, edit/createFile, edit/editFiles, search
---

# Discover a Drupal module

You are the **orchestrator**. The `drupal-module-explorer` subagents do the
heavy source reading in their own isolated contexts and **write their assigned
category files directly into the output directory**; each returns only a
compact manifest of what it wrote, so neither the module source nor the
generated docs flow through your context. You download the source, verify the
paths, spawn the explorers in parallel, then write the two files only you can
write: `summary.md` and `metadata.json`.

Inputs: a module **machine name** (required, e.g. `webform`), an optional
**version** (a release tag like `6.3.2`, or a branch; if omitted, the bundled
script resolves the **latest stable** tag), and an optional **submodule
scope** — see "Submodule scope" at the end of step 1. By default the run
documents the root module **and** all its submodules.

Follow these steps in order.

## 1. Download & GATE — one script run

**This is a hard gate. Do not spawn any explorer until it passes.** The
bundled script does the whole preparation in one run: downloads the module
source (or reuses its per-user temp cache), validates the extracted
`.info.yml`, creates the output directory, and enumerates submodules. It
lives in `scripts/` next to this SKILL.md — resolve `SKILL_DIR` to the
**absolute path of the directory containing this SKILL.md** (you know it from
where this skill was loaded); never assume a fixed project-relative location.
The script is standard-library-only Python: any `python3` works, nothing to
install.

```bash
SKILL_DIR="<absolute path of the directory containing this SKILL.md>"
# <version> is optional — omit it to auto-select the latest stable tag.
python3 "$SKILL_DIR/scripts/download.py" <module> [<version>]
```

On success the output ends with `GATE OK` followed by the machine-parseable
block. Carry every value forward **verbatim** — every later step and every
explorer prompt uses these exact strings:

```
GATE OK
MODULE=<canonical machine name>
VERSION=<resolved tag>
MODULE_ROOT=<absolute path to the dir containing the .info.yml>
OUTPUT_DIR=<~/.drupal-context/modules/<module>/<version>>
DATE_EPOCH=<unix epoch seconds — used for metadata.json in step 7>
PROJECT_INFO=<absolute path to project-info.json, or none — used in step 7>
SUBMODULE=<machine name>|<dir relative to MODULE_ROOT>   (one line per submodule)
SUBMODULES=<count>
```

`PROJECT_INFO` points at a JSON file of Drupal.org project metadata (security
coverage, maintenance/development status, categories, ecosystem, maintainers,
creation date) the script fetched best-effort from the Drupal.org API + project
page. `PROJECT_INFO=none` means the fetch failed — the run proceeds normally
and step 7 simply omits the `project` key.

The source lands in a per-user temp cache
(`<tempdir>/drupal-context-<user>/modules/<module>/<version>/source/`): it
never occupies the user's project or home directory, the OS reclaims it on its
own schedule, and re-running the same module/version is a cache hit (no
re-download).

If the script exits non-zero (unknown module name, bad ref, network failure,
or `GATE FAILED` — no `.info.yml` in the extracted source), **stop and report
its error message** — do not spawn explorers, do not try to download by other
means, and do not improvise a different path or search elsewhere on the
filesystem.

**Note the submodules.** Each `SUBMODULE=` line is a real submodule — its
**machine name** and its **directory** (relative to `MODULE_ROOT`), e.g.
`SUBMODULE=metatag_open_graph|metatag_open_graph`. If `SUBMODULES=0`, the
module has no submodules: skip the submodules explorer and the `submodules/`
output entirely, and the rest of this skill runs exactly as it does for a
single-module project.

### Submodule scope

The user may scope which part of the module this run documents. Recognize the
scope from the request in any language (e.g. "without submodules", "sem
submódulos", "only the submodules"):

- **full** (default — nothing requested): document the root module **and**
  every submodule, exactly as the steps below describe.
- **root-only** (asked to skip/exclude submodules): skip the submodule wave
  (step 4) and write nothing under `submodules/`. Keep the GATE's
  `SUBMODULE=` lines anyway: step 6 lists those submodules as *detected but
  not documented* and step 7 records them under `submodules_skipped`, so
  consumers and a later run can see exactly what is missing. This is the right choice for huge ecosystems (eca, commerce, …)
  whose submodule set dwarfs the root module.
- **submodules-only** (asked to document only the submodules, optionally a
  named subset): a **completion pass** over an existing output directory,
  typically run in a fresh session after a root-only run. Require that
  `OUTPUT_DIR/metadata.json` and the ten root category files already exist —
  if they don't, stop and tell the user to run the root discover first. Skip
  Explorers A, B, and C entirely: run only the submodule wave (step 4) for
  the requested submodules (all still-undocumented ones by default), then
  update `summary.md` and `metadata.json` **in place** (steps 6–7) and
  re-verify (step 8). The GATE still runs first — it re-resolves
  `MODULE_ROOT` (cache hit) and the authoritative submodule list.

When the user names specific submodules (in any scope), resolve each name
against the GATE's `SUBMODULE=` lines by exact machine-name match and report
any name that doesn't exist instead of guessing; submodules left out of a
named subset are recorded as skipped, exactly as in root-only.

## 2. Spawn wave 1 — Explorers A and B in parallel

**Only reach this step if the GATE in step 1 printed `GATE OK`.** If you do not
have a verified `MODULE_ROOT`, go back — do not spawn.

The explorer team runs in **sequenced waves**. Wave 1 covers the factual root
categories — Explorers A and B in parallel. When the GATE found submodules
(and the scope includes them), the **submodule wave** runs next (step 4):
`drupal-submodule-explorer` batches grounded in wave 1's files. Explorer C
(the synthesis categories `extension-points` and `ai-integration`) runs last
(step 5), after every earlier file is on disk, and uses them all as its
verified fact base. That sequencing is what keeps each later wave consistent
with the facts the earlier waves already wrote.

Launch **two** `drupal-module-explorer` subagents — A and B — **in a single
batch so they run concurrently**, each assigned a disjoint set of categories.
Give both the same `MODULE_ROOT` and `OUTPUT_DIR`, the machine name, and the
version; assign work as below. **In a submodules-only completion pass, skip
steps 2–3 entirely** (A and B already ran in the root discover) and go
straight to step 4.

- **Claude Code**: make two `Task` (Agent) calls with
  `subagent_type: drupal-module-explorer` in one turn.

Use this prompt template for each wave-1 category explorer (A/B) — **substitute the
real `MODULE_ROOT` and `OUTPUT_DIR` the gate printed, plus the real module name
and version. Do not pass literal `MODULE_ROOT`/`<module>` placeholder strings
to the explorer; they cannot resolve them and will get lost searching the
filesystem:**

> Explore the Drupal module whose source is at the path `<MODULE_ROOT>` (machine name `<module>`, release `<VERSION>`). That directory contains the module's `.info.yml`; read only files under it. Cover **only** these categories: **<assigned>**. Write one Markdown file per assigned category **directly into the output directory `<OUTPUT_DIR>`**, per your Output Contract — each file starts with its `# …` H1, no metadata header; write nothing anywhere else and never modify the module source. Then return your final message as the `=== MANIFEST ===` block (one JSON entry per file you wrote), ending with `=== END ===`. Nothing else.

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

## 4. Spawn the submodule wave — `drupal-submodule-explorer` batches

Run this step only when the GATE found submodules (`SUBMODULES` > 0) **and**
the scope includes them (full or submodules-only). Otherwise skip to step 5.

This wave runs **after** wave 1's files are on disk because the
`drupal-submodule-explorer` agent is **grounded by design**: it reads the root
module's category files in `OUTPUT_DIR` as its verified fact base for
parent-module symbols, touches parent source only for what they don't cover,
and refuses to run without that fact base. (In a submodules-only completion
pass the fact base is the earlier root run's files, which step 1 already
required.)

**Batch large sets.** One explorer cannot absorb a huge submodule set in a
single context: split the in-scope submodules into batches of at most **8**
and launch one `drupal-submodule-explorer` subagent per batch (D1, D2, …),
**all in a single parallel batch**. The output files are disjoint
(`submodules/<sub_machine>.md`), so batches never conflict.

- **Claude Code**: one `Task` (Agent) call per batch with
  `subagent_type: drupal-submodule-explorer`, all in one turn.

Prompt template per batch — substitute the real values as before:

> Document the submodules of the Drupal module whose source is at the path `<MODULE_ROOT>` (parent machine name `<module>`, release `<VERSION>`). The parent's category docs are in `<OUTPUT_DIR>` — treat them as your verified fact base, per your grounding rules. For each submodule below, read that submodule's own subdirectory and write one condensed file `<OUTPUT_DIR>/submodules/<sub_machine>.md`, per your Output Contract — each file starts with its H1, no metadata header; write nothing anywhere else and never modify the module source. The submodules are: `<sub_machine_1>` at `<dir_1>`, `<sub_machine_2>` at `<dir_2>`, … Then return your final message as the `=== MANIFEST ===` block (one JSON entry per submodule file), plus a `=== DISCREPANCIES ===` block only if you verified that a fact in a root category doc contradicts the source, ending with `=== END ===`. Nothing else.

Collect each batch's manifest exactly like step 3 (submodule entries also
carry the `submodule` key). If a batch returned `=== ERROR ===`, report it and
stop; if a manifest is missing an assigned submodule, spawn **one** follow-up
batch for just the missing ones.

**If any batch returned a non-empty `=== DISCREPANCIES ===` block**, each
entry is a fact the explorer verified against the source and found wrong in a
root category file. Spawn **one** follow-up `drupal-module-explorer` assigned
to the affected category file(s), passing the disputed point(s) verbatim, to
re-check the source and rewrite the file(s) if confirmed — and resolve this
**before step 5**, so Explorer C grounds itself in corrected files. Never
resolve a dispute by editing a file yourself, and never ignore one silently.

## 5. Spawn Explorer C — the synthesis wave

**Skip this step entirely in a submodules-only completion pass** — the
synthesis files already exist from the root run; go to step 6.

Only after every earlier wave's manifests are collected and files are on disk
(wave 1 and, when it ran, the submodule wave), launch **one** more
`drupal-module-explorer` for the synthesis categories. Use this prompt
template — substitute the real values as before:

> Explore the Drupal module whose source is at the path `<MODULE_ROOT>` (machine name `<module>`, release `<VERSION>`). Cover **only** these categories: **extension-points, ai-integration**. These are synthesis categories — follow your "Synthesis categories (fact grounding)" rules: first read the category files already present in the output directory `<OUTPUT_DIR>` and treat them as your verified fact base; read the module source for the guidance layer and for anything they do not cover. Write one Markdown file per assigned category directly into `<OUTPUT_DIR>`, per your Output Contract — each file starts with its `# …` H1, no metadata header; write nothing anywhere else and never modify the module source. Then return your final message as the `=== MANIFEST ===` block (one JSON entry per file you wrote), plus a `=== DISCREPANCIES ===` block only if you verified that a fact in an existing category file contradicts the source, ending with `=== END ===`. Nothing else.

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
It starts directly with its H1 — no metadata header:

```markdown
# Module: {Human Name} (`{machine_name}`)

## Summary

{2–4 sentence description from key-facts.}

## Key Facts

- **Machine name**: `{machine_name}`
- **Package**: {package}
- **Version**: {VERSION}
- **Dependencies**: {list}
- **Core compatibility**: {Drupal version}

## Analysis Files

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

**Add a `## Submodules` section only when the submodule wave ran.**
It indexes the per-submodule files and, for each, gives a one-line description
of what the submodule adds to the parent — derive that line from the manifest
`description` (do not invent capabilities). Group related submodules under
`###` subheadings when there are many; a flat list is fine for a few. Use
relative links into the `submodules/` folder:

```markdown
## Submodules (extensions to the core module)

Each file documents the groups, plugins, entities, services, routes, hooks, and
config the submodule adds on top of the core module.

- [{Sub Human Name}](submodules/{sub_machine}.md) — {one-line summary of what it adds}.
- …
```

**Root-only scope (or a partial submodule subset)**: add instead (or in
addition) a section listing what was deliberately left out. Names and
directories come **verbatim from the GATE's `SUBMODULE=` lines** — never
invent a description for a submodule that was not documented:

```markdown
## Submodules detected but not documented in this run

This run documented the root module only. Re-run the discover skill with
"only submodules" to complete them.

- `{sub_machine}` (at `{dir}/`)
- …
```

**Submodules-only pass**: update the existing `summary.md` in place — add the
newly documented submodules to the `## Submodules` section (create it if
absent) from the manifest descriptions, remove those entries from the "not
documented" section, and delete that section once it is empty. Leave the rest
of the file untouched.

## 7. Write `metadata.json`

All per-file metadata lives in a single `OUTPUT_DIR/metadata.json` — the doc
files themselves carry none. Assemble it from the gate values and the
explorers' manifests, **copying `category`/`title`/`description` verbatim** —
never invent or rewrite them:

```json
{
  "name": "{machine_name}",
  "human_name": "{Human Name from key-facts}",
  "type": "contrib",
  "version": "{VERSION}",
  "date": {DATE_EPOCH},
  "project": { "…the parsed contents of the PROJECT_INFO file, embedded verbatim…" },
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
**documented** submodule). `date` is the `DATE_EPOCH` from the gate
(Unix epoch seconds).

`project` is the parsed JSON object read from the gate's `PROJECT_INFO` file,
embedded **verbatim** — never retype, trim, or reorder its values (it carries
the Drupal.org facts the site importer maps onto `module_details`: coverage,
statuses, categories, ecosystem, maintainers, creation date). When
`PROJECT_INFO=none`, omit the `project` key entirely.

**Root-only scope (or a partial subset)**: `files` simply carries no entry
for an undocumented submodule. Record the skipped ones instead in a top-level
`submodules_skipped` key — one object per skipped submodule, `name` and `dir`
copied verbatim from the GATE's `SUBMODULE=<name>|<dir>` lines; omit the key
entirely when nothing was skipped:

```json
"submodules_skipped": [
  {"name": "eca_base", "dir": "modules/eca_base"}
]
```

Consumers ignore the extra key; the verifier cross-checks it (a submodule may
never be both skipped and documented).

**Submodules-only pass**: update the existing `metadata.json` in place —
leave every existing top-level value (including `date`) untouched, append the
new submodule `files` entries with `category`/`title`/`description` copied
verbatim from the manifests, remove each newly documented submodule from
`submodules_skipped`, and drop that key entirely once its list is empty.

## 8. Verify and report

Run the bundled verifier — it cross-checks `metadata.json` against the disk
in both directions (all 11 doc files present, listed, and non-empty; no
unlisted files; valid categories; submodule count matching this run's scope), and —
via `--module-root` — validates every `Drupal\<module>\…` class reference in
the docs against the source by PSR-4, so an invented class name fails the
verify:

```bash
python3 "$SKILL_DIR/scripts/verify.py" "$OUTPUT_DIR" --submodules <N> --module-root "$MODULE_ROOT"
```

`--submodules <N>` is the number of submodule doc files that must exist on
disk **after this run**: the GATE's `SUBMODULES` in a full run; `0` in a
root-only run; previously documented + newly documented in a submodules-only
pass. The verifier also cross-checks `submodules_skipped` (shape, and no
overlap with documented submodules) and resolves class references in skipped
submodules' namespaces against the source.

- **`VERIFY OK`** → done.
- **`VERIFY FAILED`** → fix what the `PROBLEM:` lines say: if a file an
  explorer reported is missing (or one was written but not reported), spawn
  one follow-up explorer for just that piece, update `metadata.json`, and
  re-run the verifier. An **unresolvable class reference** PROBLEM means a doc
  names a class that does not exist in the source — treat it like a
  discrepancy: spawn one follow-up explorer for the affected category file to
  correct or remove the reference (never edit the file yourself), then re-run.
  Call out anything still unresolved.

Then report back concisely: the `OUTPUT_DIR` path, the resolved version, the
count of category and submodule files written, and a one-line takeaway about
the module. Do **not** paste the file contents into your reply — the caller
reads the files.
