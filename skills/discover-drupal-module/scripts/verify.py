#!/usr/bin/env python3
"""Verify a discover output directory (step 7 of the discover skills).

    python3 verify.py <OUTPUT_DIR> [--submodules N] [--module-root PATH]

Cross-checks metadata.json against the files on disk in both directions:
every required doc file present, listed, and non-empty; no unlisted files;
valid categories; submodule file count matching the expected count (--submodules:
the GATE's SUBMODULES in a full run, fewer when a submodule scope deferred
some). A `submodules_skipped` key in metadata.json (written by root-only /
partial-scope runs) is validated too: each entry needs non-empty `name` and
`dir` strings, and a submodule may never be both skipped and documented.

With --module-root (the GATE's MODULE_ROOT), additionally validates every
``Drupal\\<module>\\...`` class reference found in the generated docs against
the module source via PSR-4 (``Drupal\\m\\X\\Y`` -> ``src/X/Y.php``; submodule
namespaces map to the submodule's own ``src/``). A reference that resolves to
neither a class file nor a namespace directory is reported as a PROBLEM — it
usually means a doc names a class that does not exist. References outside the
module's own namespaces (``Drupal\\Core\\...``, other modules, example
namespaces) are skipped: they cannot be checked against this source.

Standard library only. Prints WARNING/PROBLEM lines, then either "VERIFY OK"
(exit 0) or "VERIFY FAILED (n problem(s))" (exit 1).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

CORE_FILES = {
    "summary.md": "Summary",
    "entities.md": "Entities",
    "plugins.md": "Plugins",
    "services.md": "Services",
    "configuration.md": "Configuration",
    "permissions.md": "Permissions",
    "routes.md": "Routes",
    "hooks.md": "Hooks",
    "events.md": "Events",
    "extension-points.md": "Extension Points",
    "ai-integration.md": "AI Integration",
}
VALID_CATEGORIES = set(CORE_FILES.values()) | {"Submodule"}
REQUIRED_META_KEYS = ("name", "human_name", "type", "version", "date", "files")
REQUIRED_FILE_KEYS = ("file", "category", "title", "description")

FQCN_RE = re.compile(
    r"Drupal\\((?:[A-Za-z_][A-Za-z0-9_]*)(?:\\[A-Za-z_][A-Za-z0-9_]*)+)"
)


def check_fqcns(
    d: Path, module_root: Path, module_name: str, submodules: list[str]
) -> tuple[list[str], int]:
    """Validate Drupal\\<ext>\\... references in *.md files against the source."""
    ns_roots: dict[str, Path] = {module_name: module_root}
    for sub in submodules:
        info = next(
            (
                p
                for p in sorted(module_root.glob(f"**/{sub}.info.yml"))
                if "tests" not in p.parts and "test" not in p.parts
            ),
            None,
        )
        if info is not None:
            ns_roots[sub] = info.parent

    problems: list[str] = []
    seen: set[str] = set()
    checked = 0
    for md in sorted(d.rglob("*.md")):
        # Audit reports may cite invented FQCNs as examples of errors.
        if md.name.startswith("audit-"):
            continue
        # Docs sometimes write PHP-string style double backslashes; normalize.
        text = md.read_text(encoding="utf-8", errors="replace").replace("\\\\", "\\")
        for m in FQCN_RE.finditer(text):
            segs = m.group(1).split("\\")
            ext, rest = segs[0], segs[1:]
            if ext not in ns_roots or not rest:
                continue
            fqcn = "Drupal\\" + m.group(1)
            if fqcn in seen:
                continue
            seen.add(fqcn)
            checked += 1
            base = ns_roots[ext] / "src"
            as_file = base.joinpath(*rest).with_suffix(".php")
            as_dir = base.joinpath(*rest)
            if not as_file.is_file() and not as_dir.is_dir():
                rel = md.relative_to(d)
                problems.append(
                    f"{rel}: unresolvable class reference {fqcn} "
                    f"(neither src/{'/'.join(rest)}.php nor that namespace dir "
                    f"exists under the {ext} source)"
                )
    return problems, checked


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("output_dir", type=Path, help="The discover OUTPUT_DIR to verify.")
    ap.add_argument(
        "--submodules",
        type=int,
        default=None,
        help="Expected submodule doc file count on disk after this run (the "
        "GATE's SUBMODULES in a full run; fewer when a submodule scope "
        "deferred some to submodules_skipped).",
    )
    ap.add_argument(
        "--module-root",
        type=Path,
        default=None,
        help="Module source root (the GATE's MODULE_ROOT); enables validation of "
        "Drupal\\<module>\\... class references in the docs against the source.",
    )
    args = ap.parse_args()

    d = args.output_dir
    problems: list[str] = []
    warnings: list[str] = []

    if not d.is_dir():
        print(f"VERIFY FAILED: output dir does not exist: {d}")
        return 1

    meta = None
    meta_path = d / "metadata.json"
    if not meta_path.is_file():
        problems.append("metadata.json is missing")
    else:
        try:
            meta = json.loads(meta_path.read_text())
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            problems.append(f"metadata.json does not parse: {exc}")
    meta_ok = isinstance(meta, dict)

    listed: set[str] = set()
    sub_listed = 0
    documented_subs: set[str] = set()
    skipped_names: list[str] = []
    if meta_ok:
        for key in REQUIRED_META_KEYS:
            if key not in meta or meta[key] in ("", None, []):
                problems.append(f"metadata.json is missing/empty key: {key}")
        if meta.get("type") not in ("contrib", "core"):
            problems.append(
                f"metadata.json 'type' must be 'contrib' or 'core', got: {meta.get('type')!r}"
            )
        if "project" in meta:
            project = meta["project"]
            if not isinstance(project, dict):
                problems.append("metadata.json 'project' must be an object")
            else:
                if not isinstance(project.get("is_covered"), bool):
                    problems.append("project.is_covered must be a boolean")
                for key in ("categories", "ecosystem", "maintainers"):
                    if not isinstance(project.get(key), list):
                        problems.append(f"project.{key} must be a list")
                for key in ("maintenance_status", "development_status", "creation_date"):
                    if not isinstance(project.get(key), (str, type(None))):
                        problems.append(f"project.{key} must be a string or null")
        entries = meta.get("files")
        if isinstance(entries, list):
            for e in entries:
                if not isinstance(e, dict):
                    problems.append(f"files[] entry is not an object: {e!r}")
                    continue
                missing = [k for k in REQUIRED_FILE_KEYS if not e.get(k)]
                if missing:
                    problems.append(
                        f"files[] entry {e.get('file', '?')!r} missing keys: {', '.join(missing)}"
                    )
                f = e.get("file")
                if not isinstance(f, str) or not f:
                    continue
                if f in listed:
                    problems.append(f"files[] lists {f} more than once")
                listed.add(f)
                cat = e.get("category")
                if f in CORE_FILES and cat != CORE_FILES[f]:
                    problems.append(f"{f}: category should be {CORE_FILES[f]!r}, got {cat!r}")
                elif f.startswith("submodules/"):
                    sub_listed += 1
                    if cat != "Submodule":
                        problems.append(f"{f}: category should be 'Submodule', got {cat!r}")
                    if not e.get("submodule"):
                        problems.append(
                            f"{f}: missing the 'submodule' key (the submodule's machine name)"
                        )
                    else:
                        documented_subs.add(e["submodule"])
                elif cat not in VALID_CATEGORIES:
                    problems.append(f"{f}: unknown category {cat!r}")
        if "submodules_skipped" in meta:
            skipped = meta["submodules_skipped"]
            if not isinstance(skipped, list) or not skipped:
                problems.append(
                    "metadata.json 'submodules_skipped' must be a non-empty list "
                    "(drop the key when nothing was skipped)"
                )
            else:
                for e in skipped:
                    if not isinstance(e, dict) or not all(
                        isinstance(e.get(k), str) and e.get(k) for k in ("name", "dir")
                    ):
                        problems.append(
                            "submodules_skipped entry must be an object with "
                            f"non-empty 'name' and 'dir' strings: {e!r}"
                        )
                        continue
                    skipped_names.append(e["name"])
                for n in sorted({n for n in skipped_names if skipped_names.count(n) > 1}):
                    problems.append(f"submodules_skipped lists {n!r} more than once")
                for n in sorted(set(skipped_names) & documented_subs):
                    problems.append(
                        f"submodule {n!r} is listed both in submodules_skipped and "
                        "as a documented files[] entry"
                    )

    # audit-*.md files are auditor reports, not part of the generated doc set.
    on_disk = {
        str(p.relative_to(d))
        for p in d.rglob("*.md")
        if not p.name.startswith("audit-")
    }

    for f in sorted(CORE_FILES):
        if f not in on_disk:
            problems.append(f"required file missing on disk: {f}")
        if meta_ok and f not in listed:
            problems.append(f"required file not listed in metadata.json: {f}")

    if meta_ok:
        for f in sorted(listed - on_disk):
            problems.append(f"listed in metadata.json but missing on disk: {f}")
        for f in sorted(on_disk - listed):
            problems.append(f"on disk but not listed in metadata.json: {f}")

    for f in sorted(on_disk):
        size = (d / f).stat().st_size
        if size == 0:
            problems.append(f"empty file: {f}")
        elif size < 120:
            warnings.append(f"suspiciously small ({size} bytes): {f}")

    for n in sorted(set(skipped_names)):
        if f"submodules/{n}.md" in on_disk:
            problems.append(
                f"submodules/{n}.md exists on disk but {n!r} is listed in "
                "submodules_skipped (stale marker or stray file)"
            )

    sub_on_disk = sum(1 for f in on_disk if f.startswith("submodules/"))
    if args.submodules is not None and sub_on_disk != args.submodules:
        problems.append(
            f"submodule files on disk: {sub_on_disk}, expected (GATE SUBMODULES): {args.submodules}"
        )
    if meta_ok and sub_listed != sub_on_disk:
        problems.append(f"submodule files listed: {sub_listed}, on disk: {sub_on_disk}")

    fqcn_checked: int | None = None
    if args.module_root is not None:
        if not args.module_root.is_dir():
            problems.append(f"--module-root does not exist: {args.module_root}")
        elif meta_ok and isinstance(meta.get("name"), str) and meta["name"]:
            # Skipped submodules exist in the source too — resolve their
            # namespaces so root docs referencing them are still validated.
            sub_ns = set(skipped_names)
            if isinstance(meta.get("files"), list):
                sub_ns |= {
                    e["submodule"]
                    for e in meta["files"]
                    if isinstance(e, dict) and e.get("submodule")
                }
            submodule_names = sorted(sub_ns)
            fqcn_problems, fqcn_checked = check_fqcns(
                d, args.module_root, meta["name"], submodule_names
            )
            problems.extend(fqcn_problems)

    for w in warnings:
        print(f"WARNING: {w}")
    if problems:
        for p in problems:
            print(f"PROBLEM: {p}")
        print(f"VERIFY FAILED ({len(problems)} problem(s))")
        return 1

    print(f"CORE_FILES={len(CORE_FILES)}")
    print(f"SUBMODULE_FILES={sub_on_disk}")
    if skipped_names:
        print(f"SUBMODULES_SKIPPED={len(skipped_names)}")
    if fqcn_checked is not None:
        print(f"FQCN_CHECKED={fqcn_checked}")
    print("VERIFY OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
