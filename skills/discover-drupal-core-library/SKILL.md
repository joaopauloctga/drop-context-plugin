---
name: discover-drupal-core-library
description: >-
  Produce source-grounded, AI-consumable documentation for a Drupal framework
  library below core/lib/Drupal, such as Core/Ajax, Core/Batch, Core/Block,
  Core/Plugin, or Component/Plugin. Writes a stable metadata.json plus summary,
  architecture, API, and usage Markdown under
  ~/.drupal-context/core-libraries/{core-version}/{qualified-library}/. Uses a
  direct explorer for small cohesive libraries and survey/research/synthesis
  agent waves for larger or cross-cutting libraries. Use when asked to discover,
  explain, analyze, or document a Drupal core library; do not use for a module
  under core/modules (use discover-drupal-core-module instead).
---

# Discover a Drupal core library

Document one library below Drupal's `core/lib/Drupal`. The directory structure
is not a category taxonomy: some libraries are four flat files, some are
protocol families, and some are large frameworks with several connected
subsystems. Keep the final output contract stable, but derive research
workstreams and optional topic files from the real source.

You are the orchestrator. The `drupal-core-library-explorer` workers read the
source and write evidence/final docs. You run the deterministic gate, choose the
small or distributed path, assemble `metadata.json` from worker output, and run
the verifier.

Inputs:

- a library identifier (required), preferably qualified: `Core/Ajax`,
  `Core/Batch`, `Core/Authentication`, or `Component/Plugin`; a unique short
  top-level name such as `Ajax` is accepted;
- an optional Composer project root, Drupal docroot/core dir, or
  `core/lib/Drupal` path; when omitted, the gate resolves common layouts from
  the current directory;
- an optional output language; default to English (`en`) for consistency with
  the existing discover corpus unless the user requests another language.

`Core/Plugin` and `Component/Plugin` are different libraries, so ambiguous
short names are a gate failure rather than a guess.

## 1. Prepare and GATE

Resolve `SKILL_DIR` to the absolute directory containing this `SKILL.md`. Run
the bundled standard-library-only script. Pass the source root only when the
user supplied one or cwd discovery would not be appropriate:

```bash
python3 "$SKILL_DIR/scripts/prepare.py" <library> [<source-root>] --language <language>
```

The script ends with:

```text
GATE OK
LIBRARY=<canonical Core/Ajax-style path>
LIBRARY_ID=<stable drupal.core.ajax-style id>
NAMESPACE=<Drupal\Core\Ajax-style namespace>
VERSION=<Drupal core version from Drupal::VERSION>
LANGUAGE=<language tag>
DRUPAL_ROOT=<absolute Drupal docroot>
CORE_ROOT=<absolute core directory>
DRUPAL_LIB_ROOT=<absolute core/lib/Drupal directory>
LIBRARY_ROOT=<absolute target directory>
OUTPUT_DIR=<~/.drupal-context/core-libraries/<version>/<library path>>
WORK_DIR=<absolute disposable temp directory>
INVENTORY=<absolute inventory.json path>
DATE_EPOCH=<Unix epoch seconds>
PHP_FILES=<target PHP file count>
PHP_LINES=<target PHP line count>
RELATED_TEST_FILES=<candidate test count>
```

Carry every value verbatim. `INVENTORY` is the deterministic coverage ledger
and includes every target source file plus candidate tests (PHPUnit tests
under `core/tests/Drupal` and the test modules/tests under
`core/modules/*/tests/`, such as `batch_test` or `cron_queue_test`). The gate
does not download Drupal and never modifies the checkout.

If the script exits non-zero or prints `GATE FAILED`, stop and report that exact
error. Do not search for another core checkout or silently reinterpret the
library. If an output already exists, the gate refuses to overwrite it. Use
`--replace-generated` only when the user explicitly requested regeneration; it
removes known generated Markdown/metadata and refuses unknown artifacts.

## 2. Select direct or distributed exploration

Use the direct path only when both `PHP_FILES <= 25` and `PHP_LINES <= 2000`.
Use the distributed path otherwise. These thresholds prevent needless shards
for a cohesive library while ensuring API-dense frameworks do not overflow one
research context.

Workers use the agent contract at
`ai/agents/drupal-core-library-explorer.md` (installed as
`drupal-core-library-explorer` alongside this skill):

- in Claude Code, use `subagent_type: drupal-core-library-explorer`;
- in runners with generic collaborators, tell each worker to read that agent
  contract and give it one explicit mode plus the exact gate values.

Do not pass literal placeholders. Every prompt receives the real absolute paths
and identifiers from the gate.

