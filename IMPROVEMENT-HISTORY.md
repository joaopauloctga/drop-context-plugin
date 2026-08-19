# Discover pipeline — improvement history & lessons

Background for future skill-improvement sessions. This is the distilled record
of the 2026-08-13 improvement series (7 discover runs, 7 audits, ~10 shipped
changes). Read this before touching `discover-drupal-module`,
`discover-drupal-core-module`, or `agents/drupal-module-explorer.md`.
Deferred work lives in `ROADMAP.md`; the reusable audit protocol in
the `audit-discover-docs` skill.

## Current architecture (as of 2026-08-17)

1. **Download + GATE** — one bundled script run (`scripts/download.py` /
   `download-core-module.sh`): fetch → validate `.info.yml` → create
   OUTPUT_DIR → enumerate submodules → machine-parseable `GATE OK` block.
2. **Wave 1** — Explorers A (key-facts/configuration/permissions/routes) and
   B (entities/plugins/services/hooks/events) in parallel
   (`drupal-module-explorer`). Each writes its files directly and returns a
   JSON manifest.
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
   Unresolvable FQCN = PROBLEM = an invented class name.

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

## A/B protocol for evaluating the next change

1. Pick one module; run discover **before** the change and **after**, same
   model + effort (Sonnet high is the baseline).
2. Audit both with the `audit-discover-docs` skill (focus: the two C files;
   ≥20 verified claims; nonexistence rule; cross-file consistency).
3. Score errors **by taxonomy class**, and for each error check whether the
   truth already existed in wave-1 files — that tells you whether the failure
   is grounding, verification, or coverage.
4. Commit the skills/agent state before changing anything (git makes the
   rollback free).

## Where everything lives

- Skills: `ai/skills/discover-drupal-module/` (+ `-core-`) — SKILL.md,
  `scripts/download.py`, `scripts/verify.py` (core keeps copies:
  `download-core-module.sh`, `verify.py`).
- Agents: `ai/agents/drupal-module-explorer.md` — catalog, sweep, synthesis
  grounding rules, Output Contract (MANIFEST / KEY-FACTS / DISCREPANCIES) —
  and `ai/agents/drupal-submodule-explorer.md` — the grounded submodule
  worker (same contract, no KEY-FACTS).
- Audit skill: `ai/skills/audit-discover-docs/`.
- Deferred work: `ai/ROADMAP.md`.
- Output: docs `~/.drupal-context/{modules,core}/…` + `metadata.json`;
  source cache `${TMPDIR}/drupal-context-<user>/…`.
