---
name: discover-module-release
description: >-
  Map a Drupal.org module release page (and optionally GitLab merges between tags)
  into structured metadata for the Drupal Context `module_release` entity. Use when
  asked to discover, scrape, or import release notes for a contrib module tag.
  Writes storage/<module>/<tag>/release/ and can pack a ZIP for
  /admin/drupal-context/import (Module Release).
---

# Discover a module release

You map **one release/tag** of a Drupal.org project onto our `module_release`
entity fields. Drupal.org release pages are **inconsistent** — do not invent
changelog items, issue links, or summaries. Prefer omission over guesswork.

**Parameters** (required unless already clear from the user message):

| Param | Example | Meaning |
|-------|---------|---------|
| `module` | `feeds` | Project machine name |
| `tag` | `8.x-3.2` | Exact release tag to analyze |

Optional: `previous_tag` (e.g. `8.x-3.1`) — previous tag for GitLab compare. If
omitted, try to discover it from the release page or from GitLab tags (do not invent).

Load references as needed:

- [drupal-org-release-page.md](references/drupal-org-release-page.md) — how to read d.o pages
- [gitlab-compare.md](references/gitlab-compare.md) — GitLab fallback for merges
- [output-contract.md](references/output-contract.md) — JSON + ZIP contract (required)

## Target entity fields (map what you can prove)

| Entity field | Source |
|--------------|--------|
| `title` | Prefer `{module} {tag}` unless the page has a clearer official title |
| `field_module` | Resolved at import via `module_machine` (must already exist in Drupal) |
| `field_release_tag` | Exact `tag` parameter |
| `field_release_line` | Derive: `8.x-2.0-rc1` → `8.x-2.x`; `2.1.0` → `2.x`; else use tag |
| `field_release_notes_url` | Canonical `https://www.drupal.org/project/{module}/releases/{tag}` (or the page URL you actually used) |
| `field_release_notes` → paragraph | `field_tag_name`, `field_content` (summary), `field_issue_links` |

**Never invent** issue URLs, MR titles, or “what changed” text. If the page only
says “See git commits” with no detail, leave `summary` sparse and use GitLab
only when it yields concrete merged MRs / issues with real links.

## Steps

### 1. Resolve inputs

Confirm `module` + `tag`. Build the release URL:

```text
https://www.drupal.org/project/<module>/releases/<tag>
```

Working directory for outputs:

```bash
ROOT="{root_project}"   # monorepo root
OUT="$ROOT/storage/<module>/<tag>/release"
mkdir -p "$OUT"
```

### 2. Fetch and parse the Drupal.org release page

Fetch the release URL (WebFetch / curl). Follow
[drupal-org-release-page.md](references/drupal-org-release-page.md).

Extract **only** what is explicit on the page:

- Release date / status (informational; not a Drupal field yet — may go in summary)
- Changelog / release notes body → candidate `summary`
- Linked issues / change records → `issues[]` (absolute Drupal.org URLs only)
- Mentions of the previous version → `previous_tag` if clear

If the body is empty, boilerplate-only, or “no release notes”, set
`notes_quality: thin` and continue to step 3. Do **not** paraphrase marketing
blurbs into fake changelogs.

### 3. GitLab fallback (when notes are thin or issue list is empty)

When `notes_quality` is `thin` **or** you have a summary but **zero** issue links,
enrich from GitLab using [gitlab-compare.md](references/gitlab-compare.md):

1. Resolve `previous_tag` if still unknown (tags API; pick the chronologically
   previous tag when ordering is clear — otherwise skip compare).
2. Compare `previous_tag` → `tag` (commits and/or merged MRs).
3. Add only MRs/issues that have a real URL. Put a short factual summary of
   merged MR titles into `summary` if the d.o page had none — label the source
   in `sources` as `gitlab`.

If GitLab fails or returns nothing useful, keep whatever d.o gave you and set
`notes_quality: thin` (or `partial`).

### 4. Write `module-release.json`

Write **exactly** the schema in [output-contract.md](references/output-contract.md)
to:

```text
storage/<module>/<tag>/release/module-release.json
```

Rules:

- Omit keys you cannot fill (or use empty string / `[]`) — never fabricate.
- `issues` entries must be real absolute URLs (string or `{url, title}`).
- `summary` is plain text or light Markdown; no HTML.
- Include `sources` listing every URL/API you actually used.

### 5. Pack the ZIP

```bash
./scripts/pack-module-release.sh <module> <tag>
# → generated/<module>-<tag>-release.zip
```

If the pack script is unavailable, zip `module-release.json` at the ZIP root
yourself into `generated/<module>-<tag>-release.zip`.

### 6. Report

Tell the user:

- Output path of `module-release.json` and the ZIP
- `notes_quality` and whether GitLab was used
- Counts: issue links, whether summary is non-empty
- Reminder: import at `/admin/drupal-context/import` → **Module Release** → upload the ZIP  
  (module_details must already exist: `ddev drush dc:fetch-module <module>`)

Do **not** paste the full JSON into the chat unless asked.
