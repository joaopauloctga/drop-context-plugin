---
name: generate-core-module-skill
description: >-
  Generate a usable agent skill (`dc-{module-name}`) from a discovered Drupal
  *core* module (e.g. views, node, field). Reads the documentation under
  ~/.drupal-context/core/{version}/{module}/ (produced by
  discover-drupal-core-module) and writes a focused SKILL.md plus lazy-loaded
  references/*.md into ~/.drupal-context/skills/{module}/{version}/, then
  offers to install the skill into the project's agent skills directory.
  Requires the generate-module-skill skill installed alongside (this variant
  only overrides version resolution and the verify-installed template). Run
  after discover-drupal-core-module. Works from any directory — no Drupal
  project or composer.lock required.
tools: read, edit/createDirectory, edit/createFile, edit/editFiles, edit/rename, search
---

# Generate a `dc-{module-name}` skill from a discovered **core** module

This is the **core-module variant** of `generate-module-skill`. The generation
logic is identical to that skill — the only differences are **how the version
and docs directory are resolved** (core module docs live under
`~/.drupal-context/core/{version}/{module}/`, keyed by the *core* version) and
the **"verify installed" snippet** in the generated `SKILL.md` (core modules
ship with Drupal and are enabled with `drush`, never
`composer require drupal/{module}`).

So: **follow `generate-module-skill`'s SKILL.md for steps 3–9** (read
metadata.json + the docs, decide references, write `references/*.md`, write
`SKILL.md`, ground the examples, verify, offer to install) **exactly as
written**, with the overrides below substituted for that skill's steps 1, 2,
and its "Verify-installed section template". Its SKILL.md is installed as a
sibling of this one — read it at `../generate-module-skill/SKILL.md` relative
to this file.

Do not re-implement the generation logic here — read the original skill and
apply its steps 3–9 verbatim. Keeping this variant thin is intentional.

## Override for Step 1 — Resolve core module + version

Inputs: the core module **machine name** (required, e.g. `views`) and
optionally a **core version** (e.g. `11.2.2`) — a parameter the user can pin
in their prompt. When no version is given, default to the **newest**
discovered core version. No Drupal project is needed — the only source of
truth is what `discover-drupal-core-module` already produced (note the
`core/{version}/{module}` order — the inverse of the contrib layout):

```bash
MODULE={module_machine_name}
# One line per *valid* discovered core version — a version dir without a
# metadata.json is the leftover of an aborted discover run; ignore it.
ls -1 "$HOME/.drupal-context/core"/*/"$MODULE"/metadata.json 2>/dev/null
```

Each match is one discovered core version of this module. Resolve `VERSION`
(the middle path component) from that listing:

- **No matches** → stop and tell the user that **no generated documentation
  was found** for `{module}` under `~/.drupal-context/core/`, and **suggest**
  running `discover-drupal-core-module {module}` — offer to run it for them
  if they want. Never start the discover yourself unprompted: it downloads
  source and spawns an explorer team, a cost the user should opt into.
- **The user named a version** → use it if listed. If it is not listed, stop,
  show what is available, and suggest running
  `discover-drupal-core-module {module} {version}` for the version they asked
  for (offer to run it — never start it unprompted).
- **Exactly one match** → use its version.
- **Multiple matches, no version given** → pick the **newest** core version
  (highest tag — core tags are plain semver, `sort -V` order is correct).
  State in your final report which version you picked and which others are
  available.

Then verify the docs are actually there:

```bash
VERSION={chosen core version}
DOCS_DIR="$HOME/.drupal-context/core/$VERSION/$MODULE"
[ -f "$DOCS_DIR/metadata.json" ] || { echo "metadata.json missing in $DOCS_DIR — re-run discover-drupal-core-module"; exit 1; }
ls -1 "$DOCS_DIR"
```

## Override for Step 2 — Resolve the output skill directory

Identical layout and naming to the contrib skill — the skill name is `dc-` +
the machine name with underscores turned into hyphens (e.g. `dc-views`,
`dc-layout-builder`), storage is nested per version under the real machine
name, and the contrib skill's **version-suffix rule** applies unchanged: the
first generated version keeps the plain name; a later different version gets
the slugified tag appended (e.g. `dc-views-11-2-2`). Compute the name and
stamp the generation time now:

```bash
SKILL_BASE="dc-$(printf '%s' "$MODULE" | tr '_' '-')"
TAG_SLUG="$(printf '%s' "$VERSION" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9' '-' | sed 's/--*/-/g; s/^-//; s/-$//')"
OTHER_VERSIONS="$(ls -1 "$HOME/.drupal-context/skills/$MODULE" 2>/dev/null | grep -vx "$VERSION")"
if [ -n "$OTHER_VERSIONS" ]; then
  SKILL_NAME="${SKILL_BASE}-${TAG_SLUG}"   # e.g. dc-views-11-2-2