### Direct path

Launch one explorer in `direct` mode:

> Work in `direct` mode for Drupal core library `<LIBRARY>` (`<NAMESPACE>`) at
> `<LIBRARY_ROOT>`, Drupal `<VERSION>`. `CORE_ROOT=<CORE_ROOT>`,
> `INVENTORY=<INVENTORY>`, `WORK_DIR=<WORK_DIR>`,
> `OUTPUT_DIR=<OUTPUT_DIR>`, `LANGUAGE=<LANGUAGE>`. Read the complete target
> inventory plus only source-linked tests/wiring/callers, write the four required
> docs and any genuinely necessary topic docs per your contract, then return only
> `MANIFEST`, `LIBRARY-FACTS`, and `END`.

Collect its manifest and library facts, then go to step 4.

### Distributed path — survey

Launch one explorer in `survey` mode:

> Work in `survey` mode for Drupal core library `<LIBRARY>` (`<NAMESPACE>`) at
> `<LIBRARY_ROOT>`, Drupal `<VERSION>`. `CORE_ROOT=<CORE_ROOT>`,
> `INVENTORY=<INVENTORY>`, `WORK_DIR=<WORK_DIR>`. Map connected subsystems,
> assign every target PHP file to exactly one implementation workstream, add a
> targeted integration workstream when runtime edges leave the library, and
> return only `PLAN` and `END`.

Parse the JSON plan. Check it against `INVENTORY`: workstream ids are unique;
implementation ownership covers every target PHP path exactly once; workstreams
are cohesive and stay near the agent contract's size guidance. If coverage is
missing or overlapping, send one follow-up to correct the plan before research.

### Distributed path — parallel research

Launch one explorer in `research` mode per workstream, in parallel up to the
runner's safe concurrency; use additional batches when necessary. Every prompt
contains only that workstream plus the common gate values:

> Work in `research` mode for `<LIBRARY>` at `<LIBRARY_ROOT>`, Drupal
> `<VERSION>`. `CORE_ROOT=<CORE_ROOT>`, `INVENTORY=<INVENTORY>`,
> `WORK_DIR=<WORK_DIR>`. Your assigned workstream is this exact JSON:
> `<WORKSTREAM_JSON>`. Read all owned files and its targeted external evidence,
> write only `WORK_DIR/research/<id>.md`, and return only its `MANIFEST` and
> `END`.

The notes have disjoint filenames. Collect every manifest and verify one note
exists for every planned workstream. A missing note gets one focused follow-up;
an `ERROR` block stops the run.

### Distributed path — synthesis

After every research note exists, launch one explorer in `synthesis` mode:

> Work in `synthesis` mode for Drupal core library `<LIBRARY>` (`<NAMESPACE>`)
> at `<LIBRARY_ROOT>`, Drupal `<VERSION>`. `CORE_ROOT=<CORE_ROOT>`,
> `INVENTORY=<INVENTORY>`, `WORK_DIR=<WORK_DIR>`,
> `OUTPUT_DIR=<OUTPUT_DIR>`, `LANGUAGE=<LANGUAGE>`. Read all research notes as
> the fact base, resolve conflicts/unanswered points with targeted source reads,
> write the four required final docs plus only independently useful topic docs,
> assign every target PHP file exactly once in manifest `source_paths`, and
> return only `MANIFEST`, `LIBRARY-FACTS`, and `END`.

Do not ask the synthesis agent to re-read the whole library. The evidence wave
exists to compress and ground the source before final writing.

## 3. Collect the final worker contract

The direct/synthesis final response contains:

- `=== MANIFEST ===`: JSON array in curated reading order. Every entry has
  `file`, `category`, `title`, `description`, `keywords`, `symbols`, and
  `source_paths`;
- `=== LIBRARY-FACTS ===`: JSON object with `human_name`, `summary`,
  `description`, `aliases`, `use_when`, and `keywords`;
- `=== END ===`.

Required files and categories are fixed:

| File | Category |
| --- | --- |
| `summary.md` | `Summary` |
| `architecture.md` | `Architecture` |
| `api.md` | `API` |
| `usage.md` | `Usage` |
| `topics/<slug>.md` | `Topic` |

The four root files always exist. Topics are optional and source-driven. All
target PHP paths from `INVENTORY` must occur exactly once across manifest
`source_paths`; this proves the code was assigned to a final retrievable doc
without imposing a universal topic taxonomy.

If a final block is malformed or a required file/coverage path is missing, send
one follow-up to the same worker for the exact defect. Do not invent metadata or
write generated Markdown yourself.

