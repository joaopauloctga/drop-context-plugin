---
name: generate-module-skill
description: >-
  Generate a usable agent skill (`dc-{module-name}`) from a discovered Drupal
  contrib module. Reads the documentation under
  ~/.drupal-context/modules/{module}/{version}/ (produced by
  discover-drupal-module) and writes a focused SKILL.md plus lazy-loaded
  references/*.md into ~/.drupal-context/skills/{module}/{version}/, then
  offers to install the skill into the project's agent skills directory
  (.claude/skills, .agents/skills, …). Run after discover-drupal-module. Works
  from any directory — no Drupal project or composer.lock required.
tools: read, edit/createDirectory, edit/createFile, edit/editFiles, edit/rename, search
---

# Generate a `dc-{module-name}` skill from a discovered module

You are the **generator**. The `discover-drupal-module` skill has already
produced a structured analysis of the module under
`~/.drupal-context/modules/{module}/{version}/`. Your job is to turn that
analysis into a **second-order skill** that other agents will invoke when they
need to _use_, _extend_, _configure_, or _theme_ the module on a live Drupal
site.

The output skill must be:

- **Focused.** `SKILL.md` carries only what an agent needs to _get started_
  with the module — orientation, the main usage/extension/theme patterns,
  and a small set of copy-pasteable examples. Deep detail goes into
  `references/*.md` and is loaded lazily.
- **Precise.** Every code/config snippet you write must be derivable from
  the discover docs. Do not invent service IDs, hook names, field names,
  template names, or routes. If the docs do not state something, omit it.
- **Versioned.** The generated skill names the exact module version it was
  built against, and each version gets its own storage directory
  (`{module}/{version}`) — versions coexist; re-running the same version
  regenerates it in place. The frontmatter always records the module machine
  name, the version/tag, and when the skill was generated.

Follow the steps in order.

## 1. Resolve module + version

Inputs: the module **machine name** (required) and optionally a **version** —
a parameter the user can pin in their prompt ("generate the feeds skill for
8.x-3.5"). When no version is given, default to the **newest** discovered
version. No Drupal project is needed — the only source of truth is what
`discover-drupal-module` already produced under `~/.drupal-context/`:

```bash
MODULE={module_machine_name}
DOCS_BASE="$HOME/.drupal-context/modules/$MODULE"
# One line per *valid* discovered version — a version dir without a
# metadata.json is the leftover of an aborted discover run; ignore it.
ls -1 "$DOCS_BASE"/*/metadata.json 2>/dev/null
```

Each line is a discovered version. Resolve `VERSION` from that listing:

- **No directory / no entries** → stop and tell the user that **no generated
  documentation was found** for `{module}` under `~/.drupal-context/modules/`,
  and **suggest** running `discover-drupal-module {module}` — offer to run it
  for them if they want. Never start the discover yourself unprompted: it
  downloads source and spawns an explorer team, a cost the user should opt
  into.
- **The user named a version** → use it if listed. If it is not listed, stop,
  show what is available, and suggest running
  `discover-drupal-module {module} {version}` for the version they asked for
  (offer to run it — never start it unprompted).
- **Exactly one entry** → use it.
- **Multiple entries, no version given** → pick the **newest** version.
  Order version-aware: modern semver tags (`3.0.4`) are newer than legacy
  core-compat tags (`8.x-1.17`) regardless of what `sort -V` says; within the
  same scheme, highest wins. State in your final report which version you
  picked and which others are available, so the user can re-run pinned to a
  different one.

Then verify the docs are actually there:

```bash
VERSION={chosen}
DOCS_DIR="$DOCS_BASE/$VERSION"
[ -f "$DOCS_DIR/metadata.json" ] || { echo "metadata.json missing in $DOCS_DIR — re-run discover-drupal-module"; exit 1; }
ls -1 "$DOCS_DIR"
```

## 2. Resolve the output skill directory

Generated skills are always stored under `~/.drupal-context/skills/`, one
directory per module **and** version, nested as `{module}/{version}` (the
module's real machine name, underscores intact). Also compute the **skill
name** and stamp the generation time now — both go into the frontmatter in
step 6:

```bash
SKILL_BASE="dc-$(printf '%s' "$MODULE" | tr '_' '-')"
TAG_SLUG="$(printf '%s' "$VERSION" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9' '-' | sed 's/--*/-/g; s/^-//; s/-$//')"
# Was a DIFFERENT version of this module's skill already generated?
OTHER_VERSIONS="$(ls -1 "$HOME/.drupal-context/skills/$MODULE" 2>/dev/null | grep -vx "$VERSION")"
if [ -n "$OTHER_VERSIONS" ]; then
  SKILL_NAME="${SKILL_BASE}-${TAG_SLUG}"   # e.g. dc-feeds-8-x-3-5
