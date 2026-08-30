---
name: audit-docs
description: >-
  Deep, read-only quality audit of the documentation generated for a
  Drupal module (contrib, custom, or core): runs the mechanical verifier first,
  then verifies the docs' most inventable claims line-by-line against the
  module's actual source, and delivers a severity-ranked report with
  path:line evidence for every error — never editing the docs, the skills, or
  the agent. Accepts the module machine name plus an optional version
  (defaults to the newest documented) and auto-detects contrib vs core. Use
  when asked to "audit", "fact-check", "QA", or "verify" generated
  documentation, or as the measuring step of the A/B protocol when evaluating
  document-skill changes. Run after /drop-context:document-module /
  /drop-context:document-core-module, from inside the same Drupal repo (or any of
  its subdirectories).
---

# Audit generated documentation

You are the **auditor**. A document run has already produced category docs +
`metadata.json` for a module under `~/.drop-context/docs/` — a single
user-level location, the same for every repo (override the base with
`DROP_CONTEXT_HOME`). Your job is to measure how much of it is *true* — by
reading the module's actual source —
and report what you find. The docs are consumed by agents that cannot verify
claims, so a wrong "do this" recipe is worse than a gap.

**The read-only contract.** Do not edit the docs, the document/make
skills, or the explorer agent — the deliverable is a report (fixes are a
separate, opt-in cycle, step 9). The module source itself is equally
read-only: it is the user's real, version-controlled repo — only
`Read`/`Glob`/`grep`/`find` ever touch it. Never assert an error without
source evidence you actually read this session.

This skill assumes the `document-module` skill (and, for core audits,
`document-core-module`) is installed alongside — it reuses their
bundled `verify.py` and `resolve.py`. Resolve `SKILL_DIR` to the
**absolute path of the directory containing this SKILL.md** (you know it from
where this skill was loaded); the siblings are at `$SKILL_DIR/../`.

## 1. Resolve the docs root, then the module, version, and track

Docs live at a single, fixed user-level location for every repo — nothing to
search for; honour `DROP_CONTEXT_HOME` when set, else default to
`~/.drop-context`:

```bash
DROP_CONTEXT_HOME="${DROP_CONTEXT_HOME:-$HOME/.drop-context}"
DOCS_ROOT="$DROP_CONTEXT_HOME/docs"
```

Inputs: the module **machine name** (required), and optionally a **version**
and a **track** (`contrib` | `core`). Resolve what was documented:

```bash
MODULE={module_machine_name}
# Contrib/custom doc sets — one line per version:
ls -1 "$DOCS_ROOT/modules/$MODULE" 2>/dev/null
# Core doc sets — one line per core version:
ls -1d "$DOCS_ROOT/core/"*/"$MODULE" 2>/dev/null
```

- **Neither lists anything** → stop: no documentation exists for `{module}`.
  Suggest running `/drop-context:document-module` (or the core variant) first —
  offer to run it, never start it unprompted.
- **Both tracks have docs** and the user did not say which → ask.
- **Version omitted** → pick the **newest** documented version that actually
  contains a `metadata.json` (a version dir without one is an aborted run —
  ignore it). Order version-aware: modern semver tags (`3.0.4`) are newer
  than legacy core-compat tags (`8.x-1.17`); within a scheme, highest wins.
  State in the report which version you audited and which others exist.

```bash
VERSION={chosen}
DOCS_DIR="$DOCS_ROOT/modules/$MODULE/$VERSION"   # contrib/custom
DOCS_DIR="$DOCS_ROOT/core/$VERSION/$MODULE"      # core (VERSION = core version)
[ -f "$DOCS_DIR/metadata.json" ] || echo "not a valid document output"
```

Note this is unrelated to which Drupal repo you run this skill from — step 2
below still resolves the module's **source** from whatever repo you're
standing in (or point it at), since the docs root and the source repo are
independent now.

## 2. Locate the matching source

Never audit docs without the **matching** source — same module, same
version. The module lives directly in the repo — re-resolve it with the
bundled resolver (zero network). Pass `--allow-submodule-standalone`: whether
a submodule *should* be documented standalone is a document-time policy
question, already decided by however this doc set was produced — the audit
only needs the source path, never the refusal:

```bash
python3 "$SKILL_DIR/../document-module/scripts/resolve.py" "$MODULE" --allow-submodule-standalone
```

Its `MODULE_ROOT=` line is the path to use. **Compare its `VERSION=` against
the docs' `$VERSION`** — if they differ (the repo has since moved to a
different tag/commit than what was documented), stop and tell the user:
auditing docs against a different version's source would produce false
findings. If the resolver instead prints `GATE NEEDS INPUT`, the module has
since been removed from the repo (or its version is no longer resolvable) —
report that and stop; there is nothing left to audit against.

## 3. Mechanical pass first

```bash
N=$(ls -1 "$DOCS_DIR/submodules/"*.md 2>/dev/null | wc -l | tr -d ' ')
python3 "$SKILL_DIR/../document-module/scripts/verify.py" "$DOCS_DIR" \
  --submodules "$N" --module-root "$MODULE_ROOT"
```

