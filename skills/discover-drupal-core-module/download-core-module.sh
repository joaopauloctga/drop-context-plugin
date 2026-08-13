#!/usr/bin/env bash
#
# download-core-module.sh — fetch a single Drupal *core* module's source and
# cache it on disk, so the `discover-drupal-core-module` skill can analyse it in
# place without ever downloading the whole ~50 MB core archive.
#
# Drupal core has no per-module project on drupal.org: every core module lives
# inside the `drupal` repo under core/modules/<module>/. We exploit GitLab's
# `archive.zip?path=<subtree>` to download ONLY that subtree (≈1 MB), then lift
# core/modules/<module>/ out of the wrapper into a per-version+module cache dir.
#
# Usage:
#   ./download-core-module.sh <module> [version]
#
#   <module>   core module machine name (e.g. views, node, field, system).
#   [version]  core tag (e.g. 11.1.0). If omitted, the latest stable core tag
#              is resolved automatically.
#
# Besides downloading, the script runs the discover skill's GATE: it validates
# the cached source, creates the docs output directory, and enumerates
# submodules. Output (stdout, last lines, machine-parseable by the orchestrator):
#   GATE OK
#   MODULE=<machine name>
#   VERSION=<resolved version>
#   MODULE_ROOT=<absolute path to the cached module dir containing the .info.yml>
#   OUTPUT_DIR=<~/.drupal-context/core/<version>/<module>>
#   DATE_EPOCH=<unix epoch seconds, for metadata.json>
#   SUBMODULE=<machine name>|<dir relative to MODULE_ROOT>   (one per submodule)
#   SUBMODULES=<count>
#
# Cache layout (override the base with $DRUPAL_CONTEXT_CACHE) — a per-user temp
# dir, so the source never occupies the user's project or home, and the OS
# reclaims it on its own schedule (the -<user> suffix matters on Linux, where
# /tmp is shared; on macOS $TMPDIR is already per-user and it is harmless):
#   <tempdir>/drupal-context-<user>/core/<version>/<module>/<module>.info.yml
#
# Re-running for a cached <version>/<module> is a no-op download (cache hit).

set -euo pipefail

readonly API_BASE="https://git.drupalcode.org/api/v4"
# project/drupal, URL-encoded ("project%2Fdrupal") for the GitLab API path.
readonly PROJECT="project%2Fdrupal"

CACHE_BASE="${DRUPAL_CONTEXT_CACHE:-${TMPDIR:-/tmp}/drupal-context-$(id -un)}/core"

die() { echo "Error: $*" >&2; exit 1; }
log() { echo "-> $*" >&2; }

# --- resolve_latest_stable ---------------------------------------------------
# Page through every core tag, keep only pure semver tags (X.Y.Z — no
# -alpha/-beta/-rc/-dev and no non-version tags like "start"), and print the
# highest one. Uses `sort -V` (version sort) to rank.
resolve_latest_stable() {
  local page=1 names="" batch count
  while :; do
    batch="$(curl -sS -L --fail \
      "${API_BASE}/projects/${PROJECT}/repository/tags?per_page=100&page=${page}" \
      2>/dev/null | grep -oE '"name":"[^"]+"' | sed -E 's/"name":"([^"]+)"/\1/')" \
      || break
    [ -z "$batch" ] && break
    names+="${batch}"$'\n'
    count="$(printf '%s\n' "$batch" | grep -c . || true)"
    [ "$count" -lt 100 ] && break
    page=$((page + 1))
  done

  printf '%s\n' "$names" \
    | grep -E '^[0-9]+\.[0-9]+\.[0-9]+$' \
    | sort -V \
    | tail -1
}

