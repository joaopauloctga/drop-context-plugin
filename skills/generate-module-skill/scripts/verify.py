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

Consumer-contract checks: the agent that loads the generated skill has ONLY
the skill, never the discover docs, so a sentence that points it at the
discover docs ("see the discover docs' Entities category", "full catalog in
`hooks.md` of the discover docs", a bare `plugins.md` with no such sibling
reference) is a dangling pointer — a PROBLEM. Any other mention of the
discover docs (hedges like "the discover docs do not enumerate …") is a
WARNING: rephrase as a plain hedge, the consumer cannot see what is meant.

YAML-example checks: every ```yaml / ```yml fence is parsed with a minimal
stdlib YAML-subset reader (block mappings, block sequences, flow collections
consumed as opaque text, quoted/plain scalars, comments, ``|``/``>`` block
scalars). A duplicate key inside one mapping is a PROBLEM — config import
rejects it, and a real generated skill shipped a "model" with two top-level
``events:`` keys. Anything the subset cannot parse is a WARNING naming the
line (the reader is a subset, not a judge). Identifier-like scalar values
(``bef_links``, ``set:clear``, ``content_entity:presave``) that occur nowhere
in the discover docs are WARNINGs — invented enum values and guessed ids are
exactly how synthesized examples go wrong. Batch-relative sentences in
``references/submodules*.md`` ("the only one of these four submodules",
"all three submodules in this group") are WARNINGs: they re-scope a
per-batch observation into a claim about the module.

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
# Hook names may carry an upper-case placeholder segment
# (hook_migrate_MIGRATION_ID_prepare_row, hook_preprocess_HOOK). Stopping at
# the first upper-case char would extract a bare prefix ("hook_migrate_") that
# grounded() can never match, since the docs always spell the full name.
HOOK_RE = re.compile(r"\bhook_[A-Za-z0-9_]+")
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

# --- consumer-contract: dangling pointers at the discover docs -------------
DISCOVER_CATEGORY_FILES = (
    "summary",
    "entities",
    "plugins",
    "services",
    "configuration",
    "permissions",
    "routes",
    "hooks",
    "events",
    "extension-points",
    "ai-integration",
)
_CAT_WORDS = (
    r"(?:summary|entities|plugins|services|configuration|permissions|routes|"
    r"hooks|events|extension[ -]points|ai[ -]integration|submodules?)"
)
DISCOVER_DOCS_RE = re.compile(
    r"\bdiscover(?:ed|y)?[ -]doc(?:s|umentation)?\b|\bdiscover-drupal-(?:core-)?module\b",
    re.IGNORECASE,
)
# Sentences that *direct* the reader at the discover docs (a pointer the
# consumer cannot follow) as opposed to merely mentioning them (a hedge).
POINTER_RES = (
    # "see the discover docs", "consult the discover documentation for …"
    re.compile(
        r"\b(?:see|refer to|consult|check|read|open|load|look (?:at|in)|"
        r"details? (?:are |is )?in|documented in|listed in|covered in|"
        r"catalogu?ed in|described in|found in|full (?:catalog|list|table|"
        r"details?) (?:is |are )?in)\b[^.\n]{0,60}?\bdiscover(?:ed|y)?[ -]"
        r"doc(?:s|umentation)?\b",
        re.IGNORECASE,
    ),
    # "the discover docs' Entities category", "discover docs (Services section)"
    re.compile(
        r"\bdiscover(?:ed|y)?[ -]doc(?:s|umentation)?\b['’]?s?[^.\n]{0,20}?\b"
        + _CAT_WORDS
        + r"\b[^.\n]{0,12}?\b(?:category|file|section|doc)\b",
        re.IGNORECASE,
    ),
    # "see the Services category", "in the Entities category of …"
    re.compile(
        r"\b(?:see|in|from|per|refer to|consult|check)\s+(?:the\s+)?"
        + _CAT_WORDS
        + r"\s+category\b",
        re.IGNORECASE,
    ),
)
DISCOVER_FILE_RE = re.compile(
    r"`(?:submodules/)?(" + "|".join(DISCOVER_CATEGORY_FILES) + r")\.md`"
)
DISCOVER_FILE_TAIL_RE = re.compile(
    r"^[^.\n]{0,30}?\b(?:of|in|from) the discover", re.IGNORECASE
)

