#!/usr/bin/env python3
"""Verify a generated dc-* skill against the discover docs it was built from
(step 8 of generate-module-skill / generate-core-module-skill).

    python3 verify.py <SKILL_OUT> --docs-dir <DOCS_DIR> [--name SKILL_NAME]

Structural checks: SKILL.md frontmatter (kebab-case ``dc-*`` name, a
description, all mandatory metadata keys, module/version matching the docs'
metadata.json), the mandatory verify-installed section, the reference routing
table vs ``references/`` on disk in both directions, sibling cross-links,
no empty or near-empty files, the SKILL.md line caps, and leftover template
placeholders.

Grounding checks (the anti-fabrication net): the discover docs are the
generated skill's only source of truth, so an identifier absent from them
cannot be derived — only invented. Every ``Drupal\\<module>\\...`` FQCN
(module and submodule namespaces) and every module-named ``hook_*`` in the
generated files must appear verbatim somewhere in the docs (a PROBLEM
otherwise); module-prefixed dotted identifiers (service IDs, route names,
config keys) missing from the docs are fuzzier to tokenize and are reported
as WARNINGs for the generator to re-check by hand. ``audit-*.md`` files in
the docs dir are excluded from the grounding corpus — an auditor may quote
an invented identifier as an example of an error.

Standard library only. Prints WARNING/PROBLEM lines, then either "VERIFY OK"
(exit 0) or "VERIFY FAILED (n problem(s))" (exit 1).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

MANDATORY_META_KEYS = (
    "module",
    "version",
    "skill_type",
    "generated_at",
    "generated_from",
)
SKILL_TYPE_BY_DOCS_TYPE = {"contrib": "contrib_module", "core": "core_module"}
NAME_RE = re.compile(r"^dc-[a-z0-9]+(?:-[a-z0-9]+)*$")
FQCN_RE = re.compile(
    r"Drupal\\((?:[A-Za-z_][A-Za-z0-9_]*)(?:\\[A-Za-z_][A-Za-z0-9_]*)+)"
)
HOOK_RE = re.compile(r"\bhook_[a-z0-9_]+")
GENERATED_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
REF_LINK_RE = re.compile(r"references/([a-z0-9_-]+\.md)")
SIBLING_LINK_RE = re.compile(r"\]\(([a-z0-9_-]+\.md)(?:#[^)]*)?\)")
# Placeholders from the generate SKILL.md templates that must not survive
# substitution. Checked as literal substrings.
PLACEHOLDERS = (
    "{module}",
    "{version}",
    "{module_machine_name}",
    "{module-name}",
    "{SKILL_NAME}",
    "{GEN_DATE}",
    "{TAG_SLUG}",
    "{VERSION}",
    "{topic title}",
)
# A dotted <module>.<...> token whose last segment is one of these is a file
# name, not a service/route/config identifier.
FILEISH_SUFFIXES = {
    "css",
    "html",
    "inc",
    "info",
    "install",
    "js",
    "json",
    "md",
    "module",
    "php",
    "theme",
    "twig",
    "yml",
}


def norm(text: str) -> str:
    """Collapse PHP-string style double backslashes so FQCNs compare equal."""
    return text.replace("\\\\", "\\")


def parse_frontmatter(text: str) -> tuple[dict, dict, str] | None:
    """Return (top_level, metadata, body) from a SKILL.md, or None if broken.

    Line-based on purpose: the frontmatter is authored by this pipeline in a
    fixed shape, and the stdlib has no YAML parser.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return None
    top: dict[str, str] = {}
    meta: dict[str, str] = {}
    target = top
    folding: str | None = None
    for ln in lines[1:end]:
        if not ln.strip():
            continue
        indent = len(ln) - len(ln.lstrip())
        m = re.match(r"\s*([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$", ln)
        if m and (indent == 0 or (target is meta and indent == 2)):
            key, val = m.group(1), m.group(2).strip()
            if indent == 0:
                target = meta if key == "metadata" else top
                folding = None
                if key != "metadata":
                    top[key] = val
                    if val in (">", ">-", "|", "|-"):
                        folding = key
            else:
                meta[key] = val
                folding = None
        elif folding is not None and indent >= 2:
            top[folding] = (
                ln.strip()
                if top[folding] in (">", ">-", "|", "|-")
                else top[folding] + " " + ln.strip()
            )
    body = "\n".join(lines[end + 1 :])
    return top, meta, body


