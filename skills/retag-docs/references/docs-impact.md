# Change classification + docs-impact triage

Shared reference for `retag-docs` (gates: is the delta really
mechanical-only?) and `add-release` (scope: which category files get
regenerated?), and for the classification both write into `release.json`.

Both verdicts here are **evidence-based**: every classification signal and every
impact claim must point at a release-notes statement, an `.info.yml` diff hunk,
or a changed file in the local `BASELINE → TAG` diff. Nothing is inferred from
version numbers alone except the release-line signal below.

## Change level: `patch` | `minor` | `major`

Pick the **highest** level any signal triggers:

| Level | Signals |
|-------|---------|
| `major` | Release line changed vs the docs baseline (`2.x` → `3.x`, or scheme change `8.x-2.x` → `2.x`); release notes announce BC breaks / upgrade steps / API removals; `core_version_requirement` **drops** a previously supported core major; the diff removes or renames public classes, service IDs, plugin IDs, hooks, routes, or permissions; a required dependency is added/removed/major-bumped |
| `minor` | New features, new plugins/services/hooks/routes/permissions, new optional dependencies, `core_version_requirement` **gains** a core major — all additive, same line |
| `patch` | Bug fixes, internal refactors, test/CI/docs changes only |

Record alongside the level:

- `breaking_changes[]` — one concrete entry per proven break, each traceable to
  notes or a diff hunk (e.g. "service `foo.resolver` removed",
  "`hook_foo_alter()` signature changed"). Never pad; empty when none proven.
- `core_version_requirement {previous, current}` — verbatim from the two
  `.info.yml`s (baseline and new tag). Include both even when equal — "same
  core support" is exactly what makes a minor bump safe for consumers.

`change_level` is a signal, not the verdict: a `major` release almost always
lands `affected` below, but the docs verdict still comes from the diff, not
from the level.

## Docs-impact category map

Map every file in the `BASELINE → TAG` diff (changed, added, **and removed**)
onto the doc set's files:

| Changed path | Affected doc file |
|--------------|-------------------|
| `<module>.info.yml`, `composer.json` (deps / core requirement) | `summary.md` (Key Facts) — and classification signals above |
| `src/Entity/**`, entity handlers/storage | `entities.md` |
| `src/Plugin/**` | `plugins.md` |
| `<module>.services.yml`, service classes under `src/` | `services.md` |
| `config/install/**`, `config/schema/**`, settings forms | `configuration.md` |
| `<module>.permissions.yml`, `src/Access/**` | `permissions.md` |
| `<module>.routing.yml`, `<module>.links.*.yml`, `src/Controller/**`, `src/Form/**` | `routes.md` |
| `<module>.module`, `src/Hook/**` | `hooks.md` |
| `src/Event/**`, `src/EventSubscriber/**`, `*Events.php` | `events.md` |
| `<module>.api.php`; base classes / interfaces / traits meant for extension | `extension-points.md` |
| AI-module integration code (function-call / AI plugins) | `ai-integration.md` |
| `modules/<sub>/**` | `submodules/<sub>.md` |

**No-impact buckets** — changes that never affect the docs:

- `tests/**`, `.gitlab-ci.yml`, `phpcs`/`phpstan`/linter configs
- `README*`, `CHANGELOG*`, other repo docs, `*.po` translations
- `css/`, `js/`, `templates/`, `*.libraries.yml` — *unless* the doc set
  actually documents theming/asset behavior (check before bucketing)
- Comment-only or code-style-only hunks in an otherwise mapped file — you must
  have read the hunks to claim this, and say so in the evidence

Rules:

- One file can hit several categories (a service class that is also an event
  subscriber) — mark **every** plausible one.
- A file you cannot confidently map → the verdict is `affected` (over-marking
  is safe: it just triggers a full document run; under-marking ships stale docs).
- Deletions matter as much as additions — removed files usually mean removed
  documented surface.

**Coverage rule (mandatory for large diffs).** Sampling the diff under-marks —
the long tail of a 200+ file delta is where stale docs hide. Group the
complete diff deterministically and force a decision per group:

```bash
diff -rq "$SRC_BASELINE" "$SRC_TAG" \
  | sed -e "s|$SRC_BASELINE/||" -e "s|$SRC_TAG/||" \
  | grep -oE '[^ ]+' | grep / \
  | awk -F/ '{ if ($1=="modules") print $1"/"$2; else print $1 }' \
  | sort -u
```

Every group in that output must be dispatched explicitly: either every one of
its changed files is in a no-impact bucket (tests, CI, style-only hunks you
actually read), or its category file(s) go into `categories` — including one
`submodules/<sub>.md` entry per changed `modules/<sub>` group that is
documented. No group may be silently skipped because the headline changes
lived elsewhere.

## Verdict

- **`none`** — requires **all** of: a complete local diff (every changed file
  enumerated via `diff -rq` of the two downloaded trees — a possibly-paginated
  API file list does not qualify), and every file either bucketed no-impact or
  demanding at most a **mechanical fact substitution** in the docs (version
  string, core-requirement line, dependency constraint — nothing narrative).
- **`affected`** — anything mapped to a doc file beyond mechanical facts.
  List the doc files.
- **`unknown`** — diff incomplete/unavailable. Never present `unknown` as
  `none`.
- **`not_applicable`** — no docs baseline in this release line (new line or
  never-documented module).

## Contained vs sweeping (`affected` only)

The boundary between `add-release` and a full document run is the
**architecture**, not the affected-file count:

- **Contained** — the root architecture is intact: entity model, plugin-type
  system, service layout recognizably the same, so the old docs remain a
  valid fact base for grounding the regeneration, and unchanged facts can be
  carried forward. Example: eca `3.0.14 → 3.1.0` — 27 of 31 category files
  affected (removed submodules, moved plugin types, new features), yet the
  architecture stands; the upgrade run handled it correctly, copying forward
  the 4 untouched files and grounding the rest.
- **Sweeping** — the architecture itself changed (or it's a new line's first
  documentation). Example: eca `2.1.x → 3.0.x` — effectively a rewrite;
  grounding on the old docs buys nothing and risks anchoring on stale facts.
  Full `/drop-context:document-module` is safer.

The affected-file count is a **cost signal**, not a refusal trigger: when
nearly every category is affected, add-release's token savings over a full
document run shrink toward zero — say so in the report so the user can weigh it —
but the grounding benefit (old docs as verified fact base) remains.