# --- emit_gate_report --------------------------------------------------------
# GATE: prepare the docs output dir and print the machine-parseable block the
# discover skill consumes. Uses the globals MODULE, VERSION, DEST.
emit_gate_report() {
  local output_dir="$HOME/.drupal-context/core/${VERSION}/${MODULE}"
  mkdir -p "$output_dir"
  echo "GATE OK"
  echo "MODULE=${MODULE}"
  echo "VERSION=${VERSION}"
  echo "MODULE_ROOT=${DEST}"
  echo "OUTPUT_DIR=${output_dir}"
  echo "DATE_EPOCH=$(date +%s)"
  # Submodules: any *.info.yml in a SUBdirectory (a real, shippable module),
  # excluding test helper modules and vendored code.
  local count=0 f rel machine
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    rel="${f#"${DEST}"/}"
    machine="$(basename "$f" .info.yml)"
    echo "SUBMODULE=${machine}|$(dirname "$rel")"
    count=$((count + 1))
  done <<< "$(find "$DEST" -mindepth 2 -name '*.info.yml' \
    -not -path '*/tests/*' -not -path '*/test/*' -not -path '*/vendor/*' | sort)"
  echo "SUBMODULES=${count}"
}

# --- main --------------------------------------------------------------------
[ $# -ge 1 ] || die "usage: download-core-module.sh <module> [version]"

MODULE="$1"
VERSION="${2:-}"

# Guard against an accidental "core/modules/views" or path-y input.
case "$MODULE" in
  */*) die "module must be a bare machine name (e.g. views), not a path: $MODULE" ;;
esac

if [ -z "$VERSION" ]; then
  log "No version given; resolving latest stable Drupal core tag..."
  VERSION="$(resolve_latest_stable)"
  [ -n "$VERSION" ] || die "could not resolve a stable core tag from the GitLab API."
  log "Selected latest stable core: ${VERSION}"
fi

DEST="${CACHE_BASE}/${VERSION}/${MODULE}"
INFO="${DEST}/${MODULE}.info.yml"

# --- cache hit ---------------------------------------------------------------
if [ -f "$INFO" ]; then
  log "Cache hit: ${DEST}"
  emit_gate_report
  exit 0
fi

# --- cache miss: sparse download --------------------------------------------
SUBTREE="core/modules/${MODULE}"
ARCHIVE_URL="${API_BASE}/projects/${PROJECT}/repository/archive.zip?sha=${VERSION}&path=${SUBTREE}"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

log "Downloading ${MODULE} from Drupal core ${VERSION} (sparse: ${SUBTREE})..."
if ! curl -sS -L --fail -o "${TMP}/m.zip" "$ARCHIVE_URL"; then
  die "download failed for core ${VERSION}. That version tag may not exist — pass an explicit version (see https://git.drupalcode.org/project/drupal/-/tags) or omit it to use the latest stable."
fi

# GitLab answers an unknown `path=` subtree with HTTP 200 and a ZERO-byte body
# (not a 404), so --fail above won't catch a non-existent module. A real core
# module archive is always non-trivial; an empty body means the subtree wasn't
# found — i.e. the module name is wrong or it isn't under core/modules/.
if [ ! -s "${TMP}/m.zip" ]; then
  die "no source returned for '${MODULE}' in core ${VERSION}. The module name is likely wrong, or it does not live under core/modules/ (it may be a core profile, theme, or removed in this version)."
fi

log "Extracting..."
unzip -q "${TMP}/m.zip" -d "${TMP}/x" || die "downloaded archive is not a valid zip."

# GitLab wraps everything in a single <repo>-<ref>-<sha>-<path-slug>/ dir, and
# inside it the requested subtree is reproduced at its full repo path. The real
# module dir is therefore at <wrapper>/core/modules/<module>/.
WRAPPER="$(find "${TMP}/x" -maxdepth 1 -mindepth 1 -type d | head -1)"
[ -n "$WRAPPER" ] || die "unexpected archive layout: no wrapper directory."
SRC="${WRAPPER}/${SUBTREE}"
[ -d "$SRC" ] || die "module ${MODULE} not found under ${SUBTREE} in core ${VERSION}. It may live under core/profiles/ or core/themes/, or not exist in this version."

# Lift the module dir into the cache atomically-ish: extract to a sibling temp
# then move into place, so a partial/failed run never leaves a half-populated
# cache dir that would later read as a cache hit.
mkdir -p "$(dirname "$DEST")"
rm -rf "$DEST"
mv "$SRC" "$DEST"

[ -f "$INFO" ] || die "GATE FAILED: extraction succeeded but ${MODULE}.info.yml is missing under ${DEST}. Is '${MODULE}' really a core module?"

log "Cached: ${DEST}"
emit_gate_report
