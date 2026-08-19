# Drupal.org release page

## Canonical URL

```text
https://www.drupal.org/project/{machine_name}/releases/{tag}
```

Examples:

- `https://www.drupal.org/project/feeds/releases/8.x-3.2`
- `https://www.drupal.org/project/pathauto/releases/8.x-1.13`

Also useful (listing, not a single release):

```text
https://www.drupal.org/project/{machine_name}/releases
```

## What varies (expect chaos)

Release pages are **not** uniform. You may see:

- Full Markdown/HTML changelog with linked issues (`#1234567` or full `/node/` / `/project/.../issues/` URLs)
- A short paragraph and “See CHANGELOG.txt”
- Only packaging metadata (date, security coverage) and almost no notes
- Redirects or “Release not found” for bad tags
- Notes that only list dependency bumps

## Extraction rules

1. **Tag** — must match the requested tag; confirm it appears on the page or URL.
2. **Summary** — copy/condense **only** statements that describe changes in this
   release. Strip navigation, ads, and unrelated project chrome. Prefer the
   release body over comments.
3. **Issues** — collect absolute links to Drupal.org issues or change records
   that the page associates with this release. Normalize relative links to
   `https://www.drupal.org/...`. Skip `#fragment` social links.
4. **Previous tag** — only if the notes say “since 8.x-3.1”, “from 1.2.0”, etc.
5. **Do not** invent issues from the project’s general issue queue.

## Issue URL patterns to accept

- `https://www.drupal.org/node/{nid}`
- `https://www.drupal.org/project/{module}/issues/{nid}`
- `https://www.drupal.org/project/drupal/issues/{nid}` (core issues mentioned in notes)

Reject GitHub-only links unless they are clearly the project’s official tracker
**and** the release page links them (rare for d.o projects).

## Thin-page signal

Treat notes as **thin** when any of these hold:

- Body empty or under ~40 meaningful words after stripping chrome
- Only “No release notes” / “See git” / link to a repo with no list of changes
- Only security coverage / packaging lines with no changelog

Then use the GitLab fallback reference.
