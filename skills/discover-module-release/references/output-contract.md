# Output contract — `module-release.json` + ZIP

## File locations

```text
storage/<module>/<tag>/release/module-release.json
generated/<module>-<tag>-release.zip   # ZIP root must contain module-release.json
```

Pack with:

```bash
./scripts/pack-module-release.sh <module> <tag>
```

## JSON schema (required keys marked *)

```json
{
  "module_machine": "feeds",
  "release_tag": "8.x-3.2",
  "release_line": "8.x-3.x",
  "title": "feeds 8.x-3.2",
  "release_notes_url": "https://www.drupal.org/project/feeds/releases/8.x-3.2",
  "previous_tag": "8.x-3.1",
  "summary": "Plain-text or light Markdown summary of what changed. Empty string if unknown.",
  "issues": [
    "https://www.drupal.org/node/1234567",
    {
      "url": "https://www.drupal.org/project/feeds/issues/2345678",
      "title": "Optional issue title from the page or MR"
    }
  ],
  "notes_quality": "full",
  "sources": [
    "https://www.drupal.org/project/feeds/releases/8.x-3.2",
    "gitlab"
  ]
}
```

| Key | Required | Notes |
|-----|----------|-------|
| `module_machine` | * | Drupal project machine name |
| `release_tag` | * | Exact tag |
| `release_line` | | Derived line (`8.x-3.x`); importer derives if omitted |
| `title` | | Defaults to `{module_machine} {release_tag}` at import |
| `release_notes_url` | | Defaults to canonical d.o URL at import |
| `previous_tag` | | Informational / for GitLab; stored only inside summary/sources context |
| `summary` | * | May be `""` |
| `issues` | * | Array; may be `[]`. Strings or `{url, title}` objects |
| `notes_quality` | | `full` \| `partial` \| `thin` |
| `sources` | | URLs and/or `gitlab` / `drupal.org` tokens you used |

### Backward compatibility

The importer also accepts the older minimal shape:

```json
{
  "tag": "8.x-3.2",
  "summary": "…",
  "issues": ["https://www.drupal.org/node/123"]
}
```

Prefer the full schema above for new discoveries.

## Mapping to Drupal fields

| JSON | `module_release` field |
|------|-------------------------|
| `title` | entity `title` |
| `module_machine` | resolve `module_details` → `field_module` |
| `release_tag` / `tag` | `field_release_tag` |
| `release_line` | `field_release_line` |
| `release_notes_url` | `field_release_notes_url` |
| `summary` + `issues` | one `release_note` paragraph (`field_content` + `field_issue_links`; `field_tag_name` = tag) |

## Integrity

- Empty `summary` + empty `issues` is valid when the release truly has no notes.
- Do not pad `issues` with unrelated project issues.
- `module_machine` and `release_tag` must match the skill parameters.
