# Prompt: audit generated discover documentation

Paste the block below, filling in `{module}`, `{version}`, and `{contrib|core}`.

---

Audit the generated discover documentation for the Drupal module **{module}**
version **{version}** ({contrib|core}). This is a **read-only quality audit**:
do not edit the docs, the skills, or the agent — the deliverable is a report.
Never assert an error without source evidence you actually read this session.
If asked to save the report as a file, save it **outside** the docs directory
(e.g. in the workspace or a scratch dir, named `audit-{module}-{version}.md`)
— never inside `~/.drupal-context/…`, where it would pollute the generated
doc set and break `verify.py`'s unlisted-file check.

## Locate the artifacts

- Docs: `~/.drupal-context/modules/{module}/{version}/` (contrib) or
  `~/.drupal-context/core/{version}/{module}/` (core): `metadata.json`,
  `summary.md`, 10 category files, `submodules/*.md` when present.
- Source: `${TMPDIR:-/tmp}/drupal-context-$(id -un)/modules/{module}/{version}/source/`
  (contrib) or `…/core/{version}/{module}/` (core). If the cache is gone,
  re-download it with the discover skill's bundled script
  (`ai/skills/discover-drupal-module/scripts/download.py {module} {version}`)
  — never audit docs without the matching source.

## 1. Mechanical pass first

```bash
python3 ai/skills/discover-drupal-module/scripts/verify.py <DOCS_DIR> \
  --submodules <N> --module-root <SOURCE_ROOT>
```

(`<N>` = count of `submodules/*.md` files.) Report its output. It already
covers metadata/file cross-checks and PSR-4 validation of `Drupal\{module}\…`
class references — do not re-do those by hand; build on top.

## 2. Claim verification (the core of the audit)

Read `extension-points.md` and `ai-integration.md` **fully** — historically,
every factual error concentrated in these synthesis files. Read the other
files as needed for cross-checking. Extract the most *inventable* claims and
verify each against the source with grep/Read:

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

Target **at least ~20 verified claims**, prioritizing those that would mislead
a consumer agent if wrong (API entry points, "do this" recipes, gotchas).
Known error classes from past audits, hunt for these specifically: invented
symbols (a class/method that does not exist), wrong namespaces (parent vs
submodule), wrong dispatch sites, unverified counts, facts contradicting a
sibling doc file.

## 3. Nonexistence rule

Before reporting "X does not exist": (a) grep **declarations** across the
whole module source, not one file; (b) consider the **inheritance chain** —
the symbol may live in a core base class; if a Drupal core checkout is
available (e.g. `drupal-site/web/core`), grep it there too; if it is not
available, write "not declared in this module; inheritance not verified (no
core source at hand)" instead of "does not exist".

## 4. Cross-file consistency

Any fact stated in both a synthesis file and a wave-1 file (`events.md`,
`hooks.md`, `plugins.md`, `services.md`, `routes.md`, `submodules/*`) must
agree. Flag every divergence and determine which side the source supports.

## 5. Completeness spot-checks

- **Orphan sweep**: for each PHP class file under `src/` (and each submodule's
  `src/`), confirm the class name appears in at least one doc file; abstract
  bases whose concretes are documented are exempt — list any other orphan.
- **Procedural inventory**: `grep '^function '` across `.module`/`.inc` files
  vs what `services.md`/`hooks.md` list — every function accounted for.
- **api.php stubs** (if the module ships one) all covered in `hooks.md`;
  `README`, `migrations/state/`, and every `config/schema/*.yml` mentioned
  where applicable.

## 6. Report format

Lead with the verdict (error count + overall quality in one sentence). Then:

1. **Errors**, ranked by severity — each with the doc file/section, the wrong
   claim as written, and the source evidence (`path:line`);
2. **Confirmed-correct highlights** — a sample of the strongest verified
   claims (shows the audit's depth and what the docs got right);
3. **Gaps** — things the source has that no doc covers;
4. **Cross-file divergences** (from step 4);
5. **Recommendations** for the skill/agent — proposals only, do not apply.

If everything checks out, say so plainly with the verification tally — a
clean audit is a valid result, not a failure to find problems.