# --- consumer-contract: batch-relative sentences in submodule references ---
RESCOPE_RE = re.compile(
    r"\bthe only one of these\b|"
    r"\bof these (?:two|three|four|five|six|seven|eight|nine|ten|\d+) sub-?modules\b|"
    r"\ball (?:two|three|four|five|six|seven|eight|nine|ten|\d+) sub-?modules in this\b|"
    r"\bin each of these\b|"
    r"\b(?:covered |documented )?in this batch\b|\bthis batch\b",
    re.IGNORECASE,
)

# --- yaml examples ----------------------------------------------------------
FENCE_OPEN_RE = re.compile(r"^(\s*)(`{3,}|~{3,})\s*([A-Za-z0-9_+-]*)")
YAML_LITERALS = {"true", "false", "null", "yes", "no", "on", "off", "~", ""}
YAML_NUMBER_RE = re.compile(r"^[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?$")
YAML_IDENT_VALUE_RE = re.compile(r"^[a-z][a-z0-9_:.-]{2,}$")
# A value under one of these keys is the example author's own choice (a
# config entity id, a label, a field name), not an enum the docs could list.
AUTHOR_CHOSEN_KEYS = {
    "id",
    "uuid",
    "label",
    "name",
    "title",
    "description",
    "machine_name",
    "field_name",
    "langcode",
    "_core",
    "default_config_hash",
}
PLACEHOLDER_VALUE_RE = re.compile(r"^(?:my_|mymodule|example|your_|custom_|foo$|bar$|baz$)")


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


def split_fences(text: str) -> tuple[list[tuple[int, str]], list[tuple[str, int, list[str]]]]:
    """Split Markdown into prose lines and fenced blocks.

    Returns (prose, fences): prose is [(1-based line no, line)] outside any
    fence; fences is [(info string, 1-based line no of the opener, body lines)].
    """
    prose: list[tuple[int, str]] = []
    fences: list[tuple[str, int, list[str]]] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = FENCE_OPEN_RE.match(lines[i])
        if m:
            marker, info = m.group(2), m.group(3).lower()
            body: list[str] = []
            j = i + 1
            while j < len(lines):
                closer = lines[j].strip()
                if closer.startswith(marker[0]) and set(closer) == {marker[0]} and len(closer) >= len(marker):
                    break
                body.append(lines[j])
                j += 1
            fences.append((info, i + 1, body))
            i = j + 1
            continue
        prose.append((i + 1, lines[i]))
        i += 1
    return prose, fences


def check_dangling_pointers(
    gen_files: list[Path], skill_dir: Path, sibling_refs: list[str]
) -> tuple[list[str], list[str]]:
    """Pointers at the discover docs → PROBLEM; other mentions → WARNING."""
    problems: list[str] = []
    warnings: list[str] = []
    for p in gen_files:
        rel = p.relative_to(skill_dir)
        prose, _ = split_fences(p.read_text(encoding="utf-8", errors="replace"))
        for ln, line in prose:
            flagged = False
            for rx in POINTER_RES:
                if rx.search(line):
                    problems.append(
                        f"{rel}:{ln}: points the consumer at the discover docs "
                        "(it only has this skill — restate the fact or drop it): "
                        f"{line.strip()[:110]}"
                    )
                    flagged = True
                    break
            if not flagged:
                for m in DISCOVER_FILE_RE.finditer(line):
                    name = m.group(1) + ".md"
                    tail = line[m.end() :]
                    if name not in sibling_refs or DISCOVER_FILE_TAIL_RE.match(tail):
                        problems.append(
                            f"{rel}:{ln}: refers to discover file `{name}` which the "
                            "consumer cannot open (no such sibling reference): "
                            f"{line.strip()[:110]}"
                        )
                        flagged = True
                        break
            if not flagged and DISCOVER_DOCS_RE.search(line):
                warnings.append(
                    f"{rel}:{ln}: mentions the discover docs — the consumer cannot "
                    "see them; rephrase as a plain hedge or remove: "
                    f"{line.strip()[:110]}"
                )
    return problems, warnings


