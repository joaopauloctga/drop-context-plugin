# drop-context — agent skills for documenting Drupal modules

A Claude Code plugin that reads a Drupal module (contrib, custom, or core) or
a Drupal core framework library **directly out of the Drupal repo you run it
in**, and writes a structured, AI-consumable analysis to
`~/.drop-context/docs/` — a single user-level location, the same no matter
which repo you're standing in. A second stage turns that analysis into a
focused, installable agent skill (`dc-<module-name>`) so other agents can
build on the module without re-reading its source every time.

## Installation

```text
/plugin marketplace add joaopauloctga/drupal-context-ai
/plugin install drop-context@drop-context-ai
```

**Prerequisite: `python3` ≥ 3.9** (standard library only — nothing to `pip
install`). That's it; every bundled script is stdlib-only Python or plain
bash, so nothing else needs to be on your machine.

To update later:

```text
/plugin marketplace update drop-context-ai
/plugin update drop-context
```

## Releases and versioning

The plugin carries a plain semver `version` in
`.claude-plugin/plugin.json`, and each release is marked by a git tag of the
form `{name}--v{version}` — `drop-context--v1.0.0`. The tag is what a
marketplace resolves an installed version against, so the two must not drift.
`claude plugin tag` creates it and refuses to if `plugin.json` and the
enclosing marketplace entry disagree:

```bash
claude plugin validate .            # manifests well-formed?
claude plugin tag --dry-run         # what would be tagged, without tagging
claude plugin tag --push            # tag HEAD and push it to origin
```

`tag` also refuses on a dirty working tree, so a tag always points at
committed state. Cutting a release is therefore: bump `version` in
`plugin.json`, commit, `claude plugin tag --push`.

## What it does

Run a document skill **from inside a Drupal repo** (or point it at one). It
locates the module on disk — `web/modules/contrib/<module>`,
`web/modules/custom/<module>`, or `web/core/modules/<module>` — resolves its
version from what's already there (the module's own `.info.yml`,
`composer.lock`, or `Drupal::VERSION` for core), and writes category Markdown
files plus a `metadata.json` manifest to
`~/.drop-context/docs/modules/<module>/<version>/` (or `docs/core/…` for a
core module) — the source is read from the repo you're standing in, but the
output always lands at this single user-level location, never inside that
repo. **Nothing is downloaded and nothing is fetched from the network** — the
document, make, and audit skills never make an HTTP request.

```text
/drop-context:document-module <machine_name>                 # e.g. flag — reads web/modules/contrib/flag
/drop-context:document-module eca without submodules          # root-only scope: huge ecosystems, submodules deferred
/drop-context:document-module eca only submodules              # completion pass over an existing root-only run
/drop-context:document-core-module <machine_name>              # e.g. views — reads web/core/modules/views
/drop-context:document-core-library Core/Ajax                  # reads web/core/lib/Drupal/Core/Ajax
/drop-context:make-skill <machine_name> [<version>]        # run after document — turns docs into a dc-<module> skill
/drop-context:audit-docs <machine_name> [<version>]         # deep, read-only QA of a document run
```

A **custom module** (`web/modules/custom/<module>`) can be documented too —
something the old, download-only pipeline couldn't do, since it only knew how
to fetch from drupal.org.

If the module can't be found, or its version can't be resolved from what's on
disk, the skill **asks you** rather than guessing — see "Version and module
resolution" below.

What a document run does, in order:

1. **Resolve + gate** — a bundled Python script locates the module inside the
   repo, resolves its version, creates the output directory, and enumerates
   submodules. No gate, no explorers.
2. **Wave 1** — two explorer subagents run in parallel and write the factual
   root category files (entities, plugins, services, hooks, events,
   configuration, permissions, routes).
3. **Submodule wave** — when the module ships submodules, a batch of
   submodule-explorer subagents writes `submodules/*.md`, grounded in wave
   1's files.
4. **Synthesis wave** — one more explorer writes `extension-points.md` and
   `ai-integration.md`, grounded in every file written before it.
5. The orchestrator writes `summary.md` + `metadata.json` and runs the
   bundled verifier, which cross-checks the output against the module source.

Then make a skill from the result:

