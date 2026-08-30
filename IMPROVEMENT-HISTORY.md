# Discover pipeline — improvement history & lessons

Background for future skill-improvement sessions. This is the distilled record
of the 2026-08-13 improvement series (7 discover runs, 7 audits, ~10 shipped
changes). Read this before touching `document-module`,
`document-core-module`, or `agents/drupal-module-explorer.md`.
Deferred work lives in `ROADMAP.md`; the reusable audit protocol in
the `audit-docs` skill.

## Current architecture (as of 2026-08-26)

1. **Download + GATE** — one bundled script run (`scripts/download.py` /
   `download-core-module.sh`): fetch → validate `.info.yml` → create
   OUTPUT_DIR → enumerate submodules → machine-parseable `GATE OK` block.
2. **Wave 1** — Explorers A (key-facts/configuration/permissions/routes) and
   B (entities/plugins/services/hooks/events) in parallel
   (`drupal-module-explorer`). Each writes its files directly and returns a
   JSON manifest.
   **Wave-1 gate (2026-08-26)** — before anything is grounded in these
   files, `verify.py --partial --module <name> --module-root MODULE_ROOT`
   runs the content checks below on what exists; a `PROBLEM:` here is fixed
   by a scoped follow-up explorer *before* the submodule wave, because a
   wrong wave-1 fact propagates into every later file by construction.
