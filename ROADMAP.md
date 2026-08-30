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

### Free drift measurement: two discovers of byte-identical source

*Found 2026-08-18, during the release-skills validation (see
`plans/workflow-release-skill-ground-truth.md`, "Local docs state").*
`workflow` 2.1.10 and 2.2.2 are the same commit, and both were fully
discovered by independent runs — every category file differs, some
drastically (`services.md` 76 vs 23 lines, `configuration.md` 186 vs 84,
`extension-points.md` 70 vs 190). Part is skill-version delta (the 2.2.2 run
predates later improvements), part is run-to-run nondeterminism. Worth mining
when calibrating discover quality: an `audit-docs` pass over both
sets would attribute the gap (older-skill artifacts vs real variance) for
free, on perfectly controlled input.

### A/B-validate the sequenced submodule wave

*Added 2026-08-17, after restructuring the discover flow (submodules moved to
a dedicated `drupal-submodule-explorer` agent that runs after wave 1,
grounded in its files, before C).* The grounding mechanism is the one
validated in runs 7–8, but the full-run sequencing change has not been A/B'd
per the protocol in `IMPROVEMENT-HISTORY.md`. On the next discover of a
submodule-bearing module (metatag or feeds, Sonnet high): audit with
`audit-docs`, score by taxonomy class against the run-series
baselines — especially submodule-file claims and cross-file consistency —
before treating the new flow as settled.

*2026-08-26:* a **third** unvalidated change now stacks on this: the
explorer-rule batch of that day (provenance outside `MODULE_ROOT`, subclass
dispatch tracing, quote provenance, cite-means-copy, stale `api.php`
flagging, lead-in recount, catalog ownership additions) plus the wave-1
verify gate. One A/B run validates all three — do it before adding any
further prompt rules.

### Port the submodule scope to `document-core-module`

*Found 2026-08-17, adding the submodule scope to `document-module` for
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

### "Cite means entail" is shipped and still failed — needs a mechanical half

