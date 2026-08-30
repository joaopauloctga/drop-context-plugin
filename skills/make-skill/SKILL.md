---
name: make-skill
description: >-
  Generate a usable agent skill (`dc-{module-name}`) from a documented Drupal
  contrib module. Reads the documentation under
  ~/.drop-context/docs/modules/{module}/{version}/ (produced by
  /drop-context:document-module) and writes a focused SKILL.md plus lazy-loaded
  references/*.md into ~/.drop-context/docs/skills/{module}/{version}/,
  then offers to symlink the skill into the project's agent skills directory
  (.claude/skills, .agents/skills, …). Run after /drop-context:document-module, from
  any directory — the docs and the generated skill both live at a fixed
  user-level location, not inside the Drupal repo.
---

# Make a `dc-{module-name}` skill from a documented module

You are the **generator**. The `/drop-context:document-module` skill has already
produced a structured analysis of the module under
`~/.drop-context/docs/modules/{module}/{version}/` — a single user-level
location, independent of which repo you happen to be standing in (override the
base with `DROP_CONTEXT_HOME`). Your job is to turn that analysis into a
**second-order skill** that other agents will invoke when they need to _use_,
_extend_, _configure_, or _theme_ the module on a live Drupal site.

The output skill must be:

- **Focused.** `SKILL.md` carries only what an agent needs to _get started_
  with the module — orientation, the main usage/extension/theme patterns,
  and a small set of copy-pasteable examples. Deep detail goes into
  `references/*.md` and is loaded lazily.
- **Precise.** Every code/config snippet you write must be derivable from
  the doc set. Do not invent service IDs, hook names, field names,
  template names, or routes. If the docs do not state something, omit it.
- **Versioned.** The generated skill names the exact module version it was
  built against, and each version gets its own storage directory
  (`{module}/{version}`) — versions coexist; re-running the same version
  regenerates it in place. The frontmatter always records the module machine
  name, the version/tag, and when the skill was generated.

Follow the steps in order.

## 1. Resolve the docs root, then the module + version

This skill reads what `/drop-context:document-module` already wrote to
`${DROP_CONTEXT_HOME:-~/.drop-context}/docs/modules/` — a single, fixed
user-level location, the same for every repo, so there is nothing to search
for: honour `DROP_CONTEXT_HOME` when set, else default to `~/.drop-context`.

```bash
DROP_CONTEXT_HOME="${DROP_CONTEXT_HOME:-$HOME/.drop-context}"
DOCS_ROOT="$DROP_CONTEXT_HOME/docs"
```

Inputs: the module **machine name** (required) and optionally a **version** —
a parameter the user can pin in their prompt ("generate the feeds skill for
8.x-3.5"). When no version is given, default to the **newest** documented
version. The only source of truth is what `/drop-context:document-module` already
produced under `$DOCS_ROOT/modules/`:

```bash
MODULE={module_machine_name}
DOCS_BASE="$DOCS_ROOT/modules/$MODULE"
# One line per *valid* documented version — a version dir without a
# metadata.json is the leftover of an aborted document run; ignore it.
ls -1 "$DOCS_BASE"/*/metadata.json 2>/dev/null
```

Each line is a documented version. Resolve `VERSION` from that listing:

- **No directory / no entries** → stop and tell the user that **no generated
  documentation was found** for `{module}` under `$DOCS_ROOT/modules/`, and
  **suggest** running `/drop-context:document-module {module}` — offer to run it for
  them if they want. Never start the document skill yourself unprompted: it spawns
  an explorer team, a cost the user should opt into.
- **The user named a version** → use it if listed. If it is not listed, stop,
  show what is available, and suggest running
  `/drop-context:document-module {module} {version}` for the version they asked for
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
[ -f "$DOCS_DIR/metadata.json" ] || { echo "metadata.json missing in $DOCS_DIR — re-run /drop-context:document-module"; exit 1; }
ls -1 "$DOCS_DIR"
```

### Separately: find the project you're standing in (needed later, step 9 only)

Docs and the generated skill live at the fixed `$DOCS_ROOT` above, independent
of any repo — but step 9 still needs to know **which project** to offer
installing the skill into. Walk up from the current directory looking for an
ordinary project-root marker:

```bash
find_project_root() {
  local dir="$PWD"
  while [ "$dir" != "/" ]; do
    # A bare composer.json is NOT a project marker: a contrib module and
    # web/core each ship their own, so stopping at the first one found while
    # walking up would resolve the "project" to read-only vendor source and
    # offer to write .claude/skills/ inside it. Accept .git, or a
    # composer.json that actually looks like a site/app root — the same
    # discriminator resolve.py uses (lock file beside it, type "project", or
    # installer-paths; never "drupal-scaffold" alone, web/core has that too).
    if [ -d "$dir/.git" ] || [ -f "$dir/composer.lock" ] \
       || grep -qE '"type"[[:space:]]*:[[:space:]]*"project"' "$dir/composer.json" 2>/dev/null \
       || grep -q '"installer-paths"' "$dir/composer.json" 2>/dev/null; then
      echo "$dir"
      return 0
    fi
    dir="$(dirname "$dir")"
  done
  echo "$PWD"   # no marker found — fall back to cwd rather than failing
}
PROJECT_ROOT="$(find_project_root)"
```

This never blocks the run — it only feeds step 9's optional install offer.

### The Composer constraint is derived from `VERSION` — never interpolated raw

A Drupal release tag is **not** a Composer version. Composer normalizes the
legacy core-compat scheme (`8.x-1.6`) to `1.6.0` and rejects the tag itself:
`composer require 'drupal/entity:^8.x-1.6'` fails outright with *Could not
parse version constraint* — a broken install command shipped in a real
generated skill. Derive `COMPOSER_CONSTRAINT` before writing step 1 of the
generated `SKILL.md`, and use it wherever that template says
`{composer_constraint}`:

```bash
case "$VERSION" in
  dev-*|*-dev)  COMPOSER_CONSTRAINT="$VERSION" ;;            # dev branch: verbatim (8.x-1.x-dev, dev-1.0.x)
  [0-9].x-*)    COMPOSER_CONSTRAINT="^${VERSION#*.x-}" ;;    # legacy tag: 8.x-1.6 -> ^1.6
  *)            COMPOSER_CONSTRAINT="^$VERSION" ;;           # semver tag: 3.3.8   -> ^3.3.8
esac
echo "$VERSION -> $COMPOSER_CONSTRAINT"
```

All three branches were checked against Composer's own `VersionParser`:
`^1.6`, `^2.10`, `^1.0-beta3`, `^3.3.8`, `^1.0.0-rc1`, `dev-1.0.x`,
`1.0.x-dev` and `8.x-1.x-dev` all parse; only the raw-interpolated
`^8.x-1.6` shape does not.

## 2. Resolve the output skill directory