def check_rescoping(refs_dir: Path, on_disk: list[str], skill_dir: Path) -> list[str]:
    """Batch-relative sentences in references/submodules*.md → WARNING."""
    warnings: list[str] = []
    for f in on_disk:
        if not f.startswith("submodules"):
            continue
        p = refs_dir / f
        rel = p.relative_to(skill_dir)
        prose, _ = split_fences(p.read_text(encoding="utf-8", errors="replace"))
        for ln, line in prose:
            m = RESCOPE_RE.search(line)
            if m:
                warnings.append(
                    f"{rel}:{ln}: batch-relative phrase {m.group(0)!r} — a per-batch "
                    "observation re-scoped as a module fact; rewrite or drop it"
                )
    return warnings


# --- minimal YAML subset reader ----------------------------------------------
class YamlSubset:
    """Enough YAML to check generated config examples: block mappings and
    sequences, plain/quoted scalars, comments, ``|``/``>`` block scalars and
    flow collections consumed as opaque text. Records every scalar value and
    every mapping key with its line, duplicate keys, and lines it cannot
    read. Not a validator of YAML — a reader of the subset our examples use.
    """

    def __init__(self, body: list[str], base_line: int) -> None:
        self.lines = body
        self.base = base_line  # 1-based line number of the fence opener
        self.values: list[tuple[str, int, str | None]] = []  # (value, line, key)
        self.keys: set[str] = set()
        self.duplicates: list[tuple[str, int]] = []
        self.errors: list[tuple[int, str]] = []
        self._flow_depth_cache: dict[int, int] = {}

    # -- helpers -----------------------------------------------------------
    def lineno(self, i: int) -> int:
        return self.base + 1 + i

    @staticmethod
    def strip_comment(line: str) -> str:
        out: list[str] = []
        quote: str | None = None
        prev = " "
        for ch in line:
            if quote:
                out.append(ch)
                if ch == quote:
                    quote = None
            elif ch in ("'", '"'):
                quote = ch
                out.append(ch)
            elif ch == "#" and prev in (" ", "\t"):
                break
            else:
                out.append(ch)
            prev = ch
        return "".join(out).rstrip()

    def content(self, i: int) -> str:
        return self.strip_comment(self.lines[i])

    def is_blank(self, i: int) -> bool:
        c = self.content(i)
        return not c.strip() or c.strip() in ("---", "...")

    def indent(self, i: int) -> int:
        c = self.content(i)
        return len(c) - len(c.lstrip(" "))

    def next_content(self, i: int) -> int:
        while i < len(self.lines) and self.is_blank(i):
            i += 1
        return i

    def add_scalar(self, raw: str, i: int, key: str | None = None) -> None:
        v = raw.strip()
        if not v:
            return
        # tags / anchors / aliases
        v = re.sub(r"^(?:![\w!:/.-]*\s+|&[\w-]+\s+)+", "", v)
        if v.startswith("*"):
            return
        if v[:1] in ("'", '"') and v[-1:] == v[:1] and len(v) >= 2:
            v = v[1:-1]
        elif v[:1] in ("{", "["):
            self.add_flow(v, i)
            return
        self.values.append((v, self.lineno(i), key))

    def add_flow(self, text: str, i: int) -> None:
        # Opaque, but harvest `key: value` values and bare items so identifier
        # checks still see `{ id: set_value, condition: field_changed }`.
        inner = text.strip()
        if inner[:1] in ("{", "[") and inner[-1:] in ("}", "]"):
            inner = inner[1:-1]
        for part in re.split(r",(?![^\[\]{}]*[\]}])", inner):
            part = part.strip()
            if not part:
                continue
            if part[:1] in ("{", "["):
                self.add_flow(part, i)
                continue
            if ":" in part and not part.startswith(("'", '"')):
                k, _, v = part.partition(":")
                if v.startswith(" ") or v == "":
                    k = k.strip().strip("'\"")
                    self.keys.add(k)
                    if v.strip():
                        self.add_scalar(v, i, k)
                    continue
            self.add_scalar(part, i)

    # -- parsing -----------------------------------------------------------
    def parse(self) -> None:
        i = self.next_content(0)
        if i >= len(self.lines):
            return
        i = self.parse_node(i, self.indent(i))
        i = self.next_content(i)
        while i < len(self.lines):
            self.errors.append((self.lineno(i), "unexpected content after the document"))
            i = self.next_content(i + 1)

    def parse_node(self, i: int, indent: int) -> int:
        c = self.content(i).strip()
        if c.startswith("- ") or c == "-":
            return self.parse_sequence(i, indent)
        if re.match(r"^(?:'[^']*'|\"[^\"]*\"|[^\s'\"#][^#]*?)\s*:(?:\s|$)", c) and not c.startswith(("{", "[")):
            return self.parse_mapping(i, indent)
        # scalar (possibly multi-line plain / flow)
        return self.parse_scalar_block(i, indent)

    def parse_scalar_block(self, i: int, indent: int) -> int:
        buf = [self.content(i).strip()]
        j = i + 1
        while j < len(self.lines) and (self.is_blank(j) or self.indent(j) >= indent):
            if not self.is_blank(j):
                buf.append(self.content(j).strip())
            j += 1
        self.add_scalar(" ".join(buf), i)
        return j

    def consume_block_scalar(self, i: int, indent: int) -> int:
        j = i + 1
        while j < len(self.lines) and (self.is_blank(j) or self.indent(j) > indent):
            j += 1
        return j

    def consume_flow(self, i: int, first: str) -> tuple[str, int]:
        depth = 0
        buf: list[str] = []
        j = i
        while j < len(self.lines):
            seg = first if j == i else self.content(j)
            buf.append(seg.strip())
            depth += seg.count("{") + seg.count("[") - seg.count("}") - seg.count("]")
            j += 1
            if depth <= 0:
                break
        return " ".join(buf), j

    def parse_mapping(self, i: int, indent: int) -> int:
        seen: dict[str, int] = {}
        while i < len(self.lines):
            if self.is_blank(i):
                i += 1
                continue
            ind = self.indent(i)
            if ind < indent:
                return i
            c = self.content(i)
            body = c[ind:]
            if ind > indent:
                self.errors.append((self.lineno(i), f"unexpected indentation: {body.strip()[:60]}"))
                i += 1
                continue
            m = re.match(r"^(?:'([^']*)'|\"([^\"]*)\"|([^\s'\"#][^#]*?))\s*:(?:\s+(.*))?$", body)
            if not m or body.startswith(("- ", "{", "[")) or body == "-":
                if body.startswith("- ") or body == "-":
                    return i  # a sequence at the same indent ends the mapping
                self.errors.append((self.lineno(i), f"not a `key: value` line: {body.strip()[:60]}"))
                i += 1
                continue
            key = next(g for g in m.groups()[:3] if g is not None).strip()
            val = (m.group(4) or "").strip()
            if key in seen:
                self.duplicates.append((key, self.lineno(i)))
            seen[key] = self.lineno(i)
            self.keys.add(key)
            if val == "":
                j = self.next_content(i + 1)
                if j < len(self.lines):
                    jind = self.indent(j)
                    jbody = self.content(j).strip()
                    if jind > indent or (jind == indent and (jbody.startswith("- ") or jbody == "-")):
                        i = self.parse_node(j, jind)
                        continue
                i += 1
            elif re.match(r"^[|>][-+0-9]*$", val):
                i = self.consume_block_scalar(i, indent)
            elif val[:1] in ("{", "["):
                text, i = self.consume_flow(i, val)
                self.add_flow(text, i - 1)
            else:
                self.add_scalar(val, i, key)
                i += 1
        return i

    def parse_sequence(self, i: int, indent: int) -> int:
        while i < len(self.lines):
            if self.is_blank(i):
                i += 1
                continue
            ind = self.indent(i)
            if ind < indent:
                return i
            c = self.content(i)
            body = c[ind:]
            if ind > indent or not (body.startswith("- ") or body == "-"):
                if ind == indent:
                    return i  # back to the enclosing mapping
                self.errors.append((self.lineno(i), f"unexpected indentation: {body.strip()[:60]}"))
                i += 1
                continue
            item = body[2:] if body.startswith("- ") else ""
            item_col = ind + 2 + (len(item) - len(item.lstrip(" ")))
            item = item.strip()
            if item == "":
                j = self.next_content(i + 1)
                if j < len(self.lines) and self.indent(j) > indent:
                    i = self.parse_node(j, self.indent(j))
                    continue
                i += 1
            elif re.match(r"^(?:'[^']*'|\"[^\"]*\"|[^\s'\"#{\[][^#]*?)\s*:(?:\s|$)", item):
                # "- key: value" — a mapping whose first line shares the dash.
                saved = self.lines[i]
                self.lines[i] = " " * item_col + saved[ind + 2 :].lstrip(" ")
                i = self.parse_mapping(i, item_col)
            elif re.match(r"^[|>][-+0-9]*$", item):
                i = self.consume_block_scalar(i, indent)
            elif item[:1] in ("{", "["):
                text, i = self.consume_flow(i, item)
                self.add_flow(text, i - 1)
            else:
                self.add_scalar(item, i)
                i += 1
        return i


