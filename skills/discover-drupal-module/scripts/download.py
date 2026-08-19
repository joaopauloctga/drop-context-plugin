#!/usr/bin/env python3
"""Download a Drupal contrib module from git.drupalcode.org and extract it.

Bundled with the `discover-drupal-module` skill. Self-contained: standard
library only — any Python 3.9+ runs it, nothing to install.

    python3 download.py <module> [ref]
    python3 download.py <module> --list

Extracts the module source into a per-user temp cache:

    <tempdir>/drupal-context-<user>/modules/<module>/<ref>/source/

so the skill can analyse it in place without touching the user's project or
home directory. The OS reclaims the temp dir on its own schedule; re-running
the same <module>/<ref> is a cache hit (no re-download).

Besides downloading, the script runs the discover skill's GATE: it validates
the extracted source, creates the docs output directory, and enumerates
submodules. On success the last lines of stdout are machine-parseable for the
orchestrating skill:

    GATE OK
    MODULE=<canonical project name>
    VERSION=<resolved ref>
    MODULE_ROOT=<absolute path to the directory containing the .info.yml>
    OUTPUT_DIR=<~/.drupal-context/modules/<module>/<ref>>
    DATE_EPOCH=<unix epoch seconds, for metadata.json>
    PROJECT_INFO=<path to project-info.json with Drupal.org project data, or none>
    SUBMODULE=<machine name>|<dir relative to MODULE_ROOT>   (one per submodule)
    SUBMODULES=<count>

The PROJECT_INFO file carries the module's Drupal.org project metadata
(security coverage, maintenance/development status, categories, ecosystem,
maintainers, creation date) fetched best-effort from the Drupal.org JSON:API
plus a scrape of the project page (maintainers and ecosystem are not in the
API). A fetch failure never fails the gate — PROJECT_INFO=none instead.
"""

from __future__ import annotations

import argparse
import getpass
import json
import re
import shutil
import sys
import tempfile
import time
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

BASE_URL = "https://git.drupalcode.org/api/v4"

# Drupal core has no "core" project; it lives at project/drupal. Map the
# friendly alias the user types to the canonical git.drupalcode.org slug.
_PROJECT_ALIASES = {"core": "drupal"}

# Drupal tag conventions we treat as "stable":
#   - Legacy core-compat: 8.x-1.17, 7.x-2.3 (sorted by core version first)
#   - Modern semver:      3.0.1, 2.0.0     (rank above all legacy tags)
# Prereleases (-alpha/-beta/-rc/-dev suffixes) are excluded.
_LEGACY_TAG_RE = re.compile(r"^(\d+)\.x-(\d+(?:\.\d+)*)$")
_SEMVER_TAG_RE = re.compile(r"^(\d+(?:\.\d+)*)$")
_PRERELEASE_RE = re.compile(r"-(?:alpha|beta|rc|dev)\d*$", re.IGNORECASE)


def default_output_base() -> Path:
    """Per-user temp cache base for downloaded module sources.

    The <user> suffix matters on Linux, where /tmp is shared between users; on
    macOS $TMPDIR is already per-user and the suffix is harmless.
    """
    try:
        user = getpass.getuser()
    except Exception:  # no username resolvable in this environment
        user = "shared"
    return Path(tempfile.gettempdir()) / f"drupal-context-{user}" / "modules"


def _resolve_project(module: str) -> str:
    return _PROJECT_ALIASES.get(module.lower(), module)


def _project_path(module: str) -> str:
    return quote(f"project/{module}", safe="")


def _api_get(url: str, params: dict[str, object], timeout: float) -> bytes:
    full = f"{url}?{urlencode({k: str(v) for k, v in params.items()})}"
    with urlopen(full, timeout=timeout) as resp:  # follows redirects
        return resp.read()


def _stable_sort_key(tag: str) -> tuple[int, ...] | None:
    """Sortable key for a stable tag, or None for prereleases / unparseable."""
    if _PRERELEASE_RE.search(tag):
        return None
    if m := _LEGACY_TAG_RE.match(tag):
        core = int(m.group(1))
        parts = tuple(int(p) for p in m.group(2).split("."))
        return (0, core, *parts)
    if m := _SEMVER_TAG_RE.match(tag):
        parts = tuple(int(p) for p in m.group(1).split("."))
        return (1, *parts)
    return None


