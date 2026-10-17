#!/usr/bin/env python3
"""
Content export adapters with pre-publish gates: draft first, review-gated.

Turns a reviewed Markdown article (with front matter) into the formats a CMS
or automation receiver needs, the way content autopilots such as Outrank do,
but with the safety rails those tools leave out:

* Draft is the default status everywhere. ``publish`` needs an explicit
  ``--status publish`` on the command line, a ``reviewed_by`` front-matter
  field, no unresolved ``[needs source]`` / ``TODO`` / ``TK`` markers and a
  minimum word count (Google's guidance on generative-AI content asks for
  human review and fact-checking before publishing; publishing unreviewed
  pages at scale falls under the scaled-content-abuse spam policy).
* Nothing touches the network without ``--confirm``. Without it every
  network command is a dry run that prints exactly what would be sent.
* Webhook bodies are HMAC-SHA256 signed (``X-Signature-SHA256``). The secret
  and the WordPress Application Password are read from environment variables
  whose *names* are passed on the command line, never from argv values.
* Every outbound URL goes through ``url_safety`` (public hosts only, DNS
  pinned, HTTPS required, no redirects followed with credentials).

Front matter (minimal YAML subset, no PyYAML needed)::

    ---
    title: "How to choose a CRM"
    slug: how-to-choose-a-crm
    meta_description: "A 70-160 character summary shown in search results."
    primary_keyword: how to choose a crm
    tags: [crm, sales]
    image_url: https://example.com/img/crm.png
    image_alt: "Comparison table of three CRMs"
    status: draft            # draft | pending | publish (CLI --status wins)
    reviewed_by: Jane Doe    # required for publish
    canonical: https://example.com/blog/how-to-choose-a-crm
    schema: schema/article.json   # or an inline JSON-LD string
    ---

``title``, ``slug``, ``meta_description``, ``image_url``, ``status`` and
``reviewed_by`` must be text (quote values such as ``title: "1984"``);
``tags`` is a list or a comma-separated string. A ``schema`` path must be a
``.json``/``.jsonld`` JSON-LD file inside the Markdown file's folder.

Webhook events (``event_type`` in the envelope): ``publish_articles`` (the
default for ``--status publish``), ``update_article`` and ``save_draft`` (the
default for draft/pending: a non-publishing event). ``publish_articles`` and
``update_article`` always need the publish gates, whatever the status,
because an Outrank-style receiver may act on the event alone.

Gates (``check``) and why each exists: skills/seo-content-engine/references/publishing-gates.md

Usage:
    python content_export.py check post.md [--for draft|publish] [--aeo] [--json]
    python content_export.py html post.md [--allow-html]
    python content_export.py bundle post.md --out-dir build/ [--status draft]
    python content_export.py webhook post.md --url https://hooks.example.com/content \
        [--secret-env CONTENT_WEBHOOK_SECRET] [--event save_draft|publish_articles|update_article] \
        [--status draft|pending|publish] [--confirm]
    python content_export.py wordpress post.md --site https://example.com --user editor \
        [--app-password-env WP_APP_PASSWORD] [--status draft|pending|publish] [--confirm]
    python content_export.py calendar calendar.json [--indexed-pages 120] \
        [--existing-urls urls.txt] [--query-page gsc_rows.json] [--json]

Exit codes: 0 ok, 1 runtime error (I/O, HTTP failure), 2 blocked by a gate
or refused for safety.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import html as htmllib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlparse

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from seo_store import utc_now  # noqa: E402

STATUSES = ("draft", "pending", "publish")
EVENTS = ("publish_articles", "update_article", "save_draft")
DRAFT_EVENT = "save_draft"
# Events a receiver may act on by publishing, whatever the article's status says.
PUBLISHING_EVENTS = frozenset({"publish_articles", "update_article"})
REQUIRED_FIELDS = ("title", "slug", "meta_description")
META_MIN, META_MAX = 70, 160
TITLE_WARN_MAX = 60
SLUG_WARN_MAX = 75
DEFAULT_MIN_WORDS = 300
LIVE_WP_STATUSES = frozenset({"publish", "future"})
USER_AGENT = "claude-seo-content-export/3.0"
HTTP_TIMEOUT = 30
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_ENV_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]{0,63}$")
# Compared after stripping surrounding punctuation/whitespace, lower-casing,
# dropping apostrophes and collapsing inner whitespace (see reviewer_problem).
_PLACEHOLDER_REVIEWERS = frozenset({
    "todo", "to do", "tbd", "tba", "tbc", "tk", "fixme", "placeholder", "to be determined",
    "to be confirmed", "none", "n/a", "na", "n.a", "null", "nil", "nobody", "no one", "noone",
    "unknown", "pending", "pending review", "not reviewed", "unreviewed", "not yet", "reviewer",
    "reviewer name", "reviewers name", "name", "your name", "full name", "first last",
    "first name last name", "person", "someone", "somebody", "editor", "author", "human", "self",
    "me", "myself", "x", "xx", "xxx", "ai", "llm", "gpt", "chatgpt", "bot", "auto", "automated",
    "automatic", "yes", "no", "true", "false", "ok", "done", "reviewed", "approved",
})

# Markers a draft may carry while it is being researched; none may survive
# to a published page. Scanned in the RENDERED page text with <pre>/<code>
# content excluded (a tutorial may show "{{ var }}" or a TODO comment
# legitimately inside code), plus every text/list front-matter value.
UNRESOLVED_MARKERS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"\[\s*needs\s+sources?\s*\]", re.IGNORECASE), "[needs source]"),
    (re.compile(r"\[\s*citation\s+needed\s*\]", re.IGNORECASE), "[citation needed]"),
    (re.compile(r"\bTODO\b"), "TODO"),
    (re.compile(r"\bTK\b"), "TK"),
    (re.compile(r"\{\{"), "{{"),
)

# Front-matter fields that must be text when present (FrontMatterError otherwise),
# and fields where a bare number is accepted and turned into text.
_TEXT_FIELDS = ("title", "slug", "meta_description", "image_url", "status", "reviewed_by")
_TEXT_OR_NUMBER_FIELDS = ("primary_keyword", "image_alt", "canonical")

# schema: <path> safety (the file's JSON ends up in signed webhook payloads and bundle HTML).
SCHEMA_FILE_MAX_BYTES = 256 * 1024
SCHEMA_FILE_SUFFIXES = (".json", ".jsonld")
_CREDENTIAL_NAME_RE = re.compile(
    r"client[_-]?secret|token|service[_-]?account|credential|secret|password|passwd|"
    r"api[_-]?key|private[_-]?key|^\.env", re.IGNORECASE)


class FrontMatterError(ValueError):
    """Raised when the front matter is outside the supported YAML subset."""


class ExportError(RuntimeError):
    """Raised for refusals and runtime failures with an operator-facing message."""

    def __init__(self, message: str, exit_code: int = 1):
        super().__init__(message)
        self.exit_code = exit_code


# ---------------------------------------------------------------------------
# Front matter: a minimal, dependency-free YAML subset
# ---------------------------------------------------------------------------

_KEY_RE = re.compile(r"^([A-Za-z_][\w-]*)[ \t]*:(?:[ \t]+(.*)|[ \t]*)$")
_INT_RE = re.compile(r"^[-+]?\d+$")
_FLOAT_RE = re.compile(r"^[-+]?(?:\d+\.\d*|\.\d+|\d+(?:\.\d*)?[eE][-+]?\d+)$")
_BLOCK_ITEM_RE = re.compile(r"^[ \t]*-(?:[ \t]+(.*)|[ \t]*)$")


def split_front_matter(text: str) -> tuple[Optional[str], str, int]:
    """Split ``text`` into (front matter or None, body, 1-based body start line)."""
    text = text.lstrip("\ufeff")
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return None, text, 1
    for idx in range(1, len(lines)):
        if lines[idx].strip() in ("---", "..."):
            return "".join(lines[1:idx]), "".join(lines[idx + 1:]), idx + 2
    raise FrontMatterError("front matter opened with '---' but never closed")


def _strip_comment(value: str) -> str:
    """Drop a trailing ' # comment' from an unquoted scalar."""
    m = re.search(r"(^|[ \t])#", value)
    return value[:m.start()].rstrip() if m else value.rstrip()


def _parse_quoted(s: str, lineno: int) -> tuple[str, str]:
    """Parse a quoted scalar at the start of ``s``; return (value, remainder)."""
    quote_char = s[0]
    out: list[str] = []
    i = 1
    while i < len(s):
        c = s[i]
        if quote_char == "'":
            if c == "'":
                if s.startswith("''", i):
                    out.append("'")
                    i += 2
                    continue
                return "".join(out), s[i + 1:]
            out.append(c)
            i += 1
            continue
        if c == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            simple = {"n": "\n", "t": "\t", '"': '"', "\\": "\\", "/": "/", "r": "\r", "0": "\0"}
            if nxt in simple:
                out.append(simple[nxt])
                i += 2
                continue
            if nxt == "u" and re.fullmatch(r"[0-9a-fA-F]{4}", s[i + 2:i + 6] or ""):
                out.append(chr(int(s[i + 2:i + 6], 16)))
                i += 6
                continue
            raise FrontMatterError(f"line {lineno}: unsupported escape \\{nxt}")
        if c == '"':
            return "".join(out), s[i + 1:]
        out.append(c)
        i += 1
    raise FrontMatterError(f"line {lineno}: unterminated quoted string")


def _split_flow_items(inner: str, lineno: int) -> list[str]:
    items, buf, quote_char = [], [], None
    i = 0
    while i < len(inner):
        c = inner[i]
        if quote_char:
            buf.append(c)
            if c == "\\" and quote_char == '"' and i + 1 < len(inner):
                buf.append(inner[i + 1])
                i += 2
                continue
            if c == quote_char:
                quote_char = None
        elif c in ("'", '"'):
            quote_char = c
            buf.append(c)
        elif c in "[]{}":
            raise FrontMatterError(f"line {lineno}: nested collections are not supported")
        elif c == ",":
            items.append("".join(buf).strip())
            buf = []
        else:
            buf.append(c)
        i += 1
    if quote_char:
        raise FrontMatterError(f"line {lineno}: unterminated quoted string in list")
    tail = "".join(buf).strip()
    if tail or items:
        items.append(tail)
    return [it for it in items if it != ""]


def _parse_scalar(raw: str, lineno: int) -> Any:
    s = raw.strip()
    if not s:
        return None
    if s[0] in ("'", '"'):
        value, rest = _parse_quoted(s, lineno)
        rest = rest.strip()
        if rest and not rest.startswith("#"):
            raise FrontMatterError(f"line {lineno}: unexpected text after quoted string: {rest!r}")
        return value
    if s[0] == "[":
        body = _strip_comment(s)
        if not body.endswith("]"):
            raise FrontMatterError(f"line {lineno}: flow list must close with ']' on the same line")
        return [_parse_scalar(item, lineno) for item in _split_flow_items(body[1:-1], lineno)]
    if s[0] == "{":
        raise FrontMatterError(f"line {lineno}: flow mappings are not supported")
    s = _strip_comment(s)
    low = s.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low in ("null", "~"):
        return None
    if _INT_RE.match(s):
        return int(s)
    if _FLOAT_RE.match(s):
        return float(s)
    return s


def _block_scalar(lines: list[str], start: int, indicator: str) -> tuple[str, int]:
    """Collect an indented ``|`` or ``>`` block starting after line ``start``."""
    j = start + 1
    block: list[str] = []
    while j < len(lines) and (not lines[j].strip() or lines[j][:1] in (" ", "\t")):
        block.append(lines[j])
        j += 1
    while block and not block[-1].strip():
        block.pop()
        j -= 1
    indents = [len(b) - len(b.lstrip()) for b in block if b.strip()]
    cut = min(indents) if indents else 0
    body = [b[cut:] if b.strip() else "" for b in block]
    if indicator.startswith("|"):
        text = "\n".join(body)
    else:
        paragraphs, cur = [], []
        for b in body:
            if b:
                cur.append(b.strip())
            else:
                paragraphs.append(" ".join(cur))
                cur = []
        paragraphs.append(" ".join(cur))
        text = "\n".join(p for p in paragraphs)
    if not indicator.endswith("-"):
        text += "\n"  # YAML "clip"/"keep" chomping: one trailing newline
    return text, j


def parse_front_matter(fm_text: str) -> dict:
    """Parse the supported YAML subset into a dict.

    Supported: ``key: value`` with plain, single- or double-quoted scalars,
    booleans (true/false), null, ints, floats, ``[a, b]`` flow lists, ``- item``
    block lists, ``|`` / ``>`` block scalars and ``#`` comments. Nested
    mappings and anchors are refused with a line number rather than guessed.
    """
    result: dict = {}
    lines = fm_text.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        lineno = i + 2  # +1 for 1-based, +1 for the opening '---'
        if not raw.strip() or raw.lstrip().startswith("#"):
            i += 1
            continue
        if raw[:1] in (" ", "\t"):
            raise FrontMatterError(f"line {lineno}: unexpected indentation "
                                   "(nested mappings are not supported)")
        m = _KEY_RE.match(raw.rstrip())
        if not m:
            raise FrontMatterError(f"line {lineno}: expected 'key: value', got {raw.strip()!r}")
        key, rest = m.group(1), (m.group(2) or "").strip()
        if key in result:
            raise FrontMatterError(f"line {lineno}: duplicate key {key!r}")
        if rest[:1] in ("&", "*", "!"):
            raise FrontMatterError(f"line {lineno}: anchors, aliases and tags are not supported")
        if re.fullmatch(r"[|>][+-]?", _strip_comment(rest)):
            value, i = _block_scalar(lines, i, _strip_comment(rest))
            result[key] = value
            continue
        if rest == "" or rest.startswith("#"):
            items: list = []
            j = i + 1
            while j < len(lines):
                if not lines[j].strip():
                    j += 1
                    continue
                im = _BLOCK_ITEM_RE.match(lines[j])
                if not im:
                    break
                items.append(_parse_scalar(im.group(1) or "", j + 2))
                j += 1
            if items:
                result[key] = items
                i = j
                continue
            result[key] = None
            i += 1
            continue
        result[key] = _parse_scalar(rest, lineno)
        i += 1
    return result


# ---------------------------------------------------------------------------
# Markdown -> HTML (built-in converter; python-markdown used when requested)
# ---------------------------------------------------------------------------

_PH_START, _PH_END = "\ue000", "\ue001"
_PH_RE = re.compile(_PH_START + r"(\d+)" + _PH_END)
_ESCAPABLE = set("\\`*_{}[]()#+-.!|<>~\"'")
_SAFE_SCHEMES = frozenset({"http", "https", "mailto", "tel"})
_FENCE_RE = re.compile(r"^( {0,3})(`{3,}|~{3,})[ \t]*([^`\s]*)[^`]*$")
_ATX_RE = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
_HR_RE = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
_UL_RE = re.compile(r"^([ \t]*)([-*+])[ \t]+(.*)$")
_OL_RE = re.compile(r"^([ \t]*)(\d{1,9})([.)])[ \t]+(.*)$")
_BQ_RE = re.compile(r"^ {0,3}>[ ]?(.*)$")
_TABLE_SEP_RE = re.compile(r"^ {0,3}\|?[ \t]*:?-+:?[ \t]*(?:\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$")
_HTML_BLOCK_RE = re.compile(r"^ {0,3}</?[A-Za-z][A-Za-z0-9-]*(?:\s[^>]*)?/?>|^ {0,3}<!--")
_INLINE_TAG_RE = re.compile(r"</?[A-Za-z][A-Za-z0-9-]*(?:\s+[^<>]*?)?/?>|<!--.*?-->", re.DOTALL)
_AUTOLINK_RE = re.compile(r"<((?:https?|mailto):[^\s<>]+)>", re.IGNORECASE)
_STRONG_EM_RE = re.compile(r"\*\*\*(?=\S)(.+?)(?<=\S)\*\*\*")
_STRONG_RE = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*|(?<!\w)__(?=\S)(.+?)(?<=\S)__(?!\w)")
_EM_RE = re.compile(r"\*(?=[^\s*])(.+?)(?<=[^\s*])\*|(?<!\w)_(?=[^\s_])(.+?)(?<=[^\s_])_(?!\w)")


def _esc(text: str) -> str:
    return htmllib.escape(text, quote=False)


def _attr(text: str) -> str:
    return htmllib.escape(text, quote=True)


def safe_url(url: str) -> Optional[str]:
    """Return ``url`` if its scheme is http(s)/mailto/tel or it is relative; else None.

    Whitespace and control characters are removed before the scheme is read,
    because browsers ignore them there (``java\\tscript:`` is ``javascript:``).
    """
    candidate = re.sub(r"[\s\x00-\x20\x7f-\x9f]", "", url or "")
    m = re.match(r"^([A-Za-z][A-Za-z0-9+.\-]*):", candidate)
    if m and m.group(1).lower() not in _SAFE_SCHEMES:
        return None
    return url.strip()


# ---------------------------------------------------------------------------
# HTML sanitizer: one pass over the final HTML of every engine
# ---------------------------------------------------------------------------

# Attributes whose value a browser may load or navigate to.
_URL_ATTRS = frozenset({"href", "src", "action", "formaction", "xlink:href", "data", "poster",
                        "background"})
# SVG animation attributes that can set an href (<animate attributeName="href" to="javascript:...">).
_ANIMATION_VALUE_ATTRS = frozenset({"to", "from", "by", "values"})
_SAFE_ATTR_NAME_RE = re.compile(r"^[a-z_:][-a-z0-9_:.]*$")
_SAFE_TAG_NAME_RE = re.compile(r"^[a-z][a-z0-9:-]*$")
_RAW_TEXT_ELEMENTS = frozenset({"script", "style"})


def _url_value_unsafe(value: str) -> bool:
    """True when ``value`` (as parsed, or entity-decoded once more) is not a safe URL."""
    return any(safe_url(v) is None for v in {value, htmllib.unescape(value)})


class _Sanitizer(HTMLParser):
    """Re-serialize an HTML fragment from parsed tokens, dropping unsafe attributes.

    Output is rebuilt from what the parser understood, so text the parser did
    not see as a tag is escaped instead of passed through. Removed: every
    ``on*`` event-handler attribute, ``srcdoc``, URL attributes whose value
    (entity-decoded, whitespace/control characters ignored) is not
    http(s)/mailto/tel/relative, malformed attribute names, comments that
    contain markup (``<!-->`` / ``--!>`` tricks), declarations and processing
    instructions.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.removed = {"unsafe_url": 0, "event_handler": 0, "malformed": 0, "comment": 0}

    def _tag(self, tag: str, attrs: list, self_closing: bool) -> None:
        raw = self.get_starttag_text() or ""
        if not _SAFE_TAG_NAME_RE.match(tag):
            self.out.append(_esc(raw))
            return
        kept = []
        for name, value in attrs:
            local = name.rsplit(":", 1)[-1]
            if not _SAFE_ATTR_NAME_RE.match(name):
                self.removed["malformed"] += 1
                continue
            if local.startswith("on") or name == "srcdoc":
                self.removed["event_handler"] += 1
                continue
            if value is not None and (
                    (name in _URL_ATTRS and _url_value_unsafe(value))
                    or (name in _ANIMATION_VALUE_ATTRS
                        and any(_url_value_unsafe(part) for part in value.split(";")))):
                self.removed["unsafe_url"] += 1
                continue
            kept.append(name if value is None else f'{name}="{_attr(value)}"')
        self.out.append("<" + " ".join([tag] + kept) + (" />" if self_closing else ">"))

    def handle_starttag(self, tag, attrs):
        self._tag(tag, attrs, False)

    def handle_startendtag(self, tag, attrs):
        self._tag(tag, attrs, True)

    def handle_endtag(self, tag):
        if _SAFE_TAG_NAME_RE.match(tag):
            self.out.append(f"</{tag}>")

    def handle_data(self, data):
        # <script>/<style> bodies are raw text for both this parser and browsers.
        raw = getattr(self, "cdata_elem", None) in _RAW_TEXT_ELEMENTS
        self.out.append(data if raw else _esc(data))

    def handle_comment(self, data):
        if re.search(r"[<>]|--", data) or data.startswith("-"):
            self.removed["comment"] += 1
            return
        self.out.append(f"<!--{data}-->")

    def handle_decl(self, decl):
        pass

    def handle_pi(self, data):
        pass

    def unknown_decl(self, data):
        pass


