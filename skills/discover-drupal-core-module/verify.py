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

Also with --module-root: every backticked module-prefixed id string in the
docs (``<module>_foo``, ``<module>.foo`` — plugin ids, queue ids, service
ids, config object names, route names) must occur somewhere in the module
source (file contents or file paths). A miss is a WARNING, not a PROBLEM —
some ids are legitimately derived at runtime (derivative plugin ids, the
``<entity_type>_list`` cache tag) — but it is exactly how an invented
identifier reconstructed from a class name shows up (a real run wrote queue
id ``media_thumbnail_downloader`` from the class ``ThumbnailDownloader``;
the declared id was ``media_entity_thumbnail``). Dotted tokens pass when a
dotted prefix occurs (``media.settings.iframe_domain`` passes via
``media.settings`` — docs often cite a config object plus key as one path).

Doc-only consistency checks (no --module-root needed), added 2026-08-26:

* **Stated count vs enumeration** — "declares 5 services: `a`, `b`, `c`,
  `d`" or a "N routes" lead-in followed by a table/list with a different
  number of rows/items → PROBLEM (the explorers enumerate correctly and then
  miscount what they wrote; 7 audited instances across 3 modules).
* **Cross-file citation divergence** — two `path:a-b` citations of the same
  file whose line ranges overlap without one containing the other → WARNING
  (`views.module:224-228` vs `:225-229`: the same fact cited twice, once
  wrong).

Additional --module-root checks, same date:

* **Cited code spans** — a backticked *code* span (contains `$`, `->`, `::`,
  `(`…) placed next to a `path:line` citation must be a literal substring of
  those lines (±2, whitespace-normalized): found elsewhere in the file →
  WARNING with the real line; nowhere in the file → PROBLEM (an expression
  that exists nowhere — the symfony_mailer_lite `$dsns[$transportConfig->id()]`
  case).
* **Invocation sites** — `Class::method()` / `function_name()` paired with a
  `path:line` citation of that class's file (or a procedural file): the line
  must fall inside that function (docblock/attribute head included) → PROBLEM
  ("right line, wrong enclosing function" — 5 errors in one views audit).
* **Plugin ids** — every id in a `Plugin ID`/`ID` table column of `plugins.md`
  (and `submodules/*.md`) must be declared by a non-abstract class under
  `src/Plugin/**` (`#[Attr(id: 'x')]`, `#[Attr('x')]`, `@Annotation(id = "x")`)
  → PROBLEM when the row's class resolves to a module class (abstract, or
  declares a different id), WARNING otherwise; source ids absent from every
  doc → one aggregated WARNING per plugin type (recall half).
* **Libraries** — every top-level entry of `*.libraries.yml` must be named in
  some doc (`{provider}/{lib}` or `` `lib` ``) → WARNING.
* **Deprecations** — every `@deprecated` symbol (class/function/const/public
  method) must be named in some doc → PROBLEM; protected/private members →
  WARNING.
* **Bare class names** — a backticked CamelCase token with a class-like suffix
  (`…Subscriber`, `…Controller`, `…Base`, …) that is neither declared nor
  imported anywhere in the source and not introduced by an FQCN in the docs →
  WARNING (`ViewsRouteSubscriber` sailed past the FQCN check unqualified).
* **Runtime-interpolated ids** — a module-prefixed id whose suffix occurs in
  the source adjacent to a string delimiter / `$var` / `}` (built by
  interpolation or concatenation) is not warned about.

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

BACKTICK_ID_RE = re.compile(r"`([a-z][a-z0-9_.]*)`")

# Docs legitimately write *template* FQCNs whose trailing segment is a
# placeholder (`Drupal\views\Attribute\Views{Type}`, `…\Plugin\views\{type}`).
# FQCN_RE stops at the brace, leaving a stem that can never resolve to a class.
# Detect the placeholder that follows and validate the namespace dir instead.
TEMPLATE_TAIL_RE = re.compile(r"^\\?[{<]")

