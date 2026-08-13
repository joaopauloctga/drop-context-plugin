#!/usr/bin/env python3
"""Verify a discover output directory (step 6 of the discover skills).

    python3 verify.py <OUTPUT_DIR> [--submodules N]

Cross-checks metadata.json against the files on disk in both directions:
every required doc file present, listed, and non-empty; no unlisted files;
valid categories; submodule file count matching the GATE's SUBMODULES.
Standard library only.

Prints WARNING/PROBLEM lines, then either "VERIFY OK" (exit 0) or
"VERIFY FAILED (n problem(s))" (exit 1).
"""

from __future__ import annotations

import argparse
import json
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("output_dir", type=Path, help="The discover OUTPUT_DIR to verify.")
    ap.add_argument(
        "--submodules",
        type=int,
        default=None,
        help="Expected submodule file count (the GATE's SUBMODULES value).",
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
    if meta_ok:
        for key in REQUIRED_META_KEYS:
            if key not in meta or meta[key] in ("", None, []):
                problems.append(f"metadata.json is missing/empty key: {key}")
        if meta.get("type") not in ("contrib", "core"):
            problems.append(
                f"metadata.json 'type' must be 'contrib' or 'core', got: {meta.get('type')!r}"
            )
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
                elif cat not in VALID_CATEGORIES:
                    problems.append(f"{f}: unknown category {cat!r}")

    on_disk = {str(p.relative_to(d)) for p in d.rglob("*.md")}

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

    sub_on_disk = sum(1 for f in on_disk if f.startswith("submodules/"))
    if args.submodules is not None and sub_on_disk != args.submodules:
        problems.append(
            f"submodule files on disk: {sub_on_disk}, expected (GATE SUBMODULES): {args.submodules}"
        )
    if meta_ok and sub_listed != sub_on_disk:
        problems.append(f"submodule files listed: {sub_listed}, on disk: {sub_on_disk}")

    for w in warnings:
        print(f"WARNING: {w}")
    if problems:
        for p in problems:
            print(f"PROBLEM: {p}")
        print(f"VERIFY FAILED ({len(problems)} problem(s))")
        return 1

    print(f"CORE_FILES={len(CORE_FILES)}")
    print(f"SUBMODULE_FILES={sub_on_disk}")
    print("VERIFY OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