def sanitize_html(fragment: str) -> tuple[str, list[dict]]:
    """Sanitize an HTML fragment; returns (html, warnings).

    Applied to the final HTML of every engine (built-in, python-markdown,
    ``--allow-html``). Warnings use the gate names ``unsafe_url`` /
    ``unsafe_html`` and carry a ``level`` (``error`` for anything that could
    run script, ``warning`` for removed comments).
    """
    parser = _Sanitizer()
    parser.feed(fragment)
    parser.close()
    r = parser.removed
    warnings = []
    if r["unsafe_url"]:
        warnings.append({"gate": "unsafe_url", "level": "error",
                         "message": f"{r['unsafe_url']} unsafe URL attribute(s) removed (javascript:, "
                                    "data:, vbscript:, file: or similar, including entity-encoded forms)"})
    if r["event_handler"] or r["malformed"]:
        warnings.append({"gate": "unsafe_html", "level": "error",
                         "message": f"{r['event_handler'] + r['malformed']} event-handler (on*), srcdoc or "
                                    "malformed attribute(s) removed"})
    if r["comment"]:
        warnings.append({"gate": "unsafe_html", "level": "warning",
                         "message": f"{r['comment']} HTML comment(s) containing markup removed"})
    return "".join(parser.out), warnings


@dataclass
class RenderContext:
    allow_html: bool = False
    warnings: list = field(default_factory=list)


