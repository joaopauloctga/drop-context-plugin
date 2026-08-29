#!/usr/bin/env python3
"""Verify a discover-drupal-core-library output directory.

Checks the stable metadata contract, the metadata/file manifest in both
directions, required document presence, source identity/counts, Drupal Core and
Component FQCNs, backticked ``core/...:line`` evidence references (existence,
line bounds, and whether the cited line sits near a symbol the sentence names),
and every backticked ``hook_*`` name against core's ``*.api.php`` declarations.

Standard library only. Prints WARNING/PROBLEM lines and ends in ``VERIFY OK``
or ``VERIFY FAILED``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath


REQUIRED_FILES = {
    "summary.md": "Summary",
    "architecture.md": "Architecture",
    "api.md": "API",
    "usage.md": "Usage",
}
VALID_CATEGORIES = set(REQUIRED_FILES.values()) | {"Topic"}
REQUIRED_META_KEYS = (
    "schema_version",
    "id",
    "name",
    "human_name",
    "qualified_name",
    "type",
    "version",
    "date",
    "language",
    "source",
    "summary",
    "description",
    "aliases",
    "use_when",
    "keywords",
    "files",
)
REQUIRED_FILE_KEYS = (
    "file",
    "category",
    "title",
    "description",
    "keywords",
    "symbols",
    "source_paths",
)
FQCN_RE = re.compile(
    r"Drupal\\((?:Core|Component)(?:\\[A-Za-z_][A-Za-z0-9_]*)+)"
)
# Any backticked Drupal-root-relative core path with a source-like extension,
# optionally anchored to a line or a line range. The extension requirement keeps
# asset-library names such as `core/drupal.batch` out of the check.
SOURCE_REF_RE = re.compile(
    r"`(core/[^`\s:]+?\.(?:php|inc|module|install|theme|profile|engine|yml|yaml"
    r"|js|css|twig|json|txt|md|html))(?::([1-9][0-9]*)(?:-([1-9][0-9]*))?)?`"
)
# Symbols a sentence names in backticks: `Class::method()`, `Class::method`,
# `function_name()`, `method(signature)`. Used to check that a `path:line`
# citation on the same Markdown line actually lands near one of them.
SYMBOL_TOKEN_RE = re.compile(
    r"`(?:[A-Za-z_\\]+::)?([A-Za-z_][A-Za-z0-9_]*)\([^`]*\)`"
    r"|`[A-Za-z_\\]+::([A-Za-z_][A-Za-z0-9_]*)`"
)
# A citation may point a few lines above its symbol (docblock start), a bit
# below it, or at a statement inside the named function/method body.
ANCHOR_LINES_BEFORE = 4
ANCHOR_LINES_AFTER = 12
ANCHOR_IGNORED_NAMES = {"class"}
ANCHOR_PHP_SUFFIXES = {".php", ".inc", ".module", ".install", ".theme", ".profile"}
ENCLOSING_FUNCTION_RE = re.compile(r"^\s*(?:(?:abstract|final|public|protected|private|static)\s+)*function\s+&?([A-Za-z_][A-Za-z0-9_]*)\s*\(")
LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
# A hook named in backticks (`hook_foo`, `hook_foo()`, `hook_foo(array &$x)`).
HOOK_TOKEN_RE = re.compile(r"`(hook_[A-Za-z0-9_]+)(?:\([^`]*\))?`")
HOOK_DECLARATION_RE = re.compile(r"^\s*function\s+(hook_[A-Za-z0-9_]+)\s*\(", re.MULTILINE)
HOOK_PLACEHOLDER_RE = re.compile(r"[A-Z][A-Z0-9_]*[A-Z0-9]")
# A backticked signature asserting a NATIVE return type: `foo(...): Type` or
# `Class::foo(...): Type`. A docblock ``@return`` is not a declaration, so a
# signature written as if the type were declared misleads an implementer.
SIGNATURE_RETURN_RE = re.compile(
    r"`(?:([A-Za-z_\\][A-Za-z0-9_\\]*)::)?([A-Za-z_][A-Za-z0-9_]*)"
    r"\(([^`()]*(?:\([^`()]*\)[^`()]*)*)\)\s*:\s*([^`]+)`"
)
# Only judge plain type expressions; complex generics/psalm shapes are prose.
SIMPLE_TYPE_RE = re.compile(
    r"^[?\\]?[A-Za-z_][A-Za-z0-9_\\]*(?:\|[?\\]?[A-Za-z_][A-Za-z0-9_\\]*)*$"
)
FUNCTION_DECL_RE_TMPL = r"function\s+&?{name}\s*\("


def nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def valid_string_list(value: object, minimum: int = 1) -> bool:
    return (
        isinstance(value, list)
        and len(value) >= minimum
        and all(nonempty_string(item) for item in value)
    )


def safe_relative_markdown(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and ".." not in path.parts
        and value == path.as_posix()
        and path.suffix == ".md"
    )


def php_stats(library_root: Path) -> tuple[int, int]:
    files = sorted(library_root.rglob("*.php"))
    lines = 0
    for path in files:
        try:
            with path.open("rb") as handle:
                lines += sum(1 for _ in handle)
        except OSError:
            pass
    return len(files), lines


def source_digest(library_root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in library_root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(library_root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update(path.read_bytes())
        except OSError:
            pass
        digest.update(b"\0")
    return digest.hexdigest()


def fqcn_resolves(fqcn: str, drupal_lib_root: Path) -> bool:
    if not fqcn.startswith("Drupal\\"):
        return False
    relative = fqcn.split("\\")[1:]
    if not relative or relative[0] not in ("Core", "Component"):
        return False
    as_file = drupal_lib_root.joinpath(*relative).with_suffix(".php")
    as_directory = drupal_lib_root.joinpath(*relative)
    return as_file.is_file() or as_directory.is_dir()


def check_fqcns(output_dir: Path, drupal_lib_root: Path) -> tuple[list[str], int]:
    problems: list[str] = []
    seen: set[str] = set()
    checked = 0
    for markdown in sorted(output_dir.rglob("*.md")):
        text = markdown.read_text(encoding="utf-8", errors="replace").replace("\\\\", "\\")
        for match in FQCN_RE.finditer(text):
            relative = match.group(1).split("\\")
            fqcn = "Drupal\\" + match.group(1)
            if fqcn in seen:
                continue
            seen.add(fqcn)
            checked += 1
            if not fqcn_resolves(fqcn, drupal_lib_root):
                rel_doc = markdown.relative_to(output_dir)
                problems.append(
                    f"{rel_doc}: unresolvable Drupal core class/namespace {fqcn}"
                )
    return problems, checked


def check_source_references(
    output_dir: Path, drupal_root: Path
) -> tuple[list[str], int, dict[str, int]]:
    problems: list[str] = []
    checked = 0
    per_file: dict[str, int] = {}
    root = drupal_root.resolve()
    for markdown in sorted(output_dir.rglob("*.md")):
        rel_doc = str(markdown.relative_to(output_dir))
        text = markdown.read_text(encoding="utf-8", errors="replace")
        for match in SOURCE_REF_RE.finditer(text):
            source_path = (root / match.group(1)).resolve()
            try:
                source_path.relative_to(root)
            except ValueError:
                problems.append(f"{rel_doc}: source reference escapes Drupal root: {match.group(1)}")
                continue
            if not source_path.is_file():
                problems.append(
                    f"{rel_doc}: source reference does not exist: {match.group(1)}"
                )
                continue
            if match.group(2):
                line = int(match.group(2))
                end = int(match.group(3)) if match.group(3) else line
                try:
                    with source_path.open("rb") as handle:
                        total = sum(1 for _ in handle)
                except OSError:
                    total = 0
                if end < line:
                    problems.append(
                        f"{rel_doc}: source reference range is reversed: "
                        f"{match.group(1)}:{line}-{end}"
                    )
                    continue
                if end > total:
                    problems.append(
                        f"{rel_doc}: source reference line {end} exceeds {total}: "
                        f"{match.group(1)}"
                    )
                    continue
            checked += 1
            per_file[rel_doc] = per_file.get(rel_doc, 0) + 1
    return problems, checked, per_file


def declared_hooks(core_root: Path) -> tuple[set[str], list[re.Pattern[str]]]:
    """Return exact hook names and regexes for placeholder hooks from *.api.php."""
    exact: set[str] = set()
    patterns: list[re.Pattern[str]] = []
    for api_file in sorted(core_root.rglob("*.api.php")):
        try:
            text = api_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in HOOK_DECLARATION_RE.finditer(text):
            name = match.group(1)
            exact.add(name)
            if HOOK_PLACEHOLDER_RE.search(name):
                # hook_ENTITY_TYPE_insert -> hook_[a-z0-9_]+_insert
                pattern = HOOK_PLACEHOLDER_RE.sub(
                    lambda _: "[a-z0-9_]+", re.escape(name).replace("\\_", "_")
                )
                patterns.append(re.compile(rf"^{pattern}$"))
    return exact, patterns


def identifier_exists_in_core(name: str, core_root: Path) -> bool:
    """Whether a bare `hook_*`-shaped token occurs literally in core PHP source."""
    needle = re.compile(rb"(?<![A-Za-z0-9_])" + re.escape(name.encode("utf-8")) + rb"(?![A-Za-z0-9_])")
    roots = (core_root / "lib", core_root / "includes", core_root / "modules")
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.suffix not in (".php", ".inc", ".module", ".install", ".theme", ".yml"):
                continue
            try:
                if needle.search(path.read_bytes()):
                    return True
            except OSError:
                continue
    return False


def check_hook_names(
    output_dir: Path, core_root: Path
) -> tuple[list[str], list[str], int]:
    """Every backticked `hook_*` must be declared in some core *.api.php.

    A token that is not a declared hook but occurs literally in core source
    (for example the `hook_data` key-value key) is only a WARNING.
    """
    exact, patterns = declared_hooks(core_root)
    problems: list[str] = []
    warnings: list[str] = []
    seen: set[str] = set()
    checked = 0
    if not exact:
        return problems, warnings, checked
    for markdown in sorted(output_dir.rglob("*.md")):
        rel_doc = str(markdown.relative_to(output_dir))
        text = markdown.read_text(encoding="utf-8", errors="replace")
        for match in HOOK_TOKEN_RE.finditer(text):
            name = match.group(1)
            if name in seen:
                continue
            seen.add(name)
            checked += 1
            if name in exact or any(pattern.match(name) for pattern in patterns):
                continue
            hint = ""
            if name + "_alter" in exact:
                hint = f" (did you mean {name}_alter?)"
            if identifier_exists_in_core(name, core_root):
                warnings.append(
                    f"{rel_doc}: `{name}` is not a declared hook but occurs in core "
                    f"source; make sure the doc does not present it as a hook{hint}"
                )
                continue
            problems.append(
                f"{rel_doc}: hook {name} is not declared in any core *.api.php{hint}"
            )
    return problems, warnings, checked


def declared_return_types(
    name: str, library_root: Path, cache: dict[str, list[tuple[Path, int, str | None]]]
) -> list[tuple[Path, int, str | None]]:
    """Every declaration of ``name`` in the library: its native return type or None."""
    if name in cache:
        return cache[name]
    results: list[tuple[Path, int, str | None]] = []
    pattern = re.compile(FUNCTION_DECL_RE_TMPL.format(name=re.escape(name)))
    for php_file in sorted(library_root.rglob("*.php")):
        try:
            text = php_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in pattern.finditer(text):
            index = match.end() - 1
            depth = 0
            while index < len(text):
                if text[index] == "(":
                    depth += 1
                elif text[index] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                index += 1
            tail = text[index + 1 : index + 80]
            declared = re.match(r"\s*:\s*([?\\]?[A-Za-z_][A-Za-z0-9_\\|]*)", tail)
            line_no = text.count("\n", 0, match.start()) + 1
            results.append((php_file, line_no, declared.group(1) if declared else None))
    cache[name] = results
    return results


def check_signature_return_types(
    output_dir: Path, library_root: Path
) -> tuple[list[str], int]:
    """Flag a documented ``foo(): Type`` whose declarations declare no return type.

    A docblock ``@return`` annotation is not a native return type. An
    implementer who copies the documented signature adds a return type the
    interface does not declare, which is a real incompatibility. Judged only
    when the library itself declares the name and *every* declaration lacks a
    native return type; a name the library never declares, or one where any
    declaration does declare a type, is left alone.
    """
    problems: list[str] = []
    checked = 0
    cache: dict[str, list[tuple[Path, int, str | None]]] = {}
    for markdown in sorted(output_dir.rglob("*.md")):
        rel_doc = str(markdown.relative_to(output_dir))
        text = markdown.read_text(encoding="utf-8", errors="replace")
        for lineno, line_text in enumerate(text.split("\n"), 1):
            for match in SIGNATURE_RETURN_RE.finditer(line_text):
                returned = match.group(4).strip()
                if not SIMPLE_TYPE_RE.match(returned):
                    continue
                declarations = declared_return_types(
                    match.group(2), library_root, cache
                )
                qualifier = match.group(1)
                if qualifier:
                    # `Class::method(): Type` names one declaration; judge only it.
                    short = qualifier.rsplit("\\", 1)[-1]
                    owned = [
                        item for item in declarations if item[0].stem == short
                    ]
                    if owned:
                        declarations = owned
                if not declarations:
                    continue
                checked += 1
                if all(declared is None for _f, _l, declared in declarations):
                    where = ", ".join(
                        f"{f.name}:{l}" for f, l, _d in declarations[:3]
                    )
                    problems.append(
                        f"{rel_doc}:{lineno}: documented signature {match.group(0)} "
                        f"declares a return type the source does not ({where} declare "
                        f"none; a docblock @return is not a declaration)"
                    )
    return problems, checked


def check_citation_anchoring(
    output_dir: Path, drupal_root: Path
) -> tuple[list[str], int]:
    """Warn about `path:line` citations that land nowhere near the symbols named.

    For every Markdown line that both names symbols in backticks and cites a
    `core/...:line`, at least one named symbol must occur within a small window
    around the cited line. When none does but a named symbol exists elsewhere
    in the cited file, the citation points at the wrong lines of the right file.
    A citation inside the body of a named function/method also counts as
    anchored. Sentences whose named symbols do not occur in the cited file at
    all are not judged (the citation may support a different fact on the same
    line), and only PHP-like non-test files are judged. This is a heuristic
    (a sentence may cite several facts), so it reports WARNING, not PROBLEM.
    """
    warnings: list[str] = []
    checked = 0
    root = drupal_root.resolve()
    source_cache: dict[Path, list[str]] = {}
    for markdown in sorted(output_dir.rglob("*.md")):
        rel_doc = str(markdown.relative_to(output_dir))
        text = markdown.read_text(encoding="utf-8", errors="replace")
        for line_text in text.split("\n"):
            names = set()
            for token in SYMBOL_TOKEN_RE.finditer(line_text):
                name = token.group(1) or token.group(2)
                if name and len(name) >= 4 and name not in ANCHOR_IGNORED_NAMES:
                    names.add(name)
            if not names:
                continue
            for match in SOURCE_REF_RE.finditer(line_text):
                if not match.group(2):
                    continue
                source_path = (root / match.group(1)).resolve()
                if not source_path.is_file() or source_path.suffix not in ANCHOR_PHP_SUFFIXES:
                    continue
                # Tests and *.api.php are cited for data rows and doc sections,
                # where symbol proximity says nothing.
                if "/tests/" in match.group(1) or match.group(1).endswith(".api.php"):
                    continue
                if source_path not in source_cache:
                    source_cache[source_path] = source_path.read_text(
                        encoding="utf-8", errors="replace"
                    ).split("\n")
                lines = source_cache[source_path]
                start = int(match.group(2))
                end = int(match.group(3)) if match.group(3) else start
                if end > len(lines):
                    continue
                checked += 1
                window = "\n".join(
                    lines[max(0, start - 1 - ANCHOR_LINES_BEFORE) : end + ANCHOR_LINES_AFTER]
                )
                if any(re.search(rf"\b{re.escape(name)}\b", window) for name in names):
                    continue
                enclosing = None
                for index in range(start - 1, -1, -1):
                    declared = ENCLOSING_FUNCTION_RE.match(lines[index])
                    if declared:
                        enclosing = declared.group(1)
                        break
                if enclosing in names:
                    continue
                nearest: list[str] = []
                for name in sorted(names):
                    pattern = re.compile(rf"\b{re.escape(name)}\b")
                    hits = [index + 1 for index, src in enumerate(lines) if pattern.search(src)]
                    if hits:
                        closest = min(hits, key=lambda hit: abs(hit - start))
                        nearest.append(f"{name} at line {closest}")
                if nearest:
                    warnings.append(
                        f"{rel_doc}: citation {match.group(1)}:{match.group(2)} is not "
                        f"near any symbol the sentence names (wrong lines of the right "
                        f"file, or a multi-fact sentence); nearest: " + ", ".join(nearest)
                    )
    return warnings, checked


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--library-root", type=Path, required=True)
    parser.add_argument("--drupal-lib-root", type=Path, required=True)
    parser.add_argument("--library", required=True, help="Canonical Core/Ajax-style path from the gate.")
    parser.add_argument("--library-id", required=True)
    parser.add_argument("--version", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_dir = args.output_dir.resolve()
    library_root = args.library_root.resolve()
    drupal_lib_root = args.drupal_lib_root.resolve()
    problems: list[str] = []
    warnings: list[str] = []

    if not output_dir.is_dir():
        print(f"VERIFY FAILED: output dir does not exist: {output_dir}")
        return 1
    if not library_root.is_dir():
        problems.append(f"library root does not exist: {library_root}")
    if not drupal_lib_root.is_dir():
        problems.append(f"Drupal lib root does not exist: {drupal_lib_root}")

    metadata: object = None
    metadata_path = output_dir / "metadata.json"
    if not metadata_path.is_file():
        problems.append("metadata.json is missing")
    else:
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            problems.append(f"metadata.json does not parse: {exc}")
    metadata_ok = isinstance(metadata, dict)

    listed: set[str] = set()
    listed_order: list[str] = []
    covered_php: dict[str, int] = {}
    drupal_root = drupal_lib_root.parent.parent.parent
    expected_php_paths = (
        {
            str(path.relative_to(drupal_root))
            for path in library_root.rglob("*.php")
            if path.is_file()
        }
        if library_root.is_dir()
        else set()
    )
    if metadata_ok:
        assert isinstance(metadata, dict)
        for key in REQUIRED_META_KEYS:
            if key not in metadata or metadata[key] in (None, "", []):
                problems.append(f"metadata.json is missing/empty key: {key}")

        expected_qualified = "Drupal\\" + args.library.replace("/", "\\")
        expected_source_path = f"core/lib/Drupal/{args.library}"
        expected_values = {
            "schema_version": 1,
            "id": args.library_id,
            "name": args.library,
            "qualified_name": expected_qualified,
            "type": "core_library",
            "version": args.version,
        }
        for key, expected in expected_values.items():
            if metadata.get(key) != expected:
                problems.append(
                    f"metadata.json {key!r} must be {expected!r}, got {metadata.get(key)!r}"
                )
        if not isinstance(metadata.get("date"), int) or metadata.get("date", 0) <= 0:
            problems.append("metadata.json 'date' must be a positive Unix epoch integer")
        if not nonempty_string(metadata.get("human_name")):
            problems.append("metadata.json 'human_name' must be a non-empty string")
        if not isinstance(metadata.get("language"), str) or not LANGUAGE_RE.fullmatch(
            metadata.get("language", "")
        ):
            problems.append("metadata.json 'language' must be a language tag such as en or pt-BR")
        if not nonempty_string(metadata.get("summary")) or len(metadata.get("summary", "")) < 40:
            problems.append("metadata.json 'summary' must be a useful plain-text summary (at least 40 chars)")
        if not nonempty_string(metadata.get("description")) or len(metadata.get("description", "")) < 120:
            problems.append(
                "metadata.json 'description' must be a search-oriented plain-text description "
                "(at least 120 chars)"
            )
        if not valid_string_list(metadata.get("use_when")):
            problems.append("metadata.json 'use_when' must be a non-empty string array")
        if not valid_string_list(metadata.get("keywords"), minimum=3):
            problems.append("metadata.json 'keywords' must contain at least three strings")
        if not valid_string_list(metadata.get("aliases"), minimum=2):
            problems.append("metadata.json 'aliases' must contain at least two strings")
        else:
            aliases = metadata["aliases"]
            for expected_alias in (args.library, expected_qualified):
                if expected_alias not in aliases:
                    problems.append(
                        f"metadata.json 'aliases' must include {expected_alias!r}"
                    )

        actual_php_files, actual_php_lines = php_stats(library_root)
        source = metadata.get("source")
        if not isinstance(source, dict):
            problems.append("metadata.json 'source' must be an object")
        else:
            expected_source = {
                "path": expected_source_path,
                "php_files": actual_php_files,
                "php_lines": actual_php_lines,
                "digest": "sha256:" + source_digest(library_root),
            }
            for key, expected in expected_source.items():
                if source.get(key) != expected:
                    problems.append(
                        f"metadata.json source.{key} must be {expected!r}, got {source.get(key)!r}"
                    )

        entries = metadata.get("files")
        if not isinstance(entries, list):
            problems.append("metadata.json 'files' must be an array")
        else:
            for entry in entries:
                if not isinstance(entry, dict):
                    problems.append(f"files[] entry is not an object: {entry!r}")
                    continue
                missing = [key for key in REQUIRED_FILE_KEYS if key not in entry]
                if missing:
                    problems.append(
                        f"files[] entry {entry.get('file', '?')!r} missing keys: "
                        + ", ".join(missing)
                    )
                filename = entry.get("file")
                if not isinstance(filename, str) or not safe_relative_markdown(filename):
                    problems.append(f"files[] has an unsafe/non-Markdown path: {filename!r}")
                    continue
                if filename in listed:
                    problems.append(f"files[] lists {filename} more than once")
                listed.add(filename)
                listed_order.append(filename)
                category = entry.get("category")
                if filename in REQUIRED_FILES:
                    if category != REQUIRED_FILES[filename]:
                        problems.append(
                            f"{filename}: category must be {REQUIRED_FILES[filename]!r}, got {category!r}"
                        )
                elif not filename.startswith("topics/"):
                    problems.append(
                        f"optional documentation must live below topics/: {filename}"
                    )
                elif category != "Topic":
                    problems.append(f"{filename}: optional topic category must be 'Topic'")
                if category not in VALID_CATEGORIES:
                    problems.append(f"{filename}: unknown category {category!r}")
                if not nonempty_string(entry.get("title")):
                    problems.append(f"{filename}: title must be a non-empty string")
                if not nonempty_string(entry.get("description")):
                    problems.append(f"{filename}: description must be a non-empty string")
                if not valid_string_list(entry.get("keywords"), minimum=2):
                    problems.append(f"{filename}: keywords must contain at least two strings")
                symbols = entry.get("symbols")
                if not isinstance(symbols, list) or not all(
                    nonempty_string(symbol) for symbol in symbols
                ):
                    problems.append(f"{filename}: symbols must be a string array")
                elif drupal_lib_root.is_dir():
                    for symbol in symbols:
                        if not fqcn_resolves(symbol, drupal_lib_root):
                            problems.append(
                                f"{filename}: manifest symbol does not resolve in core: {symbol}"
                            )

                source_paths = entry.get("source_paths")
                if not isinstance(source_paths, list) or not all(
                    nonempty_string(path) for path in source_paths
                ):
                    problems.append(f"{filename}: source_paths must be a string array")
                else:
                    for source_path in source_paths:
                        path = (drupal_root / source_path).resolve()
                        try:
                            path.relative_to(library_root)
                        except ValueError:
                            problems.append(
                                f"{filename}: manifest source path is outside the target library: "
                                f"{source_path}"
                            )
                            continue
                        if not path.is_file():
                            problems.append(
                                f"{filename}: manifest source path does not exist: {source_path}"
                            )
                            continue
                        if path.suffix == ".php":
                            covered_php[source_path] = covered_php.get(source_path, 0) + 1

        for source_path in sorted(expected_php_paths - set(covered_php)):
            problems.append(
                f"target PHP file has no documentation owner in files[].source_paths: "
                f"{source_path}"
            )
        for source_path, count in sorted(covered_php.items()):
            if count > 1:
                problems.append(
                    f"target PHP file has {count} documentation owners in "
                    f"files[].source_paths: {source_path}"
                )
        required_order = list(REQUIRED_FILES)
        if listed_order[: len(required_order)] != required_order:
            problems.append(
                "metadata.json files[] must start in reading order: "
                + ", ".join(required_order)
            )

    on_disk = {
        str(path.relative_to(output_dir)) for path in output_dir.rglob("*.md")
    }
    all_output_files = {
        str(path.relative_to(output_dir))
        for path in output_dir.rglob("*")
        if path.is_file()
    }
    for filename in sorted(all_output_files - on_disk - {"metadata.json"}):
        problems.append(f"unexpected non-document file in output: {filename}")
    for filename in REQUIRED_FILES:
        if filename not in on_disk:
            problems.append(f"required file missing on disk: {filename}")
        if metadata_ok and filename not in listed:
            problems.append(f"required file not listed in metadata.json: {filename}")
    if metadata_ok:
        for filename in sorted(listed - on_disk):
            problems.append(f"listed in metadata.json but missing on disk: {filename}")
        for filename in sorted(on_disk - listed):
            problems.append(f"on disk but not listed in metadata.json: {filename}")

    for filename in sorted(on_disk):
        path = output_dir / filename
        try:
            path.resolve().relative_to(output_dir)
        except ValueError:
            problems.append(f"{filename}: document symlink/path escapes the output directory")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            problems.append(f"{filename}: not valid UTF-8: {exc}")
            continue
        if not text.startswith("# "):
            problems.append(f"{filename}: document must start directly with an H1")
        if len(text.strip()) < 200:
            warnings.append(f"{filename}: suspiciously short ({len(text.strip())} characters)")

    fqcn_checked = 0
    source_refs_checked = 0
    anchors_checked = 0
    hooks_checked = 0
    signatures_checked = 0
    if drupal_lib_root.is_dir():
        fqcn_problems, fqcn_checked = check_fqcns(output_dir, drupal_lib_root)
        problems.extend(fqcn_problems)
        ref_problems, source_refs_checked, refs_per_file = check_source_references(
            output_dir, drupal_root
        )
        problems.extend(ref_problems)
        anchor_warnings, anchors_checked = check_citation_anchoring(output_dir, drupal_root)
        warnings.extend(anchor_warnings)
        hook_problems, hook_warnings, hooks_checked = check_hook_names(
            output_dir, drupal_root / "core"
        )
        problems.extend(hook_problems)
        warnings.extend(hook_warnings)
        signature_problems, signatures_checked = check_signature_return_types(
            output_dir, library_root
        )
        problems.extend(signature_problems)
        for filename in ("architecture.md", "api.md", "usage.md"):
            if filename in on_disk and refs_per_file.get(filename, 0) == 0:
                problems.append(
                    f"{filename}: no valid backticked core/... source evidence reference found"
                )
        if fqcn_checked == 0 and on_disk:
            warnings.append("no Drupal Core/Component FQCN was found to validate")

    for warning in warnings:
        print(f"WARNING: {warning}")
    if problems:
        for problem in problems:
            print(f"PROBLEM: {problem}")
        print(f"VERIFY FAILED ({len(problems)} problem(s))")
        return 1

    print(f"DOC_FILES={len(on_disk)}")
    print(f"TOPIC_FILES={sum(1 for filename in on_disk if filename.startswith('topics/'))}")
    print(f"FQCN_CHECKED={fqcn_checked}")
    print(f"SOURCE_REFS_CHECKED={source_refs_checked}")
    print(f"CITATIONS_ANCHOR_CHECKED={anchors_checked}")
    print(f"HOOKS_CHECKED={hooks_checked}")
    print(f"SIGNATURES_CHECKED={signatures_checked}")
    print("VERIFY OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