def grounded(corpus: str, token: str) -> bool:
    """True if token appears in the corpus not as a prefix of a longer symbol."""
    return re.search(re.escape(token) + r"(?![A-Za-z0-9_])", corpus) is not None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("skill_out", type=Path, help="The generated skill dir (SKILL_OUT).")
    ap.add_argument(
        "--docs-dir",
        type=Path,
        required=True,
        help="The discover docs dir the skill was generated from (DOCS_DIR).",
    )
    ap.add_argument(
        "--name",
        default=None,
        help="Expected frontmatter name (the resolved SKILL_NAME).",
    )
    args = ap.parse_args()

    problems: list[str] = []
    warnings: list[str] = []

    d = args.skill_out
    if not d.is_dir():
        print(f"VERIFY FAILED: skill dir does not exist: {d}")
        return 1
    if not args.docs_dir.is_dir():
        print(f"VERIFY FAILED: --docs-dir does not exist: {args.docs_dir}")
        return 1

    docs_meta_path = args.docs_dir / "metadata.json"
    try:
        docs_meta = json.loads(docs_meta_path.read_text())
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"VERIFY FAILED: cannot read {docs_meta_path}: {exc}")
        return 1
    module = docs_meta.get("name") or ""
    version = str(docs_meta.get("version") or "")
    docs_type = docs_meta.get("type") or ""
    if not module or not version:
        print(f"VERIFY FAILED: {docs_meta_path} lacks name/version")
        return 1
    submodules = sorted(
        {
            e["submodule"]
            for e in docs_meta.get("files", [])
            if isinstance(e, dict) and e.get("submodule")
        }
    )

    skill_md = d / "SKILL.md"
    body = ""
    if not skill_md.is_file():
        problems.append("SKILL.md is missing")
    else:
        text = skill_md.read_text(encoding="utf-8", errors="replace")
        parsed = parse_frontmatter(text)
        if parsed is None:
            problems.append("SKILL.md has no parseable `---` frontmatter block")
            body = text
        else:
            top, meta, body = parsed
            name = top.get("name", "")
            expected_base = "dc-" + module.replace("_", "-")
            if not name:
                problems.append("frontmatter: missing `name`")
            elif not NAME_RE.match(name):
                problems.append(f"frontmatter: name {name!r} is not kebab-case dc-*")
            elif name != expected_base and not name.startswith(expected_base + "-"):
                problems.append(
                    f"frontmatter: name {name!r} does not derive from the module "
                    f"machine name (expected {expected_base!r} or a version-suffixed form)"
                )
            if args.name and name and name != args.name:
                problems.append(
                    f"frontmatter: name {name!r} != expected SKILL_NAME {args.name!r}"
                )
            if not top.get("description", "").strip(">-| "):
                problems.append("frontmatter: missing/empty `description`")
            for key in MANDATORY_META_KEYS:
                if not meta.get(key):
                    problems.append(f"frontmatter: metadata.{key} missing/empty")
            if meta.get("module") and meta["module"] != module:
                problems.append(
                    f"frontmatter: metadata.module {meta['module']!r} != docs module {module!r}"
                )
            if meta.get("version") and meta["version"] != version:
                problems.append(
                    f"frontmatter: metadata.version {meta['version']!r} != docs version {version!r}"
                )
            expected_type = SKILL_TYPE_BY_DOCS_TYPE.get(docs_type)
            if expected_type and meta.get("skill_type") and meta["skill_type"] != expected_type:
                problems.append(
                    f"frontmatter: metadata.skill_type {meta['skill_type']!r} != "
                    f"{expected_type!r} (docs type is {docs_type!r})"
                )
            if meta.get("generated_at") and not GENERATED_AT_RE.match(meta["generated_at"]):
                warnings.append(
                    f"metadata.generated_at {meta['generated_at']!r} is not UTC "
                    "ISO-8601 (YYYY-MM-DDTHH:MM:SSZ)"
                )
            gen_from = meta.get("generated_from", "")
            if gen_from and (module not in gen_from or version not in gen_from):
                problems.append(
                    f"frontmatter: metadata.generated_from {gen_from!r} does not "
                    f"name both the module and the version"
                )

        if f"moduleExists('{module}')" not in text:
            problems.append(
                "SKILL.md: mandatory verify-installed section missing (no "
                f"moduleExists('{module}') check)"
            )
        n_lines = text.count("\n") + 1
        if n_lines > 500:
            problems.append(f"SKILL.md is {n_lines} lines (hard cap: 500)")
        elif n_lines > 300:
            warnings.append(f"SKILL.md is {n_lines} lines (aim: ~150-300)")

    refs_dir = d / "references"
    on_disk = (
        sorted(p.name for p in refs_dir.glob("*.md")) if refs_dir.is_dir() else []
    )
    if "use.md" not in on_disk:
        problems.append("references/use.md is missing (it is always emitted)")
    mentioned = set(REF_LINK_RE.findall(body))
    for f in on_disk:
        if f not in mentioned:
            problems.append(f"references/{f} exists but SKILL.md never mentions it")
    for f in sorted(mentioned):
        if f not in on_disk:
            problems.append(f"SKILL.md mentions references/{f} but it is not on disk")

    gen_files: list[Path] = ([skill_md] if skill_md.is_file() else []) + [
        refs_dir / f for f in on_disk
    ]
    for p in gen_files:
        size = p.stat().st_size
        rel = p.relative_to(d)
        if size == 0:
            problems.append(f"empty file: {rel}")
        elif size < 120:
            warnings.append(f"suspiciously small ({size} bytes): {rel}")

    for f in on_disk:
        ref_text = (refs_dir / f).read_text(encoding="utf-8", errors="replace")
        for m in SIBLING_LINK_RE.finditer(ref_text):
            target = m.group(1)
            if target not in on_disk:
                problems.append(
                    f"references/{f} links to sibling {target} which is not on disk"
                )

    corpus_parts = [
        norm(p.read_text(encoding="utf-8", errors="replace"))
        for p in sorted(args.docs_dir.rglob("*.md"))
        if not p.name.startswith("audit-")
    ]
    corpus_parts.append(norm(docs_meta_path.read_text(encoding="utf-8", errors="replace")))
    corpus = "\n".join(corpus_parts)

    own_namespaces = {module, *submodules}
    fqcn_checked = 0
    hooks_checked = 0
    dotted_checked = 0
    seen: set[str] = set()
    dotted_re = re.compile(
        r"(?<![\w.])" + re.escape(module) + r"\.[a-z0-9_]+(?:\.[a-z0-9_]+)*"
    )
    for p in gen_files:
        gtext = norm(p.read_text(encoding="utf-8", errors="replace"))
        rel = p.relative_to(d)
        for m in FQCN_RE.finditer(gtext):
            if m.group(1).split("\\")[0] not in own_namespaces:
                continue
            fqcn = "Drupal\\" + m.group(1)
            if fqcn in seen:
                continue
            seen.add(fqcn)
            fqcn_checked += 1
            if not grounded(corpus, fqcn):
                problems.append(
                    f"{rel}: {fqcn} does not appear in the discover docs — "
                    "not derivable from them, likely invented"
                )
        for m in HOOK_RE.finditer(gtext):
            hook = m.group(0)
            if module not in hook or hook in seen:
                continue
            seen.add(hook)
            hooks_checked += 1
            if not grounded(corpus, hook):
                problems.append(
                    f"{rel}: {hook}() does not appear in the discover docs — "
                    "not derivable from them, likely invented"
                )
        for m in dotted_re.finditer(gtext):
            token = m.group(0)
            if token in seen or token.rsplit(".", 1)[-1] in FILEISH_SUFFIXES:
                continue
            seen.add(token)
            dotted_checked += 1
            if not grounded(corpus, token):
                warnings.append(
                    f"{rel}: `{token}` not found in the discover docs — "
                    "confirm it is real (service/route/config id) or remove it"
                )
    for p in gen_files:
        gtext = p.read_text(encoding="utf-8", errors="replace")
        rel = p.relative_to(d)
        for ph in PLACEHOLDERS:
            if ph in gtext:
                problems.append(f"{rel}: unsubstituted template placeholder {ph}")

    for w in warnings:
        print(f"WARNING: {w}")
    if problems:
        for p in problems:
            print(f"PROBLEM: {p}")
        print(f"VERIFY FAILED ({len(problems)} problem(s))")
        return 1

    print(f"REFERENCES={len(on_disk)}")
    print(f"FQCN_CHECKED={fqcn_checked}")
    print(f"HOOKS_CHECKED={hooks_checked}")
    print(f"DOTTED_CHECKED={dotted_checked}")
    print("VERIFY OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