def check_yaml_examples(
    gen_files: list[Path],
    skill_dir: Path,
    corpus: str,
    own_names: set[str],
) -> tuple[list[str], list[str], int, int]:
    """Parse every yaml fence: duplicate keys → PROBLEM, unreadable lines →
    WARNING, identifier-like values absent from the docs → WARNING."""
    problems: list[str] = []
    warnings: list[str] = []
    fences_seen = 0
    values_checked = 0
    for p in gen_files:
        rel = p.relative_to(skill_dir)
        _, fences = split_fences(p.read_text(encoding="utf-8", errors="replace"))
        reported: set[str] = set()
        for info, opener, body in fences:
            if info not in ("yaml", "yml"):
                continue
            fences_seen += 1
            y = YamlSubset(list(body), opener)
            try:
                y.parse()
            except (IndexError, RecursionError) as exc:  # defensive: never crash the verifier
                warnings.append(f"{rel}:{opener}: yaml example could not be read ({exc.__class__.__name__})")
                continue
            for key, ln in y.duplicates:
                problems.append(
                    f"{rel}:{ln}: duplicate key `{key}` in the yaml example opened at "
                    f"line {opener} — config import rejects it; merge or rename"
                )
            for ln, why in y.errors[:3]:
                warnings.append(
                    f"{rel}:{ln}: yaml example (opened line {opener}) has a line the "
                    f"subset reader cannot parse — {why}"
                )
            for val, ln, key in y.values:
                low = val.lower()
                if low in YAML_LITERALS or YAML_NUMBER_RE.match(val):
                    continue
                if not YAML_IDENT_VALUE_RE.match(val):
                    continue
                if val in y.keys or val in own_names or val in reported:
                    continue
                if key in AUTHOR_CHOSEN_KEYS or PLACEHOLDER_VALUE_RE.match(val):
                    continue
                if val.rsplit(".", 1)[-1] in FILEISH_SUFFIXES:
                    continue
                values_checked += 1
                if not grounded(corpus, val):
                    reported.add(val)
                    warnings.append(
                        f"{rel}:{ln}: value `{val}` in a yaml example does not occur in "
                        "the discover docs (invented enum value / guessed id?)"
                    )
    return problems, warnings, fences_seen, values_checked


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

    # Consumer contract: the loading agent has only this skill.
    ptr_problems, ptr_warnings = check_dangling_pointers(gen_files, d, on_disk)
    problems.extend(ptr_problems)
    warnings.extend(ptr_warnings)
    warnings.extend(check_rescoping(refs_dir, on_disk, d))

    # YAML examples: parse, duplicate keys, unsourced identifier values.
    yaml_problems, yaml_warnings, yaml_fences, yaml_values = check_yaml_examples(
        gen_files, d, corpus, own_namespaces
    )
    problems.extend(yaml_problems)
    warnings.extend(yaml_warnings)

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
    print(f"YAML_FENCES={yaml_fences}")
    print(f"YAML_VALUES_CHECKED={yaml_values}")
    print("VERIFY OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