def _parse_link_target(text: str, i: int) -> Optional[tuple[str, str, Optional[str], int]]:
    """Parse ``[label](url "title")`` starting at text[i] == '['."""
    depth, j = 0, i
    while j < len(text):
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                break
        j += 1
    if j >= len(text) - 1 or text[j + 1] != "(":
        return None
    label = text[i + 1:j]
    k = j + 2
    while k < len(text) and text[k] in " \t":
        k += 1
    if k < len(text) and text[k] == "<":
        end = text.find(">", k)
        if end == -1:
            return None
        url = text[k + 1:end]
        k = end + 1
    else:
        start, parens = k, 0
        while k < len(text) and not text[k].isspace():
            if text[k] == "(":
                parens += 1
            elif text[k] == ")":
                if parens == 0:
                    break
                parens -= 1
            k += 1
        url = text[start:k]
    while k < len(text) and text[k] in " \t":
        k += 1
    title = None
    if k < len(text) and text[k] in "\"'(":
        closer = ")" if text[k] == "(" else text[k]
        end = text.find(closer, k + 1)
        if end == -1:
            return None
        title = text[k + 1:end]
        k = end + 1
        while k < len(text) and text[k] in " \t":
            k += 1
    if k >= len(text) or text[k] != ")":
        return None
    return label, url, title, k + 1


def _plain(label: str) -> str:
    """Markdown label -> plain text (for alt attributes)."""
    label = re.sub(r"\\(.)", r"\1", label)
    return re.sub(r"[*_`]", "", label)


def render_inline(text: str, ctx: RenderContext, _in_link: bool = False) -> str:
    """Render inline Markdown (code, links, images, emphasis) to HTML."""
    text = text.replace(_PH_START, "").replace(_PH_END, "")
    slots: list[str] = []

    def stash(fragment: str) -> str:
        slots.append(fragment)
        return f"{_PH_START}{len(slots) - 1}{_PH_END}"

    buf: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n:
            if text[i + 1] in _ESCAPABLE:
                buf.append(stash(_esc(text[i + 1])))
                i += 2
                continue
            if text[i + 1] == "\n":
                buf.append(stash("<br />\n"))
                i += 2
                continue
        if c == "`":
            run = len(text[i:]) - len(text[i:].lstrip("`"))
            ticks = "`" * run
            close = text.find(ticks, i + run)
            while close != -1 and close + run < n and text[close + run] == "`":
                close = text.find(ticks, close + run + 1)
            if close != -1:
                code = text[i + run:close].replace("\n", " ")
                if len(code) > 2 and code.startswith(" ") and code.endswith(" "):
                    code = code[1:-1]
                buf.append(stash(f"<code>{_esc(code)}</code>"))
                i = close + run
                continue
            buf.append(ticks)
            i += run
            continue
        if c == "!" and i + 1 < n and text[i + 1] == "[":
            parsed = _parse_link_target(text, i + 1)
            if parsed:
                label, url, title, end = parsed
                src = safe_url(url)
                if src is None:
                    ctx.warnings.append({"gate": "unsafe_url", "message": f"image source dropped: {url[:80]!r}"})
                else:
                    title_attr = f' title="{_attr(title)}"' if title else ""
                    buf.append(stash(f'<img src="{_attr(src)}" alt="{_attr(_plain(label))}"{title_attr} />'))
                i = end
                continue
        if c == "[" and not _in_link:
            parsed = _parse_link_target(text, i)
            if parsed:
                label, url, title, end = parsed
                inner = render_inline(label, ctx, _in_link=True)
                href = safe_url(url)
                if href is None:
                    ctx.warnings.append({"gate": "unsafe_url",
                                         "message": f"link removed (unsafe scheme): {url[:80]!r}"})
                    buf.append(stash(inner))
                else:
                    title_attr = f' title="{_attr(title)}"' if title else ""
                    buf.append(stash(f'<a href="{_attr(href)}"{title_attr}>{inner}</a>'))
                i = end
                continue
        if c == "<":
            m = _AUTOLINK_RE.match(text, i)
            if m and not _in_link:
                url = m.group(1)
                buf.append(stash(f'<a href="{_attr(url)}">{_esc(url)}</a>'))
                i = m.end()
                continue
            if ctx.allow_html:
                m = _INLINE_TAG_RE.match(text, i)
                if m:
                    buf.append(stash(m.group(0)))
                    i = m.end()
                    continue
        buf.append(c)
        i += 1

    out = "".join(buf)
    if not ctx.allow_html:
        out = _esc(out)
    out = _STRONG_EM_RE.sub(r"<strong><em>\1</em></strong>", out)
    out = _STRONG_RE.sub(lambda m: f"<strong>{m.group(1) or m.group(2)}</strong>", out)
    out = _EM_RE.sub(lambda m: f"<em>{m.group(1) or m.group(2)}</em>", out)
    out = re.sub(r" {2,}\n", "<br />\n", out)
    while _PH_RE.search(out):
        out = _PH_RE.sub(lambda m: slots[int(m.group(1))], out)
    return out


def _indent_width(line: str) -> int:
    return len(line.expandtabs(4)) - len(line.expandtabs(4).lstrip(" "))


def _list_marker(line: str) -> Optional[tuple[int, bool, str, int]]:
    """Return (indent, ordered, marker, start) for a list item line, else None."""
    if _HR_RE.match(line):
        return None
    m = _UL_RE.match(line)
    if m:
        return _indent_width(line), False, m.group(2), 1
    m = _OL_RE.match(line)
    if m:
        return _indent_width(line), True, m.group(3), int(m.group(2))
    return None


def _item_content(line: str) -> str:
    m = _UL_RE.match(line) or _OL_RE.match(line)
    return m.group(m.lastindex) if m else line.strip()


def _starts_block(line: str, allow_html: bool) -> bool:
    return bool(_FENCE_RE.match(line) or _ATX_RE.match(line) or _HR_RE.match(line)
                or _BQ_RE.match(line) or _list_marker(line)
                or (allow_html and _HTML_BLOCK_RE.match(line)))


def _render_list(items: list[dict], ordered: bool, start: int, ctx: RenderContext) -> str:
    tag = "ol" if ordered else "ul"
    start_attr = f' start="{start}"' if ordered and start != 1 else ""
    parts = [f"<{tag}{start_attr}>"]
    for item in items:
        body = render_inline("\n".join(item["lines"]).strip(), ctx)
        for sub in item["children"]:
            body += "\n" + _render_list(sub["items"], sub["ordered"], sub["start"], ctx)
        parts.append(f"<li>{body}</li>")
    parts.append(f"</{tag}>")
    return "\n".join(parts)


def _parse_list(lines: list[str], i: int, ctx: RenderContext) -> tuple[str, int]:
    base_indent, ordered, marker, start = _list_marker(lines[i])
    items: list[dict] = []
    n = len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            j = i + 1
            while j < n and not lines[j].strip():
                j += 1
            if j < n:
                nxt = _list_marker(lines[j])
                same = nxt and nxt[0] <= base_indent + 1 and nxt[1] == ordered and nxt[2] == marker
                if same or (items and _indent_width(lines[j]) >= base_indent + 2):
                    i = j
                    continue
            break
        mk = _list_marker(line)
        if mk and mk[0] <= base_indent + 1:
            if mk[1] != ordered or mk[2] != marker:
                break
            items.append({"lines": [_item_content(line)], "children": []})
        elif mk and items:
            parent = items[-1]
            if not parent["children"] or parent["children"][-1]["ordered"] != mk[1]:
                parent["children"].append({"ordered": mk[1], "start": mk[3], "items": []})
            parent["children"][-1]["items"].append({"lines": [_item_content(line)], "children": []})
        elif items and (_indent_width(line) >= base_indent + 2 or not _starts_block(line, ctx.allow_html)):
            target = items[-1]
            if target["children"]:
                target = target["children"][-1]["items"][-1]
            target["lines"].append(line.strip())
        else:
            break
        i += 1
    return _render_list(items, ordered, start, ctx), i


def _split_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", s)]


def _parse_table(lines: list[str], i: int, ctx: RenderContext) -> Optional[tuple[str, int]]:
    if i + 1 >= len(lines) or "|" not in lines[i] or not _TABLE_SEP_RE.match(lines[i + 1]):
        return None
    header = _split_row(lines[i])
    seps = _split_row(lines[i + 1])
    if len(header) != len(seps):
        return None
    aligns = []
    for s in seps:
        left, right = s.startswith(":"), s.endswith(":")
        aligns.append("center" if left and right else "right" if right else "left" if left else None)

    def cell(tag: str, text: str, align: Optional[str]) -> str:
        style = f' style="text-align:{align}"' if align else ""
        return f"<{tag}{style}>{render_inline(text, ctx)}</{tag}>"

    out = ["<table>", "<thead>", "<tr>" + "".join(cell("th", h, a) for h, a in zip(header, aligns)) + "</tr>",
           "</thead>", "<tbody>"]
    j = i + 2
    while j < len(lines) and lines[j].strip() and "|" in lines[j]:
        row = _split_row(lines[j])
        row = (row + [""] * len(header))[:len(header)]
        out.append("<tr>" + "".join(cell("td", c, a) for c, a in zip(row, aligns)) + "</tr>")
        j += 1
    out += ["</tbody>", "</table>"]
    return "\n".join(out), j


def _para_line(line: str) -> str:
    """Strip a paragraph line but keep a trailing two-space hard break marker."""
    return line.strip() + ("  " if line.endswith("  ") else "")


def _render_blocks(lines: list[str], ctx: RenderContext) -> list[str]:
    out: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        m = _FENCE_RE.match(line)
        if m:
            indent, fence, lang = len(m.group(1)), m.group(2), m.group(3)
            close_re = re.compile(r"^ {0,3}" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}[ \t]*$")
            code, j = [], i + 1
            while j < n and not close_re.match(lines[j]):
                code.append(lines[j][indent:] if lines[j][:indent].strip() == "" else lines[j])
                j += 1
            cls = f' class="language-{_attr(lang)}"' if lang else ""
            body = _esc("\n".join(code))
            out.append(f"<pre><code{cls}>{body}\n</code></pre>" if code else f"<pre><code{cls}></code></pre>")
            i = j + 1
            continue
        m = _ATX_RE.match(line)
        if m:
            level = len(m.group(1))
            content = re.sub(r"(?:^|[ \t]+)#+[ \t]*$", "", m.group(2) or "").strip()
            out.append(f"<h{level}>{render_inline(content, ctx)}</h{level}>")
            i += 1
            continue
        if _HR_RE.match(line):
            out.append("<hr />")
            i += 1
            continue
        if _BQ_RE.match(line):
            inner, j = [], i
            while j < n and lines[j].strip():
                bm = _BQ_RE.match(lines[j])
                inner.append(bm.group(1) if bm else lines[j])
                j += 1
            out.append("<blockquote>\n" + "\n".join(_render_blocks(inner, ctx)) + "\n</blockquote>")
            i = j
            continue
        mk = _list_marker(line)
        if mk and mk[0] <= 3:
            fragment, i = _parse_list(lines, i, ctx)
            out.append(fragment)
            continue
        table = _parse_table(lines, i, ctx)
        if table:
            out.append(table[0])
            i = table[1]
            continue
        if ctx.allow_html and _HTML_BLOCK_RE.match(line):
            j = i
            while j < n and lines[j].strip():
                j += 1
            out.append("\n".join(lines[i:j]))
            i = j
            continue
        para, j = [_para_line(line)], i + 1
        while j < n and lines[j].strip() and not _starts_block(lines[j], ctx.allow_html):
            if j + 1 < n and "|" in lines[j] and _TABLE_SEP_RE.match(lines[j + 1]):
                break
            para.append(_para_line(lines[j]))
            j += 1
        para[-1] = para[-1].rstrip()
        out.append(f"<p>{render_inline(chr(10).join(para), ctx)}</p>")
        i = j
    return out