else
  SKILL_NAME="$SKILL_BASE"                 # e.g. dc-feeds
fi
SKILL_OUT="$HOME/.drupal-context/skills/${MODULE}/${VERSION}"
mkdir -p "$SKILL_OUT/references"
GEN_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "SKILL_NAME=$SKILL_NAME"
```

**Skill naming rule.** The name is `dc-` (Drupal Context) + the module machine
name with underscores turned into hyphens (`menu_item_extras` →
`dc-menu-item-extras`). Skill names must be kebab-case — the agentskills.io
spec and Claude Code accept only `[a-z0-9-]`, so `.` and `:` are invalid (and
`:` would collide with Claude Code's `plugin:skill` syntax) — and the name
must match the directory the skill is installed into. The conversion is safe
because Drupal machine names never contain hyphens; the **authoritative
machine name always lives in `metadata.module`** — downstream tools read it
from there, never by un-parsing the skill name.

**Version-suffix rule.** The first version generated for a module keeps the
plain conventional name (`dc-feeds`). When the user later generates the same
module at a **different** version (older or newer), that skill's name gets the
tag appended — `{SKILL_BASE}-{TAG_SLUG}` (e.g. `dc-feeds-8-x-3-5`,
`dc-feeds-3-0-4`) — so the two skills stay distinguishable by name and can be
installed side by side. The tag is slugified into kebab-case (lowercase,
every run of non-`[a-z0-9]` chars becomes one `-`) because dots are invalid
in skill names; the exact tag stays readable in `metadata.version`.

If the directory already exists, overwrite it freely — it is regenerable
output of this skill, and the versioned name means you are never clobbering a
different version's skill.

## 3. Read `metadata.json` + the discover docs

Read `DOCS_DIR/metadata.json` **first** — it gives you the module's
`human_name`, `version`, and the authoritative `files` list (each with its
`category`, `title`, `description`). Use that list to know exactly which doc
files exist; never fabricate content for an absent file.

Then read the docs it lists (they are pure Markdown starting at the H1):

`summary.md`, `entities.md`, `plugins.md`, `services.md`,
`configuration.md`, `permissions.md`, `routes.md`, `hooks.md`,
`events.md`, `extension-points.md`, `ai-integration.md` — **and every
`submodules/*.md`** listed in the manifest, when the module ships submodules.

`ai-integration.md` is the highest-signal source for _how to use_ the
module — it contains the core usage patterns plus non-obvious gotchas
discovered while reading the source. Lean on it heavily when writing
`SKILL.md`.

`extension-points.md`, `hooks.md`, `services.md`, and `plugins.md` are
the highest-signal sources for _how to extend_ the module.

## 4. Decide which reference files to emit

The reference files are **lazy-loaded**: an agent reads them only when
the orientation in `SKILL.md` tells them to. Emit one reference per
topic that is non-trivial _for this specific module_. Use the table
below as your default mapping, but **skip a reference whose source
discover file is empty, missing, or trivially short** (< ~10 useful
lines) — a stub reference is worse than no reference, because it wastes
the loading agent's attention.

| Reference file              | Built primarily from                                 | Emit when                                                                      |
| --------------------------- | ---------------------------------------------------- | ------------------------------------------------------------------------------ |
| `references/use.md`         | `ai-integration.md` + `summary.md`                   | Always (this is the agent's entry point for _using_ the module on a site).     |
| `references/configure.md`   | `configuration.md` + `permissions.md` + `routes.md`  | Module exposes config objects, admin UI, or permissions worth knowing.         |
| `references/extend.md`      | `extension-points.md` + `hooks.md` + `services.md`   | Module exposes alter hooks, service decoration points, or plugin types.        |
| `references/theme.md`       | `extension-points.md` (theme/template content)       | Module defines theme hooks, template suggestions, or preprocess layers.        |
| `references/fields.md`      | `entities.md` + `extension-points.md`                | Module adds fields, pseudo-fields, or alters Field UI on an entity type.       |
| `references/events.md`      | `events.md`                                          | Module dispatches custom events or subscribes to events worth overriding.      |
| `references/plugins.md`     | `plugins.md`                                         | Module defines a plugin type or ships notable plugin implementations.          |
| `references/services.md`    | `services.md` + `extension-points.md`                | Module ships injectable services with a public interface.                      |
| `references/permissions.md` | `permissions.md`                                     | Module defines permissions that custom code should check or grant.             |
| `references/routes.md`      | `routes.md`                                          | Module defines admin or front-end routes that agents need to link to or alter. |
| `references/submodules.md`  | `submodules/*.md`                                    | Module ships submodules: what each adds and when to enable it.                 |

For `references/submodules.md`, condense — one section per submodule with
what it adds, its dependencies, and the key plugins/config it contributes;
point the agent at enabling it (`drush pm:enable`) when the task needs that
capability. Skip deprecated/stub submodules or mark them as such.

You may add module-specific references not in this table when the
discover content clearly justifies them (e.g. a dedicated `views.md` for
a module with significant Views integration). Naming convention:
`lowercase-with-hyphens.md`.

## 5. Write `references/*.md` — one topic at a time, precise

For each reference you decided to emit:

1. **Lift from the discover docs, don't summarize them away.** Tables,
   service IDs, hook names, and exact strings from discover content must
   appear verbatim in the reference.
2. **Add at least one concrete, runnable example** at the top of the
   file — a Twig snippet, a `services.yml` block, a hook implementation,
   a config YAML, a `\Drupal::service(...)` call. The example must be
   grounded in identifiers that appear in the discover docs.
3. **Open with a one-line "When to load this file" hint** so the agent
   reading `SKILL.md` knows whether this reference is what they need.
4. **Cross-link with relative paths** when one reference points at
   another (e.g. `references/extend.md` may say "see [services.md](services.md)").
5. Keep each reference self-contained — do not require the agent to also
   load `SKILL.md` to make sense of it.

Reference file template:

```markdown
# dc-{module-name} — {topic title}

> Load this file when {one-line trigger, e.g. "you need to render a menu
> item's custom fields in a Twig template"}.

## Concrete example

{Minimum-viable working example, grounded in real identifiers from the
discover docs. Show the file path and the full snippet.}

## {Subsections covering the topic in depth}

{Lifted/condensed content from the relevant discover doc(s), preserving
exact identifiers, signatures, and tables.}

## Gotchas

{Pull relevant gotchas from `ai-integration.md` that apply to this topic.
Omit the section if none apply.}
```

## 6. Write `SKILL.md` — the orientation layer

`SKILL.md` is loaded into the agent's context **every time** the skill is
invoked, so it must stay small and high-signal. Aim for ~150–300 lines
(hard cap: 500). It must contain, in this order:

1. YAML frontmatter — see template below.
2. A 2–4 sentence summary of what the module does (lift from
   `summary.md` + the mental model in `ai-integration.md`).
3. **Key facts table** — machine name, version, package, dependencies,
   core compatibility.
4. **When to use this skill** — 3–6 bullet points naming the concrete
   _agent tasks_ this skill helps with ("build a menu with custom
   fields", "render a menu item via a custom view mode", "decorate the
   menu link tree handler"). Phrase each bullet as a task an agent
   might be assigned.
5. **Verify the module is installed** — a short, mandatory section placed
   immediately after "When to use this skill" and **before** any usage
   example. It makes the consuming agent confirm `{module}` is enabled on
   the target site _before_ it touches anything. Every pattern in a
   generated skill is useless (or actively misleading) when the module is
   not installed, so this guard is required in **every** generated
   `SKILL.md`. Copy the template in the "Verify-installed section template"
   block below, substituting the module machine name and the resolved
   version. Never omit this section.
6. **Use the module (the 80% path)** — one short copy-pasteable example
   for the single most common usage of the module on a site. If the
   discover docs name a primary use case (almost always present in
   `ai-integration.md`), use that.
7. **Lazy-loaded references** — a bulleted list of the
   `references/*.md` files you emitted in step 5, each with a one-line
   "load when…" hint. This is the **routing table** the agent uses to
   decide what to read next.
8. **Critical gotchas** — at most 3–5 bullets pulled from
   `ai-integration.md` that an agent will hit _early_ (cache,
   install/uninstall ordering, bundle/menu-name coupling, base-field vs
   config-field, etc.). The rest of the gotchas live inside the relevant
   reference file.

**Verify-installed section template** (paste into every generated
`SKILL.md`, substituting `{module}` and `{version}`):

````markdown
## Step 1 — Verify `{module}` is installed (do this first)

Before using anything below, confirm the module is enabled on the target site:

```bash
drush php:eval "print \Drupal::moduleHandler()->moduleExists('{module}') ? 'ENABLED' : 'NOT-INSTALLED';"
```

If this prints **`NOT-INSTALLED`**, stop — do **not** run any of the steps
below. The module must be installed first. Ask the user how to proceed, e.g.:

> `{module}` is not installed on this site. I can install it for you, or you
> can install it yourself. How would you like to proceed?

If the user asks **you** to install it:

```bash
composer require 'drupal/{module}:^{version}'   # skip if already in composer.lock
drush pm:enable {module} -y                     # add submodules you need
drush cache:rebuild
```

Re-run the verify command and confirm it prints `ENABLED` before continuing.
````

`SKILL.md` frontmatter template:

```yaml
---
name: {SKILL_NAME}
description: >-
  {What the module does + the kinds of tasks this skill unblocks, in the
  third person, ending with concrete triggers — "Use when asked to {task},
  {task}, or {task}". Other agents pick skills by this sentence alone, so
  name the *capabilities* and the module's machine + human name, not just
  the topic.}
metadata:
  module: {module_machine_name}
  version: {version}
  skill_type: contrib_module
  generated_at: {GEN_DATE}
  generated_from: ~/.drupal-context/modules/{module}/{version}/
---
```

Every `metadata` field above is **mandatory** in every generated skill:
`module` (machine name), `version` (the exact tag the skill was built
against), `generated_at` (the `GEN_DATE` from step 2), and
`generated_from`. Never omit or rename them — downstream tooling matches
skills to docs and releases by these keys.

Do **not** paste the full discover content into `SKILL.md`. Every section
in `SKILL.md` should either fit on a screen or point at a reference file.

## 7. Examples — grounded, not invented

Across `SKILL.md` and the references, every code/config example must use
identifiers (service IDs, hook names, field names, template names, route
names, config keys, permission strings) that appear in the discover
docs. When in doubt, prefer copying the example shape from
`ai-integration.md` and substituting only what the discover content
supports.

If the discover docs do not contain enough detail to write a concrete
example for a topic, **say so explicitly** in the reference (e.g. "The
module does not ship sample config; see Drupal core's `field.field.*`
documentation for the surrounding config schema") rather than fabricate
an example. Wrong examples are worse than missing ones.

## 8. Verify

```bash
ls -1 "$SKILL_OUT"
ls -1 "$SKILL_OUT/references"
wc -l "$SKILL_OUT/SKILL.md" "$SKILL_OUT/references/"*.md
```

Confirm:

- `SKILL.md` exists, has the correct frontmatter (`name` equals
  `$SKILL_NAME` — kebab-case, `dc-` prefix — and `metadata` carries all
  mandatory keys: `module` with the real machine name, `version` matching
  `$VERSION`, `generated_at` matching `$GEN_DATE`, `generated_from`), and is
  under ~300 lines.
- `SKILL.md` contains the **"Step 1 — Verify … is installed"** section,
  placed before the 80%-path example, with the `moduleExists` check and the
  stop-and-ask-the-user instruction. This section is mandatory.
- Every reference listed in `SKILL.md` §"Lazy-loaded references" exists
  on disk under `references/`, and vice versa — no dangling links, no
  orphan files.
- No reference file is empty or a near-empty stub.

## 9. Offer to install into the project's agent skills directory

The skill now lives in `~/.drupal-context/skills/` — but agents only load it
from a project's skills directory. Check whether the **current working
directory** has one:

```bash
ls -d .claude/skills .agents/skills .cursor/skills .codex/skills 2>/dev/null
```

- **None found** → skip the question; just tell the user where the skill is
  stored and that it can be installed into a project later.
- **One or more found** → **ask the user** whether to install
  `{SKILL_NAME}` there (in Claude Code, use the AskUserQuestion tool; when
  several agent dirs exist, let them pick which — or all). On yes, copy the
  skill under its **skill name** (not the versioned storage path — the
  installed directory name must equal the frontmatter `name`):

```bash
TARGET={agent_skills_dir}/$SKILL_NAME
rm -rf "$TARGET"
cp -R "$SKILL_OUT" "$TARGET"
ls -1 "$TARGET"
```

If the agent skills dir already contains a skill for the **same module at
another version** (check `metadata.module` in the existing skills' SKILL.md —
the names may differ because of the version suffix), point that out and ask
whether to keep both (they coexist fine — the names differ) or remove the old
one (an upgrade).

Then report back concisely: the `$SKILL_OUT` storage path, the list of files
written, where it was installed (if anywhere), and a one-line description of
the _capability_ the new skill unlocks for other agents (e.g.
"dc-menu-item-extras: build, render, and extend per-menu bundled
`menu_link_content` with custom fields and per-item view modes"). Do **not**
paste the generated SKILL.md or references into your reply — the caller can
read them.
