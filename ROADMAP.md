# Roadmap — deferred improvements

Running list of improvement points found while building and auditing the
pipeline. This file is for **deferred** work — things we consciously chose not
to do in the moment. Anything urgent goes straight into the skills/agent
instead. Append new items to the relevant section with the date found; move
shipped items to **Done** at the bottom.

## Discover pipeline

### PHP symbol resolution beyond grep (inheritance-aware verification)

*Found 2026-08-13, auditing the feeds sonnet-high run.*

Verifying a claim like "`Feed::deleteMultiple()` exists / does not exist"
requires the class's **full inheritance chain**, and grep only sees what is
declared in the module's own source. An inherited method lives in a core base
class (`ContentEntityBase`, `ControllerBase`, …), and the temp source cache
holds only the module subtree — no Drupal core. In this workspace we happened
to be able to cross-check against `drupal-site/web/core`, but the skills are
meant to run standalone, where no core checkout exists.

Options (undecided):

- Sparse-download the referenced core base-class files on demand, the same way
  `download-core-module.sh` fetches a module subtree (cheap, no bootstrap
  needed — resolving `extends`/`use` imports gives the exact file path under
  `core/lib/`).
- Teach explorers to **qualify** inherited-symbol claims: "declared in this
  module" vs "inherited from core — not verified here". Zero infra, weaker
  guarantee.
- A bundled resolver script (PHP reflection needs a bootstrapped autoloader —
  heavier than it looks; probably not worth it).

### Split Explorer B for very large modules

*Found 2026-08-13, discussing the verifier-agent options.*

For huge modules (webform, commerce), Explorer B's context (entities + plugins
+ services + hooks + events) gets heavy. Deliberately **not** solved by adding
more explorers globally — more overlapping writers means more contradiction
surface. Idea: orchestrator splits B only when the GATE/enumeration exceeds a
size threshold (e.g. N source files), keeping the single-B default.

### Structure-aware file reading to cut token consumption

*Found 2026-08-13 — file reads were one of the top token consumers across
discover runs and audit sessions.*

Explorers (and audits) read whole files when most passes only need the
structural surface. For file types whose structure we know, a bundled
"outline" reader could cut most of the tokens per file:

- **PHP**: emit namespace, `use` imports, class/interface/trait declaration
  with `extends`/`implements`, annotations/attributes, constants, property
  declarations, and **method signatures** (+ first docblock line) — dropping
  method bodies. On big classes that is a large cut, and it is exactly the
  input the inventory passes (enumeration, class sweep, plugin/service tables,
  signatures) need. Stdlib-only script next to `download.py`/`verify.py`,
  e.g. `outline.py <file.php>...`.
- **YAML**: usually small enough to read whole; for the big ones
  (`*.services.yml`, `config/schema/*.yml`) an option to print only key paths
  + selected values.
- **Integration**: instruct the explorer to use the outline for first-pass /
  inventory reads and fall back to a full `Read` only where behavior matters.
  **Caution**: method bodies are where call sites and gotchas live — the
  anti-fabrication and verify-call-sites rules require reading real code for
  *behavior* claims; the outline is for *inventory*, never a substitute for
  reading the body behind a behavioral claim.

### Mandatory invocation caveat for documented (api.php) hooks

*Found 2026-08-13, auditing the gpt-5.5 flag run.*

A hook documented in `{module}.api.php` is not necessarily *invoked* anywhere
(`hook_flag_options_alter` is declared but never fired in flag 5.0.3). The
better runs state that explicitly ("not an operative extension point in this
release"); the gpt-5.5 run listed it as a working extension point with no
caveat — misleading by omission, and exactly the guidance failure our rules
target. Candidate fix: in the `hooks`/`extension-points` catalog entries,
require that every api.php-documented hook be paired with its verified
invocation site — or, when grep finds none, an explicit "declared but not
invoked in this release" note. (The verify-call-sites rule covers *stated*
sites; this extends it to *listing* a hook at all.)

### Enforce `.inc` coverage in the procedural inventory

*Found 2026-08-13, auditing the gpt-sol flag run.*

The `services.md` procedural-API contract already says to enumerate
`{module}.module` **and** the `*.inc` includes, but gpt-sol silently dropped
`theme_flag_tokens_browser()` from `flag.tokens.inc` (the dead-code find that
made the Opus run valuable). Candidate mitigations: (a) sharpen the catalog
wording — the grep command shown must cover every `*.inc` and the doc must
account for every hit, including dead/legacy functions; (b) a mechanical
option: verify.py could compare `grep -c '^function '` across
`.module`/`.inc` files against function names mentioned in the docs and warn
on gaps (fuzzy — function names in prose are greppable, but risk of false
positives; prototype before committing).

### Folder checklist expansion (class completeness sweep)

The core-convention folder list in the agent's sweep is deliberately partial
(the inheritance test is the real guarantee). Add entries as they bite:
`Breadcrumb/`, `ContextProvider/`, `PathProcessor/`, `EntityReferenceSelection/`,
`Validation/` (outside Plugin), etc. One line each.

### Configuration category: name every `config/schema/*.yml` file