3. **Submodule wave** — `drupal-submodule-explorer` batches (≤8 submodules
   each, parallel) run **after** wave 1: the agent is grounded by design —
   it requires the category files in OUTPUT_DIR and copies parent-symbol
   facts from them (targeted parent grep only as fallback), writes condensed
   `submodules/*.md`, and reports conflicts via `=== DISCREPANCIES ===`. A
   contrib-only **submodule scope** ("without submodules" / "only
   submodules") can skip this wave or run it alone as a completion pass;
   skipped submodules are recorded in `metadata.json` `submodules_skipped`.
   *(Sequencing changed 2026-08-17 — full-run A/B validation pending; the
   grounding mechanism itself is the one validated in runs 7–8.)*
4. **Synthesis wave** — Explorer C (extension-points + ai-integration, the
   *synthesis* categories) runs last, reads all earlier files (submodules
   included) as its verified fact base, reads source only for the guidance
   layer and facts the base lacks, and reports conflicts via an optional
   `=== DISCREPANCIES ===` block → orchestrator spawns one follow-up
   explorer to fix the disputed file.
5. **Orchestrator** writes `summary.md` + `metadata.json` only.
6. **Verify** — `scripts/verify.py OUTPUT_DIR --submodules N --module-root
   MODULE_ROOT`: metadata/file cross-checks both directions, the
   `submodules_skipped` consistency checks, **plus PSR-4 validation of every
   `Drupal\<module>\…` FQCN in the docs** (submodule namespaces — documented
   or skipped — resolve to their own `src/`, found via `<sub>.info.yml`).
   Unresolvable FQCN = PROBLEM = an invented class name. Since 2026-08-20
   also checks every backticked module-prefixed id string
   (`<module>_…`/`<module>.…`) for existence in the source — WARNING-level,
   the invented-id counterpart to the FQCN check. **Since 2026-08-26** it
   also mechanizes the classes the later audits kept hitting: a stated
   count vs the enumeration it introduces (PROBLEM), a code span quoted next
   to a `path:line` citation that is not in those lines (PROBLEM/WARNING), a
   `Class::method()` + `path:line` pair whose line lies in another method
   (PROBLEM), a `Plugin ID` table id no non-abstract class declares
   (PROBLEM), `@deprecated` public symbols no doc names (PROBLEM), and —
   WARNING-level — two files citing one file with overlapping unequal
   ranges, `*.libraries.yml` entries and plugin ids no doc names, and bare
   module-named class names that exist nowhere. Negation context is the
   sentence, runtime-interpolated ids are exempt. Calibrated on the 67
   existing doc sets: 387 → 12 PROBLEMs, all 12 real (see the 2026-08-26
   round below).

## The empirical series

| # | Run | Model/effort | Flow | Synthesis (C) errors | Notes |
|---|-----|--------------|------|----------------------|-------|
| 1 | workflow 2.2.2 | weaker agent, pre-fixes | old | — | 8 gaps: entire `WorkflowTargetEntity` API class missing, ~20 procedural helpers uninventoried, migrations/state + field_type_categories + README unused, "8 hooks" miscount (real: 14), submodule "presumably" hedge |
| 2 | flag 5.0.3 (1st) | — | old | 1 + gaps | `ActionLinkFlashCommand` orphan, migrations/state again, **events dispatch-site contradiction B×C** |
| 3 | flag 5.0.3 (2nd) | Opus 5 | old | 0 | all regression points fixed; method tables verified 18/18 |
| 4 | flag 5.0.3 (3rd) | Sonnet 5 default | old | 3 | `CountLink` wrong namespace, "tokens work" (no `hook_tokens()` exists), `Reload` "must be subclassed" — **all 3 already correct in wave-1 files** |
| 5 | feeds 8.x-3.2 | Sonnet 5 **max** | old | 0 | ~27 claims verified; huge token cost |
| 6 | feeds (Run A) | Sonnet 5 **high** | old | 2 (+1 minor) | invented `Feed::deleteMultiple()`, wrong `TargetBase` examples — **both correct in wave-1 files** |
| 7 | feeds (Run B) | Sonnet 5 high | **two-wave** | 1 | contradiction class **2 → 0**; residual = invented `FetcherBase` (a *new* fact, fact base silent). Output sharper, not shallower — anchoring fear did not materialize |
| 8 | better_exposed_filters 7.1.3 | Sonnet 5 high | two-wave + FQCN | **0** | clean audit (~25 claims, incl. dual attribute/annotation discovery and the full theming chain); `FQCN_CHECKED=15`; correction cycle visibly fired (files rewritten post-C) |

**The decisive stat**: across runs 2–6, **6 of 6** synthesis errors were facts
already written correctly in wave-1 files of the same run. That is what
justified the two-wave grounding — contradictions were eliminated *by
construction*, not by review.

## Error taxonomy → which mechanism covers it

| Error class | Example | Covered by |
|---|---|---|
| Fact contradicts wave-1 file | events dispatch site; tokens claim | **Two-wave grounding** + DISCREPANCIES protocol |
| Invented class / wrong namespace | `FetcherBase`; `Drupal\flag\…\CountLink` | **FQCN check in verify.py** (acceptance-tested on both) |
| Invented/wrong **method** | `Feed::deleteMultiple()` | call-site rule (partial); mechanical check deferred (ROADMAP: inheritance-aware resolution) |
| Unverified counts | "8 documented hooks" (real: 14) | no-underived-counts behavioral rule |
| Orphan public classes | `WorkflowTargetEntity`, `ActionLinkFlashCommand` | inheritance-based class sweep (`extends/implements Drupal\Core|Component` ⇒ must be documented) + folder checklist |
| Procedural API invisible | ~20 workflow helpers | `services.md` 3-section contract (container / public PHP API / procedural) |
| Submodule hedging | "presumably surfaces a message" | targeted parent-module symbol lookups |
| Coverage misses | migrations/state (missed twice), field_type_categories, README | inspect-list additions **with an owning category** |
| Stated count ≠ the enumeration it introduces | ai 1.4.7 ×4, sitewide_alert ×2, block; then ai_agents/ctools/feeds/key/search_api/core node found by the check itself | **count check in verify.py** (2026-08-26) + explorer "recount lead-ins" rule |
| Right line, wrong enclosing function | views ×5; `AgentHelper::runSubAgent()` found by the check | **invocation-site check in verify.py** (2026-08-26) + "verify call sites" rule extended to the enclosing function |
| Invented plugin id (abstract base / wrong id on a real class) | views `mapping`, `links`, `prerender_list`, `entity:{entity_type}` | **plugin-id check in verify.py** (2026-08-26; attribute/annotation-derived, abstract excluded) |
| Synthesized code quotation next to a citation | symfony_mailer_lite `$dsns[$transportConfig->id()]`; workflow `->first()->set(…)` chain | **cited-span check in verify.py** (2026-08-26) + explorer rule "a span next to a citation is a literal substring" |
| Fact about a symbol outside `MODULE_ROOT` | views `-100` priority, `drush views:invalidate`, `views_ui` as provider; block `system_region_list()` "removed" ×2 | explorer rule "omit or hedge — never a value for code not read" (2026-08-26; merged with the lifecycle rule) |
| Inference error about PHP dispatch (inherited method "unaffected") | sitewide_alert `SitewideAlertDomainManager` | explorer rule "trace `$this->` to the override or say nothing" (2026-08-26); mechanical half open (ROADMAP) |
| Lossy paraphrase of a cited wave-1 fact | symfony_mailer_lite "site-wide" | synthesis rule "cite means **copy**" (2026-08-26); scope-word check open (ROADMAP) |
| Coverage gap: deprecations / libraries / install-update hooks / derivers | block ×5 deprecations; sitewide_alert `form` library; views 12 update functions; views derivers unnamed | catalog ownership + sweep rules (2026-08-26) + **deprecation/library checks in verify.py** |
| **Wave-1 cross-explorer identifier drift** — a non-synthesis file restates an identifier that a *sibling* wave-1 explorer's category actually owns, without grepping it itself | core `media` 11.4.5 audit (2026-08-19): `configuration.md` (Explorer A) named the thumbnail-download queue `media_thumbnail_downloader` — plausible from the worker class name `ThumbnailDownloader`, but the real plugin id (owned by Explorer B's `plugins.md`/`entities.md`, both correct) is `media_entity_thumbnail` | explorer rule "identifier strings come from declarations — never from class names" + **module-prefixed id-string check in verify.py** (backticked `<module>_…`/`<module>.…` tokens must occur in the source; WARNING-level — runtime-derived ids exist). Shipped 2026-08-20, acceptance-tested on the media case; A/B pending |
| **Docblock `@return` documented as a declared return type** — a signature written `foo(): Type` when the source declares `public function foo()` with no native return type | `Core/Cache` 11.4.4 (2026-08-27): `getCurrentChecksum(): string`, `isValid(): bool`, `calculateChecksum(): int`, `getContext(): string`, `VariationCacheFactoryInterface::get($bin): VariationCacheInterface`, the four `Cache.php` statics, `convertTokensToKeys()`, `optimizeTokens()`, `getAll()`, `mergeMaxAges()`, `CacheableResponseInterface::getCacheableMetadata()` — ~16 instances across 5 files in one run; 5 of them survived the adversarial fact-check and were caught only by the mechanical check | **signature-return-type check in the core-library `verify.py`** (2026-08-27; PROBLEM-level, judged only when the library declares the name and *every* declaration lacks a native return type) + explorer rule "a docblock is not a declaration" |
| **Quotation drift** — text inside quote marks is not a literal substring of the cited source | `Core/Cache` 11.4.4: core's `CacheTagsChecksumInterface:39` typo "sum total of **validations**" silently normalized to "invalidations"; `MemoryCacheInterface` "so it can" for "so that this can"; two more in `usage.md`/`backend-composition.md` | explorer rule "quote verbatim or drop the quote marks" (2026-08-27); mechanical check open (ROADMAP) |