def _list_kind(module: str, kind: str) -> None:
    url = f"{BASE_URL}/projects/{_project_path(module)}/repository/{kind}"
    params: dict[str, object] = {"per_page": 100}
    if kind == "tags":
        # Newest releases first so the relevant refs show even when truncated.
        params |= {"order_by": "version", "sort": "desc"}
    try:
        data = json.loads(_api_get(url, params, timeout=30.0))
    except HTTPError as exc:
        print("  (module not found)" if exc.code == 404 else f"  (request failed: HTTP {exc.code})")
        return
    except (URLError, OSError, ValueError) as exc:
        print(f"  (request failed: {exc})", file=sys.stderr)
        return

    if not data:
        print("  (none)")
        return
    for item in data:
        print(f"  - {item['name']}")
    if len(data) == 100:
        print("  ... (showing newest 100; pass a ref explicitly to pin one)")


def _get_tag_names(module: str) -> list[str]:
    """Return all tag names for the module, paginating through every page."""
    url = f"{BASE_URL}/projects/{_project_path(module)}/repository/tags"
    names: list[str] = []
    page = 1
    while True:
        try:
            batch = json.loads(_api_get(url, {"per_page": 100, "page": page}, timeout=30.0))
        except (HTTPError, URLError, OSError, ValueError):
            return names
        if not batch:
            break
        names.extend(item["name"] for item in batch)
        if len(batch) < 100:
            break
        page += 1
    return names


def resolve_latest_stable(module: str) -> str | None:
    """Pick the highest stable tag (semver-aware, prereleases excluded)."""
    tags = _get_tag_names(module)
    parsed = [(k, t) for t in tags if (k := _stable_sort_key(t)) is not None]
    if not parsed:
        return None
    parsed.sort()
    return parsed[-1][1]


def list_refs(module: str) -> None:
    print(f"\nTags for {module}:")
    _list_kind(module, "tags")
    print(f"\nBranches for {module}:")
    _list_kind(module, "branches")
    print()


DRUPAL_ORG_API = "https://www.drupal.org/jsonapi/index/project_modules"
DRUPAL_ORG_PROJECT_PAGE = "https://www.drupal.org/project/"


