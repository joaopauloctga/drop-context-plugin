#!/usr/bin/env python3
"""Resolve a Drupal core library and prepare a discover run.

Standard-library-only gate for ``discover-drupal-core-library``::

    python3 prepare.py <library> [<project-or-drupal-root>]

``library`` is a path below ``core/lib/Drupal`` such as ``Core/Ajax`` or
``Component/Plugin``. A unique short name such as ``Ajax`` is accepted; an
ambiguous short name is rejected with the qualified candidates.

The script never downloads Drupal. It resolves an installed checkout, creates
the documentation output and a disposable work directory, writes a source
inventory into the work directory, and ends with a machine-readable GATE block.
"""

from __future__ import annotations

import argparse
import difflib
import getpass
import hashlib
import json
import re
import sys
import tempfile
import time
from pathlib import Path


VERSION_RE = re.compile(r"const\s+VERSION\s*=\s*['\"]([^'\"]+)['\"]")
SAFE_LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")


class GateError(RuntimeError):
    """A preparation error that should stop the discover workflow."""


def default_work_base() -> Path:
    try:
        user = getpass.getuser()
    except Exception:
        user = "shared"
    return Path(tempfile.gettempdir()) / f"drupal-context-{user}" / "core-libraries"


def candidate_lib_roots(base: Path, search_ancestors: bool) -> list[Path]:
    """Return deterministic core/lib/Drupal candidates near ``base``."""
    base = base.expanduser().resolve()
    roots: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            roots.append(resolved)

    anchors = (base, *base.parents) if search_ancestors else (base,)
    for anchor in anchors:
        add(anchor)
        add(anchor / "lib" / "Drupal")
        add(anchor / "core" / "lib" / "Drupal")
        add(anchor / "web" / "core" / "lib" / "Drupal")
        add(anchor / "drupal-site" / "web" / "core" / "lib" / "Drupal")
    return roots


def is_drupal_lib_root(path: Path) -> bool:
    return (
        path.is_dir()
        and (path / "Core").is_dir()
        and (path / "Component").is_dir()
        and path.name == "Drupal"
    )


def resolve_lib_root(base: Path, search_ancestors: bool) -> Path:
    matches = [
        path
        for path in candidate_lib_roots(base, search_ancestors)
        if is_drupal_lib_root(path)
    ]
    if not matches:
        raise GateError(
            f"could not find core/lib/Drupal from {base.expanduser().resolve()}; "
            "pass the Composer project root, Drupal docroot, core directory, or "
            "core/lib/Drupal path explicitly"
        )
    return matches[0]


def normalize_selector(raw: str) -> str:
    selector = raw.strip().replace("\\", "/").strip("/")
    for prefix in ("core/lib/Drupal/", "Drupal/"):
        if selector.startswith(prefix):
            selector = selector[len(prefix) :]
    parts = selector.split("/") if selector else []
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise GateError(f"invalid library selector: {raw!r}")
    if any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", part) for part in parts):
        raise GateError(
            "library selectors may contain only namespace path segments, for "
            "example Core/Ajax or Component/Plugin"
        )
    return "/".join(parts)


def top_level_libraries(lib_root: Path) -> list[str]:
    result: list[str] = []
    for scope in ("Core", "Component"):
        scope_root = lib_root / scope
        for path in sorted(scope_root.iterdir()):
            if path.is_dir():
                result.append(f"{scope}/{path.name}")
    return result


def resolve_library(lib_root: Path, raw_selector: str) -> tuple[str, Path]:
    selector = normalize_selector(raw_selector)

    if "/" in selector:
        path = lib_root.joinpath(*selector.split("/"))
        if path.is_dir():
            return selector, path.resolve()
        # Make case errors actionable without silently changing identity.
        all_dirs = [
            str(path.relative_to(lib_root))
            for path in lib_root.rglob("*")
            if path.is_dir()
        ]
        suggestions = difflib.get_close_matches(selector, all_dirs, n=5, cutoff=0.5)
        suffix = f"; close matches: {', '.join(suggestions)}" if suggestions else ""
        raise GateError(f"library {selector!r} does not exist below {lib_root}{suffix}")

    matches = [
        candidate
        for candidate in top_level_libraries(lib_root)
        if candidate.rsplit("/", 1)[1].lower() == selector.lower()
    ]
    if len(matches) == 1:
        qualified = matches[0]
        return qualified, (lib_root / qualified).resolve()
    if len(matches) > 1:
        raise GateError(
            f"short library name {selector!r} is ambiguous; use one of: "
            + ", ".join(matches)
        )

    candidates = top_level_libraries(lib_root)
    short_names = [item.rsplit("/", 1)[1] for item in candidates]
    close = difflib.get_close_matches(selector, short_names, n=5, cutoff=0.45)
    qualified_close = [item for item in candidates if item.rsplit("/", 1)[1] in close]
    suffix = f"; close matches: {', '.join(qualified_close)}" if qualified_close else ""
    raise GateError(
        f"no top-level Core or Component library named {selector!r}{suffix}. "
        "For a nested library, pass its qualified path."
    )


