#!/usr/bin/env python3
"""Resolve a Drupal module — contrib, custom, or core — inside an installed
Drupal repo, with zero network access.

Bundled with the `document-module` skill (and reused by
`document-core-module` via a sibling path — see that skill's SKILL.md).
Standard-library-only: any Python 3.9+ runs it, nothing to install.

    python3 resolve.py <module> [--path <dir>] [--drupal-root <dir>]
                                 [--repo-root <dir>] [--version <version>]

Unlike the pipeline's old download scripts, this script never fetches
anything. It expects to run **inside a Drupal repo** (or be pointed at one)
and reads whatever is already on disk:

  - a contrib module packaged by drupal.org: `<machine>.info.yml` carries
    `version:` + `project:`.
  - a fallback/cross-check: `composer.lock` → package `drupal/<project>`.
  - Drupal core itself: `core/lib/Drupal.php` → `const VERSION`. A core
    module's OWN `.info.yml` often carries the literal placeholder string
    `version: VERSION` — that is a packaging-time token, never a real
    version, and must never be read as one.
  - a submodule inherits its parent's `project:` (and, once packaged, its
    `version:`) — that is what distinguishes a submodule from a root project,
    not directory depth.
  - a custom module, or a contrib module installed straight from git with no
    drupal.org packaging step, may have no resolvable version at all. This
    script never guesses one — it stops and asks (see "GATE NEEDS INPUT"
    below).

On success the script prints the same `GATE OK` contract the old download
scripts printed (minus `PROJECT_INFO`, which no longer exists — this script
never talks to drupal.org):

    GATE OK
    MODULE=<machine name>
    PROJECT=<drupal.org project, from info.yml `project:`, or = MODULE>
    KIND=core|contrib|custom
    VERSION=<resolved by the ladder above>
    MODULE_ROOT=<absolute path inside the repo — READ-ONLY, never write here>
    DRUPAL_ROOT=<absolute docroot>
    OUTPUT_DIR=<absolute, always under ${DROP_CONTEXT_HOME:-~/.drop-context}/docs/…>
    DATE_EPOCH=<unix epoch seconds>
    IS_SUBMODULE=yes|no
    PARENT=<parent machine name>        (only when IS_SUBMODULE=yes)
    PARENT_ROOT=<absolute path>          (only when IS_SUBMODULE=yes)
    SUBMODULE=<machine name>|<dir relative to MODULE_ROOT>   (one per submodule)
    SUBMODULES=<count>

`IS_SUBMODULE` is detected from directory nesting (a `*.info.yml` in an
ancestor directory between `MODULE_ROOT` and the module search root), not
from the `project:` key alone — a submodule without drupal.org packaging
still nests under its parent's directory. By default a submodule resolves to
`GATE NEEDS INPUT REASON=submodule-of-parent` instead of `GATE OK` (see
below) — pass `--allow-submodule-standalone` only when the caller has
explicit user confirmation to document it as a standalone set anyway.

`--kind <core|contrib|custom>[,<kind>...]` restricts which kinds are
acceptable; a resolved module whose kind isn't in the list is
`GATE NEEDS INPUT REASON=kind-mismatch` instead of `GATE OK`.

Every failure mode is actionable — never a bare "not found":

    GATE NEEDS INPUT
    REASON=module-not-found
    SEARCHED=<dirs actually searched>
    HINT=install it (composer require drupal/<x>) or re-run with --path <dir>

    GATE NEEDS INPUT
    REASON=version-unresolved
    MODULE=<machine name>
    TRIED=<what was checked and why each failed>
    SUGGEST=dev[, <short-sha>]

    GATE NEEDS INPUT
    REASON=ambiguous
    MODULE=<machine name>
    CANDIDATES=<path>|<path>|...
    HINT=re-run with --path <dir> to pick one

    GATE NEEDS INPUT
    REASON=submodule-of-parent
    MODULE=<machine name>
    PARENT=<parent machine name>
    PARENT_ROOT=<absolute path>
    HINT=run /drop-context:document-module <parent> to document this as part of its
         parent (submodules/<module>.md); pass --allow-submodule-standalone
         to force a standalone doc set anyway

    GATE NEEDS INPUT
    REASON=kind-mismatch
    MODULE=<machine name>
    EXPECTED=<requested --kind list>
    ACTUAL=<resolved kind>
    HINT=<which document skill actually handles ACTUAL>
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

VERSION_CONST_RE = re.compile(r"const\s+VERSION\s*=\s*['\"]([^'\"]+)['\"]")
INFO_VERSION_RE = re.compile(r"^version:\s*['\"]?([^'\"\r\n]+?)['\"]?\s*$", re.MULTILINE)
INFO_PROJECT_RE = re.compile(r"^project:\s*['\"]?([^'\"\r\n]+?)['\"]?\s*$", re.MULTILINE)

# The literal placeholder drupal.org's packaging script leaves in *.info.yml
# for modules that ship inside core — never a real version.
CORE_VERSION_PLACEHOLDER = "VERSION"

PRUNE_DIRS = {"tests", "test", "vendor", "node_modules", ".git"}


class GateError(RuntimeError):
    """A resolution error the document skill should stop and report."""


class NeedsInput(RuntimeError):
    """A resolution outcome the document skill must ask the user about."""

    def __init__(self, reason: str, fields: dict[str, str]) -> None:
        super().__init__(reason)
        self.reason = reason
        self.fields = fields


# --------------------------------------------------------------------------
# Repo / docroot resolution
# --------------------------------------------------------------------------


def _looks_like_site_root(anchor: Path) -> bool:
    """Does `anchor`'s composer.json look like the SITE's own composer.json,
    as opposed to a package's (a contrib module, or web/core)?

    Trap: contrib modules and web/core both ship their own composer.json, so
    a naive "first composer.json found while walking up" stops there instead
    of at the actual site root — e.g. starting inside
    web/modules/contrib/entity resolves "repo root" to the entity module
    itself, and starting inside web/core resolves it to web/core. Measured
    against a real site: the site root has a composer.lock beside it, or
    `type: project`, or `extra.installer-paths`; web/core has `type:
    drupal-core` and `extra.drupal-scaffold` but no lock file and no
    installer-paths; a contrib module has `type: drupal-module` and none of
    the above. `drupal-scaffold` alone is NOT a valid discriminator — web/core
    carries it too.
    """
    if (anchor / "composer.lock").is_file():
        return True
    try:
        data = json.loads((anchor / "composer.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if data.get("type") == "project":
        return True
    if (data.get("extra") or {}).get("installer-paths"):
        return True
    return False


def find_repo_root(start: Path) -> Path | None:
    """Walk up from `start` looking for the site's own composer.json (see
    `_looks_like_site_root`), not just the first composer.json found — that
    would catch a contrib module's or web/core's own composer.json instead.
    Falls back to the outermost composer.json seen if none qualifies."""
    fallback: Path | None = None
    for anchor in (start, *start.parents):
        if not (anchor / "composer.json").is_file():
            continue
        fallback = anchor  # keeps being overwritten -> ends up outermost
        if _looks_like_site_root(anchor):
            return anchor
    return fallback


def web_root_from_composer(repo_root: Path) -> str | None:
    try:
        data = json.loads((repo_root / "composer.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    web_root = (
        (data.get("extra") or {})
        .get("drupal-scaffold", {})
        .get("locations", {})
        .get("web-root")
    )
    if isinstance(web_root, str):
        return web_root.strip("/")
    return None


def is_drupal_root(path: Path) -> bool:
    return (path / "core" / "lib" / "Drupal.php").is_file()


def resolve_drupal_root(explicit: Path | None, repo_hint: Path | None, start: Path) -> tuple[Path, Path]:
    """Return (drupal_root, repo_root)."""
    if explicit is not None:
        drupal_root = explicit.expanduser().resolve()
        if not is_drupal_root(drupal_root):
            raise GateError(
                f"--drupal-root {drupal_root} does not look like a Drupal docroot "
                "(no core/lib/Drupal.php under it)"
            )
        repo_root = repo_hint.expanduser().resolve() if repo_hint else (
            drupal_root.parent if drupal_root.name == "web" or drupal_root.name == "docroot" else drupal_root
        )
        return drupal_root, repo_root

    repo_root = find_repo_root(start)
    if repo_root is not None:
        web_root = web_root_from_composer(repo_root)
        candidates = [repo_root / web_root] if web_root else []
        candidates += [repo_root, repo_root / "web", repo_root / "docroot"]
        for candidate in candidates:
            if is_drupal_root(candidate):
                return candidate.resolve(), repo_root.resolve()

    # No composer.json anywhere above `start`, or it didn't lead anywhere —
    # fall back to a plain ancestor walk for the conventional layouts.
    for anchor in (start, *start.parents):
        for name in (".", "web", "docroot"):
            candidate = anchor / name
            if is_drupal_root(candidate):
                return candidate.resolve(), anchor.resolve()

    raise GateError(
        f"could not find a Drupal docroot (core/lib/Drupal.php) from {start} or "
        "its ancestors, and no composer.json pointed at one. Run this from inside "
        "a Drupal repo, or pass --drupal-root <dir> explicitly."
    )


# --------------------------------------------------------------------------
# Module location
# --------------------------------------------------------------------------


def installer_path_candidates(repo_root: Path, drupal_root: Path, module: str) -> list[Path]:
    composer_path = repo_root / "composer.json"
    if not composer_path.is_file():
        return []
    try:
        data = json.loads(composer_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    installer_paths = (data.get("extra") or {}).get("installer-paths") or {}
    candidates: list[Path] = []
    for template in installer_paths:
        if "drupal-module" not in "".join(installer_paths[template]) and "drupal-custom-module" not in "".join(
            installer_paths[template]
        ):
            continue
        if "{$name}" not in template:
            continue
        rel = template.replace("{$name}", module)
        candidates.append((repo_root / rel).resolve())
    return candidates


def scan_for_module(drupal_root: Path, module: str) -> list[Path]:
    """Find every `<module>.info.yml` under the conventional module roots."""
    target_name = f"{module}.info.yml"
    matches: list[Path] = []
    seen: set[Path] = set()

    search_roots = [
        drupal_root / "modules",
        drupal_root / "core" / "modules",
        drupal_root / "profiles",
    ]
    for root in search_roots:
        if not root.is_dir():
            continue
        for info in root.rglob(target_name):
            if PRUNE_DIRS & set(info.relative_to(root).parts[:-1]):
                continue
            resolved = info.parent.resolve()
            if resolved not in seen:
                seen.add(resolved)
                matches.append(resolved)
    return matches


def locate_module(repo_root: Path, drupal_root: Path, module: str) -> Path:
    # Fast path: composer's installer-paths tells us exactly where a
    # top-level (non-nested) project lands.
    for candidate in installer_path_candidates(repo_root, drupal_root, module):
        if (candidate / f"{module}.info.yml").is_file():
            return candidate

    matches = scan_for_module(drupal_root, module)
    if not matches:
        raise NeedsInput(
            "module-not-found",
            {
                "SEARCHED": f"{drupal_root}/modules, {drupal_root}/core/modules, {drupal_root}/profiles",
                "HINT": f"install it (composer require drupal/{module}) or re-run with --path <dir>",
            },
        )
    if len(matches) > 1:
        raise NeedsInput(
            "ambiguous",
            {
                "MODULE": module,
                "CANDIDATES": "|".join(str(p) for p in matches),
                "HINT": "re-run with --path <dir> to pick one",
            },
        )
    return matches[0]


# --------------------------------------------------------------------------
# Classification + version ladder
# --------------------------------------------------------------------------


def classify_kind(module_root: Path, drupal_root: Path) -> str:
    try:
        rel_parts = module_root.relative_to(drupal_root).parts
    except ValueError:
        rel_parts = module_root.parts
    if rel_parts and rel_parts[0] == "core":
        return "core"
    if "custom" in rel_parts:
        return "custom"
    return "contrib"


def read_info_yml(info_path: Path) -> str:
    try:
        return info_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise GateError(f"cannot read {info_path}: {exc}") from exc


def info_yml_path(module_root: Path, module: str) -> Path:
    path = module_root / f"{module}.info.yml"
    if not path.is_file():
        raise GateError(f"expected {path} to exist (it was how the module was located)")
    return path


def drupal_core_version(drupal_root: Path) -> str:
    drupal_php = drupal_root / "core" / "lib" / "Drupal.php"
    try:
        text = drupal_php.read_text(encoding="utf-8")
    except OSError as exc:
        raise GateError(f"cannot read Drupal core version from {drupal_php}: {exc}") from exc
    match = VERSION_CONST_RE.search(text)
    if not match:
        raise GateError(f"Drupal::VERSION not found in {drupal_php}")
    return match.group(1)


def composer_lock_version(repo_root: Path, project: str) -> str | None:
    lock_path = repo_root / "composer.lock"
    if not lock_path.is_file():
        return None
    try:
        data = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    for section in ("packages", "packages-dev"):
        for package in data.get(section, []) or []:
            if package.get("name") == f"drupal/{project}":
                version = package.get("version")
                if isinstance(version, str):
                    return version.lstrip("v")
    return None


def git_short_sha(repo_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def resolve_version(
    kind: str,
    module: str,
    project: str,
    module_root: Path,
    drupal_root: Path,
    repo_root: Path,
    override: str | None,
) -> str:
    if override:
        return override

    if kind == "core":
        return drupal_core_version(drupal_root)

    info_text = read_info_yml(info_yml_path(module_root, module))
    tried: list[str] = []

    match = INFO_VERSION_RE.search(info_text)
    if match and match.group(1).strip() != CORE_VERSION_PLACEHOLDER:
        return match.group(1).strip()
    tried.append(
        "info.yml `version:` (absent)" if not match else "info.yml `version:` (literal VERSION placeholder — ignored)"
    )

    lock_version = composer_lock_version(repo_root, project)
    if lock_version:
        return lock_version
    tried.append(f"composer.lock (no drupal/{project} entry)")

    suggestions = ["dev"]
    sha = git_short_sha(repo_root)
    if sha:
        suggestions.append(sha)

    raise NeedsInput(
        "version-unresolved",
        {
            "MODULE": module,
            "TRIED": "; ".join(tried),
            "SUGGEST": ", ".join(suggestions),
        },
    )


def project_name(module: str, module_root: Path) -> str:
    info_path = module_root / f"{module}.info.yml"
    if not info_path.is_file():
        return module
    text = read_info_yml(info_path)
    match = INFO_PROJECT_RE.search(text)
    return match.group(1).strip() if match else module


# --------------------------------------------------------------------------
# Submodule-of relationship (is MODULE itself nested under a parent module?)
# --------------------------------------------------------------------------


def find_parent_module(module_root: Path, drupal_root: Path) -> tuple[str, Path] | None:
    """If `module_root` is nested inside another module's directory (a real
    submodule, e.g. .../flag/modules/flag_bookmark), return that parent's
    (machine name, root dir). Detected structurally — an ancestor directory,
    strictly between `module_root` and the search root, that itself holds a
    `*.info.yml` — independent of whether `project:` keys are present."""
    search_roots = (
        drupal_root / "modules",
        drupal_root / "core" / "modules",
        drupal_root / "profiles",
    )
    base = next((root for root in search_roots if root in module_root.parents), None)
    if base is None:
        return None
    current = module_root.parent
    while current != base:
        matches = sorted(current.glob("*.info.yml"))
        if matches:
            return matches[0].name[: -len(".info.yml")], current
        current = current.parent
    return None


# --------------------------------------------------------------------------
# Submodule enumeration (unchanged shape from the old download scripts)
# --------------------------------------------------------------------------


def enumerate_submodules(module_root: Path) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for info in sorted(module_root.rglob("*.info.yml")):
        rel = info.relative_to(module_root)
        if len(rel.parts) < 2:
            continue
        if PRUNE_DIRS & set(rel.parts):
            continue
        machine = info.name[: -len(".info.yml")]
        result.append((machine, str(rel.parent)))
    return result


# --------------------------------------------------------------------------
# Output dir — always under a single user-level location, independent of
# which repo the user happens to be standing in (never <repo-root>/…).
# --------------------------------------------------------------------------


def drop_context_home() -> Path:
    """Base directory for all pipeline + CLI state. Defaults to
    ~/.drop-context; override with DROP_CONTEXT_HOME (e.g. to exercise this
    script in a test without touching the real home directory)."""
    override = os.environ.get("DROP_CONTEXT_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".drop-context"


def docs_root() -> Path:
    """${DROP_CONTEXT_HOME:-~/.drop-context}/docs — the root of every document/make output this pipeline writes.

    The `docs/` level is mandatory, not decorative. `~/.drop-context/` is
    also the home of the separate `drop-context` PHP CLI, which already owns
    app.json, cache/, update-check.json, skills/ and agents/ directly under
    it — in particular ~/.drop-context/skills/ already holds CLI-installed
    skills (dc-flag, dc-views, …). Nesting this pipeline's output under
    docs/ is the only thing keeping this pipeline's own skills/ (generated
    module skills) from colliding with the CLI's skills/ directory. Do not
    flatten this away.
    """
    return drop_context_home() / "docs"


def build_output_dir(kind: str, module: str, version: str) -> Path:
    root = docs_root()
    safe_version = version.replace("/", "-")
    if kind == "core":
        output_dir = root / "core" / safe_version / module
    else:
        output_dir = root / "modules" / module / safe_version
    # Hard assertion per the read-only-repo risk: never let a resolution bug
    # point output outside the docs root.
    if root not in output_dir.parents and output_dir != root:
        raise GateError(f"refusing to write outside {root}: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("module", help="Module machine name (contrib, custom, or core).")
    parser.add_argument(
        "--path",
        type=Path,
        default=None,
        help="Where to start looking for the Drupal repo (default: cwd). "
        "Also accepted as a disambiguation hint after a `GATE NEEDS INPUT REASON=ambiguous`.",
    )
    parser.add_argument(
        "--drupal-root",
        type=Path,
        default=None,
        help="Explicit Drupal docroot (skips repo/docroot auto-discovery).",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Explicit site repo root for SOURCE-side resolution (composer.lock version "
        "lookup, git short sha) — only consulted together with --drupal-root, when the "
        "repo root can't be derived from it automatically. Does not affect output "
        "placement: output always goes under ${DROP_CONTEXT_HOME:-~/.drop-context}/docs/.",
    )
    parser.add_argument(
        "--version",
        default=None,
        help="Version label to use when it cannot be resolved from disk "
        "(answer to a prior `GATE NEEDS INPUT REASON=version-unresolved`).",
    )
    parser.add_argument(
        "--kind",
        default=None,
        help="Comma-separated allowed kinds, e.g. `contrib,custom` or `core`. "
        "A resolved module of a different kind is `GATE NEEDS INPUT REASON=kind-mismatch` "
        "instead of `GATE OK` — used by the document skills to refuse the wrong track.",
    )
    parser.add_argument(
        "--allow-submodule-standalone",
        action="store_true",
        help="Allow resolving a submodule as a standalone module (GATE OK) instead of "
        "refusing with `GATE NEEDS INPUT REASON=submodule-of-parent`. Pass this only "
        "after the user explicitly confirmed they want a standalone doc set, not the "
        "default parent-module `submodules/<module>.md` treatment.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    module = args.module

    try:
        start = (args.path or Path.cwd()).expanduser().resolve()
        drupal_root, repo_root = resolve_drupal_root(args.drupal_root, args.repo_root, start)

        module_root = locate_module(repo_root, drupal_root, module)
        kind = classify_kind(module_root, drupal_root)

        if args.kind:
            allowed = {k.strip() for k in args.kind.split(",") if k.strip()}
            if kind not in allowed:
                if kind == "core":
                    hint = "this is a core module; use /drop-context:document-core-module instead"
                elif "core" in allowed and len(allowed) == 1:
                    hint = "this is a contrib/custom module; use /drop-context:document-module instead"
                else:
                    hint = f"resolved kind {kind!r} is not in the allowed set {sorted(allowed)!r}"
                raise NeedsInput(
                    "kind-mismatch",
                    {
                        "MODULE": module,
                        "EXPECTED": args.kind,
                        "ACTUAL": kind,
                        "HINT": hint,
                    },
                )

        parent = find_parent_module(module_root, drupal_root)
        if parent is not None and not args.allow_submodule_standalone:
            parent_machine, parent_root = parent
            raise NeedsInput(
                "submodule-of-parent",
                {
                    "MODULE": module,
                    "PARENT": parent_machine,
                    "PARENT_ROOT": parent_root,
                    "HINT": f"run /drop-context:document-module {parent_machine} to document this as part "
                    f"of its parent (submodules/{module}.md); pass --allow-submodule-standalone "
                    "to force a standalone doc set anyway",
                },
            )

        project = project_name(module, module_root)
        version = resolve_version(kind, module, project, module_root, drupal_root, repo_root, args.version)

        output_dir = build_output_dir(kind, module, version)
        submodules = enumerate_submodules(module_root)

        print("GATE OK")
        print(f"MODULE={module}")
        print(f"PROJECT={project}")
        print(f"KIND={kind}")
        print(f"VERSION={version}")
        print(f"MODULE_ROOT={module_root}")
        print(f"DRUPAL_ROOT={drupal_root}")
        print(f"OUTPUT_DIR={output_dir}")
        print(f"DATE_EPOCH={int(time.time())}")
        if parent is not None:
            parent_machine, parent_root = parent
            print("IS_SUBMODULE=yes")
            print(f"PARENT={parent_machine}")
            print(f"PARENT_ROOT={parent_root}")
        else:
            print("IS_SUBMODULE=no")
        for machine, rel_dir in submodules:
            print(f"SUBMODULE={machine}|{rel_dir}")
        print(f"SUBMODULES={len(submodules)}")
        return 0
    except NeedsInput as needs:
        print("GATE NEEDS INPUT")
        print(f"REASON={needs.reason}")
        for key, value in needs.fields.items():
            print(f"{key}={value}")
        return 2
    except GateError as exc:
        print(f"GATE FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