## The 2026-08-26 mechanization round

Not a discover run — a calibration exercise over the **67 doc sets already
on disk**, every one of them `VERIFY OK` under the old verifier. Nine checks
were added to `verify.py` and tuned against that corpus on the premise that,
since the audited miscounts had all been fixed by explorer follow-ups, *any
flag on the current corpus is a false positive until read*. Numbers:

| Cut | PROBLEMs | What changed |
|---|---|---|
| 1 | 387 | first implementation (249 of them were the *old* FQCN check failing on macOS-purged `$TMPDIR` caches — measure only against intact source) |
| 2 | 29 | gaps between enumerated items limited to separators + light adjectives; a lead-in must end with an introducer; "CKEditor 5 plugin definitions" is a version, not a count; grouped lists skipped |
| 3 | 10 | inline runs flagged only when they name **more** than stated; "Two *pairs of* events" and counts inside parentheses skipped; "plus one deriver" added to the total; bullets holding several items counted by their leading run |
| 4 | 12 | `.yml` file names re-admitted as enumerable items — every one of the 12 is a real defect in a never-audited set |

Lessons that generalize:

- **The corpus is the test suite.** Fifty-plus verified doc sets are a
  better false-positive oracle than any fixture; seeded fixtures (8 classes
  on a sitewide_alert copy, abstract plugin ids on installed-core views) only
  prove recall.
- **Tune toward the observed failure, not the general case.** Every true
  miscount in the audits was an inline run naming *more* than stated or a
  `:`-terminated lead-in over a table; flagging shorter runs produced only
  false positives (partial lists). Likewise the bare-class check is silent
  on generic framework names on purpose — on the corpus every one of those
  was a real core class the module never imports; the one real error
  (`ViewsRouteSubscriber`) was module-named.
- **Adjacency is the disambiguator for citations.** `Class::method()` is
  only a claim about a `path:line` when nothing but a connector sits between
  them; "once `X::y()` has produced … (`X.php:495`)" cites the dispatch
  line, not `y()`.
- **Context windows must follow prose, not lines.** The negation check
  missed "does not ship a\n`x.libraries.yml`" because docs hard-wrap; the
  sentence is the right unit (a paragraph over-suppresses).