def _markdown_package_available() -> bool:
    try:
        import markdown  # noqa: F401
    except ImportError:
        return False
    return True


def markdown_to_html(text: str, allow_html: bool = False, engine: str = "auto") -> tuple[str, dict]:
    """Convert Markdown to an HTML fragment.

    ``engine``: ``builtin`` (deterministic converter in this file), ``markdown``
    (python-markdown, if installed) or ``auto`` (python-markdown when
    importable, else builtin). Raw HTML in the source is escaped unless
    ``allow_html``. Whatever the engine, the final HTML goes through
    ``sanitize_html``: on* event handlers are dropped and javascript:/data:/
    vbscript:/file: URLs are removed, entity-encoded forms included. Returns
    (html, info) where info carries the engine used and renderer warnings.
    """
    ctx = RenderContext(allow_html=allow_html)
    use_pkg = engine == "markdown" or (engine == "auto" and _markdown_package_available())
    if engine == "markdown" and not _markdown_package_available():
        raise ExportError("--engine markdown requested but the 'markdown' package is not installed")
    if use_pkg:
        import markdown as mdpkg
        md = mdpkg.Markdown(extensions=["tables", "fenced_code", "sane_lists"])
        if not allow_html:
            for name in ("html_block",):
                if name in md.preprocessors:
                    md.preprocessors.deregister(name)
            if "html" in md.inlinePatterns:
                md.inlinePatterns.deregister("html")
        html_out = md.convert(text)
        used = "markdown"
    else:
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        html_out = "\n".join(_render_blocks(lines, ctx))
        used = "builtin"
    html_out, sanitizer_warnings = sanitize_html(html_out)
    ctx.warnings.extend(sanitizer_warnings)
    return html_out, {"engine": used, "warnings": ctx.warnings}


class _HTMLStats(HTMLParser):
    """Collect headings, images, links and visible text from an HTML fragment."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.headings: list[tuple[int, str]] = []
        self.images: list[dict] = []
        self.links: list[str] = []
        self.scripts = 0
        self._text: list[str] = []
        self._heading: Optional[list] = None
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if re.fullmatch(r"h[1-6]", tag):
            self._heading = [int(tag[1]), []]
        elif tag == "img":
            self.images.append({"src": a.get("src") or "", "alt": a.get("alt")})
        elif tag == "a":
            self.links.append(a.get("href") or "")
        elif tag in ("pre", "script", "style"):
            self._skip += 1
            if tag == "script":
                self.scripts += 1

    def handle_endtag(self, tag):
        if self._heading and tag == f"h{self._heading[0]}":
            self.headings.append((self._heading[0], " ".join("".join(self._heading[1]).split())))
            self._heading = None
        elif tag in ("pre", "script", "style"):
            self._skip = max(0, self._skip - 1)

    def handle_data(self, data):
        if self._heading is not None:
            self._heading[1].append(data)
        if not self._skip:
            self._text.append(data)

    @property
    def text(self) -> str:
        return " ".join(" ".join(self._text).split())


def html_stats(fragment: str) -> _HTMLStats:
    parser = _HTMLStats()
    parser.feed(fragment)
    parser.close()
    return parser


_BLOCK_TAGS = frozenset({"p", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "br", "hr",
                         "tr", "td", "th", "table", "thead", "tbody", "blockquote", "section",
                         "article", "figure", "figcaption", "dd", "dt", "dl"})
_TEXT_ATTRS = ("alt", "title", "href", "src")


class _RenderedText(HTMLParser):
    """What a published page shows: text outside <pre>/<code>, entities decoded.

    Adjacent inline text is joined without a separator (``TO<b>DO</b>`` reads
    as ``TODO``); block boundaries become newlines. ``alt``/``title``/
    ``href``/``src`` values and comments are included, since they ship too.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._code = 0

    def _start(self, tag, attrs, closes: bool) -> None:
        if tag in ("pre", "code") and not closes:
            self._code += 1
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")
        if not self._code:
            for name, value in attrs:
                if name in _TEXT_ATTRS and value:
                    self.parts.append(f"\n{value}\n")

    def handle_starttag(self, tag, attrs):
        self._start(tag, attrs, False)

    def handle_startendtag(self, tag, attrs):
        self._start(tag, attrs, True)

    def handle_endtag(self, tag):
        if tag in ("pre", "code"):
            self._code = max(0, self._code - 1)
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._code:
            self.parts.append(data)

    def handle_comment(self, data):
        self.parts.append(f"\n{data}\n")

    @property
    def text(self) -> str:
        return "".join(self.parts)


def rendered_text(fragment: str) -> str:
    parser = _RenderedText()
    parser.feed(fragment)
    parser.close()
    return parser.text


def count_words(text: str) -> int:
    return len(re.findall(r"[^\W_]+(?:['\u2019-][^\W_]+)*", text))


def strip_leading_h1_html(fragment: str) -> tuple[str, bool]:
    m = re.match(r"\s*<h1\b[^>]*>.*?</h1>\s*", fragment, re.DOTALL | re.IGNORECASE)
    return (fragment[m.end():], True) if m else (fragment, False)


def strip_leading_h1_markdown(body: str) -> str:
    lines = body.split("\n")
    for idx, line in enumerate(lines):
        if not line.strip():
            continue
        m = _ATX_RE.match(line)
        if m and len(m.group(1)) == 1:
            return "\n".join(lines[:idx] + lines[idx + 1:]).lstrip("\n")
        return body
    return body


# ---------------------------------------------------------------------------
# Documents and gates
# ---------------------------------------------------------------------------

@dataclass
class Document:
    path: Path
    meta: dict
    body: str
    body_start_line: int
    raw: str


def load_document(path: str | Path) -> Document:
    p = Path(path)
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise ExportError(f"cannot read {p}: {exc}") from exc
    fm, body, start = split_front_matter(raw)
    meta = parse_front_matter(fm) if fm is not None else {}
    normalize_meta(meta)
    return Document(path=p, meta=meta, body=body, body_start_line=start, raw=raw)


def _kind(value: Any) -> str:
    if isinstance(value, bool):
        return "a true/false value"
    if isinstance(value, (int, float)):
        return "a number"
    if isinstance(value, list):
        return "a list"
    return type(value).__name__