*Found 2026-08-23, symfony_mailer_lite 2.0.4 audit.* `ai-integration.md`
restated a `hooks.md` fact and lost its qualifier ("site-wide" vs "scoped to
this module's own mail") — a lossy paraphrase, not a knowing contradiction, so
the `=== DISCREPANCIES ===` protocol never fired. **Prompt half shipped
2026-08-26** (synthesis rule "cite means copy — never paraphrase": a cited
wave-1 fact is quoted or copied with its scope words intact). **Mechanical
half still open**: for each `see \`X.md\``-style attribution, flag when the
citing sentence asserts a scope/quantity word ("site-wide", "all", "always",
"every", "never", "only") the cited file does not contain. Cruder than the
citation checks and not zero-false-positive; prototype only if the prompt
rule fails an A/B.

### Bare (unqualified) class-name resolution in verify.py

*Found 2026-08-21, views 11.3.13 audit.* The module-named case shipped
2026-08-26 (`ViewsRouteSubscriber`-style: a backticked CamelCase token that
starts with the module's CamelCase name and is declared nowhere → WARNING;
generic framework names are deliberately skipped — on the corpus every one of
those was a real core/Symfony class the module never imports).

**Still open — the inverse case** (2026-08-23, symfony_mailer_lite 2.0.4):
the *doc* was qualified and the *source* was bare. `hooks.md` said
`template_preprocess_symfony_mailer_lite_email()` sets "a fresh
`Drupal\Core\Template\Attribute` object", but `.module:48` is
`new Attribute()` in a file with **no `use` statements and no namespace**, so
the name resolves to PHP's global `\Attribute` — the doc asserted an FQCN its
own cited file never names (an upstream bug the doc silently repaired). Needs:
resolve a bare class name in a given file against that file's
imports/namespace before believing the doc's FQCN. Structurally out of reach
of the `Drupal\<module>\…`-only FQCN check, since the asserted class is a core
one.

### Config-shape errors in YAML examples escape every check — 2026-08-21

Surfaced analysing the generated `dc-better-exposed-filters` 7.1.3 skill: the
discover `ai-integration.md` wrote BEF's `views.view.*` example with a
`configuration:` wrapper around each widget's settings; the persisted shape is
flat (schema `better_exposed_filters_filter_widget`; fixture
`tests/modules/bef_test/config/install/views.view.bef_test.yml`). The
`configuration` key exists only in the Views UI *form array*, which is where
the explorer picked it up; the generator copied it into 4 snippets and an
agent following them gets silently-ignored settings.

**Make side shipped 2026-08-26** (`make-skill/scripts/verify.py`:
every ```yaml fence must parse, duplicate keys → PROBLEM, identifier-like
scalar values must occur in the discover docs → WARNING; step-7 rule that an
example's every key/value comes from the docs). **Discover side still open**:
mechanize in the discover `verify.py` — parse every ```yaml fence, locate the
module's `config/schema/*.yml` mapping for its root key, and flag keys the
schema does not declare (a minimal indented-mapping reader now exists in the
generate verifier and can be lifted). Explorer-rule alternative: every config
example in `configuration`/`ai-integration` must be derived from a schema
mapping or an exported fixture under `tests/**/config/**`, and say which.

### Decorator/subclass call-graph: an override changes inherited methods too

*Found 2026-08-26, sitewide_alert 3.1.2 audit.* `SitewideAlertDomainManager
extends SitewideAlertManager` and overrides one method; the doc concluded the
other inherited methods were "unaffected", but `nextScheduledChange()`
(`SitewideAlertManager.php:125`) reaches the **override** through `$this->`
at `:158`, so the real behaviour is asymmetric and propagates into cache
max-age and the JSON endpoint's `Expires` header. An inference error about PHP
dispatch — every symbol and line was right, so grounding checks are blind to it.
**Prompt rule shipped 2026-08-26** in both explorer agents (never call an
inherited method "unaffected" without tracing its body for `$this->` calls to
the overridden method). **Mechanical half still open, narrow**: when a doc says
a class overrides exactly one method *and* names other methods as unaffected,
grep the parent class body for `$this-><overridden>(` and flag any hit.

### Port `check_citation_anchoring()` to the module `verify.py` — 2026-08-26

*Found auditing canvas 1.10.1 (`/drop-context:audit-docs canvas`).* The same wrong
citation appeared in **three** files (`hooks.md:19`, `extension-points.md` §1,
`ai-integration.md` §5): all three attributed the "this hook will be superseded
by core's `hook_importmap_alter()` once `drupal.org/i/3398525` lands" note to
`canvas.api.php:84`. That note is a `@todo` **code comment at
`src/GlobalImports.php:84`** — `canvas.api.php` never mentions issue 3398525 and
its line 84 is unrelated media-bundle example code. Right line number, wrong
file: the classic shape of a file name reconstructed from a nearby `@see`
instead of read.

The **core-library** `verify.py` already has exactly the check that catches
this — `check_citation_anchoring()`
(`ai/skills/document-core-library/scripts/verify.py:295`): for a Markdown
line that both names backticked symbols and carries a `path:line`, at least one
named symbol must occur in a window around the cited line; when none does but a
named symbol occurs *elsewhere* in the cited file, it warns. Here the doc line
names `hook_canvas_importmap_alter()`, which occurs in `canvas.api.php` at 134
but nowhere near 84 → it would have fired on all three files.

The **module** `verify.py` has no equivalent. Its nearest check,
`check_invocation_sites()` (`:989`), only fires for `Class::method()` sitting
*immediately* next to the citation, which this prose never was. Port the
core-library implementation (WARNING, not PROBLEM — same heuristic caveats
apply: a sentence may cite several facts). Note the message would read "wrong
lines of the right file" for a wrong-file case like this one; still enough to
surface it.

Related prompt half, cheap: an explorer that cites `path:line` must have read
that file — say so in the explorer contract, since the failure mode is
reconstructing the *name* while carrying the *number* over correctly.

### "Cited line is a comment, not a call" — a distinct citation failure — 2026-08-26

*Found in the same canvas 1.10.1 audit, and the highest-severity error there.*
`ai-integration.md` §5 told an agent that
`ShapeMatchingHooks::mediaLibraryStorablePropShapeAlter()` "uses it this way
(`src/Hook/ShapeMatchingHooks.php:358-359`) and is a working template" for
`ReferenceFieldTypePropExpression::withAdditionalBranch()`. Lines 358-359 are:

```php
// ReferenceFieldTypePropExpression::withAdditionalBranch().
// @see \Drupal\canvas\PropExpressions\StructuredData\ReferenceFieldTypePropExpression::withAdditionalBranch()
```

— a comment *mentioning* the method. That method never calls it; it builds the
equivalent shape directly (`:353-363`). The only real call in non-test source is
`canvas.api.php:101`. So a consumer agent following the "working template" finds
nothing to copy.

Citation anchoring (above) does **not** catch this: the named symbol *does*
occur at the cited line, so the citation looks anchored. This is a separate
check: when a doc sentence asserts invocation ("calls", "uses", "invokes",
"dispatched from", "template for") about a symbol and the cited line lands in a
comment or docblock, flag it. The machinery already exists — `mask_php()`
(`:155`) blanks comment contents while preserving offsets, so "is this line
code or comment?" is a lookup, not a parse. Suggested severity: PROBLEM when the
symbol occurs *only* in comments within the cited span, WARNING when the span
mixes both.

Prompt half (probably ship first): the explorers' verify-call-sites rule already
says never to accept an inferred dispatch site — extend it to "a citation
supporting a *usage* claim must land on the call itself; an `@see` or a comment
naming the symbol is not a usage site."

### `verify.py` recall warnings ignore `submodules_skipped` — 2026-08-26

*Found in the canvas 1.10.1 audit (a deliberate root-only run).* The verifier
emitted four WARNINGs that were all expected-by-design: 21 `FunctionCall`
plugin ids (all from `modules/canvas_ai/`), one `Oauth2Grant` and one
`ScopeGranularity` (both `modules/canvas_headless/`), and one library from
`themes/canvas_stark/`. Every one lives in a submodule the run deliberately
skipped, and both `metadata.json` (`submodules_skipped`, 11 entries) and
`summary.md` say so.

`verify.py` already parses and shape-validates `submodules_skipped` and prints
`SUBMODULES_SKIPPED=n` (`:1650-1672`, `:1799`), and already uses the names to
skip FQCN namespaces (`:1743`) — but the recall checks don't consult it:
`check_libraries()` (`:1240`) and the plugin-id recall path iterate all source
files filtering only `TEST_DIRS`. Fix: scope both recall checks out of the `dir`
of every skipped submodule. Low effort, and it matters because these warnings
are indistinguishable from real recall gaps — on a root-only run of a large
ecosystem they are the *majority* of the verifier's output, which trains a
reader to skim past the real ones.

## Core-library pipeline (document-core-library)

*Skill + `drupal-core-library-explorer` agent landed 2026-08-24. First four
runs (Core/Batch, Core/Flood, Core/Hook, Core/Queue on 11.4.4) were audited
the same day against source: 0 HIGH, 6 MEDIUM, 11 LOW, ~8 citations pointing
at the wrong method of the right file. No fabricated symbol, signature,
service ID or example — the errors were mechanism-attribution, omitted
preconditions, and one sibling-file contradiction. MEDIUMs fixed by scoped
follow-up explorers; `verify.py` gained the wider citation regex, line-range
support, and the anchoring WARNING described below.*

### Distributed path (survey → research → synthesis) — first run audited 2026-08-25

*Originally (2026-08-24): all four runs took the `direct` path (Hook: 20
files / 1,955 lines, 45 lines under the 2,000 threshold), so the `PLAN`
parsing, `owned_paths` coverage, research notes, and synthesis manifest were
untested end to end.*

**Core/Ajax (40 files / 2,371 lines) ran 2026-08-25**: 4 workstreams
(`command-protocol-catalog`, `dialog-command-family`,
`response-attachment-delivery`, `runtime-integration`), every one of the 40
PHP files named in at least one research note, 4 root docs + 1 topic
(`topics/dialogs-modals-and-off-canvas.md`), `VERIFY OK`, no contradiction
between the five files. Three-auditor review against source: **0 HIGH,
3 MEDIUM, ~6 LOW, ~10 loose citations**. The MEDIUMs: `hook_ajax_render`
named in two files (the hook is `hook_ajax_render_alter`; the wrong name was
already in the `response-attachment-delivery` research note and synthesis
propagated it — a research-wave error the synthesis wave cannot catch since
it trusts the notes by design), and `#ajax` library attachment presented as
unconditional (it needs a resolvable `event`,
`RenderElementBase::preRenderAjaxForm()`). Main weakness is coverage rather
than accuracy: the `#ajax` key defaults, `Html::getUniqueId()`'s Ajax id
suffix (the classic wrong-`wrapper` bug), `data-dialog-renderer` (the only
link path to off-canvas), `drupalAutoButtons`, and `AjaxRenderer`'s
status-message prepend were all absent. Fixed by two scoped follow-ups.

Two contract deviations observed, **both closed 2026-08-26**: (1) the
synthesis worker also wrote a full copy of the final docs into
`WORK_DIR/final-output/` — the agent contract now forbids any copy under
`WORK_DIR`; (2) `api.md` was rewritten ~12 minutes after `metadata.json` with
no record of why — the skill's final report now logs every post-verify
follow-up (triggering `PROBLEM:`/`WARNING:` lines → files rewritten).

Next: `Core/Plugin` (61 / 4,924) as the first genuinely multi-shard run.

### Hook-name check shipped in `verify.py` — 2026-08-25

Promoted from the Ajax audit: every backticked `hook_*` must be declared as
`function hook_*(` in a core `*.api.php`; placeholder hooks
(`hook_ENTITY_TYPE_insert`, `hook_form_FORM_ID_alter`) match by pattern.
Undeclared → `PROBLEM:` (with a "did you mean `<name>_alter`" hint);
undeclared but present as a word in core source (`hook_data`, `hook_list` —
key-value keys in the Hook library docs) → `WARNING:`. Caught the
`hook_ajax_render` error on the first run. The module-pipeline `verify.py`
has an equivalent check; consider aligning the two placeholder-matching
implementations if either grows.

### Citation anchoring heuristic: WARNING, not PROBLEM — 2026-08-24

`verify.py` now warns when a `path:line` citation on a Markdown line lands
outside a window around every symbol that line names (and outside the
enclosing function). On the pre-fix docs it hit 3 real wrong-method citations
and ~3 multi-fact sentences (a paragraph naming `batch_process()` and citing
the `_batch_populate_queue()` line it calls). Promote to PROBLEM only if the
explorer contract makes sentences cite one fact per citation, or if the
check learns to pair each citation with the nearest preceding symbol instead
of pooling the whole line.

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

## Release maintenance skills (retag-docs / add-release)

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

## Make pipeline (make-skill)

*No open items — the 2026-08-21/22 entries (entity reference routing, YAML
example checks, DOM contract) shipped 2026-08-26; see Done.*

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

### `list_skills`/`get_skill` MCP tools

*Added 2026-08-27, scoping the MCP stdio migration (see `drupal-site/AGENTS.md`
"API for the CLI/MCP").* The migration to `drop-context-mcp` (stdio) ported only
the 6 tools the site's own MCP server already had: `list_modules`, `get_module`,
`get_doc`, `list_core_libraries`, `get_core_library`, `get_core_library_doc`.
Skills (`skill:add` et al.) stayed CLI-only, on purpose — deferred, not
dropped. A `list_skills`/`get_skill` tool pair, mirroring the module-docs
shape, would let an agent discover and read a skill's `SKILL.md`/references
live without installing it into a project. Needs a `Catalog/SkillCatalog` port
in `drop-context` (the `drupal_context_skill` and `paragraph_skill_reference`
entity_gateway resources already exist, for the `skill:*` commands' own use —
reuse or extend those).

### Sparse fieldsets on the entity_gateway (avoid over-fetching `field_content`)

*Added 2026-08-27, same migration.* `ModuleDocsCatalog::tableOfContents()` in
`drop-context` fetches every `module_doc` row for a release (via
`CatalogRepository::docsForRelease()`) just to build the table of contents —
the gateway has no sparse-fieldset query parameter, so every doc's whole
Markdown body (`field_content`) travels over the wire even though the TOC only
needs `sourceFile`/`title`/`docCategory`/`weight`/`submodule`. It's cached (one
fetch per release per cache generation, not per call), so this is wasted bytes
rather than a hot-path cost, but it is wasted on every cache miss / stamp
invalidation. `entity_gateway` (`joaopauloctga/entity_gateway`, a separate
repo this workspace only depends on) has no such parameter at all — see its
own `docs/querying.md` — so this is a feature request to file there, not
something fixable in `drupal-site` or `drop-context` alone.

### "Documented release" without a doc — a rule the CLI defers

*Added 2026-08-27, same migration.* `drop-context`'s `Catalog/ModuleDocsCatalog`
considers a `module_release` "documented" (and lists it in `available_releases`)
once it exists and is published — unlike `drupal-site`'s own (now-removed)
`ModuleReleaseResolver`, it does not check the release actually carries ≥1
published `module_doc`, since that would cost one extra gateway request per
release just to build a list (documented as an accepted deviation in
`drupal-site/AGENTS.md` "API for the CLI/MCP"). If a release with zero docs
ever shows up in practice (e.g. `dc:import-docs` created a bare stub before any
`module_doc` was imported for it), `get_module`/`get_doc` would show it with
`docs: []` rather than hiding it — decide then whether that's acceptable, or
whether the extra per-release request (or the sparse-fieldsets item above,
which would make that request cheap) is worth adding.

### `skill:update`/`skill:outdated` — real staleness detection

*Found 2026-08-24, while adding the site's `field_skill_version` /
`skillVersion`.* The site now stamps and serves a monotonically-increasing
version on every skill, and `drop-context` records it in `app.json`
(`SkillValueObject::$version`, populated from `SkillRow::$version` /
`skillVersion` instead of the old hardcoded `"1.0.0"`). That is necessary but
not sufficient for "is my installed skill stale?": `app.json` still records
no skill `uuid`, no source, and no gateway URL for an installed skill, so
there is nothing to re-query against later. A real `skill:update`/
`skill:outdated` needs at least the `uuid` (or title+module) and the gateway
base URL persisted per installed skill, so the CLI can look the skill back up
and compare versions.

## Done

- **Mechanization round + explorer-rule batch** — 2026-08-26, from the
  2026-08-19…26 audit backlog (block, views ×2, symfony_mailer_lite, ai
  1.4.7, sitewide_alert, eca skill). Nothing here is A/B-validated yet — see
  the pending A/B entry above.
  - **Discover `verify.py`** (both copies byte-identical; 445 → ~1,800 lines):
    doc-only *stated count vs enumeration* (inline runs flagged only when
    they name **more** than stated; a `:`-terminated lead-in vs the
    table/list below in both directions; "plus N" additive; parenthetical
    and grouped-bullet aware) and *cross-file citation divergence*
    (overlap ≥ 2 lines, neither range containing the other); with
    `--module-root`: *cited code spans* must be literal substrings of the
    cited lines ±2 (call chains → PROBLEM, `$var = value` idioms →
    WARNING), *invocation sites* (`Class::method()` adjacent to a
    `path:line` of that class's file must land inside that method —
    docblock/attribute head included, brace-depth function bounds over a
    string/comment-masked PHP text), *plugin ids* in `Plugin ID` table
    columns vs attribute/annotation declarations anywhere in the source
    (keyword `id:`, positional, `@Annotation(id = …)` and `@Annotation("…")`;
    abstract classes excluded; the row's class resolved by FQCN or unique
    short name; recall as one aggregated WARNING per plugin type),
    *libraries* (`*.libraries.yml` top-level keys), *`@deprecated`*
    (public symbols → one PROBLEM per source file; protected/private →
    WARNING), *bare module-named class names* (WARNING; generic framework
    names skipped on purpose — every one on the corpus was a real core
    class), *runtime-interpolated ids* no longer warned (suffix found after
    a quote/`}`/`$var`), and negation context widened from the line to the
    **sentence** (docs hard-wrap, so "does not ship a\n`x.libraries.yml`"
    had been slipping through — the 2026-08-23 roadmap entry was not stale
    after all). New `--partial --module <name>` mode = the **wave-1 gate**
    both discover skills now run after step 3 (content checks only;
    libraries/deprecations skipped because synthesis files own them).
    Calibration on the 67 existing doc sets (all previously `VERIFY OK`):
    first cut 387 PROBLEMs, final 12 — and every one of the 12 is a real
    defect in a never-audited set (ai_agents "11 concrete subclasses" naming
    12; ctools "8 abstract methods" naming 9; core `node` "six" action
    config entities listing 8 `.yml` files; feeds "Two
    supporting plugin types" + 5-row table; key "Two supplementary
    interfaces" + 4 items; search_api "Two reusable base types" + 3;
    `AgentHelper::runSubAgent()` cited at lines that sit in
    `runAiProvider()`; a synthesized `$this->get('entity_id')->first()->set(…)`
    chain in workflow; `workflow_transition_timestamp` listed as a plugin id
    on a class with no annotation; 11 deprecated public `ChatOutput` token
    methods undocumented in `ai`). Seeded-fixture acceptance: 8/8 classes
    caught on a sitewide_alert copy, `mapping`/`links` abstract ids caught on
    installed-core views. Measurement caveat: macOS purges `$TMPDIR` caches
    older than ~3 days, so only 7 modules had intact source — the other
    cached sets produced spurious FQCN failures from the *old* check, not
    the new ones.
  - **Explorer agents** (`drupal-module-explorer`, condensed in
    `drupal-submodule-explorer`): provenance outside `MODULE_ROOT` (omit or
    hedge; never a value for code not read — merged with the lifecycle rule),
    subclass/decorator `$this->` dispatch tracing, quote provenance kind +
    `path:line`, cite-means-**copy** (scope words intact; a code span next to
    a citation is a literal substring), stale `api.php` docblocks documented
    *and* flagged, lead-in sentences recounted against their enumeration.
    Catalog ownership: install/update/post-update hooks and unowned
    core-hook implementations → `hooks`; `help_topics/*.html.twig` listed
    by name → `routes`; every `config/schema/*.yml` named → `configuration`;
    folder checklist + `Entity/Render/`, `Plugin/Block/`,
    `Plugin/Derivative/` (derivers named), `Breadcrumb/`,
    `ContextProvider/`, `PathProcessor/`, `EntityReferenceSelection/`,
    `Validation/`; `extension-points` records the DOM contract per theme
    hook (selectors the JS/AJAX depends on, attached libraries, template
    fallbacks) and enumerates every `*.libraries.yml` entry; deprecation
    sweep completeness rule.
  - **`make-skill`**: `references/entity.md` routing row (own
    entity types) with `fields.md` re-scoped to fields on *other* types;
    consumer-contract rule (the loader has only the skill — no pointers to
    the discover docs); YAML example rules. Its `verify.py` (366 → 872
    lines): dangling discover-doc pointers → PROBLEM, a stdlib YAML-subset
    reader (duplicate key → PROBLEM, unreadable → WARNING), identifier-like
    scalar values absent from the docs → WARNING, batch-relative phrases in
    `submodules-*.md` → WARNING. Validated on all 16 skill/doc pairs: 2
    PROBLEMs, both true (easy_email `services.md:127`, metatag
    `extend.md:238`), ~13 WARNINGs of which ~6 are noise.
  - **Core-library pipeline**: consistency pass before returning (both
    modes; declaration wins), manifest `symbols` = every documented FQCN,
    synthesis writes only to `OUTPUT_DIR`, follow-up log in the final
    report, `prepare.py` `related_tests` also scans `core/modules/*/tests/**`
    (Batch 4 → 8, Queue 7 → 19 related tests; `batch_test/src/BatchTestCallbacks.php`
    still missed — it never names the namespace), `WORK_DIR` removed after
    `VERIFY OK` unless asked to keep.
  - **eca 3.1.6 doc fallout** from the 2026-08-22 skill review fixed by three
    scoped `drupal-submodule-explorer` runs against a fresh source download
    (`eca_development` `core_version_requirement`, `eca_form` `FormProcess
    implements RenderEventInterface`, `eca_views` batch-relative sentence);
    the set is `VERIFY OK` under the new checks (238 FQCNs, 408 ids, 212
    plugin ids).
  - **Not done, on purpose**: the A/B run (needs a baseline discover *before*
    prompt changes — the rules are shipped, so the next run of a
    submodule-bearing module is the "after"; use the 2026-08-25 ai 1.4.7 /
    2026-08-26 sitewide_alert audits as the "before" scored by class), the
    `release_line` decision, `.inc` coverage, Explorer B split, outline
    reader.
  - **Doc-set fallout fixed the same day** (user-requested, Sonnet explorers,
    one scoped fixer per file, verifier line quoted verbatim): the 12 defects
    above plus 6 more that surfaced once ctools/feeds/key/search_api had
    intact source again (`node_type` listed as a ctools plugin id on a class
    with no annotation; 1 + 4 deprecated public symbols undocumented in key /
    search_api → "Deprecations" sections in `ai-integration.md`). One fixer
    found the *substance* wrong, not just the citation — `ai_agents_explorer.md`
    had built an "upstream quirk" narrative on a `$promptFile` line that
    belongs to a different method. All 8 affected sets (ai_agents, ctools,
    feeds, key, search_api, core node 11.4.5, workflow, ai) are `VERIFY OK`
    under the new checks; standing WARNINGs are doc-composed ids
    (`feeds_feed.fid`), unnamed libraries (`ai/ai_setup_form`,
    `node/drupal.node.admin`, `feeds_log/feed_type_settings`) and plugin
    recall on the 52-plugin `AiAutomatorType` set.

- **Placeholder-aware FQCN resolution + negation-aware id warnings in
  verify.py** — 2026-08-21, from the views 11.3.13 re-audit that raised it.
  Both discover copies patched and kept byte-identical
  (`document-module/scripts/verify.py`,
  `document-core-module/verify.py`; `make-skill`'s verifier
  shares neither function and is untouched). (a) **Templates**: a `{…}`/`<…>`
  placeholder following an FQCN match is detected via `TEMPLATE_TAIL_RE` and
  the reference is resolved as a *namespace-dir* existence check instead of a
  class lookup — `Drupal\views\Attribute\Views{Type}` validates
  `src/Attribute/`, and a bogus namespace still PROBLEMs rather than being
  blindly skipped. (b) **Negation**: `NEGATION_RE` scans the containing line
  (bounded to ±200 chars) around a module-prefixed id and suppresses the
  warning when the sentence asserts absence. Deliberately does *not* mark the
  token seen, so the same id used affirmatively elsewhere still warns — a doc
  that denies a file exists and then uses it as real stays a detectable
  contradiction. Acceptance: 6-case seeded fixture, all correct (invented
  class → PROBLEM, real-namespace template → silent, bogus-namespace template
  → PROBLEM, affirmative invented id → WARNING, negated id → silent,
  negated-then-affirmative → WARNING). Regression-diffed against a
  reconstructed pre-change build on both doc sets whose source is still
  cached: `views` 4 false positives → `VERIFY OK` with FQCN_CHECKED=78 /
  IDS_CHECKED=110 unchanged in coverage; `views_filters_summary` 3 warnings
  suppressed, each manually confirmed to be an explicit "No `X` file exists in
  this module" assertion. No other output changed on either set.

- **Fact-discipline rules batch + module-prefixed id check** — 2026-08-20,
  from the metatag 2.2.0 and core media/block 11.4.5 audits. (a)
  `drupal-module-explorer` Behavioral Rules gained: **universal claims
  require enumeration** (the YAML item and its beyond-YAML extension, merged
  — trigger is the quantifier, not the format); **identifier strings come
  from declarations, never class names** (the media queue-id drift — the
  first intra-wave-1 error class); **lifecycle status only for symbols whose
  declaration you read** (the `system_region_list()` "removed" false
  inference); **never assert an unexecuted runtime outcome** (`php -r`
  reproduction or drop the claim); **quotation + attribution = verbatim text
  only** (the eca fabricated-quote case); **a library's behavior comes from
  its own `js:`/`css:` assets**, never `dependencies:`. Catalog additions:
  `plugins` documents annotation properties by their *effective definition
  key* (`absoluteUrl` vs `absolute_url`); `hooks` requires a cited invocation
  site for every api.php hook or an explicit "declared but not invoked" note,
  and `extension-points` carries that caveat forward; the synthesis
  grounding rules gained **"cite means entail"** (a `see X.md` sentence must
  restate X.md; self-derived claims carry no fact-base citation).
  `drupal-submodule-explorer` got condensed versions of the five
  fact-discipline rules. (b) `verify.py` (both copies): every backticked
  module-prefixed id string (`<module>_…`/`<module>.…`) in the docs must
  occur in the module source (contents or paths) — **WARNING**, not PROBLEM,
  since runtime-derived ids exist; dotted tokens pass via dotted-prefix
  leniency (config-object + key paths). Both discover SKILL.md step 8s tell
  the orchestrator how to judge the warning. Acceptance: synthetic fixture
  catches the invented `media_thumbnail_downloader` and an invented
  `media.totally_fake` while passing real ids and config paths; regression
  on metatag 2.2.0 (94 ids), core block 11.4.5 (39) → zero warnings; core
  media 11.4.5 (51) → one borderline (doc-composed
  `media_type.queue_thumbnail_downloads`). **A/B validation pending** — fold
  into the pending submodule-wave A/B run above.
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
  `make-skill/scripts/verify.py` (stdlib-only, single copy — the
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
  recommendation; new `retag-docs` (retag in place across a tiny
  delta, mechanical diff-quotable edits only, verify.py-gated) and new
  `add-release` (new doc set alongside the old; diff-affected
  categories regenerated by scoped explorers, synthesis categories re-run
  whenever a wave-1 category changed — the grounding caveat this item
  recorded). Boundaries documented in `README.md` ("Release maintenance:
  which skill when") with eca 3.0.14→3.1.0 (upgrade) vs eca 2.1.x→3.0.x
  (full discover) as the calibration examples. *(Same day, consolidated
  further: `discover-module-release` was dissolved — the user picks
  update vs upgrade themselves via the README + the d.o release page, and
  each of the two skills generates the `release.json` itself; the shared
  references moved to `retag-docs/references/`.)*
- **Pack scripts / importer format mismatch** — resolved by design during the
  per-release rework (2026-08): the site's `dc:import-docs` reads the new
  `~/.drupal-context`-shaped layout (`metadata.json`, header-less files,
  optional `release.json`) directly from `content/modules/`; the ZIP
  `pack-*.sh` path is dead, not fixed. The old "known-broken pipeline link"
  roadmap entry is superseded.

## verify.py: plugin-id resolver misses constant-valued and FQ-named attributes (2026-08-26)

Surfaced during `/drop-context:document-module canvas 1.10.1`. The `Plugin ID` check in
`ai/skills/document-module/scripts/verify.py` reported
`carries no plugin attribute/annotation` for **24 of ~30** documented plugin ids that
were in fact all correct. Two distinct parser gaps:

1. **`id: self::PLUGIN_ID`** — Canvas declares nearly every plugin id as a class
   constant and references it from the attribute (`#[Adapter(id: self::PLUGIN_ID, …)]`,
   `#[RenderElement(self::PLUGIN_ID)]`). The resolver only matches a literal string,
   so it sees the attribute but resolves no id. Fix: when the id argument is
   `self::CONST` / `static::CONST`, look up that `const` in the same class and use its
   literal value.
2. **Fully-qualified attribute names** — `#[\Drupal\Core\Validation\Attribute\Constraint(
   id: 'ColorComponentCount', …)]` is missed entirely because the attribute regex
   expects a short name. Fix: tolerate a leading `\` and any namespace prefix, matching
   on the last segment.

Impact: a real error (`computed_label`, which should have been
`computed_list_string_label`) was buried in 23 false positives, and `VERIFY FAILED`
stayed permanently red with no doc edit able to clear it. Both gaps are mechanical and
worth fixing before the next audited run — the false-positive noise defeats the gate's
purpose on any module that uses constant-valued plugin ids, which is now common style.

Related, lower priority: the **class-reference** resolver has no notion of negation, so
a doc that deliberately warns "there is no `Foo\Bar` class" trips
`unresolvable class reference`. The module-prefixed-id check already excludes negated
mentions; the class-reference check should do the same.

**Re-confirmed 2026-08-26** by an independent `/drop-context:audit-docs canvas` pass: all
**24** remaining `PROBLEM:` lines were checked one by one against the source and every
flagged class does carry its attribute with a matching id — 22 of the constant-valued
form (`id: self::PLUGIN_ID` / `#[RenderElement(self::PLUGIN_ID)]`) and 2 of the
fully-qualified form (`ColorComponentCountConstraint`,
`OneFolderPerItemLimitConstraint`). The `computed_label` error this entry mentions was
already corrected in the original run, so the set is now **100% false positive**, and
`VERIFY FAILED` is unclearable by any doc edit: the gate is permanently red on this
module and silently useless for catching a *real* future plugin-id error in it. That
raises the priority — this is no longer just noise, it is a disabled check.

---

## 2026-08-26 — `node` discover docs never spell `Drupal\node\NodeInterface`

Found while orchestrating the core-module skill-generation batch (12 skills). The
`node` docs at `~/.drupal-context/core/11.4.5/node/` name `NodeInterface` in the
short form ~7 times — `entities.md:10`/`:55`/`:57`, `plugins.md:13-15`,
`ai-integration.md:23`/`:58`, including the exact hook signatures
`hook_node_access_records(NodeInterface $node): array` and
`hook_node_links_alter(&$links, NodeInterface $entity, &$context)` — but never once
write the FQCN. Only `Drupal\node\Entity\Node` is spelled out.

Consequence for the *generate* stage: a correct PHP example needs the `use` statement,
and `use Drupal\node\NodeInterface;` is a hard `PROBLEM` from `verify.py`'s grounding
check (the FQCN is real — `core/modules/node/src/NodeInterface.php`, namespace
`Drupal\node` — the docs just never state it). The gate is unclearable without
weakening the example, so `dc-node` shipped with the import replaced by a prose note
and the type hint kept. Same shape as the "unclearable gate" entry above, but caused
by an *omission* in the docs rather than a resolver bug.

Fix direction: the explorer/discover contract should require the **first mention** of
an interface or class in `entities.md` to carry its FQCN (it already does this for
classes — `Drupal\node\Entity\Node`, `Drupal\Core\Entity\EditorialContentEntityBase` —
just not for the entity's own interface). Cheap, and it removes a whole class of
false grounding failures for every module whose entity interface gets referenced in
hook signatures.

### Fixed in passing (same session)

`verify.py`'s `HOOK_RE` was `hook_[a-z0-9_]+`, which stops at the first upper-case
char. For `hook_migrate_MIGRATION_ID_prepare_row` (verbatim in `migrate`'s
`hooks.md:22`, `extension-points.md:215`, `plugins.md:51`) it extracted the bare
prefix `hook_migrate_`, which `grounded()` can never match because it requires the
token not be a prefix of a longer symbol — a permanent false `PROBLEM` on `dc-migrate`.
Widened to `hook_[A-Za-z0-9_]+`. Strictly better: `dc-migrate` went from 0 verifiable
hooks to `HOOKS_CHECKED=8`, all grounded, and no other generated skill regressed.

## 2026-08-27 — mechanize the quotation-drift check (core-library track)

Deferred from the `Core/Cache` 11.4.4 fact-check round (see
`IMPROVEMENT-HISTORY.md`, "The 2026-08-27 core-library round"). Four defects in
that run were **quotation drift**: text inside quote marks that is not a literal
substring of the cited source. The worst was silent normalization of a typo in
core — `CacheTagsChecksumInterface.php:39` really says "Returns the sum total of
**validations** for a given set of tags", and the doc quoted it as
"invalidations", attributing wording to core that core does not use.

Shipped for now: the explorer rule "quote verbatim or do not use quotation marks".

Mechanical direction: the core-library `verify.py` already has the ingredients —
`check_citation_anchoring()` resolves a `path:line` citation on the same Markdown
line, and the module-track `verify.py` already ships a **cited-span check** (a
code span quoted next to a citation must be a literal substring of those lines,
2026-08-26). Extend that idea from code spans to *prose* quotes: for a
double-quoted run of ≥6 words on a line that also carries a `core/...:line`
citation, require it to appear verbatim in a window around the cited line,
normalizing only whitespace and Markdown hard-wraps. WARNING-level to start —
docs legitimately quote across a wrap, and quoting a docblock sentence
reflowed onto one line is the common case, so the normalizer is the whole
difficulty. Calibrate against all documented libraries as usual; any flag on
the existing corpus is a false positive until read.

## drupal-site: `skills` view page order was non-deterministic (2026-08-28, fixed same day)

Surfaced by the preprocess-standardization regression snapshots
(`drupal-site/plans/preprocess-standardization.md`): `/skills` showed a different
page-1 subset after every cache rebuild. Root cause was worse than a tie: the
view's only sort was `node_field_data.created` (a leftover from a node-based
view) — Views could not join it to the `drupal_context` base table and emitted a
bare `ORDER BY "created"`, which MySQL resolved by accident and which ties on the
import batch's shared timestamp. Fixed in `views.view.skills` (default display,
inherited by page/my_skills/block_by_module): `drupal_context.changed DESC`,
then `title ASC` as the deterministic tie-break. Still worth checking on
`context_modules` / `core_lib` whenever a bulk import lands many entities in
one second — a `title`/`id` secondary sort costs nothing.

## make-skill: `composer require` constraint breaks on legacy `8.x-N.M` version tags (2026-08-29, found during batch skill generation)

Surfaced by an Opus validator pass while batch-generating skills for the 30
modules discovered but not yet generate-skilled. `field_permissions` (version
tag `8.x-1.5`) got `composer require 'drupal/field_permissions:^8.x-1.5'` in
its SKILL.md — Composer's `VersionParser` cannot parse `^8.x-1.5` at all
(confirmed with Composer 2.8.10), so the copy-pasteable install command
hard-fails. Root cause is the generator template's literal substitution at
`ai/skills/make-skill/SKILL.md:292`: `drupal/{module}:^{version}`,
which is only valid for semver-shaped versions. It happened to come out right
for `key` (`8.x-1.22` → `^1.22`) and `feeds` (`8.x-3.2` → `^3.2`) only because
those two runs caught and fixed it ad hoc — it is not handled systematically.

Fix: in the generator template, strip a leading `8.x-` from `{version}` before
building the composer constraint (`8.x-1.5` → `^1.5`), matching the pattern
already used ad hoc for `key`/`feeds`. Worth an audit pass over all previously
generated skills for modules with legacy `8.x-N.M` tags to catch any other
instance of this same bug.

## make-skill: generated prose sometimes points readers at doc-set filenames instead of skill references (2026-08-29, found during batch skill generation)

Surfaced by Opus validators during the same batch run as the composer-constraint
bug above. Two independent instances so far: `rabbit_hole/1.2/references/use.md`
had a heading "(see ai-integration for the full source-verified list)", and
`rabbit_hole/1.2/references/submodules.md` pointed a reader at `use.md` for a
fact that actually lives in `plugins.md`. The first class is worse: a consumer
of the generated skill only ever has the skill's own `references/*.md` — it has
no access to the discover doc set (`summary.md`, `ai-integration.md`, etc.) —
so a pointer at a discover-doc name is a dead end for whoever installs the
skill. Root cause: the generator's step-6 routing-table rules don't forbid
naming discover-doc filenames in prose, and cross-reference pointers between
the skill's own reference files aren't checked for correctness (only for
existence — `verify.py` checks referenced files exist, not that the fact
being pointed at is actually where the pointer says).

Fix direction: add a `verify.py` check (or a generation-time reminder) that
flags any prose mention of a discover-doc-only filename
(`summary.md`, `entities.md`, `plugins.md`, `services.md`, `configuration.md`,
`permissions.md`, `routes.md`, `hooks.md`, `events.md`, `extension-points.md`,
`ai-integration.md`) inside a generated skill file — those names should never
leak into consumer-facing output.

## make-skill: unquoted `generated_at` timestamp can break YAML-timestamp-sensitive tooling (2026-08-29, found during batch skill generation)

Surfaced by an Opus validator on `tool/1.0.0-beta6`. The generator template
(`ai/skills/make-skill/SKILL.md:315`) emits `generated_at:
2026-08-29T17:24:19Z` unquoted in every skill's frontmatter. Standard YAML
resolves that shape to a native timestamp type, not a string. Harmless for the
Symfony YAML parser used in these validation passes, but `verify.py:726` runs
a regex directly against that value — under a stricter/different YAML loader
that resolves timestamps, this would throw a TypeError instead of matching.
Fix: quote the value in the template (`generated_at: "2026-08-29T17:24:19Z"`)
so it's unambiguously a string everywhere it's consumed.
