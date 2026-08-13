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
  write the category files directly.
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

Inputs: a module **machine name** (required, e.g. `webform`) and an optional
**version** (a release tag like `6.3.2`, or a branch). If the version is
omitted, the bundled script resolves the **latest stable** tag.

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
DATE_EPOCH=<unix epoch seconds — used for metadata.json in step 5>
SUBMODULE=<machine name>|<dir relative to MODULE_ROOT>   (one line per submodule)
SUBMODULES=<count>
```

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

## 2. Spawn the explorer team — in parallel

**Only reach this step if the GATE in step 1 printed `GATE OK`.** If you do not
have a verified `MODULE_ROOT`, go back — do not spawn.

Launch **three** `drupal-module-explorer` subagents (**or four — add Explorer D
when the GATE found submodules**, i.e. `SUBMODULES` > 0) **in a single batch so
they run concurrently**, each assigned a disjoint set of categories. Give every
explorer the same `MODULE_ROOT` and `OUTPUT_DIR`, the machine name, and the
version; assign work as below.

- **Claude Code**: make three (or four) `Task` (Agent) calls with
  `subagent_type: drupal-module-explorer` in one turn.

Use this prompt template for each category explorer (A/B/C) — **substitute the
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
| **C — extension**   | `extension-points`, `ai-integration`                  |
| **D — submodules**  | `submodules` task (**only if `SUBMODULES` > 0**)      |

(Explorer C reads the same source as B to write high-fidelity extension
guidance; the overlapping reads are intentional, the price of parallelism.)

**Explorer D** runs the dedicated `submodules` task: it writes one condensed
`submodules/<sub_machine>.md` file per submodule. Pass it the full list of
submodules you recorded in the GATE (each submodule's machine name + its
directory). Use this prompt template:

> Explore the submodules of the Drupal module whose source is at the path `<MODULE_ROOT>` (parent machine name `<module>`, release `<VERSION>`). Run the **submodules task**: for each submodule below, read that submodule's own subdirectory (plus targeted parent-module lookups for symbols the submodule references but does not define, per your `submodules` catalog entry) and write one condensed file `<OUTPUT_DIR>/submodules/<sub_machine>.md` (per that catalog entry and your Output Contract — each file starts with its H1, no metadata header; write nothing anywhere else). The submodules are: `<sub_machine_1>` at `<dir_1>`, `<sub_machine_2>` at `<dir_2>`, … Then return your final message as the `=== MANIFEST ===` block (one JSON entry per submodule file), ending with `=== END ===`. Nothing else.

## 3. Collect the manifests

Each explorer's final message is a `=== MANIFEST ===` block holding a JSON
array — one entry per file it wrote, with `file`, `category`, `title`, and
`description` keys (submodule entries also carry `submodule`) — and, for
Explorer A only, a `=== KEY-FACTS ===` block with the inline fact sheet.
Parse the JSON arrays and keep the key-facts text.

If any explorer returned an `=== ERROR ===` block instead, report it and stop —
do not fabricate the missing categories. If an explorer's manifest is missing
some assigned category (or a submodule), spawn **one** follow-up explorer for
just the missing pieces before giving up.

## 4. Build `summary.md` yourself

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

**Add a `## Submodules` section only when Explorer D ran (`SUBMODULES` > 0).**
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

## 5. Write `metadata.json`

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
(Unix epoch seconds).

## 6. Verify and report

Run the bundled verifier — it cross-checks `metadata.json` against the disk
in both directions (all 11 doc files present, listed, and non-empty; no
unlisted files; valid categories; submodule count matching the GATE):

```bash
python3 "$SKILL_DIR/scripts/verify.py" "$OUTPUT_DIR" --submodules <SUBMODULES>
```

- **`VERIFY OK`** → done.
- **`VERIFY FAILED`** → fix what the `PROBLEM:` lines say: if a file an
  explorer reported is missing (or one was written but not reported), spawn
  one follow-up explorer for just that piece, update `metadata.json`, and
  re-run the verifier. Call out anything still unresolved.

Then report back concisely: the `OUTPUT_DIR` path, the resolved version, the
count of category and submodule files written, and a one-line takeaway about
the module. Do **not** paste the file contents into your reply — the caller
reads the files.