- **`$TMPDIR` is not a cache.** macOS reclaims files untouched for ~3 days;
  a directory tree with zero `.php` files underneath is what that looks
  like. Re-download before any source-backed measurement.
- **Wave 1 is where mechanization pays most.** The gate now runs before the
  submodule and synthesis waves, so the classes above are caught before
  they are copied — the same reasoning that motivated two-wave grounding,
  applied one wave earlier.

## The 2026-08-27 core-library round (Core/Cache)

First adversarial fact-check of the **core-library** track (`Core/Cache`
11.4.4 — 86 PHP files, 7,643 lines, the largest library documented so far).
The run passed `VERIFY OK` on the first try, so the mechanical verifier was
not the thing that found anything: five read-only checkers re-derived the
docs' claims from source and returned **1 CRITICAL, 13 MAJOR, ~35 MINOR**
across 10 of 11 files. Four fixer explorers corrected all 49 (0 rejected);
one fixer corrected a *checker's* own miscount, which is the expected
direction of that safeguard.

What the run says about where errors live:

- **`VERIFY OK` is a floor, not a ceiling.** 19,400 words carried 66
  citations, 47 of them line-anchored — so the verifier was validating a
  small fraction of the prose and every behavioural claim was unchecked.
  The CRITICAL (`architecture.md` claiming only `MemoryBackend` implements
  `CacheTagsInvalidatorInterface`, when `BackendChain` and
  `ChainedFastBackend` do too — and the `chainedfast`-backed bins are the
  most-used ones) is invisible to every mechanical check we have.
- **Synthesis is still where hallucination concentrates**, now in the
  distributed shape: the research notes were accurate, and the defects
  appeared in the *synthesized* files — `architecture.md` (the CRITICAL plus
  a false dependency-direction invariant) and `usage.md` (a fabricated
  rationale, a nonexistent `ConfigBase::getCacheTagsToInvalidate()`, a
  `#[Autowire]` snippet missing its import that would fatal on paste). Same
  finding as runs 2-6 on the module track, reached independently.
- **Cross-file contradiction survives a self-consistency pass.** The agent
  contract already requires a consistency re-read, and it still shipped
  `architecture.md` contradicting `topics/backend-composition.md` on the
  interface question. Self-review does not substitute for an independent
  reader.
- **The catalog held.** All 25 cache contexts — service ID, class,
  calculated-vs-simple, behaviour — verified correct row by row, as did the
  tag-checksum algorithm, the `{cachetags}` schema, the 5-tier
  `CacheFactory` precedence and every deprecation version. Density of
  verified detail was not the problem; the connective prose around it was.

Shipped from this round: the signature-return-type check in the core-library
`verify.py`, plus the two explorer rules in the taxonomy table above.

The check's own calibration is worth recording, because recall and false
positives pulled in opposite directions:

- **First cut — unanimity rule.** Judge a documented `foo(): Type` only when
  the library declares `foo` and *every* declaration lacks a native return
  type. Across all 7 documented libraries (Ajax, Batch, Cache, Flood, Hook,
  Queue, Validation): 15 signatures judged, 0 false positives, and 4 true
  defects in Cache that the five fact-checkers had **not** reported — the
  mechanical check outperformed the adversarial readers on its own narrow
  class, which is the usual argument for mechanizing.
- **The recall gap.** The follow-up explorer fixing those 4 found a 5th by
  re-scanning: `CacheableResponseInterface::getCacheableMetadata()`. The
  check had skipped it because `getCacheableMetadata` has 27 declarations in
  the library and exactly one — `Context/ExceptionStatusCodeCacheContext.php:40`
  — declares `: CacheableMetadata`, so unanimity never held. A single
  outlier declaration blinds the rule for the whole name.
- **Second cut — qualifier-aware.** When the doc writes
  `Class::method(...): Type`, resolve that class's own declaration (by
  `Class.php` stem) and judge only it; fall back to unanimity for a bare
  `method(...): Type`. Acceptance-tested by re-seeding the exact missed case
  (caught, correctly attributed to `CacheableResponseInterface.php:36`), then
  recalibrated: all 7 libraries `VERIFY OK`, **26 signatures judged, 0 false
  positives**.

Generalizable: **unanimity rules under-fire on interface families.** Any
check keyed on "all declarations of this name agree" degrades exactly where
core is richest — a widely-implemented interface where one implementation
modernized its signature. Prefer resolving the specific declaration the doc
names, and keep unanimity only as the unqualified fallback.

## Hard-won methodology lessons