```text
/drop-context:make-skill flag
```

This reads `~/.drop-context/docs/modules/flag/<version>/`, writes a focused
`dc-flag` skill to `~/.drop-context/docs/skills/flag/<version>/`, and offers
to **symlink** it into your project's agent skills directory
(`.claude/skills/`, `.agents/skills/`, …) under the name `dc-flag` — an
**absolute** symlink (the target now lives outside the project entirely, so a
relative link would not resolve). Regenerating the skill later updates what
agents load with no separate reinstall step.

## Output location

Everything this plugin writes lands under `~/.drop-context/docs/` — a single
location shared by every repo, never inside the repo you ran the skill from
(override the base with the `DROP_CONTEXT_HOME` environment variable, e.g. to
point it at a scratch directory):

```text
~/.drop-context/
└── docs/
    ├── modules/<module>/<version>/          # contrib + custom module docs
    ├── core/<version>/<module>/             # core module docs
    ├── core-libraries/<version>/<Core-or-Component>/<library>/   # core framework library docs
    └── skills/<module>/<version>/           # generated dc-<module> skills, before symlinking
```

The `docs/` level is mandatory, not decorative: `~/.drop-context/` is also the
home of the separate `drop-context` CLI, which stores its own `app.json`,
`cache/`, `agents/`, and — directly under `~/.drop-context/skills/` (no
`docs/`) — the skills *it* installs, by name. Nesting this plugin's output
under `docs/` is the only thing keeping this plugin's generated `skills/` from
colliding with the CLI's own `skills/` directory. This plugin never writes to
`~/.drop-context/skills/`, `~/.drop-context/app.json`, or anything else the
CLI owns.

Since output no longer lands inside your project, there is nothing to add to
your project's `.gitignore` for it.

## The read-only guarantee

Every module/library source path this plugin resolves — `MODULE_ROOT`,
`LIBRARY_ROOT`, `CORE_ROOT` — is the **user's real, version-controlled Drupal
source**. It is read-only: every skill and worker agent only ever `Read`,
`Glob`, or `grep`/`find` under it. Every write, in every skill, goes only
under `~/.drop-context/docs/` (or `DROP_CONTEXT_HOME/docs` when overridden).
Nothing this plugin does touches `web/modules/`, `web/core/`, or any other
part of your checkout.

The two exceptions to "zero network" — `retag-docs` and `add-release` — are
release-maintenance skills for a module that's already documented. They diff
two tags to decide how much of the doc set changed, which needs both tags'
source on disk at once; an installed repo only ever holds one checked-out
version, so those two skills download the two tags into a disposable temp
cache instead of reading your repo. They never write to `web/` either.

## Release maintenance: which skill when

When a documented module ships a new release, **you** pick the skill — there
is no router skill. The Drupal.org release page usually tells you everything
you need: breaking changes announced? core support changed? or just fixes?
Both skills also generate the release's `release.json` (notes, classification,
issue links) into the version's doc-set directory.

```text
/drop-context:retag-docs <module> [<current>] <target>    # tiny delta: retag docs in place + release notes
/drop-context:add-release <module> [<current>] <target>   # real but contained delta: new doc set alongside + release notes
/drop-context:document-module <module> <target>            # sweeping delta / new line / first documentation
```

| Situation | Skill | Result |
|-----------|-------|--------|
| Delta doesn't touch documented surface (fixes, tests, style; at most mechanical fact edits like a core-requirement line) | `retag-docs` | The existing doc set is **retagged in place** to the target version + the target's `release.json` |
| Real changes but **contained** — features added, surface removed, breaking changes, architecture intact | `add-release` | A **new doc set is created alongside** the current one; only diff-affected categories are regenerated, the rest copied forward + the target's `release.json` |
| **Sweeping** — near-rewrite or a new major line, or the module was never documented, or the delta can't be diffed | `document-module` | Full fresh document run |

The names carry the distinction now: `retag-docs` retags one doc set in
place, `add-release` adds a second doc set alongside the first. Skipping
intermediate tags is the norm — both skills diff the *cumulative*
`current → target` source delta, so `3.1.0 → 3.1.6` runs directly rather than
hop-by-hop. Both gate their own preconditions and refuse across the boundary
(`retag-docs` refuses prose work, `add-release` refuses rewrites) — a refusal
names the right skill and changes nothing on disk.