*Found 2026-08-13, flag audit (rounds 1–2): `flag.views.schema.yml` was never
mentioned by name.* Optional instruction for the `configuration` catalog entry:
list each schema file, even when its contents (e.g. Views plugin option
schemas) are only summarized.

## Model/effort operations

### Effort guidance for discover runs

*Series result (2026-08-13):* synthesis-explorer (C) error count tracked
model/effort — Opus 0, Sonnet max 0, Sonnet high 2, Sonnet default 3 — and 6 of
6 errors were facts already correct in wave-1 files.

*Run B validation (2026-08-13, feeds @ Sonnet high, two-wave):* the
fact-base-contradiction error class went **2 → 0** on the same
module/model/effort; C's output got *sharper*, not shallower (line-precise call
sites, new verified gotchas). The one residual error was an **invented new
symbol** (`FetcherBase`) — a fact the wave-1 files did not cover — which the
FQCN check in verify.py (now shipped) catches deterministically. Standing
recommendation: Sonnet high is fine for discover runs with the two-wave flow +
FQCN verify; reserve Opus/max effort for especially API-dense modules.

## Pack / import (known-broken pipeline link)

### Update pack scripts + site importer to the new layout

`scripts/pack-*.sh` and the drupal-site importer still expect the **old**
layout (`storage/<module>/<tag>/discover/` + 6-line in-file headers +
`ai/skills/boost-*`). The discover/generate skills now write
`~/.drupal-context/…` + `metadata.json` with no headers. Until the pack
scripts and the importer learn the new format, freshly generated content
cannot be packed/imported. (Also tracked in CLAUDE.md's "⚠ In transition"
note.)

### Migrate legacy `boost-*` skills to `dc-*`

~35 legacy `boost-*` skills predate the `dc-<module-name>` naming. Decide:
regenerate from fresh discovers vs mechanical rename (+ frontmatter update).

## drop-context CLI

### `download`/discover front-end command

Original idea from the standalone-skills rework: a drop-context command as an
alternative front-end for downloading/discovering modules, so non-agent users
get the same pipeline. Tradeoff: duplicates the bundled skill scripts vs
depending on the CLI. Parked.

## Done

- **Generate-skill verifier (structure + docs-grounding)** — 2026-08-14. The
  generate step is synthesis — the error class where all discover
  hallucination concentrated — but its verify step was manual `ls`/`wc`. New
  `generate-module-skill/scripts/verify.py` (stdlib-only, single copy — the
  core variant runs it from the contrib skill it already requires): checks
  frontmatter (name/metadata keys, module+version+type matched against the
  docs' `metadata.json`), the mandatory verify-installed section, the
  reference routing table vs disk both directions, sibling cross-links,
  stub/empty files, line caps, leftover `{placeholder}` tokens — and
  **grounding**: every `Drupal\<module>\…` FQCN and module-named `hook_*` in
  the generated skill must appear verbatim in the discover docs (PROBLEM);
  module-prefixed dotted IDs missing from the docs are WARNINGs. The
  grounding corpus excludes `audit-*.md` (an auditor may quote an invented
  identifier as an error example). Acceptance-tested on fixtures grounded in
  the better_exposed_filters 7.1.3 docs: clean fixture passes; 9/9 seeded
  error classes caught, zero false positives. SKILL.md step 8 rewritten to
  run it; step 7 gained "identifiers verbatim" + "carry hedges forward"
  rules.
- **FQCN validation in verify.py** — 2026-08-13. `--module-root` flag: every
  `Drupal\<module>\…` (and submodule-namespace) class reference in the docs
  must resolve via PSR-4 to a class file or namespace dir in the source;
  unresolvable → PROBLEM, and the skills' step 7 treats it like a discrepancy
  (follow-up explorer fixes the file). Acceptance-tested: caught feeds Run B's
  invented `FetcherBase` and, retroactively, the flag sonnet run's
  `Drupal\flag\…\CountLink` wrong-namespace error — zero false positives on
  both full doc sets. Both skills now pass `--module-root "$MODULE_ROOT"`.
- **Two-wave discover (synthesis fact grounding)** — 2026-08-13. Explorer C
  runs after A/B/D, reads their files as the verified fact base, reports
  conflicts via `=== DISCREPANCIES ===`; orchestrator re-checks via one
  follow-up explorer. Motivated by 6/6 synthesis errors whose correct version
  already existed on disk in wave 1. **Validated on feeds Run B** (same
  module/model/effort as Run A): contradiction-class errors 2 → 0, output
  sharper, no anchoring shallowness.
- **Class completeness sweep (inheritance-based) + core-folder checklist** —
  2026-08-13. Any class extending/implementing `Drupal\Core\…`/
  `Drupal\Component\…` must be documented; folder→category recall table.
- **Procedural API inventory** (`services.md`: container / public PHP API /
  procedural sections) — 2026-08-13.
- **Verified call sites, no underived counts, submodule parent lookups,
  README/`field_type_categories.yml`/`migrations/state/` coverage** —
  2026-08-13, various audit rounds (workflow, flag ×2, feeds ×2).
