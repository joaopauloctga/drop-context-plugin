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

### Free drift measurement: two discovers of byte-identical source

*Found 2026-08-18, during the release-skills validation (see
`plans/workflow-release-skill-ground-truth.md`, "Local docs state").*
`workflow` 2.1.10 and 2.2.2 are the same commit, and both were fully
discovered by independent runs — every category file differs, some
drastically (`services.md` 76 vs 23 lines, `configuration.md` 186 vs 84,
`extension-points.md` 70 vs 190). Part is skill-version delta (the 2.2.2 run
predates later improvements), part is run-to-run nondeterminism. Worth mining
when calibrating discover quality: an `audit-discover-docs` pass over both
sets would attribute the gap (older-skill artifacts vs real variance) for
free, on perfectly controlled input.

### A/B-validate the sequenced submodule wave

*Added 2026-08-17, after restructuring the discover flow (submodules moved to
a dedicated `drupal-submodule-explorer` agent that runs after wave 1,
grounded in its files, before C).* The grounding mechanism is the one
validated in runs 7–8, but the full-run sequencing change has not been A/B'd
per the protocol in `IMPROVEMENT-HISTORY.md`. On the next discover of a
submodule-bearing module (metatag or feeds, Sonnet high): audit with
`audit-discover-docs`, score by taxonomy class against the run-series
baselines — especially submodule-file claims and cross-file consistency —
before treating the new flow as settled.

### Anti-fabricated-quotation rule for the explorers