Generated skills are always stored under **`$DOCS_ROOT/skills/`** — i.e.
`${DROP_CONTEXT_HOME:-~/.drop-context}/docs/skills/` — **not**
`${DROP_CONTEXT_HOME:-~/.drop-context}/skills/` (no `docs/`), which belongs to
the separate `drop-context` PHP CLI: it already stores CLI-installed skills
there directly under `~/.drop-context/` (`dc-flag`, `dc-views`, …), alongside
its own `app.json`/`cache/`/`agents/`. The `docs/` level is the **only** thing
keeping this pipeline's generated skills from colliding with the CLI's own
`skills/` directory — do not flatten it away. This exact path is the single
place that name is written in this skill — if it ever needs to change, this is
the one line to edit. One directory per module **and** version, nested as
`{module}/{version}` (the module's real machine name, underscores intact).
Also compute the **skill name** and stamp the generation time now — both go
into the frontmatter in step 6:

```bash
GENERATED_SKILLS_ROOT="$DOCS_ROOT/skills"   # the one place this path is defined
SKILL_BASE="dc-$(printf '%s' "$MODULE" | tr '_' '-')"
TAG_SLUG="$(printf '%s' "$VERSION" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9' '-' | sed 's/--*/-/g; s/^-//; s/-$//')"
# Was a DIFFERENT version of this module's skill already generated?
OTHER_VERSIONS="$(ls -1 "$GENERATED_SKILLS_ROOT/$MODULE" 2>/dev/null | grep -vx "$VERSION")"
if [ -n "$OTHER_VERSIONS" ]; then
  SKILL_NAME="${SKILL_BASE}-${TAG_SLUG}"   # e.g. dc-feeds-8-x-3-5
else
  SKILL_NAME="$SKILL_BASE"                 # e.g. dc-feeds
fi
SKILL_OUT="$GENERATED_SKILLS_ROOT/${MODULE}/${VERSION}"
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

## 3. Read `metadata.json` + the doc set

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
doc set file is empty, missing, or trivially short** (< ~10 useful
lines) — a stub reference is worse than no reference, because it wastes
the loading agent's attention.

| Reference file              | Built primarily from                                 | Emit when                                                                      |
| --------------------------- | ---------------------------------------------------- | ------------------------------------------------------------------------------ |
| `references/use.md`         | `ai-integration.md` + `summary.md`                   | Always (this is the agent's entry point for _using_ the module on a site).     |
| `references/configure.md`   | `configuration.md` + `permissions.md` + `routes.md`  | Module exposes config objects, admin UI, or permissions worth knowing.         |
| `references/extend.md`      | `extension-points.md` + `hooks.md` + `services.md`   | Module exposes alter hooks, service decoration points, or plugin types.        |
| `references/theme.md`       | `extension-points.md` (theme/template content)       | Module defines theme hooks, template suggestions, or preprocess layers.        |
| `references/entity.md`      | `entities.md`                                        | Module defines its **own** content or config entity types: base-field names, entity keys, getter/setter names, bundle/config-entity properties, custom storage/handler APIs. |
| `references/fields.md`      | `entities.md` + `extension-points.md`                | Module adds fields, pseudo-fields, or Field UI alterations to **other** entity types (not its own — those go in `entity.md`). |
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
doc set content clearly justifies them (e.g. a dedicated `views.md` for
a module with significant Views integration). Naming convention:
`lowercase-with-hyphens.md`.

## 5. Write `references/*.md` — one topic at a time, precise

For each reference you decided to emit:

1. **Lift from the doc set, don't summarize them away.** Tables,
   service IDs, hook names, and exact strings from doc set content must
   appear verbatim in the reference.
2. **Add at least one concrete, runnable example** at the top of the
   file — a Twig snippet, a `services.yml` block, a hook implementation,
   a config YAML, a `\Drupal::service(...)` call. The example must be
   grounded in identifiers that appear in the doc set.
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
doc set. Show the file path and the full snippet.}

## {Subsections covering the topic in depth}

{Lifted/condensed content from the relevant doc set file(s), preserving
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
   doc set names a primary use case (almost always present in
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
`SKILL.md`, substituting `{module}` and `{composer_constraint}` — the
constraint derived in step 1, never the raw version):

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
composer require 'drupal/{module}:{composer_constraint}'   # skip if already in composer.lock
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
  generated_from: ~/.drop-context/docs/modules/{module}/{version}/
---
```

Every `metadata` field above is **mandatory** in every generated skill:
`module` (machine name), `version` (the exact tag the skill was built
against), `generated_at` (the `GEN_DATE` from step 2), and
`generated_from`. Never omit or rename them — downstream tooling matches
skills to docs and releases by these keys.

Do **not** paste the full doc set content into `SKILL.md`. Every section
in `SKILL.md` should either fit on a screen or point at a reference file.

## 7. Examples — grounded, not invented

Across `SKILL.md` and the references, every code/config example must use
identifiers (service IDs, hook names, field names, template names, route
names, config keys, permission strings) that appear in the doc set. When in doubt, prefer copying the example shape from
`ai-integration.md` and substituting only what the doc set content
supports.

If the doc set does not contain enough detail to write a concrete
example for a topic, **say so explicitly** in the reference (e.g. "The
module does not ship sample config; see Drupal core's `field.field.*`
documentation for the surrounding config schema") rather than fabricate
an example. Wrong examples are worse than missing ones.

Two rules that make step 8's grounding check work for you:

- **Write identifiers exactly as the docs spell them** — full FQCNs
  (`Drupal\{module}\…`), exact hook names, exact service/route/config IDs.
  The verifier greps the doc set for every identifier you use; a
  paraphrased, abbreviated, or re-assembled identifier fails the check
  even when your intent was right.
- **Carry hedges forward.** When a doc set file qualifies a fact —
  "declared but not invoked in this release", "not verified" — the
  generated skill must keep that qualifier next to the fact (or drop the
  fact entirely). Never promote a hedged fact into working guidance: the
  document pipeline hedged it because the source did not support more.
- **Never invent the body of a file the docs only describe.** A Twig
  template, a JS behavior, a config fixture: if the doc set lists its
  variables or keys but do not quote its content, do not write a
  "minimal" version of it — the parts the docs did not mention (a wrapper
  element a JS selector targets, a library attach, a fallback branch) are
  exactly what a from-scratch rewrite drops. Instead tell the agent to
  copy the module's own file (name its path, e.g. `templates/flag.html.twig`)
  into the theme/module and edit from there, and list what the docs say it
  must keep.
- **The consumer has only this skill — never point it at the doc
  set.** The agent that loads `dc-*` cannot open `~/.drop-context/docs/`; a
  sentence like "see the doc set's Entities category for those" or
  "full catalog in `hooks.md`" is a dead end. Either restate the needed
  fact in the reference (that is what `references/entity.md` and friends
  are for) or omit it. When a hedge is needed, phrase it without the
  pipeline ("the module's own schema does not enumerate these keys"), not
  "the doc set does not say".
- **YAML/config examples are documents, not prose.** A concrete example
  must parse (one key per mapping — a duplicated `events:` or `actions:`
  is rejected on import), follow the entity's documented shape, and take
  **every** key and value from the doc set: the schema mapping, an
  exported fixture, or a documented enum value. Never guess a value's type
  (`severity: "info"` for an integer field), invent an enum member
  (`mode: set` when the documented values are `set:clear` / `set:force_clear`
  …), or choose a format the docs never state. If the docs do not enumerate
  a plugin's configuration keys, say so in one line next to the example
  ("configuration keys not enumerated in the docs") instead of filling
  them in.
- **No batch-relative sentences in `references/submodules*.md`.** The
  generator reads submodules in groups; "the only one of these four
  submodules with an extra dependency" or "all three submodules in this
  group compute access directly" are true of the batch, not the module, and
  the consumer has no batch to relate them to. State each submodule's facts
  on their own; never generalise one submodule's default across its
  siblings unless every sibling's doc says the same.

## 8. Verify — run the bundled checker

The verifier lives in `scripts/` next to this SKILL.md — resolve `SKILL_DIR`
to the **absolute path of the directory containing this SKILL.md** (you know
it from where this skill was loaded); never assume a fixed project-relative
location. It is standard-library-only Python: any `python3` works, nothing
to install.

```bash
SKILL_DIR="<absolute path of the directory containing this SKILL.md>"
python3 "$SKILL_DIR/scripts/verify.py" "$SKILL_OUT" --docs-dir "$DOCS_DIR" --name "$SKILL_NAME"
```

It checks **structure** — frontmatter (`name` equals `$SKILL_NAME`,
kebab-case `dc-*`; every mandatory `metadata` key present and matching the
docs' `metadata.json` module/version/type), the mandatory verify-installed
section, the reference routing table vs `references/` on disk in both
directions, sibling cross-links, no empty or stub files, the SKILL.md line
caps, and leftover `{placeholder}` tokens — and **grounding**: every
`Drupal\{module}\…` FQCN and every module-named `hook_*` you wrote must
appear verbatim in the doc set; module-prefixed dotted identifiers
(service IDs, route names, config keys) missing from the docs come back as
warnings. It also enforces the **consumer contract** and the **example
rules** from step 7: a sentence that points the reader at the doc set
("see the doc set's Entities category", a bare `hooks.md` with no such
sibling reference) is a PROBLEM, any other mention of the doc set a
WARNING; every ```yaml fence is parsed — a duplicate key in one mapping is
a PROBLEM, a line the subset reader cannot parse a WARNING, and an
identifier-like value (`bef_links`, `set:clear`) that occurs nowhere in the
doc set a WARNING (an invented enum value or guessed id, unless it is
your own example's `id`/`label`/field name — those are skipped);
batch-relative phrases in `references/submodules*.md` are WARNINGs.

- **`VERIFY OK`** → continue to step 9.
- **`PROBLEM:` lines** → each one is a defect in what you wrote; fix it in
  the generated skill and re-run until `VERIFY OK`. For a grounding
  problem, re-open the relevant doc set file, find the identifier the docs
  actually use, and correct the skill — and if the docs simply do not
  contain it, **delete the claim** (step 7: wrong examples are worse than
  missing ones). Never resolve a grounding problem by editing the doc
  set — they are the fact base, owned by the document pipeline.
- **`WARNING:` lines** → judgment calls the script cannot make. Re-check
  each flagged identifier against the docs: fix real mistakes; if you keep
  one, say so in your final report with the doc line that justifies it.

The script cannot judge prose. Before moving on, re-read two things
yourself: the frontmatter `description` (other agents select this skill by
that sentence alone — does it name the module and the concrete tasks?), and
the **"Step 1 — Verify … is installed"** placement (it must come before the
80%-path example, with the stop-and-ask-the-user instruction intact).

## 9. Offer to symlink into the project's agent skills directory

The skill now lives in `$SKILL_OUT` (under `~/.drop-context/docs/skills/`) —
but agents only load it from a project's skills directory. Check whether
`$PROJECT_ROOT` (resolved in step 1) has one:

```bash
for d in .claude/skills .agents/skills .cursor/skills .codex/skills; do
  [ -d "$PROJECT_ROOT/$d" ] && echo "found: $PROJECT_ROOT/$d"
done
```

- **None found** → skip the question; just tell the user where the skill is
  stored and that it can be installed into a project later.
- **One or more found** → **ask the user** whether to link `{SKILL_NAME}`
  there (in Claude Code, use the AskUserQuestion tool; when several agent
  dirs exist, let them pick which — or all). On yes, create an **absolute**
  symlink named after the **skill name** (not the versioned storage path —
  the link name must equal the frontmatter `name`). It must be absolute, not
  relative: `$SKILL_OUT` now lives under `~/.drop-context/docs/skills/`,
  entirely outside the project, so a path relative to the agent skills
  directory would not resolve:

```bash
AGENT_SKILLS_DIR="$PROJECT_ROOT/.claude/skills"   # the dir the user picked
TARGET="$AGENT_SKILLS_DIR/$SKILL_NAME"
SOURCE="$SKILL_OUT"   # absolute path — see note above; never relativize this

if [ -L "$TARGET" ]; then
  # Already a symlink — almost certainly ours from a previous generation.
  # Refresh it unconditionally: regenerating a skill should update what
  # agents load without a separate reinstall step.
  rm "$TARGET"
  ln -s "$SOURCE" "$TARGET"
elif [ -e "$TARGET" ]; then
  # A REAL directory/file already sits there — never overwrite silently.
  echo "$TARGET already exists and is not a symlink — ask the user before touching it"
else
  ln -s "$SOURCE" "$TARGET"
fi
ls -la "$TARGET"
```

If `$TARGET` exists as a real directory (not a symlink), stop and ask the
user how to proceed (overwrite, skip, or pick a different name) — never
delete or replace a real directory unprompted.

If the agent skills dir already contains a skill (real or symlinked) for the
**same module at another version** (check `metadata.module` in the existing
skill's SKILL.md — the names may differ because of the version suffix), point
that out and ask whether to keep both (they coexist fine — the names differ)
or remove the old link (an upgrade).

Then report back concisely: the `$SKILL_OUT` storage path, the list of files
written, where it was linked (if anywhere), and a one-line description of
the _capability_ the new skill unlocks for other agents (e.g.
"dc-menu-item-extras: build, render, and extend per-menu bundled
`menu_link_content` with custom fields and per-item view modes"). Do **not**
paste the generated SKILL.md or references into your reply — the caller can
read them.