# Cues that the surrounding sentence asserts the identifier is ABSENT — e.g.
# "the module does not ship a `views.permissions.yml` file". Warning on those
# punishes the docs for being precise about what does not exist.
NEGATION_RE = re.compile(
    r"\b(?:not|no|never|none|absent|lacks?|without|cannot|omits?|omitted|"
    r"missing|unverifiable)\b|\b(?:can|does|do|is|are|has|have)n't\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Shared helpers: doc iteration, citations, Markdown blocks, PHP structure
# ---------------------------------------------------------------------------

SKIP_DIRS = ("node_modules", "vendor", ".git")
TEST_DIRS = ("tests", "test")

# `src/Foo/Bar.php:46`, `views.module:225-229`, `(sitewide_alert.routing.yml:12`
CITATION_RE = re.compile(
    r"(?<![\w/\\.:-])((?:[A-Za-z0-9_.\-]+/)*[A-Za-z0-9_\-]+(?:\.[A-Za-z0-9_\-]+)*"
    r"\.(?:php|module|inc|install|theme|profile|yml|yaml|js|twig|css|json|txt|md))"
    r":(\d{1,6})(?:\s*[-–]\s*(\d{1,6}))?(?![\w.:-]|\d)"
)
PHP_EXTS = (".php", ".module", ".inc", ".install", ".theme", ".profile")
BACKTICK_SPAN_RE = re.compile(r"`([^`\n]+)`")


def iter_docs(d: Path) -> list[tuple[str, str]]:
    """(relative path, text) for every generated doc, skipping audit reports."""
    out = []
    for md in sorted(d.rglob("*.md")):
        if md.name.startswith("audit-"):
            continue
        out.append((str(md.relative_to(d)), md.read_text(encoding="utf-8", errors="replace")))
    return out


def mask_php(text: str) -> str:
    """Blank string and comment contents (keeping delimiters and newlines).

    Good enough for brace counting and declaration scanning without a parser.
    """
    out = []
    i, n = 0, len(text)
    state: str | None = None
    heredoc_id = ""
    while i < n:
        c = text[i]
        if state is None:
            if text.startswith("//", i) or (c == "#" and not text.startswith("#[", i)):
                state = "//"
                out.append(c)
            elif text.startswith("/*", i):
                state = "/*"
                out.append("/*")
                i += 1
            elif c in ("'", '"'):
                state = c
                out.append(c)
            elif text.startswith("<<<", i):
                m = re.match(r"<<<\s*['\"]?([A-Za-z_]\w*)['\"]?\r?\n", text[i:])
                if m:
                    state = "<<<"
                    heredoc_id = m.group(1)
                    out.append("<<<")
                    for ch in m.group(0)[3:]:
                        out.append("\n" if ch == "\n" else " ")
                    i += len(m.group(0))
                    continue
                out.append(c)
            else:
                out.append(c)
            i += 1
            continue
        if state == "//":
            if c == "\n":
                state = None
                out.append(c)
            else:
                out.append(" ")
            i += 1
            continue
        if state == "/*":
            if text.startswith("*/", i):
                state = None
                out.append("*/")
                i += 2
            else:
                out.append("\n" if c == "\n" else " ")
                i += 1
            continue
        if state in ("'", '"'):
            if c == "\\" and i + 1 < n:
                out.append("  " if text[i + 1] != "\n" else " \n")
                i += 2
                continue
            if c == state:
                state = None
                out.append(c)
            else:
                out.append("\n" if c == "\n" else " ")
            i += 1
            continue
        if state == "<<<":
            # Terminates on a line whose first token is the identifier.
            if c == "\n":
                out.append(c)
                i += 1
                m = re.match(r"[ \t]*" + re.escape(heredoc_id) + r"\b", text[i:])
                if m:
                    state = None
                    out.append(m.group(0))
                    i += len(m.group(0))
                continue
            out.append(" ")
            i += 1
            continue
    return "".join(out)


FUNC_DECL_RE = re.compile(
    r"^[ \t]*(?:(?:abstract|final|public|protected|private|static)\s+)*"
    r"function\s+&?([A-Za-z_]\w*)\s*\(",
    re.M,
)
CLASS_DECL_RE = re.compile(
    r"^[ \t]*(?:(?:abstract|final|readonly)\s+)*(class|interface|trait|enum)\s+([A-Za-z_]\w*)",
    re.M,
)
NAMESPACE_RE = re.compile(r"^namespace\s+([\w\\]+)\s*;", re.M)


class PhpFunc:
    __slots__ = ("name", "decl", "start", "end", "visibility", "in_class")

    def __init__(self, name, decl, start, end, visibility, in_class):
        self.name, self.decl, self.start, self.end = name, decl, start, end
        self.visibility, self.in_class = visibility, in_class


def php_functions(raw: str, masked: str) -> list[PhpFunc]:
    """Every named function/method with 1-based [start, end] line bounds.

    `start` includes the docblock / attribute head directly above the
    declaration, so a citation of the docblock counts as inside the function.
    """
    lines = raw.split("\n")
    funcs: list[PhpFunc] = []
    class_spans: list[tuple[int, int]] = []
    for cm in CLASS_DECL_RE.finditer(masked):
        brace = masked.find("{", cm.end())
        if brace == -1:
            continue
        depth, j = 0, brace
        while j < len(masked):
            if masked[j] == "{":
                depth += 1
            elif masked[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        class_spans.append((masked.count("\n", 0, cm.start()) + 1, masked.count("\n", 0, j) + 1))

    for m in FUNC_DECL_RE.finditer(masked):
        decl_line = masked.count("\n", 0, m.start()) + 1
        # Skip the signature's parentheses, then find `{` (body) or `;` (abstract).
        j, depth = m.end() - 1, 0
        while j < len(masked):
            if masked[j] == "(":
                depth += 1
            elif masked[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        k = j + 1
        while k < len(masked) and masked[k] not in "{;":
            k += 1
        if k >= len(masked):
            continue
        if masked[k] == ";":
            end_line = masked.count("\n", 0, k) + 1
        else:
            depth, j = 0, k
            while j < len(masked):
                if masked[j] == "{":
                    depth += 1
                elif masked[j] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            end_line = masked.count("\n", 0, j) + 1
        # Head: contiguous docblock / attribute lines directly above.
        start = decl_line
        in_attr = False
        idx = decl_line - 2
        while idx >= 0:
            s = lines[idx].strip()
            if not s:
                break
            if s.startswith(("*", "/**", "/*", "#[")) or s.endswith("*/"):
                in_attr = False
                start = idx + 1
                idx -= 1
                continue
            if s.endswith(("]", ")]", ",")) and (in_attr or True):
                # Inside a multi-line attribute (`  id: 'x',` … `)]`).
                in_attr = True
                start = idx + 1
                idx -= 1
                continue
            break
        mods = m.group(0)
        vis = "public"
        for v in ("protected", "private"):
            if re.search(r"\b" + v + r"\b", mods):
                vis = v
        in_class = any(a <= decl_line <= b for a, b in class_spans)
        funcs.append(PhpFunc(m.group(1), decl_line, start, end_line, vis, in_class))
    return funcs


def enclosing_function(funcs: list[PhpFunc], line: int) -> PhpFunc | None:
    """The innermost function whose (head-inclusive) span contains `line`."""
    best = None
    for f in funcs:
        if f.start <= line <= f.end and (best is None or f.start >= best.start):
            best = f
    return best


class Source:
    """Lazy view over the module source: file index, corpus, PHP structure."""

    def __init__(self, root: Path):
        self.root = root
        self.files: list[Path] = []
        parts: list[str] = []
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(root)
            if any(seg in SKIP_DIRS for seg in rel.parts):
                continue
            self.files.append(rel)
            parts.append(str(rel))
            try:
                if p.stat().st_size <= 2_000_000:
                    parts.append(p.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
        self.corpus = "\n".join(parts)
        self._text: dict[Path, str] = {}
        self._masked: dict[Path, str] = {}
        self._funcs: dict[Path, list[PhpFunc]] = {}
        self._by_suffix: dict[str, list[Path]] = {}
        for rel in self.files:
            self._by_suffix.setdefault(rel.name, []).append(rel)

    def read(self, rel: Path) -> str:
        if rel not in self._text:
            try:
                self._text[rel] = (self.root / rel).read_text(encoding="utf-8", errors="replace")
            except OSError:
                self._text[rel] = ""
        return self._text[rel]

    def masked(self, rel: Path) -> str:
        if rel not in self._masked:
            self._masked[rel] = mask_php(self.read(rel))
        return self._masked[rel]

    def functions(self, rel: Path) -> list[PhpFunc]:
        if rel not in self._funcs:
            self._funcs[rel] = php_functions(self.read(rel), self.masked(rel))
        return self._funcs[rel]

    def php_files(self, include_tests: bool = False) -> list[Path]:
        out = []
        for rel in self.files:
            if rel.suffix not in PHP_EXTS and not rel.name.endswith(PHP_EXTS):
                continue
            if not include_tests and any(seg in TEST_DIRS for seg in rel.parts):
                continue
            out.append(rel)
        return out

    def resolve(self, cited: str) -> Path | None:
        """Map a doc citation path onto a source file (exact, else unique suffix)."""
        cited = cited.lstrip("./")
        cand = Path(cited)
        if cand in self._by_suffix.get(cand.name, []):
            return cand
        matches = [
            rel for rel in self._by_suffix.get(cand.name, [])
            if str(rel).endswith(cited) and (len(str(rel)) == len(cited) or str(rel)[-len(cited) - 1] == "/")
        ]
        if not matches:
            # Tolerate a submodule-relative path (`src/Foo.php` inside modules/sub/).
            matches = [
                rel for rel in self._by_suffix.get(cand.name, [])
                if str(rel).endswith("/" + cited)
            ]
        if len(matches) == 1:
            return matches[0]
        if matches:
            # Prefer a non-test match when the rest are tests.
            non_test = [r for r in matches if not any(s in TEST_DIRS for s in r.parts)]
            if len(non_test) == 1:
                return non_test[0]
        return None

    def word_in_corpus(self, word: str) -> bool:
        return re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", self.corpus) is not None


# --- Markdown block structure -------------------------------------------------

TABLE_SEP_RE = re.compile(r"^\|?\s*:?-{2,}")
LIST_ITEM_RE = re.compile(r"^(\s*)(?:[-*+]|\d+[.)])\s+")


def parse_blocks(text: str) -> list[dict]:
    """Split a doc into blocks: heading, fence, table, list, para."""
    blocks: list[dict] = []
    lines = text.split("\n")
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.startswith("```") or line.startswith("~~~"):
            fence = line[:3]
            j = i + 1
            while j < n and not lines[j].startswith(fence):
                j += 1
            blocks.append({"type": "fence", "start": i, "end": min(j, n - 1), "lines": lines[i : j + 1]})
            i = j + 1
            continue
        if line.startswith("#"):
            blocks.append({"type": "heading", "start": i, "end": i, "lines": [line]})
            i += 1
            continue
        if line.lstrip().startswith("|"):
            j = i
            while j < n and lines[j].lstrip().startswith("|"):
                j += 1
            blocks.append({"type": "table", "start": i, "end": j - 1, "lines": lines[i:j]})
            i = j
            continue
        if LIST_ITEM_RE.match(line):
            j = i + 1
            while j < n and lines[j].strip() and (LIST_ITEM_RE.match(lines[j]) or lines[j].startswith((" ", "\t"))):
                j += 1
            blocks.append({"type": "list", "start": i, "end": j - 1, "lines": lines[i:j]})
            i = j
            continue
        j = i + 1
        while j < n and lines[j].strip() and not lines[j].startswith(("#", "```", "~~~")) \
                and not lines[j].lstrip().startswith("|") and not LIST_ITEM_RE.match(lines[j]):
            j += 1
        blocks.append({"type": "para", "start": i, "end": j - 1, "lines": lines[i:j]})
        i = j
    return blocks


def table_row_count(lines: list[str]) -> int:
    """Data rows, excluding the header, the separator and section rows
    (a row with at most one non-empty cell groups the rows below it)."""
    rows = [ln for ln in lines if ln.strip() and not TABLE_SEP_RE.match(ln.strip())]
    data = [r for r in rows[1:] if sum(1 for c in table_cells(r) if c) > 1]
    return len(data)


def list_items(lines: list[str], min_indent: int = 0, max_indent: int | None = None) -> list[tuple[int, str]]:
    """(indent, line) for every list item line within the indent window."""
    out = []
    for ln in lines:
        m = LIST_ITEM_RE.match(ln)
        if not m:
            continue
        ind = len(m.group(1).replace("\t", "    "))
        if ind < min_indent or (max_indent is not None and ind > max_indent):
            continue
        out.append((ind, ln))
    return out


def table_cells(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


# ---------------------------------------------------------------------------
# Doc-only checks
# ---------------------------------------------------------------------------

NUMBER_WORDS = {
    "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20,
}
COUNT_NOUNS = (
    "implementations|hooks|routes|services|permissions|plugins|libraries|methods|"
    "classes|functions|events|constants|commands|templates|submodules|sub-modules|"
    "dependencies|fields|forms|controllers|subscribers|listeners|actions|conditions|"
    "widgets|formatters|files|entries|keys|options|settings|tags|tables|columns|"
    "properties|arguments|parameters|steps|stages|phases|branches|modes|states|"
    "values|groups|categories|sections|blocks|elements|items|tokens|filters|sorts|"
    "areas|displays|styles|rows|handlers|providers|processors|sources|targets|"
    "fetchers|parsers|mappers|schemas|links|tasks|queues|workers|endpoints|"
    "resources|decorators|aliases|overrides|definitions|interfaces|traits|"
    "attributes|annotations|derivers|migrations|bundles|entity types|plugin types|"
    "theme hooks|base fields|config entities|content entities|cache tags|"
    "cache contexts|drush commands|cli commands|access checks|route subscribers|"
    "event subscribers|queue workers|field types|field widgets|field formatters|"
    "menu links|local tasks|local actions|contextual links|config objects|"
    "config schemas|schema files|twig templates|js files|css files|js behaviors|"
    "behaviors|callbacks|hook implementations|alter hooks|api hooks|"
    "operations|transitions|types|kinds|variants|flavors|layers|components|"
    "subclasses|abstract classes|base classes|exceptions|validators|constraints|"
    "checkers|helpers|managers|factories|repositories|storages|storage handlers|"
    "list builders|route providers|access handlers|view builders|form classes|"
    "form handlers|entity handlers|handler classes|render elements|form elements|"
    "element types|block plugins|views plugins|views handlers|action plugins|"
    "condition plugins|source plugins|process plugins|destination plugins|"
    "id map plugins|fetcher plugins|parser plugins|processor plugins|"
    "data types|token types|entity bundles|view modes|form modes|display modes|"
    "regions|breakpoints|variables|placeholders|substitutions|patterns"
)
COUNT_RE = re.compile(
    r"(?<![\w.$\-/#])(?:\*\*)?(\d{1,3}|" + "|".join(NUMBER_WORDS) + r")(?:\*\*)?"
    r"\s+((?:(?:`[^`]*`|[A-Za-z][\w\-]*)\s+){0,3}?)(" + COUNT_NOUNS + r")(?![\w\-])",
    re.IGNORECASE,
)
# Preceding context that makes the number a subset / bound, not a total.
COUNT_PRE_SKIP_RE = re.compile(
    r"(?:\bof\s+(?:the|its|these|those|their)?|\bamong\b|\bany\b|\bsome\b|\bat\s+(?:least|most)|"
    r"\bup\s+to|\bmore\s+than|\bfewer\s+than|\bless\s+than|\bover\b|\bunder\b|"
    r"\bnearly\b|\babout\b|\baround\b|\broughly\b|\bapproximately\b|\bthan\b|"
    r"\bfirst\b|\blast\b|\bnext\b|\bother\b|\bversion\b|\bdrupal\b|\bphp\b|\b(?:step|phase|wave|level|depth|weight|priority)\b|[-–]\s*)$",
    re.IGNORECASE,
)
# Modifier right after the number that makes it a partial / relative count.
COUNT_MOD_SKIP_RE = re.compile(
    r"^(?:more|fewer|other|additional|further|new|extra|remaining|different|"
    r"separate|distinct|main|key|major|minor|common|typical|notable|primary|"
    r"important|optional|possible|potential|core|custom|sample|example|"
    r"or\b|to\b|and\b)",
    re.IGNORECASE,
)
PARTIAL_LIST_RE = re.compile(
    r"\b(?:including|such\s+as|e\.g\.|for\s+example|for\s+instance|among\s+them|"
    r"notably|most\s+notably|like|etc\b|and\s+so\s+on|and\s+others|and\s+more|"
    r"in\s+particular|the\s+most\s+important|key\s+ones|examples?)\b|…|\.\.\.",
    re.IGNORECASE,
)
# Between two enumerated items only separators and light articles/adjectives
# may appear ("`a`, `b`, and the autowired `c`") — any other word ends the run.
INLINE_GAP_RE = re.compile(
    r"^\s*(?:[,;/]\s*)?(?:(?:and|or|plus|&)\s+)?"
    r"(?:(?:the|a|an|its|their|one|each|both|also|autowired|static|abstract|final|"
    r"optional|own|new|deprecated|legacy|public|private|protected|internal|base|"
    r"concrete|generic|default|custom|core|contrib|sibling|matching|corresponding|"
    r"respective|separate|distinct|standalone|lazy|eager|shared|dedicated)\s+){0,2}$"
)
# What may stand between the counted noun and the first enumerated item.
INLINE_LEAD_RE = re.compile(r"^[^`.]{0,60}?(?:[:—–]|\(|-\s|\bnamely\b|\bare\b|\bis\b|\bbeing\b)\s*(?:\*\*)?\s*$")
PAREN_LEAD_RE = re.compile(r"^\s*(?:(?:verified|namely|all|both|i\.e\.|currently|specifically|respectively)\s*:?\s*)?(?:\*\*)?$", re.IGNORECASE)
PRODUCT_VERSION_RE = re.compile(r"[A-Z][A-Za-z0-9]*$")


def _count_value(tok: str) -> int:
    return int(tok) if tok.isdigit() else NUMBER_WORDS[tok.lower()]


def _strip_parens(s: str) -> str:
    """Remove depth-1 parenthesized groups that are outside backticks."""
    out, depth, in_tick = [], 0, False
    for ch in s:
        if ch == "`":
            if depth == 0:
                in_tick = not in_tick
                out.append(ch)
            continue
        if in_tick:
            out.append(ch)
            continue
        if ch == "(":
            depth += 1
            continue
        if ch == ")":
            if depth > 0:
                depth -= 1
                continue
        if depth == 0:
            out.append(ch)
    return "".join(out)


def _sentence_after(text: str, pos: int) -> str:
    """Text from pos to the end of the sentence (outside backticks/parens)."""
    depth, in_tick, i = 0, False, pos
    while i < len(text):
        ch = text[i]
        if ch == "`":
            in_tick = not in_tick
        elif not in_tick:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth = max(0, depth - 1)
            elif ch in ".;" and depth == 0:
                # Sentence end: `. ` (also `.** `, `.) `, `." `), not `e.g. `.
                after = re.match(r"[*_\")\]]*(?:\s|$)", text[i + 1 : i + 6])
                prev = text[max(0, i - 3) : i].lower()
                if after and not prev.endswith(("e.g", "i.e", "vs", "etc")):
                    return text[pos:i]
        i += 1
    return text[pos:]


# A doc-set cross-reference (`configuration.md`) or a `path:line` citation
# tacked onto an enumeration is not one of its items; `*.yml` / `*.php` file
# names, however, are routinely the enumerated things themselves.
DOC_REF_SPAN_RE = re.compile(r"\.md(?::\d+)?$|:\d+(?:-\d+)?$|/$")


def _run_length(spans: list[re.Match], s: str) -> int:
    run = 1
    for prev, cur in zip(spans, spans[1:]):
        gap = s[prev.end() : cur.start()].replace("**", "")
        if not INLINE_GAP_RE.match(gap) or DOC_REF_SPAN_RE.search(cur.group(1)):
            break  # a file/doc reference (`configuration.md`) is a citation, not an item
        run += 1
    return run


def inline_run_length(sentence: str) -> int:
    """Length of the enumeration run that directly follows the counted noun.

    Two shapes count: "N services: `a`, `b` and `c`" (an introducer, then a run
    of backticked items separated only by commas/and/light adjectives) and
    "N classes (`a`, `b`, `c`)" (a parenthetical right after the noun). 0
    when the sentence does not enumerate.
    """
    # Parenthetical enumeration directly after the noun phrase — only
    # punctuation may separate them ("three areas: management (`a`, `b`)"
    # enumerates the first area, not the areas).
    head = sentence[:60]
    p = head.find("(")
    if p != -1 and re.fullmatch(r"[\s*:—–,]*", head[:p]):
        inner = _balanced(sentence, p)[1:-1]
        spans = list(BACKTICK_SPAN_RE.finditer(inner))
        if spans:
            lead = inner[: spans[0].start()]
            if PAREN_LEAD_RE.match(lead) and not PARTIAL_LIST_RE.search(lead):
                return _run_length(spans, inner)
    s = _strip_parens(sentence)
    spans = list(BACKTICK_SPAN_RE.finditer(s))
    if not spans:
        return 0
    lead = s[: spans[0].start()]
    if not INLINE_LEAD_RE.match(lead) or PARTIAL_LIST_RE.search(lead):
        return 0
    return _run_length(spans, s)


def _units(blk: dict) -> list[tuple[int, str, list[str], list[int]]]:
    """(first line index, text, nested lines, per-char line index) per unit.

    A paragraph is one unit; every top-level list item is a unit whose nested
    lines are the indented lines that follow it.
    """
    units = []
    if blk["type"] == "para":
        text, line_of = "", []
        for k, ln in enumerate(blk["lines"]):
            piece = ln.strip() + " "
            text += piece
            line_of.extend([blk["start"] + k] * len(piece))
        units.append((blk["start"], text.rstrip(), [], line_of))
        return units
    items = blk["lines"]
    k = 0
    while k < len(items):
        m = LIST_ITEM_RE.match(items[k])
        if not m:
            k += 1
            continue
        ind = len(m.group(1).replace("\t", "    "))
        j = k + 1
        nested: list[str] = []
        while j < len(items):
            m2 = LIST_ITEM_RE.match(items[j])
            if m2 and len(m2.group(1).replace("\t", "    ")) <= ind:
                break
            nested.append(items[j])
            j += 1
        # Continuation lines that are not list items belong to the item text.
        text_lines = [items[k][m.end():].strip()]
        rest: list[str] = []
        for ln in nested:
            if LIST_ITEM_RE.match(ln) or rest or ln.lstrip().startswith("|"):
                rest.append(ln)
            else:
                text_lines.append(ln.strip())
        text = " ".join(text_lines)
        units.append((blk["start"] + k, text, rest, [blk["start"] + k] * len(text)))
        k = j
    return units


def check_counts(docs: list[tuple[str, str]]) -> tuple[list[str], int]:
    """A stated count must match the enumeration it introduces.

    Inline runs are only flagged when they hold MORE items than stated (a
    shorter run is usually a partial list); a table/list introduced by a
    lead-in sentence ending in ":" is flagged in both directions.
    """
    problems: list[str] = []
    checked = 0
    for rel, text in docs:
        blocks = parse_blocks(text)
        for bi, blk in enumerate(blocks):
            if blk["type"] not in ("para", "list"):
                continue
            for line_off, utext, nested, line_of in _units(blk):
                matches = list(COUNT_RE.finditer(utext))
                for m in matches:
                    pre = utext[max(0, m.start() - 30) : m.start()].rstrip()
                    if COUNT_PRE_SKIP_RE.search(pre):
                        continue
                    if m.group(1).isdigit() and PRODUCT_VERSION_RE.search(pre):
                        continue  # "CKEditor 5 plugin definitions", "Drupal 10 sites"
                    if COUNT_MOD_SKIP_RE.match(m.group(2) or "") or re.search(r"\bof\b", m.group(2) or ""):
                        continue  # "two pairs of events", "two of its submodules"
                    n = _count_value(m.group(1))
                    noun = m.group(3)
                    line_no = (line_of[m.start()] if m.start() < len(line_of) else line_off) + 1
                    before = _strip_parens(utext[: m.start()] + "\x00")
                    if not before.endswith("\x00"):
                        continue  # the count sits inside a parenthetical aside
                    sentence = _sentence_after(utext, m.end())
                    last_sentence = len(sentence) == len(utext) - m.end()
                    # (1) Inline enumeration in the same sentence.
                    run = inline_run_length(sentence)
                    if run >= 2:
                        checked += 1
                        if run > n:
                            problems.append(
                                f"{rel}:{line_no}: states {m.group(1)} {noun} but the inline "
                                f"enumeration that follows names {run} (recount, then fix the number)"
                            )
                        continue
                    # (2) A table/list introduced by this sentence. Only a
                    # short lead-in counts ("N routes:", "N services (…):",
                    # "N hooks are:") — a long tail or a backticked reference
                    # after the noun means the number describes something else.
                    if len(matches) != 1 or not last_sentence or PARTIAL_LIST_RE.search(utext):
                        continue
                    tail = utext[m.end():].rstrip()
                    if not tail.endswith(":"):
                        continue
                    tail_flat = _strip_parens(tail[:-1])
                    if len(tail_flat) > 45 or "`" in tail:
                        continue
                    for pm in re.finditer(r"\bplus\s+(?:\*\*)?(\d{1,3}|one|" + "|".join(NUMBER_WORDS) + r")\b", tail, re.I):
                        n += 1 if pm.group(1).lower() == "one" else _count_value(pm.group(1))
                    enum_kind, found_n, alt_n = None, None, None

                    def _list_count(lines: list[str], min_indent: int = 0):
                        items = list_items(lines, min_indent=min_indent)
                        if not items:
                            return None, None
                        top = min(i for i, _ in items)
                        if not all(i == top for i, _ in items):
                            return None, None  # grouped lists are ambiguous
                        # Commentary items ("Both routes use…") are not entries.
                        entries = [ln for _, ln in items if re.match(r"\s*(?:[-*+]|\d+[.)])\s+[`*\\\[]", ln)]
                        # Grouped bullets ("`A` and `B` — …") hold several
                        # items each: the run of spans at each item's start.
                        alt = 0
                        for ln in entries:
                            body = LIST_ITEM_RE.sub("", ln, count=1).replace("**", "")
                            spans = list(BACKTICK_SPAN_RE.finditer(body))
                            alt += _run_length(spans, body) if spans and not body[: spans[0].start()].strip() else 1
                        return (len(entries) or len(items)), alt

                    if nested:
                        if any(ln.lstrip().startswith("|") for ln in nested):
                            enum_kind, found_n = "table", table_row_count(
                                [ln for ln in nested if ln.lstrip().startswith("|")]
                            )
                        else:
                            found_n, alt_n = _list_count(nested, min_indent=1)
                            enum_kind = "nested list"
                    elif blk["type"] == "para" and bi + 1 < len(blocks):
                        nxt = blocks[bi + 1]
                        if nxt["type"] == "table":
                            enum_kind, found_n = "table", table_row_count(nxt["lines"])
                        elif nxt["type"] == "list":
                            found_n, alt_n = _list_count(nxt["lines"])
                            enum_kind = "list"
                    if enum_kind is None or found_n is None or found_n < 2:
                        continue
                    checked += 1
                    # A grouped enumeration ("`A` and `B` — …" bullets) may
                    # hold N items across fewer bullets: accept the span count.
                    if found_n != n and not (alt_n is not None and alt_n >= found_n and alt_n == n):
                        problems.append(
                            f"{rel}:{line_no}: states {m.group(1)} {noun} but the {enum_kind} "
                            f"it introduces has {found_n} (recount, then fix the number)"
                        )
    return problems, checked


def collect_citations(docs: list[tuple[str, str]]) -> list[tuple[str, int, str, int, int]]:
    """(doc, doc line, cited path, a, b) for every path:line citation."""
    out = []
    for rel, text in docs:
        for li, line in enumerate(text.split("\n"), 1):
            for m in CITATION_RE.finditer(line):
                a = int(m.group(2))
                b = int(m.group(3)) if m.group(3) else a
                if b < a:
                    a, b = b, a
                out.append((rel, li, m.group(1).lstrip("./"), a, b))
    return out


def check_citation_overlap(citations) -> tuple[list[str], int]:
    """Two citations of one file whose ranges partially overlap contradict."""
    by_name: dict[str, list] = {}
    for c in citations:
        by_name.setdefault(Path(c[2]).name, []).append(c)
    warnings: list[str] = []
    seen: set[tuple] = set()
    for group in by_name.values():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                d1, l1, p1, a1, b1 = group[i]
                d2, l2, p2, a2, b2 = group[j]
                if not (p1.endswith(p2) or p2.endswith(p1)):
                    continue
                if (a1, b1) == (a2, b2):
                    continue
                # Sharing one boundary line (179-216 vs 216-229) is adjacency,
                # not divergence — require a real overlap.
                overlap = min(b1, b2) - max(a1, a2) + 1 >= 2
                contains = (a1 <= a2 and b2 <= b1) or (a2 <= a1 and b1 <= b2)
                if overlap and not contains:
                    key = (d1, l1, d2, l2, a1, b1, a2, b2)
                    if key in seen:
                        continue
                    seen.add(key)
                    warnings.append(
                        f"citation ranges diverge for {p1}: {d1}:{l1} cites {a1}-{b1}, "
                        f"{d2}:{l2} cites {a2}-{b2} (same code, different lines — one is wrong)"
                    )
    return warnings, len(citations)


# ---------------------------------------------------------------------------
# --module-root checks
# ---------------------------------------------------------------------------

# A span is a *code quotation* (not an identifier) when it carries PHP syntax.
CODE_SPAN_RE = re.compile(r"\$|->|::|\w\(|\bnew\s+[A-Z]")
# …and a *strong* one (call chain / expression, not a `$var = value` idiom
# docs use to paraphrase a parameter) when it has a call or a chain in it.
STRONG_SPAN_RE = re.compile(r"->|::|\w\(")
STATIC_REF_RE = re.compile(r"^[\w\\]+::\$?\w+(?:\(\))?$")
BARE_CALL_RE = re.compile(r"^\w+\(\)$")


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("\\\\", "\\")).strip()


def check_cited_spans(docs, src: Source) -> tuple[list[str], list[str], int]:
    """A code span next to a `path:line` citation must be in those lines."""
    problems: list[str] = []
    warnings: list[str] = []
    checked = 0
    for rel, text in docs:
        for li, line in enumerate(text.split("\n"), 1):
            cits = list(CITATION_RE.finditer(line))
            if not cits:
                continue
            for ci, cm in enumerate(cits):
                if not cm.group(1).endswith(PHP_EXTS + (".yml", ".yaml", ".js", ".twig")):
                    continue
                target = src.resolve(cm.group(1))
                if target is None:
                    continue
                a = int(cm.group(2))
                b = int(cm.group(3)) if cm.group(3) else a
                if b < a:
                    a, b = b, a
                if b - a > 40:
                    continue
                prev_end = cits[ci - 1].end() if ci else 0
                window = line[max(prev_end, cm.start() - 160) : cm.start()]
                spans = [s.group(1) for s in BACKTICK_SPAN_RE.finditer(window)]
                # Only the span(s) right before the citation belong to it:
                # "`expr` (`path:line`)" or "(`expr`, `path:line`)".
                tail = window[window.rfind("`") + 1 :] if spans else ""
                if not spans or not re.fullmatch(r"[\s,;:—–\-()*]*(?:at|in|see|from|via|on)?[\s,;:—–\-()*]*`?", tail):
                    continue
                span = spans[-1]
                if not CODE_SPAN_RE.search(span) or STATIC_REF_RE.match(span) or BARE_CALL_RE.match(span):
                    continue
                if "…" in span or "..." in span or CITATION_RE.search(span):
                    continue
                src_lines = src.read(target).split("\n")
                lo, hi = max(1, a - 2), min(len(src_lines), b + 2)
                cited = _norm_ws(" ".join(src_lines[lo - 1 : hi]))
                needle = _norm_ws(span)
                variants = [needle]
                m = re.match(r"^[\w\\]+(::\w+\(.*)$", needle)
                if m:
                    variants.append(m.group(1))
                    variants.append(m.group(1)[2:])
                checked += 1
                if any(v and v in cited for v in variants):
                    continue
                whole = [_norm_ws(ln) for ln in src_lines]
                hit = next(
                    (i + 1 for i, ln in enumerate(whole) if any(v and v in ln for v in variants)),
                    None,
                )
                if hit is None:
                    joined = _norm_ws(" ".join(src_lines))
                    if any(v and v in joined for v in variants):
                        hit = -1
                if hit == -1:
                    warnings.append(
                        f"{rel}:{li}: `{span}` is not within cited lines {a}-{b} of {cm.group(1)} "
                        "(it spans other lines — fix the citation)"
                    )
                elif hit is not None:
                    warnings.append(
                        f"{rel}:{li}: `{span}` is not within cited lines {a}-{b} of {cm.group(1)} "
                        f"(found at line {hit} — fix the citation)"
                    )
                else:
                    msg = (
                        f"{rel}:{li}: `{span}` cited as {cm.group(1)}:{cm.group(2)}"
                        f"{'-' + cm.group(3) if cm.group(3) else ''} exists nowhere in that file "
                        "(synthesized code — describe the mechanism in prose instead)"
                    )
                    if STRONG_SPAN_RE.search(span):
                        problems.append(msg)
                    else:
                        warnings.append(msg)
    return problems, warnings, checked


METHOD_TOKEN_RE = re.compile(r"`?((?:\\?[A-Za-z_]\w*\\)*)([A-Za-z_]\w*)::(\$?[A-Za-z_]\w*)(?:\(\))?`?")
FUNC_TOKEN_RE = re.compile(r"`([a-z_][a-z0-9_]*)\(\)`")


def check_invocation_sites(docs, src: Source) -> tuple[list[str], int]:
    """`Class::method()` + `path:line`: the line must be inside that method."""
    problems: list[str] = []
    checked = 0
    for rel, text in docs:
        for li, line in enumerate(text.split("\n"), 1):
            cits = list(CITATION_RE.finditer(line))
            if not cits:
                continue
            for ci, cm in enumerate(cits):
                if not cm.group(1).endswith(PHP_EXTS):
                    continue
                target = src.resolve(cm.group(1))
                if target is None:
                    continue
                a = int(cm.group(2))
                b = int(cm.group(3)) if cm.group(3) else a
                if b < a:
                    a, b = b, a
                prev_end = cits[ci - 1].end() if ci else 0
                window = line[max(prev_end, cm.start() - 220) : cm.start()]
                basename = Path(cm.group(1)).stem
                is_class_file = bool(CLASS_DECL_RE.search(src.masked(target)))
                # The token must sit right next to the citation — "`X::y()`
                # (`X.php:12`)", "in `X::y()`, `X.php:12`", "`y()` at `f.module:8`".
                # Anything wordier ("once `X::y()` has produced … (`X.php:12`)")
                # cites some other line and is not a verdict.
                cands: list[tuple[int, int, str]] = []
                for tm in METHOD_TOKEN_RE.finditer(window):
                    if tm.group(2) == basename and not tm.group(3).startswith("$"):
                        cands.append((tm.start(), tm.end(), tm.group(3)))
                if not is_class_file:
                    for fm in FUNC_TOKEN_RE.finditer(window):
                        cands.append((fm.start(), fm.end(), fm.group(1)))
                if not cands:
                    continue
                _, end, name = max(cands)
                between = window[end:]
                if not re.fullmatch(r"[\s,;:—–\-*`]*(?:\(|at|in|see|—|–)?[\s`(]*", between) or len(between) > 20:
                    continue
                funcs = src.functions(target)
                if not any(f.name == name for f in funcs):
                    continue  # not declared in this file — the FQCN check's territory
                enc_a = enclosing_function(funcs, a)
                enc_b = enclosing_function(funcs, b)
                if enc_a is None or enc_b is None or enc_a is not enc_b:
                    continue  # class-level line or a range spanning functions: no verdict
                checked += 1
                if enc_a.name != name:
                    problems.append(
                        f"{rel}:{li}: cites `{name}()` at {cm.group(1)}:{a}"
                        f"{'-' + str(b) if b != a else ''}, but that line is inside "
                        f"`{enc_a.name}()` ({enc_a.start}-{enc_a.end}) — fix the method or the line"
                    )
    return problems, checked


ATTR_RE = re.compile(r"^#\[([A-Za-z_]\w*)\s*\(", re.M)
ANNOT_RE = re.compile(r"^\s*\*\s*@([A-Z][A-Za-z_]\w*)\s*\(", re.M)
ATTR_ID_RE = re.compile(r"\bid\s*:\s*(['\"])(.+?)\1")
ANNOT_ID_RE = re.compile(r"\bid\s*=\s*(['\"])(.+?)\1")
POSITIONAL_ID_RE = re.compile(r"^\s*(['\"])(.+?)\1")
NON_PLUGIN_ATTRS = {
    "Hook", "LegacyHook", "ReorderHook", "RemoveHook", "StopProceduralHookScan", "Attribute",
    "Override", "ReturnTypeWillChange", "Deprecated", "SensitiveParameter", "AllowDynamicProperties",
    "Autowire", "AutowireIterator", "AutoconfigureTag", "Group", "CoversClass", "RunTestsInSeparateProcesses",
    "DataProvider", "Test", "IgnoreDeprecations", "CoversMethod", "UsesClass", "Depends",
}


class PluginDecl:
    __slots__ = ("id", "attr", "fqcn", "file", "abstract", "has_deriver")

    def __init__(self, id_, attr, fqcn, file, abstract, has_deriver):
        self.id, self.attr, self.fqcn, self.file = id_, attr, fqcn, file
        self.abstract, self.has_deriver = abstract, has_deriver


def _balanced(text: str, start: int, open_ch: str = "(", close_ch: str = ")") -> str:
    depth = 0
    for i in range(start, len(text)):
        if text[i] == open_ch:
            depth += 1
        elif text[i] == close_ch:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text[start:]


class ClassInfo:
    __slots__ = ("fqcn", "file", "abstract", "plugins")

    def __init__(self, fqcn, file, abstract):
        self.fqcn, self.file, self.abstract = fqcn, file, abstract
        self.plugins: list[PluginDecl] = []


def collect_classes(src: Source) -> dict[str, ClassInfo]:
    """Every class in the source (FQCN → info) with its plugin declarations.

    Plugin attributes/annotations are collected wherever the class lives —
    `src/Plugin/**` by convention, but `src/Element/` (`@FormElement`),
    `src/Feeds/Target/`, `src/Plugin/views/**` and others are real too.
    """
    out: dict[str, ClassInfo] = {}
    for rel in src.php_files():
        if rel.suffix != ".php":
            continue
        masked = src.masked(rel)
        cm = CLASS_DECL_RE.search(masked)
        if not cm:
            continue
        raw = src.read(rel)
        ns = NAMESPACE_RE.search(masked)
        fqcn = (ns.group(1) + "\\" if ns else "") + cm.group(2)
        abstract = bool(re.match(r"^[ \t]*abstract\b", masked[masked.rfind("\n", 0, cm.start()) + 1 : cm.end()]))
        info = ClassInfo(fqcn, rel, abstract)
        head = raw[: cm.start()]
        for am in ATTR_RE.finditer(head):
            name = am.group(1)
            if name in NON_PLUGIN_ATTRS:
                continue
            inner = _balanced(head, am.end() - 1)[1:-1]
            idm = ATTR_ID_RE.search(inner) or POSITIONAL_ID_RE.match(inner)
            if idm:
                info.plugins.append(PluginDecl(idm.group(2), name, fqcn, rel, abstract, "deriver" in inner))
        for an in ANNOT_RE.finditer(head):
            name = an.group(1)
            if name in ("Translation", "PluralTranslation", "ContextDefinition"):
                continue
            inner = _balanced(head, an.end() - 1)[1:-1]
            idm = ANNOT_ID_RE.search(inner) or POSITIONAL_ID_RE.match(inner)
            if idm:
                info.plugins.append(PluginDecl(idm.group(2), name, fqcn, rel, abstract, "deriver" in inner))
        out[fqcn] = info
    return out


ID_HEADER_RE = re.compile(r"^(?:plugin\s*)?id$", re.IGNORECASE)
CLASS_HEADER_RE = re.compile(r"^(?:class|plugin class|implementation|handler class)$", re.IGNORECASE)


def check_plugin_ids(docs, src: Source, module_name: str) -> tuple[list[str], list[str], int]:
    classes = collect_classes(src)
    decls = [p for c in classes.values() for p in c.plugins]
    if not decls:
        return [], [], 0
    by_id: dict[str, list[PluginDecl]] = {}
    for dcl in decls:
        by_id.setdefault(dcl.id, []).append(dcl)
    by_short: dict[str, list[ClassInfo]] = {}
    for info in classes.values():
        by_short.setdefault(info.fqcn.rsplit("\\", 1)[-1], []).append(info)

    def row_class(cell: str) -> ClassInfo | None:
        cell = cell.replace("\\\\", "\\")
        # Prefer a fully qualified name; fall back to a unique short name.
        for fm in re.finditer(r"(?<![\w\\])((?:\\?[A-Za-z_]\w*\\)+[A-Za-z_]\w*)", cell):
            fq = fm.group(1).lstrip("\\")
            if fq in classes:
                return classes[fq]
        first = cell.split("(")[0].strip("` *")
        sm = re.search(r"([A-Za-z_]\w*)\s*$", first)
        if sm and len(by_short.get(sm.group(1), [])) == 1:
            return by_short[sm.group(1)][0]
        return None

    problems: list[str] = []
    warnings: list[str] = []
    checked = 0
    doc_ids: set[str] = set()
    for rel, text in docs:
        if not (rel == "plugins.md" or rel.startswith("submodules/")):
            continue
        for blk in parse_blocks(text):
            if blk["type"] != "table":
                continue
            header = table_cells(blk["lines"][0])
            id_col = next((i for i, h in enumerate(header) if ID_HEADER_RE.match(h.replace("`", "").strip())), None)
            if id_col is None:
                continue
            class_col = next((i for i, h in enumerate(header) if CLASS_HEADER_RE.match(h.replace("`", "").strip())), None)
            for off, row in enumerate(blk["lines"][1:], 1):
                if TABLE_SEP_RE.match(row.strip()):
                    continue
                cells = table_cells(row)
                if id_col >= len(cells):
                    continue
                ids = [s.group(1) for s in BACKTICK_SPAN_RE.finditer(cells[id_col])]
                info = row_class(cells[class_col]) if class_col is not None and class_col < len(cells) else None
                for pid in ids:
                    if not re.fullmatch(r"[A-Za-z0-9_.\-]+", pid):
                        continue  # derivative / placeholder / composite ids
                    if pid[0] in "_.-" or pid[-1] in "_.-":
                        continue  # a fragment ("`eca_render_alter_link` + `_set_url`"), not an id
                    doc_ids.add(pid)
                    checked += 1
                    line_no = blk["start"] + off + 1
                    if pid in by_id and any(not dcl.abstract for dcl in by_id[pid]):
                        continue
                    if pid in by_id:
                        dcl = by_id[pid][0]
                        problems.append(
                            f"{rel}:{line_no}: plugin id `{pid}` is declared only on abstract class "
                            f"{dcl.fqcn} ({dcl.file}) — no such plugin exists"
                        )
                        continue
                    if info is not None:
                        if info.plugins:
                            real = ", ".join(sorted({f"`{o.id}`" for o in info.plugins}))
                            problems.append(
                                f"{rel}:{line_no}: plugin id `{pid}` is not declared by {info.fqcn} "
                                f"({info.file}) — it declares {real}"
                            )
                        else:
                            kind = "abstract class" if info.abstract else "class"
                            problems.append(
                                f"{rel}:{line_no}: plugin id `{pid}` — {kind} {info.fqcn} "
                                f"({info.file}) carries no plugin attribute/annotation"
                            )
                        continue
                    if re.search(r"['\"]" + re.escape(pid) + r"['\"]", src.corpus):
                        continue  # a literal in the source (core plugin the module refers to)
                    warnings.append(
                        f"{rel}:{line_no}: plugin id `{pid}` is declared by no plugin class under "
                        f"src/Plugin and occurs nowhere in the source"
                    )
    # Recall half: source ids no doc mentions, one line per plugin type.
    corpus_docs = "\n".join(t for _, t in docs)
    missing: dict[str, list[str]] = {}
    totals: dict[str, int] = {}
    for dcl in decls:
        if dcl.abstract:
            continue
        totals[dcl.attr] = totals.get(dcl.attr, 0) + 1
        if f"`{dcl.id}`" in corpus_docs or re.search(r"(?<![\w.:-])" + re.escape(dcl.id) + r"(?![\w.:-])", corpus_docs):
            continue
        missing.setdefault(dcl.attr, []).append(dcl.id)
    for attr, ids in sorted(missing.items()):
        shown = ", ".join(f"`{i}`" for i in sorted(ids)[:10])
        more = f", … (+{len(ids) - 10})" if len(ids) > 10 else ""
        warnings.append(
            f"{len(ids)} of {totals[attr]} `{attr}` plugin ids are mentioned in no doc file: {shown}{more}"
        )
    return problems, warnings, checked


LIB_KEY_RE = re.compile(r"^([A-Za-z0-9_.\-]+):\s*(?:#.*)?$", re.M)


def check_libraries(docs, src: Source) -> tuple[list[str], int]:
    warnings: list[str] = []
    corpus_docs = "\n".join(t for _, t in docs)
    checked = 0
    for rel in src.files:
        if not rel.name.endswith(".libraries.yml") or any(s in TEST_DIRS for s in rel.parts):
            continue
        provider = rel.name[: -len(".libraries.yml")]
        for m in LIB_KEY_RE.finditer(src.read(rel)):
            lib = m.group(1)
            checked += 1
            if f"{provider}/{lib}" in corpus_docs or f"`{lib}`" in corpus_docs:
                continue
            warnings.append(
                f"library `{provider}/{lib}` ({rel}) is mentioned in no doc file "
                "(every *.libraries.yml entry must be accounted for)"
            )
    return warnings, checked


DEPRECATED_RE = re.compile(r"@deprecated\b")
DECL_AFTER_RE = re.compile(
    r"^\s*(?:(?:abstract|final|public|protected|private|static|readonly)\s+)*"
    r"(?:(function)\s+&?([A-Za-z_]\w*)|(const)\s+([A-Za-z_]\w*)|(class|interface|trait|enum)\s+([A-Za-z_]\w*)|"
    r"(?:\??[\w\\|]+\s+)?(\$)([A-Za-z_]\w*))"
)


def check_deprecations(docs, src: Source) -> tuple[list[str], list[str], int]:
    problems: list[str] = []
    warnings: list[str] = []
    corpus_docs = "\n".join(t for _, t in docs)
    checked = 0
    seen: set[str] = set()
    public_missing: dict[Path, list[str]] = {}
    other_missing: dict[Path, list[str]] = {}
    for rel in src.php_files():
        raw = src.read(rel)
        if "@deprecated" not in raw:
            continue
        lines = raw.split("\n")
        for i, line in enumerate(lines):
            if not DEPRECATED_RE.search(line) or not line.lstrip().startswith(("*", "/**")):
                continue
            # Walk to the docblock end, then to the declaration it documents.
            j = i
            while j < len(lines) and "*/" not in lines[j]:
                j += 1
            k = j + 1
            while k < len(lines) and (not lines[k].strip() or lines[k].lstrip().startswith("#[")
                                      or (lines[k].strip().endswith((",", "]", ")]")) and not DECL_AFTER_RE.match(lines[k]))):
                k += 1
            if k >= len(lines):
                continue
            dm = DECL_AFTER_RE.match(lines[k])
            if not dm:
                continue
            if dm.group(1):
                name, kind = dm.group(2), "function"
            elif dm.group(3):
                name, kind = dm.group(4), "const"
            elif dm.group(5):
                name, kind = dm.group(6), dm.group(5)
            else:
                name, kind = dm.group(8), "property"
            vis = "public"
            for v in ("protected", "private"):
                if re.search(r"\b" + v + r"\b", lines[k]):
                    vis = v
            key = f"{rel}:{name}"
            if key in seen:
                continue
            seen.add(key)
            checked += 1
            if re.search(r"(?<![\w$])" + re.escape(name) + r"(?![\w])", corpus_docs):
                continue
            bucket = public_missing if vis == "public" and kind != "property" else other_missing
            bucket.setdefault(rel, []).append(f"{kind} `{name}` (:{k + 1})")
    # One line per source file keeps the fix cycle scoped to one explorer.
    for rel, syms in sorted(public_missing.items()):
        problems.append(
            f"@deprecated public symbols in {rel} appear in no doc file: {', '.join(syms)} "
            "— document each with its replacement"
        )
    for rel, syms in sorted(other_missing.items()):
        warnings.append(
            f"@deprecated protected/private symbols in {rel} appear in no doc file: {', '.join(syms)}"
        )
    return problems, warnings, checked


BARE_CLASS_RE = re.compile(
    r"`([A-Z][A-Za-z0-9]*(?:Subscriber|Controller|Manager|Plugin|Base|Interface|Trait|Factory|"
    r"Deriver|Helper|Form|Builder|Handler|Service|Storage|Provider|Resolver|Processor|Repository|"
    r"Validator|Constraint|Command|Formatter|Widget|Block|Filter|Listener|Event|Exception|Hooks|"
    r"Access|ListBuilder|Collector|Generator|Renderer|Worker|Source|Fetcher|Parser|Mapper|Target|"
    r"Element|Normalizer|Encoder|Loader|Dispatcher|Checker|Comparator|Converter|Discovery|Definition|"
    r"Wrapper|Adapter|Client|Executable|Router|Matcher|Negotiator|Policy|Strategy|Registry|Installer|"
    r"Updater|Migrator|Importer|Exporter|Iterator|Collection|Query|Condition|Action|Entity|Type|Item|"
    r"Settings|Config|Cache|Batch|Queue|Job|Task|Runner|Tester|Guard|Voter|Rule|Sorter|Grouper))`"
)


def check_bare_class_names(docs, src: Source, module_names: list[str]) -> tuple[list[str], int]:
    """A bare `FooBarSubscriber` that starts with the module's CamelCase name
    must exist in the source. Generic framework names (`EventSubscriberInterface`,
    `RouteNotFoundException`) are skipped — they are almost always real core
    classes the module never imports; the observed failure (`ViewsRouteSubscriber`)
    is a module-named class that was invented."""
    prefixes = tuple(
        "".join(part.capitalize() for part in name.split("_")) for name in module_names
    )
    warnings: list[str] = []
    introduced: set[str] = set()
    for _, text in docs:
        for m in FQCN_RE.finditer(text.replace("\\\\", "\\")):
            introduced.add(m.group(1).rsplit("\\", 1)[-1])
        for m in re.finditer(r"\\([A-Z][A-Za-z0-9]+)\b", text):
            introduced.add(m.group(1))
    checked = 0
    seen: set[str] = set()
    for rel, text in docs:
        for li, line in enumerate(text.split("\n"), 1):
            for m in BARE_CLASS_RE.finditer(line):
                tok = m.group(1)
                if tok in seen:
                    continue
                seen.add(tok)
                if tok in introduced or not tok.startswith(prefixes):
                    continue
                checked += 1
                if src.word_in_corpus(tok):
                    continue
                warnings.append(
                    f"{rel}:{li}: `{tok}` — no class of that name is declared or imported anywhere in "
                    "the source, and no FQCN in the docs introduces it (invented or misspelled class?)"
                )
    return warnings, checked


def check_id_strings(
    d: Path, src: Source, module_name: str, submodules: list[str]
) -> tuple[list[str], int]:
    """Backticked module-prefixed id strings in the docs must occur in the source."""
    prefixes = {module_name} | set(submodules)
    corpus = src.corpus

    def interpolated(tok: str) -> bool:
        # `"$entity_type_id.revision_revert_translation_confirm"` or
        # `$id . '_suffix'`: the suffix exists in the source right after a
        # string delimiter, a `}` or a `$var` — an id built at runtime.
        for pre in prefixes:
            for sep in ("_", "."):
                if tok.startswith(pre + sep):
                    suffix = tok[len(pre):]
                    if re.search(
                        r"(?:[\"'}]|\$[A-Za-z_][\w>\-]*(?:\(\))?)" + re.escape(suffix) + r"(?![\w])", corpus
                    ):
                        return True
        return False

    def found(tok: str) -> bool:
        if tok in corpus:
            return True
        # Dotted tokens are often a config object plus a key path written as
        # one id (`media.settings.iframe_domain`); accept when a dotted
        # prefix occurs. A bare `<module>.foo` that never occurs still warns.
        while "." in tok:
            tok = tok.rsplit(".", 1)[0]
            if "." in tok and tok in corpus:
                return True
        return False

    warnings: list[str] = []
    seen: set[str] = set()
    checked = 0
    for md in sorted(d.rglob("*.md")):
        # Audit reports may cite invented ids as examples of errors.
        if md.name.startswith("audit-"):
            continue
        text = md.read_text(encoding="utf-8", errors="replace")
        for m in BACKTICK_ID_RE.finditer(text):
            tok = m.group(1)
            if tok in seen:
                continue
            if not any(
                tok == pre or tok.startswith(pre + "_") or tok.startswith(pre + ".")
                for pre in prefixes
            ):
                continue
            # A sentence asserting the id is ABSENT is not an invention. Note
            # the deliberate `continue` without marking the token seen: if the
            # same id also appears in an affirmative sentence elsewhere, that
            # occurrence still warns (a doc that denies a file exists and then
            # uses it as real is a contradiction worth surfacing).
            # Context = the sentence around the id (docs hard-wrap at ~80
            # columns, so "does not ship a\n`x.libraries.yml`" splits the
            # negation and the id across lines — a line-bounded context
            # missed it), bounded by sentence ends / blank lines / ±200 chars.
            before = text[max(0, m.start() - 200) : m.start()]
            after = text[m.end() : m.end() + 200]
            cut = max(before.rfind("\n\n"), before.rfind(". "), before.rfind(".\n"))
            if cut != -1:
                before = before[cut + 2 :]
            stop = min(
                (i for i in (after.find("\n\n"), after.find(". "), after.find(".\n")) if i != -1),
                default=len(after),
            )
            ctx = before + after[:stop]
            if NEGATION_RE.search(ctx):
                continue
            seen.add(tok)
            checked += 1
            if not found(tok) and not interpolated(tok):
                rel = md.relative_to(d)
                warnings.append(
                    f"{rel}: module-prefixed id `{tok}` not found anywhere in the "
                    "module source (invented identifier, or an id derived at runtime)"
                )
    return warnings, checked


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
            base = ns_roots[ext] / "src"

            # Template reference — a `{…}`/`<…>` placeholder segment follows.
            # `…\Attribute\Views{Type}`: the leaf is a partial name, so the
            # namespace dir above it is what can be verified.
            # `…\Plugin\views\{type}`: the whole match is already the namespace.
            tail = TEMPLATE_TAIL_RE.match(text[m.end() :])
            if tail:
                ns = rest if tail.group(0).startswith("\\") else rest[:-1]
                key = fqcn + "\\{}"
                if not ns or key in seen:
                    continue
                seen.add(key)
                checked += 1
                if not base.joinpath(*ns).is_dir():
                    rel = md.relative_to(d)
                    problems.append(
                        f"{rel}: unresolvable namespace in template reference "
                        f"{fqcn}{{…}} (src/{'/'.join(ns)} does not exist under "
                        f"the {ext} source)"
                    )
                continue

            if fqcn in seen:
                continue
            seen.add(fqcn)
            checked += 1
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
    ap.add_argument(
        "--partial",
        action="store_true",
        help="Wave-1 gate mode: run the content checks on whatever doc files exist "
        "and skip the completeness checks (metadata.json, required files, "
        "submodule counts). Use after wave 1, before the submodule and synthesis "
        "waves, so later explorers ground themselves in already-verified files.",
    )
    ap.add_argument(
        "--module",
        default=None,
        help="Module machine name; required with --partial when metadata.json does "
        "not exist yet (it is read from metadata.json otherwise).",
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
        if args.partial:
            if not args.module:
                print("VERIFY FAILED: --partial without metadata.json needs --module <name>")
                return 1
            meta = {"name": args.module, "files": []}
        else:
            problems.append("metadata.json is missing")
    else:
        try:
            meta = json.loads(meta_path.read_text())
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            problems.append(f"metadata.json does not parse: {exc}")
    meta_ok = isinstance(meta, dict)
    synthetic_meta = args.partial and not meta_path.is_file()

    listed: set[str] = set()
    sub_listed = 0
    documented_subs: set[str] = set()
    skipped_names: list[str] = []
    if meta_ok and not synthetic_meta:
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

    sub_on_disk = sum(1 for f in on_disk if f.startswith("submodules/"))
    if args.partial:
        # Wave-1 gate: only what exists is checked; completeness comes later.
        if not on_disk:
            problems.append("no doc files on disk to check (--partial)")
        for f in sorted(on_disk):
            if (d / f).stat().st_size == 0:
                problems.append(f"empty file: {f}")
    else:
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

        if args.submodules is not None and sub_on_disk != args.submodules:
            problems.append(
                f"submodule files on disk: {sub_on_disk}, expected (GATE SUBMODULES): {args.submodules}"
            )
        if meta_ok and sub_listed != sub_on_disk:
            problems.append(f"submodule files listed: {sub_listed}, on disk: {sub_on_disk}")

    # Doc-only consistency checks (no source needed).
    docs = iter_docs(d)
    counters: list[tuple[str, int]] = []
    count_problems, counts_checked = check_counts(docs)
    problems.extend(count_problems)
    counters.append(("COUNTS_CHECKED", counts_checked))
    overlap_warnings, citations_seen = check_citation_overlap(collect_citations(docs))
    warnings.extend(overlap_warnings)
    counters.append(("CITATIONS_SEEN", citations_seen))

    fqcn_checked: int | None = None
    ids_checked: int | None = None
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
            src = Source(args.module_root)
            fqcn_problems, fqcn_checked = check_fqcns(
                d, args.module_root, meta["name"], submodule_names
            )
            problems.extend(fqcn_problems)
            id_warnings, ids_checked = check_id_strings(
                d, src, meta["name"], submodule_names
            )
            warnings.extend(id_warnings)
            counters.append(("FQCN_CHECKED", fqcn_checked))
            counters.append(("IDS_CHECKED", ids_checked))

            p, w, n = check_cited_spans(docs, src)
            problems.extend(p)
            warnings.extend(w)
            counters.append(("SPANS_CHECKED", n))
            p, n = check_invocation_sites(docs, src)
            problems.extend(p)
            counters.append(("SITES_CHECKED", n))
            p, w, n = check_plugin_ids(docs, src, meta["name"])
            problems.extend(p)
            warnings.extend(w)
            counters.append(("PLUGIN_IDS_CHECKED", n))
            # Libraries and deprecations are owned by the synthesis-wave files
            # (extension-points / ai-integration), so a wave-1 gate cannot
            # judge their coverage yet.
            if not args.partial:
                w, n = check_libraries(docs, src)
                warnings.extend(w)
                counters.append(("LIBRARIES_CHECKED", n))
                p, w, n = check_deprecations(docs, src)
                problems.extend(p)
                warnings.extend(w)
                counters.append(("DEPRECATIONS_CHECKED", n))
            w, n = check_bare_class_names(docs, src, [meta["name"]] + submodule_names)
            warnings.extend(w)
            counters.append(("BARE_CLASSES_CHECKED", n))

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
    for name, value in counters:
        print(f"{name}={value}")
    print("VERIFY OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