- **"No category owns it" is the root cause of most coverage gaps.** An
  inspect-list entry without an owning category falls through twice
  (migrations/state proved it). Every new "also look at X" needs "…and
  category Y documents it".
- **Verify call sites at the dispatch line; never infer** from the service
  that "should" do it. Events dispatched from entity lifecycle methods
  (`postSave`/`preDelete`) fire on direct entity ops too — the difference is
  material to consumers.
- **The nonexistence rule cuts both ways.** Before claiming "X does not
  exist": whole-module grep + inheritance chain (+ core checkout if
  available). Two incidents: `deleteMultiple` (auditor initially
  under-verified) and `SortWidgetBase` (auditor's own truncated `ls | head`
  nearly produced a false accusation — the doc was right).
- **Mechanical stages become scripts.** Download+gate and verify+FQCN started
  as improvised orchestrator bash; as scripts they are deterministic,
  model-independent, and free to re-run. Prefer promoting a check into
  `verify.py` over adding prose rules, when it is mechanizable.
- **Synthesis (C) is where all hallucination concentrated** — every factual
  error in the series, all 8 runs, lived in `extension-points.md` /
  `ai-integration.md`. Guidance prose invites asserting beyond verification.
  Wave-1 category files were near-flawless throughout.
- **Model/effort economics**: pre-two-wave, C error count tracked effort
  (Opus 0 / Sonnet max 0 / high 2 / default 3). Post two-wave + FQCN,
  **Sonnet high is the operating point** (run 8: zero errors). Reserve
  Opus/max for exceptionally API-dense modules.
- **Splitting explorers does not fix contradiction risk — it multiplies it**
  (more overlapping writers of the same facts). Rejected in favor of
  sequencing. Splitting B purely for *context size* on huge modules remains a
  separate, valid idea (ROADMAP).
- **Wave-1 is near-flawless, not flawless** — the first counter-example to
  "every error in the series lived in synthesis C" surfaced in a 2026-08-19
  audit of core `media` 11.4.5 (outside the tracked 2026-08-13 series, done
  with the `audit-docs` skill): `configuration.md`, a wave-1 file,
  misnamed the thumbnail queue as `media_thumbnail_downloader` — a plausible
  guess from the worker class's short name (`ThumbnailDownloader`) rather
  than a grep of the plugin's actual `id:` attribute — while `entities.md`
  and `plugins.md`, written by the *other* wave-1 explorer in the same run,
  both had it right (`media_entity_thumbnail`). Same underlying risk as the
  "splitting multiplies contradiction risk" lesson above, just observed
  intra-wave-1 instead of wave-1-vs-synthesis: two parallel explorers can
  each state a fact belonging to the other's category from memory instead of
  the source. `verify.py`'s FQCN check doesn't catch this class — it only
  resolves `Drupal\<module>\…` class references, not string ids (queue/
  plugin/service ids). A same-run audit also caught a synthesis-file
  overstatement in `ai-integration.md` (claimed the `oembed` source plugin
  catches both `ResourceException` and `ProviderException`; source shows it
  only catches the former) — ordinary synthesis mis-citation, consistent
  with the existing pattern.

## A/B protocol for evaluating the next change

1. Pick one module; run discover **before** the change and **after**, same
   model + effort (Sonnet high is the baseline).
2. Audit both with the `audit-docs` skill (focus: the two C files;
   ≥20 verified claims; nonexistence rule; cross-file consistency).
3. Score errors **by taxonomy class**, and for each error check whether the
   truth already existed in wave-1 files — that tells you whether the failure
   is grounding, verification, or coverage.
4. Commit the skills/agent state before changing anything (git makes the
   rollback free).

## Where everything lives

- Skills: `ai/skills/document-module/` (+ `-core-`) — SKILL.md,
  `scripts/download.py`, `scripts/verify.py` (core keeps copies:
  `download-core-module.sh`, `verify.py`). `verify.py --partial --module
  <name>` is the wave-1 gate mode.
- Agents: `ai/agents/drupal-module-explorer.md` — catalog, sweep, synthesis
  grounding rules, Output Contract (MANIFEST / KEY-FACTS / DISCREPANCIES) —
  and `ai/agents/drupal-submodule-explorer.md` — the grounded submodule
  worker (same contract, no KEY-FACTS).
- Audit skill: `ai/skills/audit-docs/`.
- Deferred work: `ai/ROADMAP.md`.
- Output: docs `~/.drop-context/docs/{modules,core}/…` + `metadata.json`,
  read directly from the Drupal repo the discover skill is run in — no
  download, no source cache.