*Found 2026-08-17, auditing the eca 3.0.14 root-only run — first finding of
this error class in the audited series.* Explorer C wrote that
`ContextDataProvider` is "explicitly built as 'an extension point for other
modules' (per its own docblock)" — the quoted phrase exists nowhere in the
module source; the real docblock says something else entirely. Etiology:
`services.md` (the fact base) offered the phrase as its own
*characterization*, and the synthesis wave upgraded it to a verbatim,
attributed quotation. The same run also quoted a real docblock correctly
(`TokenGenerateEvent` `@internal`), so the failure is the upgrade, not
quoting per se. Proposed rule for both explorer agents (Behavioral Rules):
quotation marks plus an attribution ("per its docblock", "the deprecation
message says", "the comment states") may only wrap text copied verbatim from
a file read this session; fact-base characterizations are re-stated without
quotes or attribution. Partially mechanizable in verify.py: extract quoted
spans adjacent to docblock/comment attributions in the docs and require an
exact (whitespace-normalized) match somewhere in the module source — worth
prototyping before adding prose rules, per the "deterministic beats
instructed" lesson.

### Port the submodule scope to `discover-drupal-core-module`

*Found 2026-08-17, adding the submodule scope to `discover-drupal-module` for
huge ecosystems like eca.* The sequenced submodule wave and the
`drupal-submodule-explorer` agent ARE shared with the core skill; what stayed
contrib-only are the **scope modes** (root-only / submodules-only). Core
modules essentially never ship nested `*.info.yml` submodules, so the core
skill gains nothing today. The shared `verify.py` already understands
`submodules_skipped` (the copies are identical), so porting the modes is a
SKILL.md-only change if a need ever appears.

### Synthesis refresh after a submodules-only completion pass

*Found 2026-08-17, same change.* In a **full** run Explorer C now runs after
the submodule wave, so the synthesis files see `submodules/*.md` by
construction. The gap is only the two-phase flow: a root-only run synthesizes
without the submodule fact base, and the later submodules-only pass
deliberately does not re-run C (keeps the pass cheap, avoids rewriting
verified files). Optional follow-up: offer a C re-run after a completion pass
so the synthesis files can cite submodule capabilities — worth it mainly for
ecosystems where the submodules ARE the extension surface (eca). Needs the
discrepancy protocol unchanged.

## Migrate pipeline

### `migrate-discover-docs` step 5/6 can't be delegated to a forked worker

*Found 2026-08-17, migrating `core/migrate` + `core/migrate_drupal` (11.3.13)
from legacy `storage/` docs.*

To keep the orchestrator's context clean across a multi-module batch, I tried
running each module's step 5 (content audit) + step 6 (fix cycle) inside a
forked subagent — the fork does the heavy reading, then spawns
`drupal-module-explorer` itself for any confirmed fix, and reports back only
the distilled findings. Step 5 (audit, read-only) worked fine in a fork. Step
6 did not: both forks hit a hard error attempting to spawn a nested
`drupal-module-explorer` — nested agent delegation is blocked one level down
from the top-level orchestrator, fork or not. Per the skill's own fallback
("if the explorer is unavailable, report — don't hand-edit"), both forks
correctly stopped short of editing and reported their findings with
path:line evidence instead, so no docs were touched incorrectly — but the fix
cycle had to be re-run from the top-level orchestrator context, one
`drupal-module-explorer` call per affected file, based on the forks' reports.

Net effect: forking step 5 alone (without step 6) is a solid pattern for a
batch — audits ran in parallel and stayed out of the orchestrator's context;
only the fix cycle needed top-level calls. Candidate fix: split the skill's
step 6 instructions so they explicitly assume "the fix cycle runs wherever
`Agent` can reach `drupal-module-explorer` directly" and call out that a
forked step-5 worker should report findings rather than attempt step 6 itself
— saves a round-trip discovering the constraint live. Undecided whether to
also note this as a general orchestration constraint (agents can't spawn
sub-subagents) somewhere more central than this skill.

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

## Release maintenance skills (update-module-docs / upgrade-module-docs)

### Decide the `release_line` granularity (data inconsistency on the site)

*Found 2026-08-18, auditing the validation runs.* The runs wrote three
different shapes for semver tags — workflow got `2.x`, eca 3.1.0 got
`3.1.x`, eca 3.1.6 got `3.x` — and all three are now imported as
`field_release_line` on the site (the importer accepts any non-empty
string; its own no-release.json fallback derives major-level, `2.1.0` →
`2.x`). Options: pin the contract to d.o branch granularity (`3.1.x` for
semver, `8.x-3.x` for legacy — matches what drupal.org shows, more
informative when 3.0.x/3.1.x lines coexist) or to major-level (matches the
importer's fallback). **User decision pending**; whichever wins, fix the
contract example, re-generate or hand-fix the inconsistent stored values,
and consider aligning `deriveReleaseLine()` in the site importer.

## Legacy cleanup

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

- **Submodule scope + dedicated `drupal-submodule-explorer` agent** —
  2026-08-17. Motivated by eca-sized ecosystems where one explorer covering
  every submodule cannot fit a context. (a) **Scope modes** (contrib skill):
  **full** (default), **root-only** ("without submodules" — records the
  GATE's submodule list in `metadata.json` `submodules_skipped` + a
  "detected but not documented" summary section), **submodules-only** (a
  completion pass over an existing output dir, run from a clean context,
  updating summary/metadata in place). (b) **Dedicated agent**: the
  submodules task moved out of `drupal-module-explorer` into
  `drupal-submodule-explorer`, grounded by design — it requires and reads
  the root category docs as its parent-symbol fact base (targeted parent
  grep only as fallback) and shares the MANIFEST/DISCREPANCIES contract.
  (c) **Sequenced waves** (both discover skills): A+B → submodule batches
  (≤8 each, parallel) → C, so C's fact base includes submodule files.
  (d) `verify.py` (both copies) validates `submodules_skipped` shape,
  forbids skipped∩documented, resolves skipped namespaces in the FQCN
  check, prints `SUBMODULES_SKIPPED=n`; `--submodules` now means "submodule
  files expected on disk after this run" — acceptance-tested on synthetic
  fixtures (7/7) + regression on calculation_fields 1.0.4 and
  better_exposed_filters 7.1.3 (both still VERIFY OK). Audit + migrate
  skills route submodule-file fixes to the new agent. Full-run sequencing
  A/B validation pending (see Discover pipeline).
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
- **Scoped category refresh → shipped as the release-maintenance skill trio** —
  2026-08-18. `discover-module-release` slimmed to notes + classification +
  recommendation; new `update-module-docs` (retag in place across a tiny
  delta, mechanical diff-quotable edits only, verify.py-gated) and new
  `upgrade-module-docs` (new doc set alongside the old; diff-affected
  categories regenerated by scoped explorers, synthesis categories re-run
  whenever a wave-1 category changed — the grounding caveat this item
  recorded). Boundaries documented in `README.md` ("Release maintenance:
  which skill when") with eca 3.0.14→3.1.0 (upgrade) vs eca 2.1.x→3.0.x
  (full discover) as the calibration examples. *(Same day, consolidated
  further: `discover-module-release` was dissolved — the user picks
  update vs upgrade themselves via the README + the d.o release page, and
  each of the two skills generates the `release.json` itself; the shared
  references moved to `update-module-docs/references/`.)*
- **Pack scripts / importer format mismatch** — resolved by design during the
  per-release rework (2026-08): the site's `dc:import-docs` reads the new
  `~/.drupal-context`-shaped layout (`metadata.json`, header-less files,
  optional `release.json`) directly from `content/modules/`; the ZIP
  `pack-*.sh` path is dead, not fixed. The old "known-broken pipeline link"
  roadmap entry is superseded.