## 4. Write `metadata.json`

Write only `OUTPUT_DIR/metadata.json`. Copy all worker-produced values verbatim;
do not rewrite search text or file descriptions. Read `INVENTORY` for
`source.digest` and use the gate counts:

```json
{
  "schema_version": 1,
  "id": "<LIBRARY_ID>",
  "name": "<LIBRARY>",
  "human_name": "<LIBRARY-FACTS.human_name>",
  "qualified_name": "<NAMESPACE>",
  "type": "core_library",
  "version": "<VERSION>",
  "date": 0,
  "language": "<LANGUAGE>",
  "source": {
    "path": "core/lib/Drupal/<LIBRARY>",
    "php_files": 0,
    "php_lines": 0,
    "digest": "sha256:<INVENTORY.source_digest>"
  },
  "summary": "<LIBRARY-FACTS.summary>",
  "description": "<LIBRARY-FACTS.description>",
  "aliases": ["<copied verbatim>"],
  "use_when": ["<copied verbatim>"],
  "keywords": ["<copied verbatim>"],
  "files": ["<MANIFEST entries copied verbatim and in the returned order>"]
}
```

Use the integer `DATE_EPOCH`, `PHP_FILES`, and `PHP_LINES` from the gate in
place of the zeros. Prefix the inventory's hexadecimal `source_digest` with
`sha256:` exactly once. The stable library key is (`id`, `version`); a future
document entity can use (`id`, `version`, `files[].file`). Absolute local paths
never enter metadata.

## 5. Verify and report

Run the bundled verifier with exact gate values:

```bash
python3 "$SKILL_DIR/scripts/verify.py" "$OUTPUT_DIR" \
  --library-root "$LIBRARY_ROOT" \
  --drupal-lib-root "$DRUPAL_LIB_ROOT" \
  --library "$LIBRARY" \
  --library-id "$LIBRARY_ID" \
  --version "$VERSION"
```

It checks schema/types, stable identity, source counts/digest, metadata/file
parity, required files/categories, safe paths, complete one-owner PHP coverage,
FQCN resolution across `Drupal\Core` and `Drupal\Component`, and every
backticked `core/...` source citation (file exists, line/range in bounds —
`core/includes/*.inc`, `core/core.services.yml`, `core/misc/*.js` included).
Every backticked `hook_*` name must be declared in a core `*.api.php`
(placeholder hooks such as `hook_ENTITY_TYPE_insert` match by pattern); an
undeclared name is a `PROBLEM:`, or a `WARNING:` when the token exists in
core source as something other than a hook (a key-value key, for instance).
A documented signature such as `foo(): array` is a `PROBLEM:` when every
declaration of `foo` in the library declares no native return type — a
docblock `@return` is not a declaration, and copying the documented form
into an implementation is a real incompatibility.
It also emits a `WARNING:` when a `path:line` citation lands nowhere near any
symbol the same sentence names — usually the right file but the wrong
method, sometimes just a sentence citing several facts; judge each one.

- `VERIFY OK`: report completion.
- `VERIFY FAILED`: give the exact `PROBLEM:` lines to one focused follow-up
  explorer when docs/manifest are wrong; update `metadata.json` only from its
  corrected returned blocks, then re-run. Fix deterministic assembly errors
  yourself. Never hand-edit worker-authored Markdown.
- Judge `WARNING:` lines before reporting; resolve likely shallow output,
  unvalidated symbols, or citations that point at the wrong method with a
  focused follow-up, and mention any warning left intentionally.
- Keep a follow-up log as you go: for every post-verify follow-up you send,
  record the exact `PROBLEM:`/`WARNING:` lines that triggered it and the files
  it rewrote. A doc rewritten after `metadata.json` with no recorded cause is
  an unexplained change in the output.

After `VERIFY OK`, remove `WORK_DIR` (`rm -rf "$WORK_DIR"`) — its inventory
and research notes are disposable evidence, and the source cache philosophy is
that temp artifacts do not accumulate. Keep it only when the user asked to
keep the work dir (any "keep the work dir" phrasing) or when the run ended in
`VERIFY FAILED`, so the notes remain available for a retry; say which in the
report.

Report the canonical library, Drupal version, `OUTPUT_DIR`, number of final and
topic docs, whether direct or distributed exploration ran, the follow-up log
(each follow-up: triggering `PROBLEM:`/`WARNING:` lines → files rewritten; or
"no follow-ups"), whether `WORK_DIR` was removed or kept, and a one-line
takeaway. Do not paste generated docs into the response.
