# Output contract — `release.json`

Produced by the `update-module-docs` and `upgrade-module-docs` skills as part
of their runs — one `release.json` per documented version, describing that
version's release.

## File location

```text
~/.drupal-context/modules/<module>/<tag>/release.json
```

Always inside the version's doc-set directory — nothing else. The consumer is
`drupal-site`'s file-based importer (`ddev drush dc:import-docs`, alias
`dcid`), which reads `release.json` inside a version dir under
`content/modules/` — but staging that directory is the **user's manual copy
step**, out of both skills' scope; the file simply rides along with the doc
set. (A version dir holding only `release.json` is safe everywhere: the
`generate-module-skill` version resolver and the site importer both ignore
version dirs without a `metadata.json`.)

## JSON schema (required keys marked *)

```json
{
  "module_machine": "feeds",
  "release_tag": "8.x-3.2",
  "release_line": "8.x-3.x",
  "title": "feeds 8.x-3.2",
  "release_notes_url": "https://www.drupal.org/project/feeds/releases/8.x-3.2",
  "previous_tag": "8.x-3.1",
  "summary": "Light-Markdown summary of what changed. Include a '**Breaking changes:**' section when any are proven. Empty string if unknown.",
  "issues": [
    "https://www.drupal.org/node/1234567",
    {
      "url": "https://www.drupal.org/project/feeds/issues/2345678",
      "title": "Optional issue title from the page or MR"
    }
  ],
  "change_level": "minor",
  "breaking_changes": [],
  "core_version_requirement": {
    "previous": "^10.3 || ^11",
    "current": "^10.3 || ^11"
  },
  "docs_impact": {
    "status": "none",
    "baseline": "8.x-3.1",
    "categories": [],
    "handled_by": "update-module-docs",
    "evidence": "complete diff, 7 changed files, all in tests/ and CI config"
  },
  "notes_quality": "full",
  "sources": [
    "https://www.drupal.org/project/feeds/releases/8.x-3.2",
    "gitlab",
    "local-diff 8.x-3.1..8.x-3.2"
  ]
}
```

| Key | Required | Importer | Notes |
|-----|----------|----------|-------|
| `module_machine` | * | validation | Must equal the machine name (and the dir's) |
| `release_tag` | * | validation | Must equal the exact tag = version dirname |
| `release_line` | | consumed | `8.x-2.0-rc1` → `8.x-2.x`; `2.1.0` → `2.x`; importer derives from the tag when omitted |
| `title` | | consumed | Defaults to `{module} {tag}` shape when omitted |
| `release_notes_url` | | consumed | Canonical d.o URL (or the page actually used) |
| `summary` | * | consumed | May be `""`; becomes the release-note body |
| `issues` | * | consumed | May be `[]`; strings or `{url, title}` objects |
| `previous_tag` | | ignored | Same-line predecessor used for the notes compare |
| `change_level` | | ignored | `patch` \| `minor` \| `major` (see docs-impact.md) |
| `breaking_changes` | | ignored | Proven breaks only; `[]` when none |
| `core_version_requirement` | | ignored | `{previous, current}` verbatim from the two `.info.yml`s |
| `docs_impact` | | ignored | `{status, baseline, categories[], handled_by, evidence}`; status `none` \| `affected` \| `unknown` \| `not_applicable`; `categories[]` entries are doc-set **file names** as in docs-impact.md's map (`services.md`, `submodules/eca_base.md` — with the `.md`); handled_by names the skill that produced the doc set (`update-module-docs` \| `upgrade-module-docs`). `not_applicable` covers "target version was already documented" — `evidence` says so |
| `notes_quality` | | ignored | `full` \| `partial` \| `thin` |
| `sources` | | ignored | URLs and/or `gitlab` / `local-diff …` tokens actually used |

Keys the importer ignores are still contract: they are read by agents (and by
future importer phases) — fill them honestly or omit them.

## What the importer does with it (current behavior)

- **Validation**: the file is only trusted when `module_machine` equals the
  module dir's machine name **and** `release_tag` equals the version dirname.
  Any mismatch (or absent key) → skipped with a logged warning, the
  `module_release` entity left untouched. (`tag` is accepted as a legacy
  fallback for `release_tag` — never write it in new output.)
- `title` / `release_line` / `release_notes_url` are applied only when
  non-empty — a partial file never blanks an existing field.
- `summary` + `issues[]` **unconditionally rebuild** the release's single
  `release_note` paragraph (including the legitimate empty case).
- Each `issues[]` entry needs a usable absolute `http://`/`https://` URL —
  anything else (schemeless, free text, empty) is **dropped** with a warning,
  never repaired.
- A missing `release.json` never blanks an already-enriched release.

## Integrity

- Empty `summary` + empty `issues` is valid when the release truly has no notes.
- An `issues[]` entry's `title` may come from the release page, the d.o issue
  page, an MR title, or a commit title — always **verbatim** from that source
  (typos included), never rewritten or synthesized. Prefer the d.o issue page's
  own title when you already fetched that page; a commit title is a fine
  cheaper stand-in.
- Do not pad `issues` with unrelated project issues.
- `module_machine` and `release_tag` must match the skill parameters exactly.
- `breaking_changes` and `docs_impact` must be traceable to the evidence
  gathered in the run — never inferred from version numbers alone.