else
  SKILL_NAME="$SKILL_BASE"                 # e.g. dc-views
fi
SKILL_OUT="$HOME/.drupal-context/skills/${MODULE}/${VERSION}"
mkdir -p "$SKILL_OUT/references"
GEN_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "SKILL_NAME=$SKILL_NAME"
```

If the directory already exists, overwrite it freely — it is regenerable,
and the versioned name means you are never clobbering a different version.

When writing the `SKILL.md` frontmatter in step 6, set the core variant
values:

```yaml
metadata:
  module: {module_machine_name}
  version: {version}            # the Drupal core version
  skill_type: core_module
  generated_at: {GEN_DATE}
  generated_from: ~/.drupal-context/core/{version}/{module}/
---
```

Every `metadata` field above is **mandatory** (same rule as the contrib
skill): `module`, `version`, `generated_at`, and `generated_from` — never
omit or rename them.

## Override for the "Verify-installed section template"

Core modules ship **with** Drupal — they are never installed via
`composer require drupal/{module}`. Use this template instead of the original
skill's verify-installed block when writing step-6's "Step 1 — Verify …
installed" section (substitute `{module}`):

````markdown
## Step 1 — Verify `{module}` is enabled (do this first)

`{module}` is a Drupal **core** module — it ships with core, so there is nothing
to `composer require`. But it may not be *enabled*. Confirm before using anything
below:

```bash
drush php:eval "print \Drupal::moduleHandler()->moduleExists('{module}') ? 'ENABLED' : 'NOT-ENABLED';"
```

If this prints **`NOT-ENABLED`**, stop — do **not** run any of the steps below.
Ask the user how to proceed, e.g.:

> `{module}` is a core module but is not enabled on this site. I can enable it
> for you, or you can do it yourself. How would you like to proceed?

If the user asks **you** to enable it:

```bash
drush pm:enable {module} -y      # enable related submodules (e.g. {module}_ui) as needed
drush cache:rebuild
```

Re-run the verify command and confirm it prints `ENABLED` before continuing.
````

## Everything else

For all remaining work — reading `metadata.json` + the docs (step 3), choosing
which `references/*.md` to emit (step 4), writing precise lifted references
(step 5), writing the focused `SKILL.md` orientation layer (step 6), grounding
every example in real identifiers (step 7), the verify pass (step 8), and the
offer to install into the project's agent skills directory (step 9) —
**apply `generate-module-skill`'s SKILL.md exactly as written.** The docs have
the same file names and the same `metadata.json` shape for core modules as for
contrib (`"type": "core"`, and the version is the core tag), so those steps
need no changes.

One path note for step 8: the bundled verifier ships with the contrib skill —
run it from there (this variant deliberately keeps no copy, since the contrib
skill is required alongside). With `DOCS_DIR` set to the core docs dir from
step 1, the script needs nothing else: it reads `"type": "core"` from
`metadata.json` and expects `skill_type: core_module`, and its verify-installed
check only requires the `moduleExists('{module}')` line, which this variant's
template also contains.

```bash
python3 "<dir containing this SKILL.md>/../generate-module-skill/scripts/verify.py" \
  "$SKILL_OUT" --docs-dir "$DOCS_DIR" --name "$SKILL_NAME"
```