## Version and module resolution

The resolver never guesses. For a contrib or custom module it reads, in
order: the module's own `.info.yml` `version:` key, then `composer.lock`'s
`drupal/<project>` entry. A core module's version is always the repo's own
`Drupal::VERSION` — never its `.info.yml`, which typically carries the
literal placeholder string `version: VERSION` (a drupal.org packaging-time
token, not a real version).

If the module can't be found anywhere in the repo, or a contrib/custom
module's version can't be resolved from either source, the skill stops and
asks you — offering to install the module, take an explicit path, or supply a
version label (`dev`, a short git SHA, or anything else you choose) — rather
than silently fabricating one.

## Validating the output

Three layers, cheapest first:

1. **The bundled verifier** runs automatically as the document skill's last
   step, and cross-checks `metadata.json` against the files on disk in both
   directions, plus grounds the docs in the source (every class reference
   resolves, every stated count matches its enumeration, every cited
   `path:line` is real).
2. **Quick manual smoke checks** — see `CONTRIBUTING.md` if you're modifying
   the skills themselves.
3. **Deep audit** — `/drop-context:audit-docs <machine_name> [<version>]`
   verifies claims against source at the line level and delivers a
   severity-ranked, `path:line`-evidenced report. It is read-only by contract.

## Where the output can go next

This plugin is self-contained: everything it produces is plain Markdown and
JSON under `~/.drop-context/docs/`, and the generated `dc-<module>` skills are
usable the moment they are symlinked into your project. Nothing below is
required to use it.

It is also the first stage of a longer pipeline. The same doc sets can be
published to **[dropcontext.dev](https://dropcontext.dev)**, a Drupal site
that imports them (one entity per documented release, one per doc file) and
serves them anonymously as JSON. The separate `drop-context` PHP CLI reads
that API and ships `drop-context-mcp`, a stdio MCP server that gives any agent
`list_modules` / `get_module` / `get_doc` tools over the published catalog —
so a module documented once is available to agents that never had the source.

The two directions are complementary: this plugin documents what is installed
in *your* repo, including custom modules that exist nowhere else; the
published catalog covers contrib releases already documented by someone else.

## What's in this plugin

| Path | What it is |
| --- | --- |
| `skills/document-module/` | Document a **contrib or custom** module → category docs + `metadata.json`. Bundles the resolver (`scripts/resolve.py`) and verifier (`scripts/verify.py`). |
| `skills/document-core-module/` | Same for **core** modules — reuses `document-module`'s resolver via a sibling path; keeps its own copy of the verifier. |
| `skills/document-core-library/` | Document a framework library below `core/lib/Drupal` → stable summary/architecture/API/usage docs, optional source-driven topics, and search-oriented `metadata.json`. |
| `skills/make-skill/` / `make-core-skill/` | Turn documented docs into an installable `dc-<module-name>` agent skill, symlinked into your project's agent skills directory. |
| `skills/audit-docs/` | Deep, read-only quality audit of generated documentation — verifies claims against the module source and delivers a `path:line`-evidenced report. |
| `skills/retag-docs/` | Version-bump maintenance for a documented module (small delta: retag in place + release.json). One of the two networked skills. |
| `skills/add-release/` | Version-bump maintenance for real but contained deltas (new doc set alongside + release.json). The other networked skill. |
| `agents/drupal-module-explorer.md` | The category worker agent the document skills orchestrate. |
| `agents/drupal-submodule-explorer.md` | The submodule worker agent — documents submodules in condensed `submodules/*.md` files, grounded in the already-written category docs. |
| `agents/drupal-core-library-explorer.md` | Multi-mode worker for core libraries: surveys source topology, writes per-workstream evidence notes, and synthesizes the stable library documentation. |

For contributing to this plugin itself — the editing rules, the machine-parseable
contracts that must not break, and how to validate a change — see
`CONTRIBUTING.md`. `IMPROVEMENT-HISTORY.md` is the distilled record of past
improvement rounds to the document skills and explorer agents.
