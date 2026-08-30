# GitLab compare (Drupal.org GitLab)

Role in these skills: **enrichment and fallback**. The primary delta mechanism
is the local diff of the two downloaded tags — use this API to resolve
`previous_tag`, to enrich the release-notes summary with merged-MR titles and
issue links, and as the delta source only when the download fails. An API file
list (possibly paginated/truncated) is **not** a complete diff: a docs-impact
verdict built only from it can be at best `unknown`, never `none` — and
`retag-docs`' gates require the complete local diff outright.

Public API base: `https://git.drupalcode.org/api/v4`

Project path for contrib modules is usually `project/{machine_name}`  
(URL-encoded as `project%2F{machine_name}`).

## Resolve project

```http
GET /projects/project%2F{machine_name}
```

Use `id` from the JSON for subsequent calls. `web_url` is good to list in `sources`.

## List tags

```http
GET /projects/{id}/repository/tags?per_page=50
```

Each item has `name` and `commit.committed_date`. Use this to:

- Confirm the target `tag` exists
- Pick `previous_tag` only when ordering by commit date is unambiguous
  (the tag immediately older than the target). If unsure, **do not guess**.

## Compare two tags

```http
GET /projects/{id}/repository/compare?from={previous_tag}&to={tag}
```

Use commits in the response for a factual bullet list **only when** commit
messages clearly describe user-facing changes. Prefer merge requests when available.

## Merged merge requests between tags

Preferred enrichment path:

1. Get commit dates (or created dates) for `previous_tag` and `tag`.
2. List merged MRs updated/merged in that window:

```http
GET /projects/{id}/merge_requests?state=merged&per_page=50&updated_after={iso8601}
```

Filter client-side to MRs whose merge commit / merge date falls between the two
tags when possible. Each MR should contribute:

- `url`: `web_url` from the MR (git.drupalcode.org) **or** a linked Drupal.org
  issue from the description when present
- `title`: MR `title` (do not rewrite)

Drupal.org issue IDs often appear in MR titles/descriptions as `#1234567` —
expand only when you can form a real URL (`https://www.drupal.org/node/1234567`).

## Commits-only fallback

If MR listing is empty, use compare commits:

- Include commit `title` lines in the summary as a short bullet list
- Do **not** invent issue links from commit hashes alone

## Honesty

- Record `gitlab` in `sources` when you use this API.
- If the API errors (404 project, private, timeout), leave GitLab fields empty
  and keep Drupal.org-only data.
- Never fabricate MR lists to “look complete”.