def _www_get(url: str, timeout: float) -> bytes:
    """GET against www.drupal.org (which rejects the default urllib UA)."""
    req = Request(url, headers={"User-Agent": "drupal-context-discover/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


class _ProjectPageParser(HTMLParser):
    """Extracts maintainers and ecosystem from a drupal.org project page.

    Mirrors the site's DrupalOrgService scrape: ecosystem = the links of the
    ``ul.project-info`` item whose text starts with "Ecosystem:"; maintainers =
    the ``/u/...`` links inside the ``div.maintainers`` section.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ecosystem: list[tuple[str, str]] = []  # (name, href)
        self.maintainers: list[str] = []
        self._info_ul_depth = 0
        self._in_info_li = False
        self._li_text: list[str] = []
        self._li_links: list[tuple[str, str]] = []
        self._maint_div_depth = 0
        self._link_text: list[str] | None = None
        self._link_kind = ""
        self._link_href = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        cls = attr.get("class") or ""
        if tag == "ul" and self._info_ul_depth == 0 and "project-info" in cls.split():
            self._info_ul_depth = 1
        elif tag == "ul" and self._info_ul_depth:
            self._info_ul_depth += 1
        if tag == "li" and self._info_ul_depth == 1:
            self._in_info_li = True
            self._li_text = []
            self._li_links = []
        if tag == "div":
            if self._maint_div_depth:
                self._maint_div_depth += 1
            elif "maintainers" in cls.split():
                self._maint_div_depth = 1
        if tag == "a":
            href = attr.get("href") or ""
            if self._in_info_li:
                self._link_text, self._link_kind, self._link_href = [], "info", href
            elif self._maint_div_depth and "/u/" in href:
                self._link_text, self._link_kind, self._link_href = [], "maintainer", href

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._link_text is not None:
            name = "".join(self._link_text).strip()
            if name:
                if self._link_kind == "info":
                    self._li_links.append((name, self._link_href))
                elif self._link_kind == "maintainer" and name not in self.maintainers:
                    self.maintainers.append(name)
            self._link_text = None
        if tag == "li" and self._in_info_li:
            if "".join(self._li_text).strip().startswith("Ecosystem:"):
                self.ecosystem.extend(t for t in self._li_links if t not in self.ecosystem)
            self._in_info_li = False
        if tag == "ul" and self._info_ul_depth:
            self._info_ul_depth -= 1
        if tag == "div" and self._maint_div_depth:
            self._maint_div_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._in_info_li:
            self._li_text.append(data)
        if self._link_text is not None:
            self._link_text.append(data)


def fetch_project_info(module: str) -> dict[str, object] | None:
    """Fetch the module's Drupal.org project metadata, best-effort.

    Returns None (after a stderr warning) on any failure — the discover gate
    must never fail because Drupal.org is unreachable.
    """
    query = {
        "filter[status]": "1",
        "filter[type]": "project_module",
        "filter[project_type]": "full",
        "filter[machine_name][value][0]": module,
        "filter[machine_name][operator]": "IN",
        "filter[machine_name][path]": "machine_name",
        "include": "field_module_categories,field_maintenance_status,field_development_status",
        "page[limit]": "1",
    }
    try:
        data = json.loads(_www_get(f"{DRUPAL_ORG_API}?{urlencode(query)}", timeout=30.0))
    except (HTTPError, URLError, OSError, ValueError) as exc:
        print(f"-> WARNING: Drupal.org API fetch failed for {module}: {exc}", file=sys.stderr)
        return None

    items = data.get("data") or []
    if not items:
        print(f"-> WARNING: no Drupal.org project found for {module}", file=sys.stderr)
        return None
    attrs = items[0].get("attributes") or {}
    rels = items[0].get("relationships") or {}
    included: dict[str, dict[str, dict]] = {}
    for inc in data.get("included") or []:
        included.setdefault(inc.get("type", ""), {})[inc.get("id", "")] = inc.get("attributes") or {}

    def _included_name(rel: object) -> str | None:
        if not isinstance(rel, dict) or not rel.get("id"):
            return None
        return (included.get(rel.get("type", ""), {}).get(rel["id"], {})).get("name")

    categories = []
    for ref in (rels.get("field_module_categories") or {}).get("data") or []:
        if name := _included_name(ref):
            categories.append(name)

    coverage = attrs.get("field_security_advisory_coverage") or ""
    info: dict[str, object] = {
        "machine_name": attrs.get("field_project_machine_name") or module,
        "title": attrs.get("title") or "",
        "security_coverage": coverage,
        "is_covered": coverage == "covered",
        "maintenance_status": _included_name((rels.get("field_maintenance_status") or {}).get("data")),
        "development_status": _included_name((rels.get("field_development_status") or {}).get("data")),
        "categories": categories,
        "ecosystem": [],
        "maintainers": [],
        "creation_date": attrs.get("created"),
        "fetched_at": int(time.time()),
    }

    try:
        parser = _ProjectPageParser()
        parser.feed(_www_get(DRUPAL_ORG_PROJECT_PAGE + module, timeout=30.0).decode("utf-8", errors="replace"))
        # A module that heads its own ecosystem gets a self-referencing
        # "Ecosystem:" link on drupal.org — that is not an ecosystem it
        # *belongs to*, so drop it and keep only links to other projects.
        self_path = f"/project/{module}".rstrip("/")
        info["ecosystem"] = [
            name
            for name, href in parser.ecosystem
            if href.split("?", 1)[0].removeprefix("https://www.drupal.org").rstrip("/") != self_path
        ]
        info["maintainers"] = parser.maintainers
    except (HTTPError, URLError, OSError) as exc:
        print(f"-> WARNING: Drupal.org project page scrape failed for {module}: {exc}", file=sys.stderr)

    return info


def _find_info_yml(dest_dir: Path) -> Path | None:
    """Locate the module's .info.yml at depth 1 (normal) or 2 (nested repos)."""
    for pattern in ("*.info.yml", "*/*.info.yml"):
        matches = sorted(p for p in dest_dir.glob(pattern) if "tests" not in p.parts)
        if matches:
            return matches[0]
    return None


def _replace_into(dest_dir: Path, item: Path) -> None:
    target = dest_dir / item.name
    if target.is_symlink() or target.is_file():
        target.unlink()
    elif target.is_dir():
        shutil.rmtree(target)
    shutil.move(str(item), str(target))


def _gate_report(module: str, ref: str, module_root: Path, cache_dir: Path) -> None:
    """GATE: prepare the output dir and print the machine-parseable block."""
    output_dir = Path.home() / ".drupal-context" / "modules" / module / ref.replace("/", "-")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Drupal.org project metadata, cached next to source/ for the module/ref.
    project_info = cache_dir / "project-info.json"
    if not project_info.is_file():
        if (info := fetch_project_info(module)) is not None:
            project_info.write_text(json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("GATE OK")
    print(f"MODULE={module}")
    print(f"VERSION={ref}")
    print(f"MODULE_ROOT={module_root.resolve()}")
    print(f"OUTPUT_DIR={output_dir}")
    print(f"DATE_EPOCH={int(time.time())}")
    print(f"PROJECT_INFO={project_info if project_info.is_file() else 'none'}")
    # Submodules: any *.info.yml in a SUBdirectory (a real, shippable module),
    # excluding test helper modules and vendored code.
    count = 0
    for info in sorted(module_root.rglob("*.info.yml")):
        rel = info.relative_to(module_root)
        if len(rel.parts) < 2:
            continue
        if {"tests", "test", "vendor", "node_modules"} & set(rel.parts):
            continue
        machine = info.name[: -len(".info.yml")]
        print(f"SUBMODULE={machine}|{rel.parent}")
        count += 1
    print(f"SUBMODULES={count}")


def download_module(module: str, ref: str, output_base: Path) -> None:
    # A ref can contain "/" (rare branch names); flatten it for the dir name.
    dest_dir = output_base / module / ref.replace("/", "-") / "source"

    # Cache hit: the source is already extracted for this module/ref.
    if (info := _find_info_yml(dest_dir)) is not None:
        print(f"-> Cache hit: {dest_dir}")
        _gate_report(module, ref, info.parent, dest_dir.parent)
        return

    dest_dir.mkdir(parents=True, exist_ok=True)
    url = f"{BASE_URL}/projects/{_project_path(module)}/repository/archive.zip"
    print(f"-> Downloading {module}@{ref}...")
    try:
        data = _api_get(url, {"sha": ref}, timeout=120.0)
    except HTTPError as exc:
        if exc.code == 404:
            print(f"Error: {module}@{ref} not found on git.drupalcode.org", file=sys.stderr)
        else:
            print(f"Error: download failed (HTTP {exc.code})", file=sys.stderr)
        sys.exit(1)
    except (URLError, OSError) as exc:
        print(f"Error: download failed ({exc})", file=sys.stderr)
        sys.exit(1)

    print(f"-> Downloaded ({len(data) // 1024} KiB), extracting...")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        zip_path = tmp_path / f"{module}.zip"
        zip_path.write_bytes(data)
        try:
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(tmp_path)
        except zipfile.BadZipFile:
            print("Error: downloaded archive is not a valid zip", file=sys.stderr)
            sys.exit(1)
        zip_path.unlink()

        # GitLab wraps contents in a single <repo>-<ref>-<sha>/ directory.
        # Lift that wrapper's contents so the module files land directly
        # under source/ rather than a nested wrapper dir.
        entries = list(tmp_path.iterdir())
        if len(entries) == 1 and entries[0].is_dir():
            for item in list(entries[0].iterdir()):
                _replace_into(dest_dir, item)
        else:
            for item in entries:
                _replace_into(dest_dir, item)

    info = _find_info_yml(dest_dir)
    if info is None:
        print(f"GATE FAILED: extracted {dest_dir} contains no *.info.yml — not a Drupal module?", file=sys.stderr)
        sys.exit(1)
    print(f"-> Extracted to: {dest_dir}")
    _gate_report(module, ref, info.parent, dest_dir.parent)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="download.py",
        description=(
            "Download a Drupal module from git.drupalcode.org into a per-user "
            "temp cache (<tempdir>/drupal-context-<user>/modules/<module>/<ref>/source/)."
        ),
    )
    parser.add_argument(
        "module_name",
        help="Drupal module machine name (e.g. token), or 'core' for Drupal core.",
    )
    parser.add_argument(
        "ref",
        nargs="?",
        help=(
            "Tag or branch to download (e.g. 8.x-1.x, 1.15). "
            "If omitted, the latest stable tag is auto-selected."
        ),
    )
    parser.add_argument(
        "-l", "--list", action="store_true",
        help="List available tags and branches for the module.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Base output directory (default: the per-user temp cache).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    project = _resolve_project(args.module_name)
    if project != args.module_name:
        print(f"-> '{args.module_name}' resolves to Drupal core project '{project}'")

    if args.list:
        list_refs(project)
        if not args.ref:
            return 0

    ref = args.ref
    if not ref:
        print(f"-> No ref specified, resolving latest stable tag for {project}...")
        ref = resolve_latest_stable(project)
        if not ref:
            print(
                f"Error: no stable tag found for {project}. "
                "Run with --list to see all refs (including dev branches) and pick one explicitly.",
                file=sys.stderr,
            )
            return 1
        print(f"-> Selected latest stable: {ref}")

    download_module(project, ref, args.output_dir or default_output_base())
    return 0


if __name__ == "__main__":
    sys.exit(main())