def drupal_version(lib_root: Path) -> str:
    drupal_class = lib_root.parent / "Drupal.php"
    try:
        text = drupal_class.read_text(encoding="utf-8")
    except OSError as exc:
        raise GateError(f"cannot read Drupal version from {drupal_class}: {exc}") from exc
    match = VERSION_RE.search(text)
    if not match:
        raise GateError(f"Drupal::VERSION was not found in {drupal_class}")
    return match.group(1)


def slug_part(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    if not slug:
        raise GateError(f"cannot build a stable id from namespace segment {value!r}")
    return slug


def library_id(relative_path: str) -> str:
    return "drupal." + ".".join(slug_part(part) for part in relative_path.split("/"))


def count_lines(path: Path) -> int:
    try:
        with path.open("rb") as handle:
            return sum(1 for _ in handle)
    except OSError:
        return 0


def contains_consecutive_parts(
    haystack: tuple[str, ...], needle: tuple[str, ...]
) -> bool:
    if not needle or len(needle) > len(haystack):
        return False
    return any(
        haystack[index : index + len(needle)] == needle
        for index in range(len(haystack) - len(needle) + 1)
    )


def test_roots(core_root: Path) -> list[Path]:
    """Directories that hold core's tests: core/tests/Drupal plus every
    core/modules/<module>/tests (PHPUnit tests and the test modules that are
    the real usage evidence for libraries such as Batch or Queue)."""
    roots: list[Path] = []
    framework_tests = core_root / "tests" / "Drupal"
    if framework_tests.is_dir():
        roots.append(framework_tests)
    modules_root = core_root / "modules"
    if modules_root.is_dir():
        for module_dir in sorted(modules_root.iterdir()):
            module_tests = module_dir / "tests"
            if module_tests.is_dir():
                roots.append(module_tests)
    return roots


def related_tests(core_root: Path, namespace: str, library_parts: tuple[str, ...]) -> list[str]:
    results: list[str] = []
    needle = namespace.encode("utf-8")
    for tests_root in test_roots(core_root):
        for path in sorted(tests_root.rglob("*.php")):
            rel_parts = path.relative_to(tests_root).parts
            path_match = contains_consecutive_parts(rel_parts, library_parts)
            content_match = False
            if not path_match:
                try:
                    if path.stat().st_size <= 2_000_000:
                        content_match = needle in path.read_bytes()
                except OSError:
                    pass
            if path_match or content_match:
                results.append(str(path.relative_to(core_root.parent)))
    return results


def source_digest(library_root: Path, files: list[Path]) -> str:
    """Hash relative paths and contents so source drift is detectable."""
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(library_root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update(path.read_bytes())
        except OSError as exc:
            raise GateError(f"cannot hash source file {path}: {exc}") from exc
        digest.update(b"\0")
    return digest.hexdigest()


def build_inventory(
    lib_root: Path,
    library_root: Path,
    relative_path: str,
    version: str,
) -> dict[str, object]:
    core_root = lib_root.parent.parent
    namespace = "Drupal\\" + relative_path.replace("/", "\\")
    files = [path for path in sorted(library_root.rglob("*")) if path.is_file()]
    php_files = [path for path in files if path.suffix == ".php"]
    source_files = [
        {
            "path": str(path.relative_to(core_root.parent)),
            "library_path": str(path.relative_to(library_root)),
            "kind": "php" if path.suffix == ".php" else "support",
            "lines": count_lines(path),
        }
        for path in files
    ]
    test_files = related_tests(
        core_root,
        namespace,
        tuple(relative_path.split("/")),
    )
    return {
        "schema_version": 1,
        "library": relative_path,
        "library_id": library_id(relative_path),
        "namespace": namespace,
        "version": version,
        "source_path": f"core/lib/Drupal/{relative_path}",
        "php_files": len(php_files),
        "php_lines": sum(item["lines"] for item in source_files if item["kind"] == "php"),
        "source_digest": source_digest(library_root, files),
        "source_files": source_files,
        "related_test_files": test_files,
    }


def prepare_output(path: Path, replace_generated: bool) -> None:
    path.mkdir(parents=True, exist_ok=True)
    existing = [item for item in path.iterdir()]
    if not existing:
        return
    if not replace_generated:
        raise GateError(
            f"output directory is not empty: {path}. Refusing to overwrite it; "
            "use --replace-generated only when the user explicitly requested regeneration"
        )

    # Delete only the skill's known generated artifacts. Unknown files remain
    # a hard stop, so --replace-generated cannot erase an arbitrary directory.
    for markdown in sorted(path.rglob("*.md")):
        markdown.unlink()
    metadata = path / "metadata.json"
    if metadata.is_file():
        metadata.unlink()
    for directory in sorted(
        (item for item in path.rglob("*") if item.is_dir()),
        key=lambda item: len(item.parts),
        reverse=True,
    ):
        try:
            directory.rmdir()
        except OSError:
            pass
    leftovers = [item for item in path.iterdir()]
    if leftovers:
        raise GateError(
            f"output directory contains unknown artifacts that were not removed: {path}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "library",
        help="Library below core/lib/Drupal (Core/Ajax, Component/Plugin, or a unique short name).",
    )
    parser.add_argument(
        "source_root",
        nargs="?",
        type=Path,
        help="Composer project root, Drupal docroot/core dir, or core/lib/Drupal. Defaults to cwd discovery.",
    )
    parser.add_argument(
        "--language",
        default="en",
        help="Documentation language tag (default: en).",
    )
    parser.add_argument(
        "--output-base",
        type=Path,
        default=Path.home() / ".drupal-context" / "core-libraries",
        help="Output root, mainly for isolated testing.",
    )
    parser.add_argument(
        "--work-base",
        type=Path,
        default=default_work_base(),
        help="Disposable work root used for inventory and research notes.",
    )
    parser.add_argument(
        "--replace-generated",
        action="store_true",
        help="Remove only existing generated Markdown/metadata before the run. Requires explicit user intent.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if not SAFE_LANGUAGE_RE.fullmatch(args.language):
            raise GateError(f"invalid language tag: {args.language!r}")
        discovery_base = args.source_root or Path.cwd()
        lib_root = resolve_lib_root(
            discovery_base,
            search_ancestors=args.source_root is None,
        )
        relative_path, library_root = resolve_library(lib_root, args.library)
        version = drupal_version(lib_root)
        lib_id = library_id(relative_path)
        namespace = "Drupal\\" + relative_path.replace("/", "\\")

        if not any(path.is_file() for path in library_root.rglob("*")):
            raise GateError(f"library directory contains no files: {library_root}")

        output_dir = args.output_base.expanduser() / version / relative_path
        prepare_output(output_dir, args.replace_generated)

        args.work_base.expanduser().mkdir(parents=True, exist_ok=True)
        work_dir = Path(
            tempfile.mkdtemp(
                prefix=f"{lib_id.replace('.', '-')}-{version}-",
                dir=args.work_base.expanduser(),
            )
        )
        inventory = build_inventory(lib_root, library_root, relative_path, version)
        inventory_path = work_dir / "inventory.json"
        inventory_path.write_text(
            json.dumps(inventory, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        core_root = lib_root.parent.parent
        print("GATE OK")
        print(f"LIBRARY={relative_path}")
        print(f"LIBRARY_ID={lib_id}")
        print(f"NAMESPACE={namespace}")
        print(f"VERSION={version}")
        print(f"LANGUAGE={args.language}")
        print(f"DRUPAL_ROOT={core_root.parent.resolve()}")
        print(f"CORE_ROOT={core_root.resolve()}")
        print(f"DRUPAL_LIB_ROOT={lib_root.resolve()}")
        print(f"LIBRARY_ROOT={library_root.resolve()}")
        print(f"OUTPUT_DIR={output_dir.resolve()}")
        print(f"WORK_DIR={work_dir.resolve()}")
        print(f"INVENTORY={inventory_path.resolve()}")
        print(f"DATE_EPOCH={int(time.time())}")
        print(f"PHP_FILES={inventory['php_files']}")
        print(f"PHP_LINES={inventory['php_lines']}")
        print(f"RELATED_TEST_FILES={len(inventory['related_test_files'])}")
        return 0
    except GateError as exc:
        print(f"GATE FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