Quote its output in the report. `VERIFY OK` + `FQCN_CHECKED=n` is the pass
signal; every `PROBLEM:` line is already a confirmed finding. It covers the
metadata/file cross-checks in both directions and PSR-4 validation of every
`Drupal\{module}\…` class reference in the docs — **do not re-do those by
hand; build on top.**

## 4. Claim verification (the core of the audit)

Read `extension-points.md` and `ai-integration.md` **fully** — across every
audited run so far, all factual errors concentrated in these synthesis files.
Read the other files as needed for cross-checking. Extract the most
*inventable* claims and verify each against the source with grep/Read:

- **Method names on real classes** (verify.py validates classes, not methods).
- **Dispatch/invocation sites** ("dispatched from `X::y()`"): grep the actual
  `dispatch(` / `invokeAll(` / `->alter(` call and confirm the **enclosing
  function** — never accept an inferred site.
- **Line-number citations** (`file.php:123`): confirm what is on that line.
- **Signatures, subscriber priorities, config defaults, schema types,
  permission/route/service names**: compare verbatim.
- **Quoted strings** (deprecation messages, `@todo` comments): confirm verbatim.
- **Counts** ("8 hooks", "two dozen targets"): recount via enumeration.
- **Negative claims** ("no X", "verified absent"): apply the nonexistence rule
  below.

Target **at least ~20 verified claims**, prioritizing those that would
mislead a consumer agent if wrong (API entry points, "do this" recipes,
gotchas). Known error classes from past audits — hunt for these specifically:
invented symbols (a class/method that does not exist), wrong namespaces
(parent vs submodule), wrong dispatch sites, unverified counts, facts
contradicting a sibling doc file.

## 5. Nonexistence rule

Before reporting "X does not exist": (a) grep **declarations** across the
whole module source, not one file; (b) consider the **inheritance chain** —
the symbol may live in a core base class. Since this skill runs inside the
same Drupal repo the module was resolved from, **the core checkout is always
available** at `$DRUPAL_ROOT/core` (the `resolve.py` gate's `DRUPAL_ROOT=`
line) — grep it there before ever writing "does not exist"; only fall back to
"not declared in this module; inheritance not verified" when the symbol truly
resolves to neither the module nor core (e.g. it comes from another contrib
dependency you were not asked to audit). And never base a nonexistence claim
on a **truncated listing** — an `ls | head` has produced a false accusation
before; enumerate completely or don't claim.

## 6. Cross-file consistency

Any fact stated in both a synthesis file and a wave-1 file (`events.md`,
`hooks.md`, `plugins.md`, `services.md`, `routes.md`, `submodules/*`) must
agree. Flag every divergence and determine which side the source supports.

## 7. Completeness spot-checks

- **Orphan sweep**: for each PHP class file under `src/` (and each submodule's
  `src/`), confirm the class name appears in at least one doc file; abstract
  bases whose concretes are documented are exempt — list any other orphan.
- **Procedural inventory**: `grep '^function '` across `.module`/`.inc` files
  vs what `services.md`/`hooks.md` list — every function accounted for.
- **api.php stubs** (if the module ships one) all covered in `hooks.md`;
  `README`, `migrations/state/`, and every `config/schema/*.yml` mentioned
  where applicable.

## 8. The report

Lead with the verdict (error count + overall quality in one sentence). Then:

1. **Errors**, ranked by severity — each with the doc file/section, the wrong
   claim as written, and the source evidence (`path:line`);
2. **Confirmed-correct highlights** — a sample of the strongest verified
   claims (shows the audit's depth and what the docs got right);
3. **Gaps** — things the source has that no doc covers;
4. **Cross-file divergences** (from step 6);
5. **Recommendations** for the skill/agent — proposals only, never apply
   them in this session.

A clean audit is a valid result, not a failure to find problems — say so
plainly with the verification tally.

**If asked to save the report as a file**, save it **outside** the docs
directory (a scratch dir, named `audit-$MODULE-$VERSION.md`) — never inside
`~/.drop-context/docs/…`, where it would pollute the generated doc set
(verify.py ignores the `audit-*` prefix only defensively).

## 9. Fix cycle — separate, and only on request

If the user wants confirmed errors fixed after seeing the report: spawn **one**
follow-up explorer per affected file, scoped to that file, passing the
disputed point(s) verbatim with your `path:line` evidence — the same
discrepancy protocol the document skill uses. Route by file type:
`drupal-module-explorer` for a category file, `drupal-submodule-explorer` for
a `submodules/<sub>.md` file (give it just that one submodule; it grounds
itself in the category docs, which exist in any audited set). Then re-run
step 3 and spot-check the rewritten file. **Never hand-edit generated docs**,
and never "fix" the docs to match a claim the source does not support. If the
explorer agents are not available in this runner, the fix is re-running the
document skill — not manual edits.