def normalize_meta(meta: dict) -> dict:
    """Type-check and normalize front matter in place; raise FrontMatterError on wrong types.

    YAML turns ``reviewed_by: false`` into a boolean and ``title: 1984`` into
    a number; stringifying those would let ``false``/``0``/``[]`` pass the
    reviewer gate and crash exporters, so they are refused with a fix hint.
    """
    for key in _TEXT_FIELDS:
        value = meta.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            hint = ("one person's name" if key == "reviewed_by" else "text")
            raise FrontMatterError(f"front matter '{key}' must be {hint} in quotes, got {_kind(value)} "
                                   f"({value!r}); write e.g. {key}: \"...\"")
        meta[key] = value.strip()
    for key in _TEXT_OR_NUMBER_FIELDS:
        value = meta.get(key)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise FrontMatterError(f"front matter '{key}' must be text, got {_kind(value)} ({value!r})")
        meta[key] = str(value).strip()
    tags = meta.get("tags")
    if tags is None:
        meta["tags"] = []
    elif isinstance(tags, str):
        meta["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
    elif isinstance(tags, list):
        clean = []
        for t in tags:
            if t is None:
                continue
            if isinstance(t, bool) or not isinstance(t, (str, int, float)):
                raise FrontMatterError(f"front matter 'tags' items must be text, got {_kind(t)} ({t!r})")
            if str(t).strip():
                clean.append(str(t).strip())
        meta["tags"] = clean
    else:
        raise FrontMatterError(f"front matter 'tags' must be a list such as [crm, sales] or a "
                               f"comma-separated string, got {_kind(tags)} ({tags!r})")
    if meta.get("status"):
        meta["status"] = meta["status"].lower()
    return meta


def reviewer_problem(value: Any) -> Optional[str]:
    """None when ``reviewed_by`` names someone; else why it does not."""
    if not isinstance(value, str):
        return "reviewed_by must name the person who reviewed and fact-checked this draft"
    norm = re.sub(r"^[\W_]+|[\W_]+$", "", value).lower().replace("'", "").replace("’", "")
    norm = " ".join(norm.split())
    if not re.search(r"[^\W\d_]", norm):
        return "reviewed_by must name the person who reviewed and fact-checked this draft"
    if norm in _PLACEHOLDER_REVIEWERS:
        return (f"reviewed_by {value!r} is a placeholder; it must name the person who reviewed and "
                "fact-checked this draft")
    return None


def _config_dirs() -> list[Path]:
    dirs = [Path.home() / ".config"]
    if os.environ.get("XDG_CONFIG_HOME"):
        dirs.append(Path(os.environ["XDG_CONFIG_HOME"]))
    out = []
    for d in dirs:
        try:
            out.append(d.resolve())
        except (OSError, RuntimeError):
            continue
    return out


def _schema_path(doc: Document, text: str) -> tuple[Optional[Path], Optional[str]]:
    """Resolve a ``schema:`` path, refusing anything that could leak local secrets.

    The file's JSON is embedded in signed webhook payloads and bundle HTML,
    and front matter can be drafted by an LLM from untrusted research, so a
    path must stay inside the Markdown file's folder (no absolute paths, no
    ``..`` or symlinks out of it), end in .json/.jsonld, and not look like a
    credential or config file.
    """
    if Path(text).is_absolute() or text.startswith("~"):
        return None, (f"schema path {text!r} must be relative to the Markdown file's folder "
                      "(absolute and home paths are refused)")
    base = doc.path.parent.resolve()
    try:
        candidate = (base / text).resolve()
    except (OSError, RuntimeError) as exc:
        return None, f"cannot resolve schema path {text!r}: {exc}"
    if not candidate.is_relative_to(base):
        return None, (f"schema path {text!r} leaves the Markdown file's folder; keep the JSON-LD file "
                      "next to the document or in a subfolder (no '..' or symlinks out of it)")
    if candidate.suffix.lower() not in SCHEMA_FILE_SUFFIXES or Path(text).suffix.lower() not in SCHEMA_FILE_SUFFIXES:
        return None, f"schema path {text!r} must name a .json or .jsonld file"
    rel_parts = candidate.relative_to(base).parts
    names = set(rel_parts) | {p for p in Path(text).parts if p not in (".", "..")}
    if any(n.startswith(".") for n in names):
        return None, f"schema path {text!r} points into a hidden file or folder; refused"
    if any(_CREDENTIAL_NAME_RE.search(n) for n in names):
        return None, (f"schema path {text!r} looks like a credential file (secret/token/credentials/"
                      "service account/.env); refused")
    if any(candidate.is_relative_to(d) for d in _config_dirs()):
        return None, f"schema path {text!r} is inside a config folder (~/.config); refused"
    if not candidate.is_file():
        return None, f"schema file not found: {text}"
    return candidate, None


def _looks_like_jsonld(data: Any) -> bool:
    blocks = data if isinstance(data, list) else [data]
    return bool(blocks) and all(isinstance(b, dict) and ("@context" in b or "@type" in b) for b in blocks)


def resolve_schema(doc: Document) -> tuple[Optional[Any], Optional[str]]:
    """Return (parsed JSON-LD or None, error message or None)."""
    value = doc.meta.get("schema")
    if value in (None, ""):
        return None, None
    if not isinstance(value, str):
        return None, "schema must be a JSON-LD string or a path to a .json file"
    text = value.strip()
    from_file = not text.startswith(("{", "["))
    if from_file:
        candidate, problem = _schema_path(doc, text)
        if problem:
            return None, problem
        try:
            with open(candidate, "rb") as fh:
                data = fh.read(SCHEMA_FILE_MAX_BYTES + 1)
        except OSError as exc:
            return None, f"cannot read schema file {text}: {exc}"
        if len(data) > SCHEMA_FILE_MAX_BYTES:
            return None, f"schema file {text} is larger than {SCHEMA_FILE_MAX_BYTES // 1024} KiB; refused"
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            return None, f"schema file {text} is not UTF-8 text"
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"schema is not valid JSON: {exc.msg} (line {exc.lineno}, column {exc.colno})"
    if from_file and not _looks_like_jsonld(parsed):
        return None, (f"schema file {value.strip()} is not JSON-LD (every object needs @context or "
                      "@type); refused")
    return parsed, None


def _unfenced_lines(doc: Document) -> list[tuple[int, str]]:
    """(file line number, text) for body lines outside fenced code blocks."""
    out, fence = [], ""
    for offset, line in enumerate(doc.body.split("\n")):
        if fence:
            if re.fullmatch(re.escape(fence[0]) + "{" + str(len(fence)) + ",}", line.strip()):
                fence = ""
            continue
        m = _FENCE_RE.match(line)
        if m:
            fence = m.group(2)
            continue
        out.append((doc.body_start_line + offset, line))
    return out


def _code_free_lines(doc: Document) -> list[tuple[int, str]]:
    """(file line number, text) for body lines outside fenced code, inline code removed."""
    return [(n, re.sub(r"`+[^`]*`+", "", line)) for n, line in _unfenced_lines(doc)]


def _front_matter_strings(meta: dict):
    for key, value in meta.items():
        if isinstance(value, str):
            yield key, value
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    yield key, item


def _marker_findings(doc: Document, html_body: str) -> list[dict]:
    """Unresolved markers in the rendered page text and in front matter.

    The decision uses the rendered HTML (what a reader sees; <pre>/<code>
    excluded), so a malformed code span that renders as plain text cannot
    hide a marker. Line numbers are best-effort pointers into the Markdown.
    """
    findings: list[dict] = []
    text = rendered_text(html_body)
    code_free = _code_free_lines(doc)
    unfenced = [(n, re.sub(r"\\(.)", r"\1", t)) for n, t in _unfenced_lines(doc)]
    pairs = [(a[0], a[1] + "\n" + b[1]) for a, b in zip(unfenced, unfenced[1:]) if b[0] == a[0] + 1]
    for pattern, label in UNRESOLVED_MARKERS:
        if not pattern.search(text):
            continue
        lines = ([n for n, t in code_free if pattern.search(t)]
                 or [n for n, t in unfenced if pattern.search(t)]
                 or [n for n, t in pairs if pattern.search(t)][:1])
        if lines:
            findings.extend(_finding("unresolved_marker", "error", "publish",
                                     f"unresolved marker {label!r}", line=n) for n in lines)
        else:
            findings.append(_finding("unresolved_marker", "error", "publish",
                                     f"unresolved marker {label!r} in the rendered page"))
    seen = set()
    for key, value in _front_matter_strings(doc.meta):
        for pattern, label in UNRESOLVED_MARKERS:
            if (key, label) not in seen and pattern.search(value):
                seen.add((key, label))
                findings.append(_finding("unresolved_marker", "error", "publish",
                                         f"unresolved marker {label!r} in front matter '{key}'"))
    return findings


def _finding(gate: str, level: str, scope: str, message: str, line: Optional[int] = None) -> dict:
    f = {"gate": gate, "level": level, "scope": scope, "message": message}
    if line is not None:
        f["line"] = line
    return f


def check_document(doc: Document, for_: str = "draft", min_words: int = DEFAULT_MIN_WORDS,
                   allow_html: bool = False, engine: str = "auto") -> dict:
    """Run the export gates. ``for_`` is 'draft' or 'publish' (publish = draft + more)."""
    meta = doc.meta
    findings: list[dict] = []
    html_body, info = markdown_to_html(doc.body, allow_html=allow_html, engine=engine)
    stats = html_stats(html_body)
    words = count_words(stats.text)

    for key in REQUIRED_FIELDS:
        if not (meta.get(key) or "").strip():
            findings.append(_finding("required_field", "error", "draft", f"front matter field '{key}' is required"))
    if not (meta.get("primary_keyword") or "").strip():
        findings.append(_finding("required_field", "warning", "draft",
                                 "no primary_keyword: optimizer and placement checks cannot run"))
    slug = (meta.get("slug") or "").strip()
    if slug and not _SLUG_RE.match(slug):
        findings.append(_finding("slug_format", "error", "draft",
                                 f"slug {slug!r} must be kebab-case (a-z, 0-9, single hyphens)"))
    elif slug and len(slug) > SLUG_WARN_MAX:
        findings.append(_finding("slug_format", "warning", "draft", f"slug is {len(slug)} chars; keep it short"))
    md = (meta.get("meta_description") or "").strip()
    if md and not META_MIN <= len(md) <= META_MAX:
        findings.append(_finding("meta_description_length", "error", "draft",
                                 f"meta_description is {len(md)} chars; must be {META_MIN}-{META_MAX}"))
    title = (meta.get("title") or "").strip()
    if title and len(title) > TITLE_WARN_MAX:
        findings.append(_finding("title_length", "warning", "draft",
                                 f"title is {len(title)} chars; search results usually truncate "
                                 f"past ~{TITLE_WARN_MAX}"))
    status = meta.get("status")
    if status and status not in STATUSES:
        findings.append(_finding("status_value", "error", "draft",
                                 f"status {status!r} must be one of {', '.join(STATUSES)}"))

    h1s = [h for h in stats.headings if h[0] == 1]
    h1_total = len(h1s) if h1s else (1 if title else 0)
    if h1_total != 1:
        detail = "no H1 and no title" if h1_total == 0 else f"{len(h1s)} H1 headings in the body"
        findings.append(_finding("single_h1", "error", "draft", f"exactly one H1 required ({detail})"))

    for img in stats.images:
        if not (img.get("alt") or "").strip():
            findings.append(_finding("image_alt", "error", "draft",
                                     f"image without alt text: {img.get('src', '')[:80]}"))
    if (meta.get("image_url") or "").strip():
        if not (meta.get("image_alt") or "").strip():
            findings.append(_finding("image_alt", "error", "draft", "image_url is set but image_alt is empty"))
        if not re.match(r"^https?://", meta["image_url"].strip(), re.IGNORECASE):
            findings.append(_finding("url_format", "error", "draft", "image_url must be an absolute http(s) URL"))
    canonical = (meta.get("canonical") or "").strip()
    if canonical and not re.match(r"^https?://[^\s/]+", canonical, re.IGNORECASE):
        findings.append(_finding("url_format", "error", "draft", "canonical must be an absolute http(s) URL"))

    schema, schema_err = resolve_schema(doc)
    if schema_err:
        findings.append(_finding("schema_json", "error", "draft", schema_err))
    elif schema is not None:
        blocks = schema if isinstance(schema, list) else [schema]
        if not all(isinstance(b, dict) and b.get("@type") for b in blocks):
            findings.append(_finding("schema_json", "warning", "draft", "schema parses but a block lacks @type"))

    for w in info["warnings"]:
        findings.append(_finding(w["gate"], w.get("level", "error"), "draft", w["message"]))
    if not allow_html and any(re.search(r"<[A-Za-z][A-Za-z0-9-]*[\s>/]", t) for _, t in _code_free_lines(doc)):
        findings.append(_finding("raw_html", "warning", "draft",
                                 "raw HTML found; it is escaped unless --allow-html is passed"))
    if stats.scripts:
        findings.append(_finding("raw_html", "warning", "draft", "body contains <script>; most CMSs strip it"))

    if for_ == "publish":
        problem = reviewer_problem(meta.get("reviewed_by"))
        if problem:
            findings.append(_finding("human_review", "error", "publish", problem))
        findings.extend(_marker_findings(doc, html_body))
        if words < min_words:
            findings.append(_finding("word_floor", "error", "publish",
                                     f"{words} words is below the {min_words}-word publish floor"))

    errors = sum(1 for f in findings if f["level"] == "error")
    return {
        "file": str(doc.path),
        "for": for_,
        "status": "blocked" if errors else "pass",
        "errors": errors,
        "warnings": sum(1 for f in findings if f["level"] == "warning"),
        "findings": findings,
        "stats": {"word_count": words, "h1_in_body": len(h1s), "images": len(stats.images),
                  "links": len(stats.links), "engine": info["engine"]},
    }


def citability_sections(doc: Document, allow_html: bool = False, engine: str = "auto") -> dict:
    """Informational AEO pass: score each H2 section with citability_scorer.score_passage.

    The scorer's own CLI only reads live URLs; this lets a draft be scored before
    it is published. Never a gate: the AEO score is reported, not enforced.
    """
    from citability_scorer import score_passage
    fragment, _ = markdown_to_html(doc.body, allow_html=allow_html, engine=engine)
    sections, heading, buf = [], "Introduction", []

    def flush() -> None:
        text = html_stats("".join(buf)).text
        if count_words(text) >= 20:
            r = score_passage(text, heading)
            sections.append({"heading": heading, "score": r["total_score"], "grade": r["grade"],
                             "word_count": r["word_count"]})

    for part in re.split(r"(<h2\b[^>]*>.*?</h2>)", fragment, flags=re.DOTALL):
        m = re.fullmatch(r"<h2\b[^>]*>(.*?)</h2>", part, flags=re.DOTALL)
        if m:
            flush()
            heading, buf = html_stats(m.group(1)).text or "Untitled", []
        else:
            buf.append(part)
    flush()
    avg = round(sum(x["score"] for x in sections) / len(sections), 1) if sections else None
    return {"average_citability": avg, "sections": sections,
            "below_50": [x["heading"] for x in sections if x["score"] < 50],
            "note": "AEO citability (scripts/citability_scorer.py); reported separately, never blended "
                    "into SEO scores and never a publishing gate"}


# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------

def article_id(slug: str) -> str:
    """Stable article id: first 16 hex chars of sha256(slug)."""
    return hashlib.sha256(slug.encode("utf-8")).hexdigest()[:16]


def effective_status(cli_status: Optional[str], doc: Document) -> tuple[str, list[str]]:
    """CLI --status wins; front matter alone never escalates to publish."""
    notices = []
    status = cli_status or "draft"
    fm = doc.meta.get("status")
    if cli_status is None and fm in ("pending", "publish"):
        notices.append(f"front matter requests status '{fm}'; exporting as 'draft'. "
                       f"Pass --status {fm} to apply it (publish gates apply to publish).")
    return status, notices


def build_article(doc: Document, status: str, allow_html: bool = False, engine: str = "auto") -> dict:
    """Outrank-compatible article object plus review metadata."""
    body_md = strip_leading_h1_markdown(doc.body)
    html_body, info = markdown_to_html(doc.body, allow_html=allow_html, engine=engine)
    html_body, stripped = strip_leading_h1_html(html_body)
    schema, _ = resolve_schema(doc)
    created = doc.meta.get("created_at") or doc.meta.get("date") or utc_now()
    slug = doc.meta.get("slug") or ""
    article = {
        "id": article_id(slug),
        "title": doc.meta.get("title") or "",
        "content_markdown": body_md.strip() + "\n",
        "content_html": html_body.strip(),
        "meta_description": doc.meta.get("meta_description") or "",
        "image_url": doc.meta.get("image_url") or None,
        "image_alt": doc.meta.get("image_alt") or None,
        "slug": slug,
        "tags": list(doc.meta.get("tags") or []),
        "created_at": str(created),
        "status": status,
        "reviewed_by": doc.meta.get("reviewed_by") or None,
        "primary_keyword": doc.meta.get("primary_keyword") or None,
        "canonical": doc.meta.get("canonical") or None,
        "schema_jsonld": schema,
    }
    return {"article": article, "engine": info["engine"], "leading_h1_stripped": stripped}


def build_payload(article: dict, event: str) -> dict:
    """Webhook envelope: {event_type, timestamp, data: {articles: [...]}}."""
    return {"event_type": event, "timestamp": utc_now(), "data": {"articles": [article]}}


def payload_bytes(payload: dict) -> bytes:
    """Canonical body bytes: the exact bytes that are signed and sent."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_body(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def read_secret_env(name: str, purpose: str) -> Optional[str]:
    """Read a secret from the environment variable NAME (never from argv)."""
    if not _ENV_NAME_RE.match(name or ""):
        raise ExportError(f"{purpose}: pass the NAME of an environment variable (e.g. "
                          f"CONTENT_WEBHOOK_SECRET), not the secret itself", exit_code=2)
    value = os.environ.get(name)
    return value if value else None


def _require_https_public(url: str, label: str) -> str:
    from url_safety import validate_url
    parsed = urlparse(url or "")
    if parsed.scheme.lower() != "https":
        raise ExportError(f"{label} must use https:// (credentials and signed content are never sent "
                          "over plain HTTP)", exit_code=2)
    if not validate_url(url):
        raise ExportError(f"{label} refused by url_safety (private, loopback or metadata host): {url}",
                          exit_code=2)
    return url


def default_event(status: str) -> str:
    """publish_articles only for an explicit publish; drafts get the non-publishing save_draft."""
    return "publish_articles" if status == "publish" else DRAFT_EVENT


def resolve_event(event: Optional[str], status: str, notices: list[str]) -> str:
    """Pick the event (default by status), validate it and note a publishing event on a draft."""
    event = event or default_event(status)
    if event not in EVENTS:
        raise ExportError(f"--event must be one of {', '.join(EVENTS)}", exit_code=2)
    if event in PUBLISHING_EVENTS and status != "publish":
        notices.append(f"event '{event}' can make the receiver publish whatever 'status' says, so the "
                       f"publish gates apply; use --event {DRAFT_EVENT} to send a draft")
    return event


def gate_for_status(status: str, event: Optional[str] = None) -> str:
    """Which gate set an export needs.

    Publish status, and the publishing events (publish_articles, update_article)
    whatever the status, need the publish gates: a receiver keyed on
    ``event_type`` may publish the article without looking at ``status``.
    """
    return "publish" if status == "publish" or event in PUBLISHING_EVENTS else "draft"


def _default_session_factory():
    from url_safety import safe_requests_session
    return safe_requests_session


def send_webhook(url: str, body: bytes, headers: dict,
                 session_factory: Optional[Callable] = None) -> dict:
    """POST ``body`` to ``url`` over a DNS-pinned session; never follows redirects."""
    factory = session_factory or _default_session_factory()
    try:
        with factory(url) as session:
            resp = session.post(url, data=body, headers=headers, timeout=HTTP_TIMEOUT,
                                allow_redirects=False)
    except Exception as exc:  # url_safety errors, connection errors
        raise ExportError(f"webhook request failed: {type(exc).__name__}: {exc}") from exc
    ok = 200 <= resp.status_code < 300
    result = {"sent": True, "http_status": resp.status_code, "ok": ok,
              "response_excerpt": (getattr(resp, "text", "") or "")[:500]}
    if not ok:
        hint = " (redirects are not followed; use the final URL)" if 300 <= resp.status_code < 400 else ""
        raise ExportError(f"webhook receiver returned HTTP {resp.status_code}{hint}: "
                          f"{result['response_excerpt'][:200]}")
    return result


def run_webhook(doc: Document, url: str, secret_env: str, event: Optional[str], cli_status: Optional[str],
                confirm: bool, allow_unsigned: bool = False, allow_html: bool = False,
                engine: str = "auto", min_words: int = DEFAULT_MIN_WORDS,
                session_factory: Optional[Callable] = None) -> dict:
    """Build, gate and (with ``confirm``) send the signed webhook.

    ``event`` None picks the default for the status: ``publish_articles`` for
    publish, ``save_draft`` otherwise.
    """
    if event is not None and event not in EVENTS:
        raise ExportError(f"--event must be one of {', '.join(EVENTS)}", exit_code=2)
    _require_https_public(url, "--url")
    status, notices = effective_status(cli_status, doc)
    event = resolve_event(event, status, notices)
    gates = gate_for_status(status, event)
    check = check_document(doc, gates, min_words=min_words, allow_html=allow_html, engine=engine)
    secret = read_secret_env(secret_env, "--secret-env")
    built = build_article(doc, status, allow_html=allow_html, engine=engine)
    payload = build_payload(built["article"], event)
    body = payload_bytes(payload)
    headers = {"Content-Type": "application/json; charset=utf-8", "User-Agent": USER_AGENT,
               "X-Content-Event": event}
    if secret:
        headers["X-Signature-SHA256"] = sign_body(body, secret)
    result = {
        "command": "webhook", "url": url, "event": event, "status": status, "gates": gates,
        "check": check, "signed": bool(secret), "secret_env": secret_env,
        "headers": headers, "body_bytes": len(body), "engine": built["engine"],
        "leading_h1_stripped": built["leading_h1_stripped"], "notices": notices,
        "dry_run": not confirm,
    }
    if check["status"] == "blocked":
        result["refused"] = f"{gates} gates failed; nothing sent"
        result["payload"] = payload
        raise _Refusal(result)
    if not secret:
        msg = (f"environment variable {secret_env} is not set: the payload would be unsigned")
        if confirm and not allow_unsigned:
            result["refused"] = msg + "; set the secret or pass --allow-unsigned"
            raise _Refusal(result)
        notices.append(msg)
    if not confirm:
        result["payload"] = payload
        notices.append("dry run: nothing was sent. Re-run with --confirm after the operator approves.")
        return result
    result["response"] = send_webhook(url, body, headers, session_factory=session_factory)
    return result


class _Refusal(Exception):
    """Carries a structured result for a gate/safety refusal (exit code 2)."""

    def __init__(self, result: dict):
        super().__init__(result.get("refused", "refused"))
        self.result = result


# ---------------------------------------------------------------------------
# WordPress REST API (Application Passwords)
# ---------------------------------------------------------------------------

def _wp_api_base(site: str) -> str:
    return site.rstrip("/") + "/wp-json/wp/v2"


def _basic_auth(user: str, password: str) -> str:
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def _scrub(text: str, secret: Optional[str]) -> str:
    if secret:
        text = text.replace(secret, "[redacted]")
        text = text.replace(secret.replace(" ", ""), "[redacted]")
    return text


def _wp_error(resp, secret: Optional[str]) -> str:
    try:
        data = resp.json()
        detail = data.get("message") or data.get("code") or ""
    except Exception:
        detail = (getattr(resp, "text", "") or "")[:200]
    hint = ""
    if resp.status_code in (401, 403):
        hint = (" Check the user name, that the Application Password is valid, and that the user "
                "can edit posts.")
    elif resp.status_code == 404:
        hint = " Is the REST API reachable at /wp-json/ on this site?"
    elif 300 <= resp.status_code < 400:
        hint = (" The site redirects and redirects are not followed with credentials; pass the final "
                "site URL (check www vs non-www and any subdirectory).")
    return _scrub(f"HTTP {resp.status_code}: {detail}.{hint}", secret)


def wordpress_post_body(article: dict, status: str, tag_ids: list[int]) -> dict:
    body = {"title": article["title"], "content": article["content_html"],
            "excerpt": article["meta_description"], "slug": article["slug"], "status": status}
    if tag_ids:
        body["tags"] = tag_ids
    return body


def run_wordpress(doc: Document, site: str, user: str, password_env: str, cli_status: Optional[str],
                  confirm: bool, allow_html: bool = False, engine: str = "auto",
                  min_words: int = DEFAULT_MIN_WORDS, session_factory: Optional[Callable] = None) -> dict:
    _require_https_public(site, "--site")
    if not user:
        raise ExportError("--user is required", exit_code=2)
    status, notices = effective_status(cli_status, doc)
    gates = gate_for_status(status)
    check = check_document(doc, gates, min_words=min_words, allow_html=allow_html, engine=engine)
    password = read_secret_env(password_env, "--app-password-env")
    built = build_article(doc, status, allow_html=allow_html, engine=engine)
    article = built["article"]
    api = _wp_api_base(site)
    slug = article["slug"]
    result = {
        "command": "wordpress", "site": site, "api": api, "status": status, "gates": gates,
        "check": check, "user": user, "password_env": password_env,
        "password_available": bool(password), "slug": slug, "engine": built["engine"],
        "leading_h1_stripped": built["leading_h1_stripped"], "notices": notices,
        "dry_run": not confirm,
        "not_sent": ["meta_description is sent as the post excerpt; SEO-plugin meta fields "
                     "(Yoast/Rank Math) are not REST-writable by default",
                     "image_url is not uploaded; set the featured image in WordPress",
                     "schema JSON-LD and canonical are not sent (WordPress strips <script> for most "
                     "roles; set them through your SEO plugin)"],
    }
    if check["status"] == "blocked":
        result["refused"] = f"{gates} gates failed; nothing sent"
        raise _Refusal(result)
    plan = {"lookup": f"GET {api}/posts?slug={slug}&status=any&context=edit",
            "then": f"POST {api}/posts/<id> if exactly one returned post has slug {slug!r}, "
                    f"else POST {api}/posts",
            "body": wordpress_post_body(article, status, [])}
    if not confirm:
        result["plan"] = plan
        if not password:
            notices.append(f"environment variable {password_env} is not set; --confirm will fail")
        notices.append("dry run: no request was made. Re-run with --confirm after the operator approves.")
        return result
    if not password:
        result["refused"] = f"environment variable {password_env} is not set"
        raise _Refusal(result)

    factory = session_factory or _default_session_factory()
    headers = {"Authorization": _basic_auth(user, password), "User-Agent": USER_AGENT,
               "Accept": "application/json"}
    try:
        with factory(api) as session:
            resp = session.get(f"{api}/posts", params={"slug": slug, "status": "any", "context": "edit"},
                               headers=headers, timeout=HTTP_TIMEOUT, allow_redirects=False)
            if resp.status_code != 200:
                raise ExportError("slug lookup failed: " + _wp_error(resp, password))
            existing = resp.json() or []
            if not isinstance(existing, list):
                raise ExportError("slug lookup returned an unexpected response shape")
            # Only an exact slug match may be updated: a plugin or a lenient lookup can
            # return other posts, and updating one of those would overwrite the wrong article.
            matches = [p for p in existing if isinstance(p, dict) and p.get("slug") == slug]
            others = [p for p in existing if not (isinstance(p, dict) and p.get("slug") == slug)]
            if others:
                ids = ", ".join(str(p.get("id")) if isinstance(p, dict) else "?" for p in others)
                notices.append(f"slug lookup also returned {len(others)} post(s) whose slug is not "
                               f"{slug!r} (ids {ids}); ignored")
            if len(matches) > 1:
                ids = ", ".join(str(p.get("id")) for p in matches)
                result["refused"] = (f"{len(matches)} posts share slug {slug!r} (ids {ids}); "
                                     "resolve the duplicate in WordPress first")
                raise _Refusal(result)
            post = matches[0] if matches else None
            current = ((post or {}).get("status") or "").lower()
            if post and current in LIVE_WP_STATUSES and status != "publish":
                # Publish gates already ran when status == "publish".
                result["refused"] = (f"post {post.get('id')} is '{current}': updating it changes live "
                                     "content. Re-run with --status publish after review "
                                     "(publish gates apply); a live post is never downgraded.")
                raise _Refusal(result)
            tag_ids, unresolved = [], []
            for tag in article["tags"]:
                tag_slug = re.sub(r"[^a-z0-9]+", "-", tag.lower()).strip("-")
                tresp = session.get(f"{api}/tags", params={"slug": tag_slug}, headers=headers,
                                    timeout=HTTP_TIMEOUT, allow_redirects=False)
                found = tresp.json() if tresp.status_code == 200 else []
                if isinstance(found, list) and found:
                    tag_ids.append(int(found[0]["id"]))
                else:
                    unresolved.append(tag)
            if unresolved:
                notices.append("tags not found in WordPress (not created): " + ", ".join(unresolved))
            body = wordpress_post_body(article, status, tag_ids)
            if post:
                presp = session.post(f"{api}/posts/{int(post['id'])}", json=body, headers=headers,
                                     timeout=HTTP_TIMEOUT, allow_redirects=False)
                action = "updated"
            else:
                presp = session.post(f"{api}/posts", json=body, headers=headers,
                                     timeout=HTTP_TIMEOUT, allow_redirects=False)
                action = "created"
            if presp.status_code not in (200, 201):
                raise ExportError(f"{action[:-1]} failed: " + _wp_error(presp, password))
            data = presp.json() or {}
    except (ExportError, _Refusal):
        raise
    except Exception as exc:
        raise ExportError(_scrub(f"WordPress request failed: {type(exc).__name__}: {exc}", password)) from exc
    result.update({"action": action, "post_id": data.get("id"), "link": data.get("link"),
                   "wp_status": data.get("status"), "tags_resolved": tag_ids})
    return result


# ---------------------------------------------------------------------------
# Standalone bundle
# ---------------------------------------------------------------------------

def _jsonld_script(schema: Any) -> str:
    text = json.dumps(schema, ensure_ascii=False, indent=2)
    text = text.replace("</", "<\\/").replace("<!--", "<\\!--")
    return f'<script type="application/ld+json">\n{text}\n</script>'


def standalone_html(doc: Document, status: str, allow_html: bool = False, engine: str = "auto") -> str:
    fragment, _ = markdown_to_html(doc.body, allow_html=allow_html, engine=engine)
    stats = html_stats(fragment)
    meta = doc.meta
    title = meta.get("title") or ""
    head = ['<meta charset="utf-8" />',
            '<meta name="viewport" content="width=device-width, initial-scale=1" />',
            f"<title>{_esc(title)}</title>"]
    if meta.get("meta_description"):
        head.append(f'<meta name="description" content="{_attr(meta["meta_description"])}" />')
    if meta.get("canonical"):
        head.append(f'<link rel="canonical" href="{_attr(meta["canonical"])}" />')
    if status != "publish":
        head.append("<!-- not yet approved for publishing: keep out of the index -->")
        head.append('<meta name="robots" content="noindex" />')
    schema, _ = resolve_schema(doc)
    if schema is not None:
        head.append(_jsonld_script(schema))
    heading = "" if any(h[0] == 1 for h in stats.headings) else f"<h1>{_esc(title)}</h1>\n"
    lang = _attr(str(meta.get("lang") or "en"))
    return ("<!doctype html>\n" f'<html lang="{lang}">\n<head>\n' + "\n".join(head) +
            "\n</head>\n<body>\n<article>\n" + heading + fragment + "\n</article>\n</body>\n</html>\n")


def run_bundle(doc: Document, out_dir: str, cli_status: Optional[str], event: Optional[str] = None,
               allow_html: bool = False, engine: str = "auto",
               min_words: int = DEFAULT_MIN_WORDS) -> dict:
    status, notices = effective_status(cli_status, doc)
    event = resolve_event(event, status, notices)
    gates = gate_for_status(status, event)
    check = check_document(doc, gates, min_words=min_words, allow_html=allow_html, engine=engine)
    result = {"command": "bundle", "status": status, "event": event, "gates": gates, "check": check,
              "notices": notices}
    if check["status"] == "blocked":
        result["refused"] = f"{gates} gates failed; nothing written"
        raise _Refusal(result)
    slug = doc.meta["slug"]  # validated kebab-case by the gates: safe as a filename
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    built = build_article(doc, status, allow_html=allow_html, engine=engine)
    files = {
        "html": out / f"{slug}.html",
        "json": out / f"{slug}.json",
        "md": out / f"{slug}.md",
    }
    files["html"].write_text(standalone_html(doc, status, allow_html, engine), encoding="utf-8")
    files["json"].write_text(json.dumps(build_payload(built["article"], event), ensure_ascii=False,
                                        indent=2, sort_keys=True) + "\n", encoding="utf-8")
    files["md"].write_text(doc.raw, encoding="utf-8")
    result["files"] = {k: str(v) for k, v in files.items()}
    return result


# ---------------------------------------------------------------------------
# Content calendar validation + volume guard
# ---------------------------------------------------------------------------

CALENDAR_REQUIRED = ("date", "keyword", "intent", "funnel", "article_type", "expected_length",
                     "instructions", "quality_questions", "status")
CALENDAR_STATUSES = ("planned", "briefed", "drafted", "in_review", "approved", "exported",
                     "published", "skipped")
INTENTS = ("informational", "commercial", "transactional", "navigational")
FUNNELS = ("TOFU", "MOFU", "BOFU")
# Volume guard thresholds (see references/content-calendar-format.md).
VOLUME_WARN_SHARE = 0.25     # new pages in any 30 days > 25% of indexed pages
VOLUME_HIGH_SHARE = 1.0      # new pages in any 30 days >= the whole indexed site
CADENCE_WARN_MULTIPLE = 2.0  # any ISO week above 2x the profile cadence
RANKING_PAGE_MIN_IMPRESSIONS = 50


def _norm_kw(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (text or "").lower()))


def _slug_of(item: dict) -> str:
    if item.get("slug"):
        return str(item["slug"]).strip()
    target = str(item.get("target_url") or "")
    return urlparse(target).path.rstrip("/").rsplit("/", 1)[-1] if target else ""


def validate_calendar(cal: dict, indexed_pages: Optional[int] = None,
                      cadence_per_week: Optional[float] = None,
                      existing_urls: Optional[list[str]] = None,
                      query_page_rows: Optional[list[dict]] = None) -> dict:
    """Validate a content calendar and run the scaled-content volume guard.

    ``indexed_pages`` / ``cadence_per_week`` default to the calendar's own values.
    """
    indexed_pages = indexed_pages or cal.get("indexed_pages")
    cadence_per_week = cadence_per_week or cal.get("cadence_per_week")
    findings: list[dict] = []
    items = cal.get("items")
    if not isinstance(items, list) or not items:
        return {"status": "blocked", "errors": 1, "warnings": 0,
                "findings": [_finding("calendar_items", "error", "calendar", "calendar has no items")]}
    seen_kw: dict[str, int] = {}
    seen_slug: dict[str, int] = {}
    dated_new: list[date] = []
    for idx, item in enumerate(items):
        where = f"item {idx} ({item.get('keyword', '?')!r})"
        for key in CALENDAR_REQUIRED:
            if item.get(key) in (None, "", []):
                findings.append(_finding("calendar_field", "error", "calendar", f"{where}: '{key}' is required"))
        if not (item.get("slug") or item.get("target_url")):
            findings.append(_finding("calendar_field", "error", "calendar",
                                     f"{where}: 'slug' or 'target_url' is required"))
        slug = _slug_of(item)
        if item.get("slug") and not _SLUG_RE.match(str(item["slug"])):
            findings.append(_finding("slug_format", "error", "calendar", f"{where}: slug must be kebab-case"))
        if item.get("intent") and item["intent"] not in INTENTS:
            findings.append(_finding("calendar_field", "error", "calendar",
                                     f"{where}: intent must be one of {INTENTS}"))
        if item.get("funnel") and item["funnel"] not in FUNNELS:
            findings.append(_finding("calendar_field", "error", "calendar",
                                     f"{where}: funnel must be one of {FUNNELS}"))
        if item.get("status") and item["status"] not in CALENDAR_STATUSES:
            findings.append(_finding("calendar_field", "error", "calendar",
                                     f"{where}: status must be one of {', '.join(CALENDAR_STATUSES)}"))
        kind = item.get("kind", "new")
        if kind not in ("new", "refresh"):
            findings.append(_finding("calendar_field", "error", "calendar", f"{where}: kind must be new|refresh"))
        try:
            when = date.fromisoformat(str(item.get("date")))
        except ValueError:
            when = None
            if item.get("date"):
                findings.append(_finding("calendar_field", "error", "calendar", f"{where}: date must be YYYY-MM-DD"))
        if item.get("status") == "skipped":
            continue
        kw = _norm_kw(item.get("keyword", ""))
        if kw:
            if kw in seen_kw:
                findings.append(_finding("calendar_duplicate", "error", "calendar",
                                         f"{where}: keyword duplicates item {seen_kw[kw]} (cannibalization risk)"))
            seen_kw.setdefault(kw, idx)
        if slug:
            if slug in seen_slug:
                findings.append(_finding("calendar_duplicate", "error", "calendar",
                                         f"{where}: slug duplicates item {seen_slug[slug]}"))
            seen_slug.setdefault(slug, idx)
        if kind == "new" and when:
            dated_new.append(when)
        if kind == "new" and existing_urls and slug:
            for url in existing_urls:
                if urlparse(url).path.rstrip("/").rsplit("/", 1)[-1] == slug:
                    findings.append(_finding("existing_url", "warning", "calendar",
                                             f"{where}: slug already exists on the site ({url}); "
                                             "refresh it instead of creating a new page"))
                    break
        if kind == "new" and query_page_rows and kw:
            ranking = [r for r in query_page_rows
                       if _norm_kw(r.get("query", "")) == kw
                       and float(r.get("impressions") or 0) >= RANKING_PAGE_MIN_IMPRESSIONS]
            if ranking:
                best = max(ranking, key=lambda r: float(r.get("impressions") or 0))
                findings.append(_finding("cannibalization_precheck", "warning", "calendar",
                                         f"{where}: {best.get('page')} already gets "
                                         f"{int(float(best.get('impressions') or 0))} "
                                         f"impressions for this query (avg position {best.get('position')}); "
                                         "consider refreshing that page instead of a new one"))

    weeks: dict[str, int] = {}
    for d in dated_new:
        iso = d.isocalendar()
        key = f"{iso[0]}-W{iso[1]:02d}"
        weeks[key] = weeks.get(key, 0) + 1
    volume: dict = {"new_pages": len(dated_new), "new_pages_per_iso_week": dict(sorted(weeks.items())),
                    "indexed_pages": indexed_pages, "cadence_per_week": cadence_per_week}
    if cadence_per_week:
        for wk, count in sorted(weeks.items()):
            if count > CADENCE_WARN_MULTIPLE * cadence_per_week:
                findings.append(_finding("volume_guard", "warning", "calendar",
                                         f"{wk}: {count} new pages vs a cadence of {cadence_per_week}/week"))
    if dated_new:
        dated_new.sort()
        peak, lo = 0, 0
        for hi in range(len(dated_new)):
            while dated_new[hi] - dated_new[lo] >= timedelta(days=30):
                lo += 1
            peak = max(peak, hi - lo + 1)
        volume["peak_new_pages_30d"] = peak
        if indexed_pages:
            share = peak / max(1, indexed_pages)
            volume["peak_share_of_indexed"] = round(share, 3)
            if share >= VOLUME_HIGH_SHARE:
                findings.append(_finding("volume_guard", "warning", "calendar",
                                         f"HIGH: {peak} new pages within 30 days would at least double a site of "
                                         f"{indexed_pages} indexed pages; scaled-content-abuse risk. Slow down."))
            elif share > VOLUME_WARN_SHARE:
                findings.append(_finding("volume_guard", "warning", "calendar",
                                         f"{peak} new pages within 30 days is {share:.0%} of {indexed_pages} indexed "
                                         "pages; make sure each page has unique value and human review"))
        else:
            findings.append(_finding("volume_guard", "warning", "calendar",
                                     "indexed page count unknown; pass --indexed-pages to size the volume guard"))
    errors = sum(1 for f in findings if f["level"] == "error")
    return {"status": "blocked" if errors else "pass", "errors": errors,
            "warnings": sum(1 for f in findings if f["level"] == "warning"),
            "findings": findings, "volume": volume, "items": len(items)}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

LIMITATIONS = [
    "Markdown support is a documented subset (no reference-style links, footnotes or setext headings).",
    "The webhook shape mirrors Outrank's publish_articles/update_article envelope; save_draft (the default "
    "event for draft/pending exports) is this tool's own non-publishing event. Confirm field names and "
    "how your receiver treats each event_type.",
    "Gates check structure and review state, not truth: claims still need content_verify.py and a human.",
]


def _emit(obj: dict, as_json: bool, text: str) -> None:
    if as_json:
        print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))
    else:
        print(text)


def _check_text(check: dict) -> str:
    lines = [f"{check['file']}: {check['status'].upper()} for {check['for']} "
             f"({check['errors']} errors, {check['warnings']} warnings, {check['stats']['word_count']} words)"]
    for f in check["findings"]:
        where = f" (line {f['line']})" if "line" in f else ""
        lines.append(f"  [{f['level']}] {f['gate']}: {f['message']}{where}")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Draft-first content export with publishing gates")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def common(p, status=True):
        p.add_argument("file", help="Markdown file with front matter")
        p.add_argument("--allow-html", action="store_true", help="Pass raw HTML through (escaped by default)")
        p.add_argument("--engine", choices=("auto", "builtin", "markdown"), default="auto")
        p.add_argument("--min-words", type=int, default=DEFAULT_MIN_WORDS, help="Publish word floor")
        p.add_argument("--json", action="store_true")
        if status:
            p.add_argument("--status", choices=STATUSES, default=None,
                           help="Export status (default draft; front matter never escalates)")

    p = sub.add_parser("check", help="Run the export gates")
    common(p, status=False)
    p.add_argument("--for", dest="for_", choices=("draft", "publish"), default="draft")
    p.add_argument("--aeo", action="store_true",
                   help="Also report per-section AEO citability (informational, not a gate)")

    p = sub.add_parser("html", help="Print the HTML fragment")
    common(p, status=False)

    event_help = ("Envelope event_type (default: publish_articles for --status publish, else "
                  f"{DRAFT_EVENT}); publish_articles/update_article always need the publish gates")
    p = sub.add_parser("bundle", help="Write <slug>.html/.json/.md")
    common(p)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--event", choices=EVENTS, default=None, help=event_help)

    p = sub.add_parser("webhook", help="Send (or dry-run) a signed webhook")
    common(p)
    p.add_argument("--url", required=True)
    p.add_argument("--secret-env", default="CONTENT_WEBHOOK_SECRET",
                   help="NAME of the env var holding the HMAC secret")
    p.add_argument("--event", choices=EVENTS, default=None, help=event_help)
    p.add_argument("--allow-unsigned", action="store_true")
    p.add_argument("--confirm", action="store_true", help="Actually send (default: dry run)")

    p = sub.add_parser("wordpress", help="Create/update a WordPress post by slug")
    common(p)
    p.add_argument("--site", required=True)
    p.add_argument("--user", required=True)
    p.add_argument("--app-password-env", default="WP_APP_PASSWORD",
                   help="NAME of the env var holding the Application Password")
    p.add_argument("--confirm", action="store_true", help="Actually send (default: dry run)")

    p = sub.add_parser("calendar", help="Validate a content calendar + volume guard")
    p.add_argument("file")
    p.add_argument("--indexed-pages", type=int)
    p.add_argument("--cadence", type=float, help="Planned new pages per week (default: calendar value)")
    p.add_argument("--existing-urls", help="Text file, one site URL per line")
    p.add_argument("--query-page", help="JSON list of GSC query x page rows")
    p.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    try:
        if args.cmd == "calendar":
            try:
                cal = json.loads(Path(args.file).read_text(encoding="utf-8"))
                urls = ([u.strip() for u in Path(args.existing_urls).read_text(encoding="utf-8").splitlines()
                         if u.strip()] if args.existing_urls else None)
                qp = json.loads(Path(args.query_page).read_text(encoding="utf-8")) if args.query_page else None
            except (OSError, json.JSONDecodeError) as exc:
                raise ExportError(f"cannot read input: {exc}") from exc
            if isinstance(qp, dict):
                qp = qp.get("rows") or qp.get("query_page") or []
            res = validate_calendar(cal, indexed_pages=args.indexed_pages, cadence_per_week=args.cadence,
                                    existing_urls=urls, query_page_rows=qp)
            res.update({"command": "calendar", "file": args.file})
            text = "\n".join([f"{args.file}: {res['status'].upper()} ({res['errors']} errors, "
                              f"{res['warnings']} warnings)"] +
                             [f"  [{f['level']}] {f['gate']}: {f['message']}" for f in res["findings"]])
            _emit(res, args.json, text)
            return 2 if res["status"] == "blocked" else 0

        doc = load_document(args.file)
        if args.cmd == "check":
            res = check_document(doc, args.for_, min_words=args.min_words,
                                 allow_html=args.allow_html, engine=args.engine)
            res["data_sources"] = ["local Markdown file"]
            res["limitations"] = LIMITATIONS
            text = _check_text(res)
            if args.aeo:
                res["aeo"] = citability_sections(doc, allow_html=args.allow_html, engine=args.engine)
                text += (f"\n  AEO citability (informational): average {res['aeo']['average_citability']}"
                         + "".join(f"\n    {x['score']:>3} {x['grade']}  {x['heading']}"
                                   for x in res["aeo"]["sections"]))
            _emit(res, args.json, text)
            return 2 if res["status"] == "blocked" else 0
        if args.cmd == "html":
            fragment, info = markdown_to_html(doc.body, allow_html=args.allow_html, engine=args.engine)
            _emit({"html": fragment, **info}, args.json, fragment)
            return 0
        if args.cmd == "bundle":
            res = run_bundle(doc, args.out_dir, args.status, args.event, args.allow_html, args.engine,
                             args.min_words)
            _emit(res, args.json, "wrote " + ", ".join(res["files"].values()))
            return 0
        if args.cmd == "webhook":
            res = run_webhook(doc, args.url, args.secret_env, args.event, args.status, args.confirm,
                              allow_unsigned=args.allow_unsigned, allow_html=args.allow_html,
                              engine=args.engine, min_words=args.min_words)
            verb = "DRY RUN" if res["dry_run"] else f"SENT (HTTP {res['response']['http_status']})"
            _emit(res, args.json, f"{verb}: {res['event']} {res['status']} -> {res['url']} "
                                  f"({res['body_bytes']} bytes, signed={res['signed']})"
                                  + "".join(f"\n  note: {n}" for n in res["notices"]))
            return 0
        if args.cmd == "wordpress":
            res = run_wordpress(doc, args.site, args.user, args.app_password_env, args.status,
                                args.confirm, allow_html=args.allow_html, engine=args.engine,
                                min_words=args.min_words)
            if res["dry_run"]:
                text = f"DRY RUN: {res['plan']['lookup']}\n  then {res['plan']['then']}"
            else:
                text = f"{res['action'].upper()} post {res['post_id']} ({res['wp_status']}): {res.get('link')}"
            _emit(res, args.json, text + "".join(f"\n  note: {n}" for n in res["notices"]))
            return 0
    except _Refusal as ref:
        res = ref.result
        if args.json:
            print(json.dumps(res, indent=2, ensure_ascii=False, default=str))
        else:
            print(f"REFUSED: {res.get('refused')}", file=sys.stderr)
            if res.get("check"):
                print(_check_text(res["check"]), file=sys.stderr)
        return 2
    except (ExportError, FrontMatterError) as exc:
        code = getattr(exc, "exit_code", 1)
        if getattr(args, "json", False):
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return code
    return 1


if __name__ == "__main__":
    sys.exit(main())
