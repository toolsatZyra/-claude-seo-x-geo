"""
Tests for scripts/content_export.py — front matter, Markdown -> HTML,
publishing gates, bundle output, signed webhooks, WordPress adapter and the
content-calendar volume guard.

No network: HTTP goes through injected fake sessions, URLs that must be
refused are IP literals (refused before any socket opens), and secrets come
from monkeypatched environment variables.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import content_export as ce  # noqa: E402

PY = sys.executable
SCRIPT = str(SCRIPTS / "content_export.py")
PUBLIC_HOOK = "https://93.184.215.14/hooks/content"   # public IP literal: no DNS lookup needed
PUBLIC_WP = "https://93.184.215.14"
SLUG = "how-to-choose-a-crm"

BODY_WORDS = " ".join(f"Sentence {i} explains how small teams compare CRM plans." for i in range(60))

GOOD_DOC = f"""---
title: "How to choose a CRM"
slug: how-to-choose-a-crm
meta_description: "A practical guide to choosing a CRM for a small team: requirements, pricing and vendor questions."
primary_keyword: how to choose a crm
tags: [crm, sales]
image_url: https://example.com/img/crm.png
image_alt: "Three CRM dashboards side by side"
status: draft
reviewed_by: Jane Doe
canonical: https://example.com/blog/how-to-choose-a-crm
schema: '{{"@context": "https://schema.org", "@type": "Article", "headline": "How to choose a CRM </script>"}}'
---

# How to choose a CRM

{BODY_WORDS}

## Requirements

- Contacts
- Pipelines

![Pipeline view](https://example.com/img/pipeline.png)
"""


def write(tmp_path, text, name="post.md"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def doc_with(tmp_path, **overrides):
    fm, body, _ = ce.split_front_matter(GOOD_DOC)
    meta = ce.parse_front_matter(fm)
    body = overrides.pop("_body", body)
    lines = []
    for key, value in {**meta, **overrides}.items():
        if value is None:
            continue
        if isinstance(value, list):
            lines.append(f"{key}: [{', '.join(value)}]")
        else:
            lines.append(f"{key}: {json.dumps(value) if isinstance(value, str) else value}")
    text = "---\n" + "\n".join(lines) + "\n---\n" + body
    return ce.load_document(write(tmp_path, text))


# ---------------------------------------------------------------------------
# Front matter
# ---------------------------------------------------------------------------

def test_front_matter_subset():
    fm = """title: "Quoted \\"title\\" with: colon"   # comment
single: 'it''s single'
plain: value with # not-a-comment-without-space#x
tags: [a, "b, c", 'd']
list:
  - one
  - "two"
count: 3
ratio: 0.5
flag: true
off: FALSE
nothing: null
folded: >
  line one
  line two
literal: |
  keep
  lines
empty:
"""
    meta = ce.parse_front_matter(fm)
    assert meta["title"] == 'Quoted "title" with: colon'
    assert meta["single"] == "it's single"
    assert meta["plain"] == "value with"
    assert meta["tags"] == ["a", "b, c", "d"]
    assert meta["list"] == ["one", "two"]
    assert (meta["count"], meta["ratio"], meta["flag"], meta["off"]) == (3, 0.5, True, False)
    assert meta["nothing"] is None and meta["empty"] is None
    assert meta["folded"] == "line one line two\n"
    assert meta["literal"] == "keep\nlines\n"


@pytest.mark.parametrize("bad,msg", [
    ("a: 1\na: 2", "duplicate key"),
    ("parent:\n  child: x", "nested"),
    ("x: {a: 1}", "flow mappings"),
    ("x: [a, [b]]", "nested collections"),
    ('x: "unterminated', "unterminated"),
    ("x: &anchor 1", "anchors"),
    ("just text", "expected 'key: value'"),
])
def test_front_matter_refuses_unsupported_yaml(bad, msg):
    with pytest.raises(ce.FrontMatterError, match=msg):
        ce.parse_front_matter(bad)


def test_unclosed_front_matter():
    with pytest.raises(ce.FrontMatterError):
        ce.split_front_matter("---\ntitle: x\n# body")


def test_no_front_matter_is_fine():
    fm, body, start = ce.split_front_matter("# Title\n\nText")
    assert fm is None and body.startswith("# Title") and start == 1


# ---------------------------------------------------------------------------
# Markdown -> HTML (built-in engine)
# ---------------------------------------------------------------------------

def md(text, **kw):
    return ce.markdown_to_html(text, engine="builtin", **kw)[0]


def test_headings_emphasis_code_and_links():
    out = md("## Title ##\n\nA **bold** and *em* and ***both*** with `<b>code</b>` and "
             "[link](https://x.example/a_(b) \"T\") plus snake_case_word.")
    assert "<h2>Title</h2>" in out
    assert "<strong>bold</strong>" in out and "<em>em</em>" in out
    assert "<strong><em>both</em></strong>" in out
    assert "<code>&lt;b&gt;code&lt;/b&gt;</code>" in out
    assert '<a href="https://x.example/a_(b)" title="T">link</a>' in out
    assert "snake_case_word" in out


def test_fenced_code_is_escaped_and_not_parsed():
    out = md("```html\n<script>alert(1)</script>\n**not bold**\n```")
    assert out.startswith('<pre><code class="language-html">&lt;script&gt;')
    assert "<strong>" not in out


def test_raw_html_escaped_by_default_and_passed_with_allow_html():
    assert md('<div class="x">hi</div>') == '<p>&lt;div class="x"&gt;hi&lt;/div&gt;</p>'
    assert '<div class="x">hi</div>' in md('<div class="x">hi</div>', allow_html=True)
    assert "<span>ok</span>" in md("inline <span>ok</span>", allow_html=True)
    assert "&lt;span&gt;" in md("inline <span>ok</span>")


@pytest.mark.parametrize("src", ["[x](javascript:alert(1))", "[x](JaVaScRiPt:alert(1))",
                                 "[x]( javascript:alert(1))", "![a](data:image/png;base64,AAA)",
                                 "[x](vbscript:msgbox)"])
def test_unsafe_urls_are_dropped(src):
    html_out, info = ce.markdown_to_html(src, engine="builtin")
    assert "javascript:" not in html_out.lower() and "data:" not in html_out and "vbscript" not in html_out
    assert info["warnings"]


def test_unsafe_attributes_neutralized_even_with_allow_html():
    out = md('<a href="javascript:alert(1)">x</a> <img src=\'data:x\'>', allow_html=True)
    assert "javascript:" not in out and "data:x" not in out


def test_lists_nested_ordered_start_and_lazy_continuation():
    out = md("3. three\n4. four\n   - nested a\n   - nested b\n5. five\n\n- a\n- b\ncontinued")
    assert '<ol start="3">' in out
    assert "<li>four\n<ul>\n<li>nested a</li>\n<li>nested b</li>\n</ul></li>" in out
    assert "<li>b\ncontinued</li>" in out


def test_blockquote_hr_table_and_hard_break():
    out = md("> quote **b**\n> more\n\n---\n\n| A | B |\n|:--|--:|\n| 1 | 2 \\| 3 |\n\nline one  \nline two")
    assert "<blockquote>\n<p>quote <strong>b</strong>\nmore</p>\n</blockquote>" in out
    assert "<hr />" in out
    assert '<th style="text-align:left">A</th><th style="text-align:right">B</th>' in out
    assert '<td style="text-align:right">2 | 3</td>' in out
    assert "line one<br />\nline two" in out


def test_images_and_autolinks():
    out = md('![Alt *text*](https://e.example/i.png "Cap") <https://e.example>')
    assert '<img src="https://e.example/i.png" alt="Alt text" title="Cap" />' in out
    assert '<a href="https://e.example">https://e.example</a>' in out


def test_backslash_escapes():
    assert md(r"\*not em\* and \[x\]") == "<p>*not em* and [x]</p>"


def test_engine_markdown_requires_package(monkeypatch):
    monkeypatch.setattr(ce, "_markdown_package_available", lambda: False)
    with pytest.raises(ce.ExportError):
        ce.markdown_to_html("x", engine="markdown")
    assert ce.markdown_to_html("x", engine="auto")[1]["engine"] == "builtin"


# ---------------------------------------------------------------------------
# HTML sanitizer (final pass for every engine)
# ---------------------------------------------------------------------------

DANGEROUS_HTML = [
    '<p><a href="&#106;avascript:alert(1)">x</a></p>',          # python-markdown keeps entities
    '<p><a href="&#106avascript:alert(1)">x</a></p>',
    '<p><a href="&#x6A;avascript:alert(1)">x</a></p>',
    '<p><a href="javascript&colon;alert(1)">x</a></p>',
    '<p><a href="java&#x09;script:alert(1)">x</a></p>',
    '<p><a href="java\nscript:alert(1)">x</a></p>',
    '<p><a href="  JaVaScRiPt:alert(1)">x</a></p>',
    '<p><a href="&amp;#106;avascript:alert(1)">x</a></p>',      # double-encoded
    '<a href=javascript:alert(1)>x</a>',
    '<img src="data:text/html,<script>alert(1)</script>">',
    '<img src="vbscript:msgbox(1)">',
    '<form action="javascript:alert(1)"><button formaction="file:///etc/passwd">b</button></form>',
    '<svg><a xlink:href="javascript:alert(1)">x</a></svg>',
    '<svg><a><animate attributeName="href" values="0;javascript:alert(1)"/>x</a></svg>',
    '<img src=x onerror=alert(1)>',
    '<IMG SRC=x ONERROR=alert(1)>',
    '<a href="https://ok.example"onclick="alert(1)">x</a>',
    '<a/href="javascript:alert(1)"/onmouseover=alert(1)>x</a>',
    '<body onload=alert(1)>',
    '<iframe srcdoc="&lt;img src=x onerror=alert(1)&gt;"></iframe>',
    '<!--> <a href="javascript:alert(1)">x</a> -->',            # HTML5 ends this comment at "<!-->"
    '<p>ok</p>\n<img src=x onerror=alert(1)',                  # unterminated tag would merge with the wrapper
]


@pytest.mark.parametrize("html_in", DANGEROUS_HTML)
def test_sanitizer_removes_scriptable_attributes(html_in):
    out, warnings = ce.sanitize_html(html_in)
    low = out.lower()
    for bad in ("javascript", "vbscript", "data:", "file:", "onerror", "onclick", "onload", "onmouseover",
                "srcdoc", "alert"):
        assert bad not in low, (bad, out)
    assert warnings or "<a" not in low and "<img" not in low


def test_sanitizer_keeps_safe_html_byte_for_byte():
    safe = ('<h2>Title</h2>\n<p>A <a href="https://ok.example/?a=1&amp;b=2" title="T &amp; &quot;q&quot;">link</a>, '
            '<code>&lt;b&gt;</code> &amp; <img src="/i.png" alt="Alt" /> AT&amp;T</p>\n'
            '<pre><code class="language-js">if (a &lt; b) {}\n</code></pre>\n<ol start="3">\n<li>x</li>\n</ol>\n'
            '<table>\n<tr><th style="text-align:left">A</th></tr>\n</table>\n<hr />\n<!--more-->')
    out, warnings = ce.sanitize_html(safe)
    assert out == safe and warnings == []


@pytest.mark.parametrize("src", ['<a href="&#106;avascript:alert(1)">x</a>', '<a href="javascript&colon;x">x</a>',
                                 '<a href="java&#x09;script:alert(1)">x</a>', "<img src=x onerror=alert(1)>",
                                 '<p onclick="alert(1)">hi</p>'])
def test_allow_html_is_sanitized_and_blocks_the_draft(tmp_path, src):
    out, info = ce.markdown_to_html(src, allow_html=True, engine="builtin")
    assert "javascript" not in out.lower() and "onerror" not in out and "onclick" not in out
    assert info["warnings"] and all(w["level"] == "error" for w in info["warnings"])
    doc = doc_with(tmp_path, _body="# T\n\n" + src + "\n\n" + BODY_WORDS)
    res = ce.check_document(doc, "draft", allow_html=True, engine="builtin")
    assert res["status"] == "blocked"
    assert {f["gate"] for f in res["findings"]} & {"unsafe_url", "unsafe_html"}


def test_python_markdown_engine_output_is_sanitized(monkeypatch):
    """The 'markdown' package is not installed here: a stand-in returns what it would emit."""
    import types

    class FakeMarkdown:
        def __init__(self, extensions=None):
            self.preprocessors, self.inlinePatterns = {}, {}

        def convert(self, text):
            return ('<p><a href="&#106;avascript:alert(1)">x</a> <a href="java&#x09;script:alert(1)">y</a> '
                    '<img alt="a" src="x" onerror="alert(1)" /></p>')

    monkeypatch.setitem(sys.modules, "markdown", types.SimpleNamespace(Markdown=FakeMarkdown))
    monkeypatch.setattr(ce, "_markdown_package_available", lambda: True)
    out, info = ce.markdown_to_html("irrelevant", engine="markdown")
    assert info["engine"] == "markdown"
    assert out == '<p><a>x</a> <a>y</a> <img alt="a" src="x" /></p>'
    assert {w["gate"] for w in info["warnings"]} == {"unsafe_url", "unsafe_html"}


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------

def gates(result):
    return {(f["gate"], f["level"]) for f in result["findings"]}


def test_good_doc_passes_draft_and_publish(tmp_path):
    doc = ce.load_document(write(tmp_path, GOOD_DOC))
    assert ce.check_document(doc, "draft", engine="builtin")["status"] == "pass"
    res = ce.check_document(doc, "publish", engine="builtin")
    assert res["status"] == "pass", res["findings"]
    assert res["stats"]["h1_in_body"] == 1


def test_required_fields_slug_and_meta_length(tmp_path):
    doc = doc_with(tmp_path, slug="How_To", meta_description="too short", title=None)
    res = ce.check_document(doc, "draft", engine="builtin")
    g = gates(res)
    assert ("required_field", "error") in g
    assert ("slug_format", "error") in g
    assert ("meta_description_length", "error") in g
    assert res["status"] == "blocked"


def test_multiple_h1_blocked_and_title_counts_when_body_has_none(tmp_path):
    two = doc_with(tmp_path, _body="# One\n\n# Two\n\n" + BODY_WORDS)
    assert ("single_h1", "error") in gates(ce.check_document(two, "draft", engine="builtin"))
    none = doc_with(tmp_path, _body="## Section\n\n" + BODY_WORDS)
    assert ("single_h1", "error") not in gates(ce.check_document(none, "draft", engine="builtin"))


def test_image_alt_and_schema_json_gates(tmp_path):
    doc = doc_with(tmp_path, schema="{not json", image_alt=None,
                   _body="# T\n\n![](https://e.example/x.png)\n\n" + BODY_WORDS)
    g = gates(ce.check_document(doc, "draft", engine="builtin"))
    assert ("image_alt", "error") in g
    assert ("schema_json", "error") in g


def test_schema_from_file_path(tmp_path):
    (tmp_path / "schema.json").write_text('{"@context": "https://schema.org", "@type": "Article"}')
    doc = doc_with(tmp_path, schema="schema.json")
    schema, err = ce.resolve_schema(doc)
    assert err is None and schema["@type"] == "Article"
    missing = doc_with(tmp_path, schema="nope.json")
    assert ("schema_json", "error") in gates(ce.check_document(missing, "draft", engine="builtin"))


def test_publish_requires_reviewer_markers_resolved_and_word_floor(tmp_path):
    body = ("# T\n\nA claim [needs source] and TODO here. {{ placeholder }}\n\n"
            "```\nTODO in code is fine {{ x }}\n```\n\nShort.")
    doc = doc_with(tmp_path, reviewed_by="TBD", _body=body)
    res = ce.check_document(doc, "publish", engine="builtin")
    g = gates(res)
    assert ("human_review", "error") in g
    assert ("word_floor", "error") in g
    markers = [f for f in res["findings"] if f["gate"] == "unresolved_marker"]
    assert {m["message"] for m in markers} == {"unresolved marker '[needs source]'",
                                              "unresolved marker 'TODO'", "unresolved marker '{{'"}
    assert all(m["line"] == markers[0]["line"] for m in markers)   # all on the prose line, none in code
    assert ce.check_document(doc, "draft", engine="builtin")["status"] == "pass"


@pytest.mark.parametrize("value", ["false", "true", "[]", "0", "3.5", '[""]', "[Jane Doe]", "\n  -",
                                   "\n  - Jane Doe"])
def test_reviewed_by_must_be_text_not_a_yaml_value(tmp_path, value):
    path = write(tmp_path, GOOD_DOC.replace("reviewed_by: Jane Doe", f"reviewed_by: {value}"))
    with pytest.raises(ce.FrontMatterError, match="reviewed_by"):
        ce.load_document(path)
    r = subprocess.run([PY, SCRIPT, "check", str(path), "--for", "publish"], capture_output=True, text=True)
    assert r.returncode == 1 and "reviewed_by" in r.stderr and "Traceback" not in r.stderr


@pytest.mark.parametrize("value", ["tbd.", "TBD", "'TODO'", "'n/a'", "N/A.", "'[Reviewer Name]'", "'<name>'",
                                   "pending", "'Pending review'", "'-'", "'--'", "'???'", "'123'", "'  '", "none",
                                   "'Reviewer:'", "x"])
def test_placeholder_reviewers_are_blocked(tmp_path, value):
    doc = ce.load_document(write(tmp_path, GOOD_DOC.replace("reviewed_by: Jane Doe", f"reviewed_by: {value}")))
    res = ce.check_document(doc, "publish", engine="builtin")
    assert ("human_review", "error") in gates(res), value
    assert res["status"] == "blocked"


@pytest.mark.parametrize("value", ["Jane Doe", "'O’Brien, Siobhán'", "'Dr. Li Wei (editor)'", "Al"])
def test_real_reviewer_names_pass(tmp_path, value):
    doc = ce.load_document(write(tmp_path, GOOD_DOC.replace("reviewed_by: Jane Doe", f"reviewed_by: {value}")))
    assert ce.reviewer_problem(doc.meta["reviewed_by"]) is None
    assert ce.check_document(doc, "publish", engine="builtin")["status"] == "pass"


def with_front_matter_line(line):
    """GOOD_DOC with ``line`` replacing (or adding) the front-matter key it sets."""
    key = line.split(":", 1)[0]
    text = "\n".join(l for l in GOOD_DOC.split("\n") if not l.startswith(key + ":"))
    return text.replace("---\n", "---\n" + line + "\n", 1)


@pytest.mark.parametrize("line,field", [
    ("tags: 5", "tags"), ("tags: true", "tags"), ("tags: [crm, true]", "tags"),
    ("slug: 12", "slug"), ("meta_description: [a, b]", "meta_description"),
    ("image_url: true", "image_url"), ("status: 1", "status"), ("title: 1984", "title"),
    ("canonical: [a]", "canonical"), ("count: 3", None),   # control: an unrelated numeric key is fine
])
def test_wrong_typed_front_matter_is_a_clear_error(tmp_path, line, field):
    path = write(tmp_path, with_front_matter_line(line))
    if field is None:
        ce.load_document(path)
        return
    with pytest.raises(ce.FrontMatterError, match=f"'{field}'"):
        ce.load_document(path)
    for cmd in (["bundle", "--out-dir", str(tmp_path / "out")], ["webhook", "--url", PUBLIC_HOOK],
                ["wordpress", "--site", PUBLIC_WP, "--user", "ed"]):
        r = subprocess.run([PY, SCRIPT, cmd[0], str(path), *cmd[1:], "--engine", "builtin"],
                           capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})
        assert r.returncode == 1 and f"'{field}'" in r.stderr and "Traceback" not in r.stderr, r.stderr


def test_numeric_text_fields_and_tag_items_are_accepted(tmp_path):
    text = GOOD_DOC.replace("tags: [crm, sales]", "tags: [crm, 2026]").replace(
        "primary_keyword: how to choose a crm", "primary_keyword: 1099")
    doc = ce.load_document(write(tmp_path, text))
    assert doc.meta["tags"] == ["crm", "2026"] and doc.meta["primary_keyword"] == "1099"


@pytest.mark.parametrize("line,label", [
    ("Some text ``TODO` more.", "TODO"),                  # unbalanced backticks render as text
    ("Fact `[needs source]`` here.", "[needs source]"),
    ("Fact [needs  source] here.", "[needs source]"),      # two spaces
    ("Fact [needs\tsource] and [citation  needed].", "[needs source]"),
    ("Fact [needs\nsource] across a soft break.", "[needs source]"),
    (r"Escaped \[needs source\] brackets.", "[needs source]"),
    ("A TO<b>DO</b> split by markup.", None),               # escaped without --allow-html: not a marker
    ("[Source](TODO) link target.", "TODO"),
    ("![TK](https://e.example/i.png) alt text.", "TK"),
])
def test_markers_are_found_in_the_rendered_page(tmp_path, line, label):
    doc = doc_with(tmp_path, _body=f"# T\n\n{BODY_WORDS}\n\n{line}\n")
    res = ce.check_document(doc, "publish", engine="builtin")
    found = {f["message"].split("'")[1] for f in res["findings"] if f["gate"] == "unresolved_marker"}
    if label is None:
        assert not found
    else:
        assert label in found and res["status"] == "blocked"


def test_marker_split_by_inline_html_is_found_with_allow_html(tmp_path):
    doc = doc_with(tmp_path, _body=f"# T\n\n{BODY_WORDS}\n\nA TO<b>DO</b> split by markup.\n")
    res = ce.check_document(doc, "publish", allow_html=True, engine="builtin")
    assert ("unresolved_marker", "error") in gates(res)


def test_markers_in_code_spans_and_blocks_do_not_block(tmp_path):
    body = f"# T\n\n{BODY_WORDS}\n\nUse `TODO` and ``{{{{ var }}}}`` in templates.\n\n```\nTK [needs source]\n```\n"
    res = ce.check_document(doc_with(tmp_path, _body=body), "publish", engine="builtin")
    assert res["status"] == "pass", res["findings"]


@pytest.mark.parametrize("extra", ["tags: [crm, TODO]", "tags:\n  - crm\n  - '[needs  source]'",
                                   "image_alt: 'TK: chart'", "notes: '{{ fill me }}'"])
def test_markers_in_list_and_text_front_matter_block_publish(tmp_path, extra):
    key = extra.split(":", 1)[0]
    doc = ce.load_document(write(tmp_path, with_front_matter_line(extra)))
    res = ce.check_document(doc, "publish", engine="builtin")
    assert any(f["gate"] == "unresolved_marker" and f"front matter '{key}'" in f["message"]
               for f in res["findings"])


# ---------------------------------------------------------------------------
# schema: path safety
# ---------------------------------------------------------------------------

JSONLD = '{"@context": "https://schema.org", "@type": "Article", "headline": "x"}'


def schema_doc(folder, schema_value):
    folder.mkdir(parents=True, exist_ok=True)
    return ce.load_document(write(folder, with_front_matter_line(f"schema: '{schema_value}'")))


def test_schema_file_in_folder_or_subfolder_is_allowed(tmp_path):
    (tmp_path / "schema").mkdir()
    (tmp_path / "schema" / "article.json").write_text(JSONLD)
    (tmp_path / "graph.jsonld").write_text('[{"@context": "https://schema.org", "@type": "FAQPage"}]')
    for value in ("schema/article.json", "./schema/../schema/article.json", "graph.jsonld"):
        schema, err = ce.resolve_schema(schema_doc(tmp_path, value))
        assert err is None and schema, value


@pytest.mark.parametrize("make,value,msg", [
    (lambda t: (t / "x.json").write_text(JSONLD), "{abs}/x.json", "relative"),
    (lambda t: (t / "x.json").write_text(JSONLD), "../x.json", "leaves"),
    (lambda t: (t / "x.json").write_text(JSONLD), "~/x.json", "relative"),
    (lambda t: (t / "doc" / "a.txt").write_text(JSONLD), "a.txt", ".json"),
    (lambda t: (t / "doc" / "client_secret_123.json").write_text(JSONLD), "client_secret_123.json", "credential"),
    (lambda t: (t / "doc" / "oauth-token.json").write_text(JSONLD), "oauth-token.json", "credential"),
    (lambda t: (t / "doc" / "service_account.json").write_text(JSONLD), "service_account.json", "credential"),
    (lambda t: (t / "doc" / "my-credentials.json").write_text(JSONLD), "my-credentials.json", "credential"),
    (lambda t: ((t / "doc" / ".secrets").mkdir(), (t / "doc" / ".secrets" / "s.json").write_text(JSONLD)),
     ".secrets/s.json", "hidden"),
    (lambda t: (t / "doc" / "keys.json").write_text('{"api_key": "AIzaFAKE", "client_secret": "x"}'),
     "keys.json", "not JSON-LD"),
    (lambda t: (t / "doc" / "list.json").write_text('[{"@type": "Article"}, {"token": "x"}]'), "list.json",
     "not JSON-LD"),
    (lambda t: (t / "doc" / "big.json").write_text(
        '{"@type": "Article", "text": "' + "a" * (ce.SCHEMA_FILE_MAX_BYTES + 10) + '"}'), "big.json", "larger"),
])
def test_schema_path_refusals(tmp_path, make, value, msg):
    (tmp_path / "doc").mkdir()
    make(tmp_path)
    doc = schema_doc(tmp_path / "doc", value.replace("{abs}", str(tmp_path)))
    schema, err = ce.resolve_schema(doc)
    assert schema is None and msg in err, err
    assert ("schema_json", "error") in gates(ce.check_document(doc, "draft", engine="builtin"))


def test_schema_symlink_out_of_folder_is_refused(tmp_path):
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "x.json").write_text(JSONLD)
    (tmp_path / "doc").mkdir()
    (tmp_path / "doc" / "link.json").symlink_to(tmp_path / "outside" / "x.json")
    schema, err = ce.resolve_schema(schema_doc(tmp_path / "doc", "link.json"))
    assert schema is None and "leaves" in err


def test_schema_under_user_config_folder_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    folder = tmp_path / ".config" / "claude-seo"
    folder.mkdir(parents=True)
    (folder / "google-api.json").write_text('{"@type": "Article", "api_key": "AIzaFAKE"}')
    schema, err = ce.resolve_schema(schema_doc(folder, "google-api.json"))
    assert schema is None and "config" in err


def test_webhook_never_embeds_a_local_secret_file(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTENT_WEBHOOK_SECRET", "s")
    (tmp_path / "secret.json").write_text('{"@type": "Thing", "api_key": "AIzaFAKEFAKE"}')
    doc = schema_doc(tmp_path / "doc", str(tmp_path / "secret.json"))
    with pytest.raises(ce._Refusal) as exc:
        ce.run_webhook(doc, PUBLIC_HOOK, "CONTENT_WEBHOOK_SECRET", None, None, confirm=True,
                       engine="builtin", session_factory=forbidden_factory)
    assert "AIzaFAKE" not in json.dumps(exc.value.result, default=str)
    with pytest.raises(ce._Refusal):
        ce.run_bundle(doc, str(tmp_path / "out"), None, engine="builtin")
    assert not (tmp_path / "out").exists()


def test_cli_check_exit_codes(tmp_path):
    good = write(tmp_path, GOOD_DOC)
    r = subprocess.run([PY, SCRIPT, "check", str(good), "--for", "publish", "--json", "--engine", "builtin"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    out = json.loads(r.stdout)
    assert out["status"] == "pass" and out["limitations"]
    bad = write(tmp_path, GOOD_DOC.replace("reviewed_by: Jane Doe", "reviewed_by: ''"), "bad.md")
    r = subprocess.run([PY, SCRIPT, "check", str(bad), "--for", "publish"], capture_output=True, text=True)
    assert r.returncode == 2
    assert "human_review" in r.stdout


# ---------------------------------------------------------------------------
# Payloads and bundle
# ---------------------------------------------------------------------------

def test_article_payload_is_outrank_compatible(tmp_path):
    doc = ce.load_document(write(tmp_path, GOOD_DOC))
    built = ce.build_article(doc, "draft", engine="builtin")
    art = built["article"]
    for key in ("id", "title", "content_markdown", "content_html", "meta_description", "image_url",
                "slug", "tags", "created_at", "status", "reviewed_by"):
        assert key in art
    assert art["id"] == hashlib.sha256(b"how-to-choose-a-crm").hexdigest()[:16]
    assert built["leading_h1_stripped"] and not art["content_html"].startswith("<h1")
    assert not art["content_markdown"].startswith("# ")
    payload = ce.build_payload(art, "publish_articles")
    assert payload["event_type"] == "publish_articles" and payload["data"]["articles"][0] is art


def test_front_matter_never_escalates_status(tmp_path):
    doc = doc_with(tmp_path, status="publish")
    status, notices = ce.effective_status(None, doc)
    assert status == "draft" and "--status publish" in notices[0]
    assert ce.effective_status("publish", doc)[0] == "publish"


def test_bundle_writes_three_files_with_noindex_and_safe_jsonld(tmp_path):
    doc = ce.load_document(write(tmp_path, GOOD_DOC))
    res = ce.run_bundle(doc, str(tmp_path / "out"), None, engine="builtin")
    files = {k: Path(v) for k, v in res["files"].items()}
    assert {p.name for p in files.values()} == {"how-to-choose-a-crm.html", "how-to-choose-a-crm.json",
                                                "how-to-choose-a-crm.md"}
    page = files["html"].read_text()
    assert '<meta name="robots" content="noindex" />' in page
    assert "<\\/script>" in page and page.count("</script>") == 1
    assert '<link rel="canonical" href="https://example.com/blog/how-to-choose-a-crm" />' in page
    assert json.loads(files["json"].read_text())["data"]["articles"][0]["status"] == "draft"
    assert files["md"].read_text() == GOOD_DOC


def test_bundle_refuses_blocked_doc_and_writes_nothing(tmp_path):
    doc = doc_with(tmp_path, slug="../../etc/passwd")
    with pytest.raises(ce._Refusal):
        ce.run_bundle(doc, str(tmp_path / "out"), None, engine="builtin")
    assert not (tmp_path / "out").exists()


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------

class FakeResponse:
    def __init__(self, status=200, payload=None, text="ok"):
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def _next(self, method, url, **kw):
        self.calls.append((method, url, kw))
        return self.responses.pop(0)

    def get(self, url, **kw):
        return self._next("GET", url, **kw)

    def post(self, url, **kw):
        return self._next("POST", url, **kw)


def factory_for(session, opened=None):
    @contextmanager
    def factory(url):
        if opened is not None:
            opened.append(url)
        yield session
    return factory


def forbidden_factory(url):
    raise AssertionError("network must not be touched in a dry run")


def test_webhook_dry_run_sends_nothing_and_signs(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTENT_WEBHOOK_SECRET", "s3cret")
    doc = ce.load_document(write(tmp_path, GOOD_DOC))
    res = ce.run_webhook(doc, PUBLIC_HOOK, "CONTENT_WEBHOOK_SECRET", "publish_articles", None,
                         confirm=False, engine="builtin", session_factory=forbidden_factory)
    assert res["dry_run"] is True and res["signed"] is True
    assert res["payload"]["data"]["articles"][0]["status"] == "draft"
    body = ce.payload_bytes(res["payload"])
    assert res["headers"]["X-Signature-SHA256"] == hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    assert "s3cret" not in json.dumps(res)


def test_webhook_confirm_posts_exact_signed_bytes(tmp_path, monkeypatch):
    monkeypatch.setenv("HOOK_KEY", "k3y")
    doc = ce.load_document(write(tmp_path, GOOD_DOC))
    session, opened = FakeSession([FakeResponse(202)]), []
    res = ce.run_webhook(doc, PUBLIC_HOOK, "HOOK_KEY", "publish_articles", "draft", confirm=True,
                         engine="builtin", session_factory=factory_for(session, opened))
    assert opened == [PUBLIC_HOOK]
    method, url, kw = session.calls[0]
    assert (method, url, kw["allow_redirects"]) == ("POST", PUBLIC_HOOK, False)
    sig = kw["headers"]["X-Signature-SHA256"]
    assert sig == hmac.new(b"k3y", kw["data"], hashlib.sha256).hexdigest()
    sent = json.loads(kw["data"])
    assert sent["event_type"] == "publish_articles" and sent["data"]["articles"][0]["slug"] == "how-to-choose-a-crm"
    assert res["response"]["http_status"] == 202


def test_webhook_refuses_unsigned_send_unless_allowed(tmp_path, monkeypatch):
    monkeypatch.delenv("CONTENT_WEBHOOK_SECRET", raising=False)
    doc = ce.load_document(write(tmp_path, GOOD_DOC))
    with pytest.raises(ce._Refusal, match="unsigned"):
        ce.run_webhook(doc, PUBLIC_HOOK, "CONTENT_WEBHOOK_SECRET", "publish_articles", None, confirm=True,
                       engine="builtin", session_factory=forbidden_factory)
    session = FakeSession([FakeResponse(200)])
    res = ce.run_webhook(doc, PUBLIC_HOOK, "CONTENT_WEBHOOK_SECRET", "publish_articles", None, confirm=True,
                         allow_unsigned=True, engine="builtin", session_factory=factory_for(session))
    assert "X-Signature-SHA256" not in session.calls[0][2]["headers"] and res["signed"] is False


@pytest.mark.parametrize("url", ["http://93.184.215.14/hook", "https://127.0.0.1/hook",
                                 "https://169.254.169.254/latest", "https://localhost/x",
                                 "https://10.1.2.3/hook"])
def test_webhook_url_must_be_https_and_public(tmp_path, url):
    doc = ce.load_document(write(tmp_path, GOOD_DOC))
    with pytest.raises(ce.ExportError) as exc:
        ce.run_webhook(doc, url, "CONTENT_WEBHOOK_SECRET", "publish_articles", None, confirm=True,
                       engine="builtin", session_factory=forbidden_factory)
    assert exc.value.exit_code == 2


@pytest.mark.parametrize("name", ["my-secret-value", "s3cret", "lower_case", ""])
def test_secret_must_be_an_env_var_name(name):
    with pytest.raises(ce.ExportError, match="NAME of an environment variable"):
        ce.read_secret_env(name, "--secret-env")


def test_publish_and_update_events_require_publish_gates(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTENT_WEBHOOK_SECRET", "x")
    doc = doc_with(tmp_path, reviewed_by=None)
    for status, event in (("publish", "publish_articles"), ("draft", "update_article"),
                          ("draft", "publish_articles"), ("pending", "publish_articles"),
                          ("publish", None)):
        with pytest.raises(ce._Refusal) as exc:
            ce.run_webhook(doc, PUBLIC_HOOK, "CONTENT_WEBHOOK_SECRET", event, status, confirm=True,
                           engine="builtin", session_factory=forbidden_factory)
        assert exc.value.result["gates"] == "publish", (status, event)
    res = ce.run_webhook(doc, PUBLIC_HOOK, "CONTENT_WEBHOOK_SECRET", None, "draft",
                         confirm=False, engine="builtin", session_factory=forbidden_factory)
    assert res["gates"] == "draft" and res["event"] == "save_draft"
    assert res["payload"]["event_type"] == "save_draft"


@pytest.mark.parametrize("status,event", [(None, "save_draft"), ("draft", "save_draft"),
                                          ("pending", "save_draft"), ("publish", "publish_articles")])
def test_default_webhook_event_depends_on_status(status, event):
    assert ce.default_event(status or "draft") == event
    assert ce.gate_for_status(status or "draft", event) == ("publish" if event != "save_draft" else "draft")
    assert "save_draft" in ce.EVENTS and ce.gate_for_status("draft", "update_article") == "publish"


def test_cli_webhook_draft_defaults_to_save_draft_event(tmp_path):
    post = write(tmp_path, GOOD_DOC.replace("reviewed_by: Jane Doe\n", ""))   # unreviewed draft
    r = subprocess.run([PY, SCRIPT, "webhook", str(post), "--url", PUBLIC_HOOK, "--json", "--engine", "builtin"],
                       capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})
    assert r.returncode == 0, r.stdout + r.stderr
    out = json.loads(r.stdout)
    assert out["event"] == "save_draft" and out["gates"] == "draft"
    assert out["payload"]["event_type"] == "save_draft"
    r = subprocess.run([PY, SCRIPT, "webhook", str(post), "--url", PUBLIC_HOOK, "--event", "publish_articles",
                        "--engine", "builtin"], capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})
    assert r.returncode == 2 and "REFUSED" in r.stderr and "human_review" in r.stderr


def test_bundle_draft_payload_uses_non_publishing_event(tmp_path):
    doc = ce.load_document(write(tmp_path, GOOD_DOC))
    res = ce.run_bundle(doc, str(tmp_path / "out"), None, engine="builtin")
    assert res["event"] == "save_draft" and res["gates"] == "draft"
    assert json.loads(Path(res["files"]["json"]).read_text())["event_type"] == "save_draft"


def test_webhook_non_2xx_is_an_error(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTENT_WEBHOOK_SECRET", "x")
    doc = ce.load_document(write(tmp_path, GOOD_DOC))
    with pytest.raises(ce.ExportError, match="HTTP 302"):
        ce.run_webhook(doc, PUBLIC_HOOK, "CONTENT_WEBHOOK_SECRET", "publish_articles", None, confirm=True,
                       engine="builtin", session_factory=factory_for(FakeSession([FakeResponse(302)])))


def test_cli_webhook_dry_run(tmp_path):
    post = write(tmp_path, GOOD_DOC)
    r = subprocess.run([PY, SCRIPT, "webhook", str(post), "--url", PUBLIC_HOOK, "--json", "--engine", "builtin"],
                       capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})
    assert r.returncode == 0, r.stdout + r.stderr
    out = json.loads(r.stdout)
    assert out["dry_run"] is True and out["signed"] is False
    assert any("not set" in n for n in out["notices"])


def test_cli_webhook_publish_blocked_exit_2(tmp_path):
    post = write(tmp_path, GOOD_DOC.replace("reviewed_by: Jane Doe\n", ""))
    r = subprocess.run([PY, SCRIPT, "webhook", str(post), "--url", PUBLIC_HOOK, "--status", "publish",
                        "--engine", "builtin"], capture_output=True, text=True)
    assert r.returncode == 2
    assert "REFUSED" in r.stderr


# ---------------------------------------------------------------------------
# WordPress
# ---------------------------------------------------------------------------

def test_wordpress_dry_run_is_offline(tmp_path, monkeypatch):
    monkeypatch.setenv("WP_APP_PASSWORD", "abcd efgh ijkl")
    doc = ce.load_document(write(tmp_path, GOOD_DOC))
    res = ce.run_wordpress(doc, PUBLIC_WP, "editor", "WP_APP_PASSWORD", None, confirm=False,
                           engine="builtin", session_factory=forbidden_factory)
    assert res["dry_run"] and res["status"] == "draft"
    assert res["plan"]["body"]["status"] == "draft"
    assert "slug=how-to-choose-a-crm" in res["plan"]["lookup"]
    assert "abcd" not in json.dumps(res)


def test_wordpress_creates_when_slug_not_found(tmp_path, monkeypatch):
    monkeypatch.setenv("WP_APP_PASSWORD", "abcd efgh ijkl")
    doc = ce.load_document(write(tmp_path, GOOD_DOC))
    session = FakeSession([FakeResponse(200, []), FakeResponse(200, [{"id": 7}]), FakeResponse(200, []),
                           FakeResponse(201, {"id": 42, "link": "https://x/?p=42", "status": "draft"})])
    res = ce.run_wordpress(doc, PUBLIC_WP, "editor", "WP_APP_PASSWORD", None, confirm=True,
                           engine="builtin", session_factory=factory_for(session))
    lookup = session.calls[0]
    assert lookup[1] == f"{PUBLIC_WP}/wp-json/wp/v2/posts"
    assert lookup[2]["params"] == {"slug": "how-to-choose-a-crm", "status": "any", "context": "edit"}
    expected_auth = "Basic " + base64.b64encode(b"editor:abcd efgh ijkl").decode()
    assert lookup[2]["headers"]["Authorization"] == expected_auth
    create = session.calls[-1]
    assert create[0] == "POST" and create[1].endswith("/wp/v2/posts")
    assert create[2]["json"]["status"] == "draft" and create[2]["json"]["tags"] == [7]
    assert not create[2]["json"]["content"].startswith("<h1")
    assert res["action"] == "created" and res["post_id"] == 42
    assert any("sales" in n for n in res["notices"])          # unresolved tag reported, not created
    assert "abcd" not in json.dumps(res)


def test_wordpress_updates_existing_draft_by_id(tmp_path, monkeypatch):
    monkeypatch.setenv("WP_APP_PASSWORD", "pw")
    doc = doc_with(tmp_path, tags=[])
    session = FakeSession([FakeResponse(200, [{"id": 5, "status": "draft", "slug": SLUG}]),
                           FakeResponse(200, {"id": 5, "status": "pending"})])
    res = ce.run_wordpress(doc, PUBLIC_WP, "editor", "WP_APP_PASSWORD", "pending", confirm=True,
                           engine="builtin", session_factory=factory_for(session))
    assert session.calls[-1][1].endswith("/wp/v2/posts/5")
    assert res["action"] == "updated"


def test_wordpress_never_downgrades_or_silently_edits_live_post(tmp_path, monkeypatch):
    monkeypatch.setenv("WP_APP_PASSWORD", "pw")
    doc = ce.load_document(write(tmp_path, GOOD_DOC))   # has tags: refusal must come before tag lookups
    session = FakeSession([FakeResponse(200, [{"id": 5, "status": "publish", "slug": SLUG}])])
    with pytest.raises(ce._Refusal, match="live"):
        ce.run_wordpress(doc, PUBLIC_WP, "editor", "WP_APP_PASSWORD", None, confirm=True,
                         engine="builtin", session_factory=factory_for(session))
    assert len(session.calls) == 1   # lookup only, no POST


def test_wordpress_refuses_duplicate_slugs(tmp_path, monkeypatch):
    monkeypatch.setenv("WP_APP_PASSWORD", "pw")
    doc = doc_with(tmp_path, tags=[])
    session = FakeSession([FakeResponse(200, [{"id": 5, "slug": SLUG}, {"id": 9, "slug": SLUG}])])
    with pytest.raises(ce._Refusal, match="share slug"):
        ce.run_wordpress(doc, PUBLIC_WP, "editor", "WP_APP_PASSWORD", None, confirm=True,
                         engine="builtin", session_factory=factory_for(session))


def test_wordpress_only_updates_an_exact_slug_match(tmp_path, monkeypatch):
    monkeypatch.setenv("WP_APP_PASSWORD", "pw")
    doc = doc_with(tmp_path, tags=[])
    # Lookup returns an unrelated post (lenient plugin / fuzzy match): never update it, create instead.
    session = FakeSession([FakeResponse(200, [{"id": 9, "status": "draft", "slug": "totally-different-post"}]),
                           FakeResponse(201, {"id": 42, "status": "draft"})])
    res = ce.run_wordpress(doc, PUBLIC_WP, "editor", "WP_APP_PASSWORD", None, confirm=True,
                           engine="builtin", session_factory=factory_for(session))
    assert res["action"] == "created" and session.calls[-1][1].endswith("/wp/v2/posts")
    assert any("ignored" in n and "9" in n for n in res["notices"])
    # An exact match among non-matching results is the one updated.
    session = FakeSession([FakeResponse(200, [{"id": 9, "status": "draft", "slug": "other"},
                                              {"id": 5, "status": "draft", "slug": SLUG}]),
                           FakeResponse(200, {"id": 5, "status": "draft"})])
    res = ce.run_wordpress(doc, PUBLIC_WP, "editor", "WP_APP_PASSWORD", None, confirm=True,
                           engine="builtin", session_factory=factory_for(session))
    assert res["action"] == "updated" and session.calls[-1][1].endswith("/wp/v2/posts/5")
    # A live post with another slug does not trigger the live-post refusal.
    session = FakeSession([FakeResponse(200, [{"id": 9, "status": "publish", "slug": "other"}]),
                           FakeResponse(201, {"id": 43, "status": "draft"})])
    assert ce.run_wordpress(doc, PUBLIC_WP, "editor", "WP_APP_PASSWORD", None, confirm=True, engine="builtin",
                            session_factory=factory_for(session))["action"] == "created"


def test_wordpress_publish_needs_gates_and_password(tmp_path, monkeypatch):
    monkeypatch.delenv("WP_APP_PASSWORD", raising=False)
    doc = ce.load_document(write(tmp_path, GOOD_DOC))
    with pytest.raises(ce._Refusal, match="not set"):
        ce.run_wordpress(doc, PUBLIC_WP, "editor", "WP_APP_PASSWORD", None, confirm=True,
                         engine="builtin", session_factory=forbidden_factory)
    unreviewed = doc_with(tmp_path, reviewed_by=None)
    with pytest.raises(ce._Refusal) as exc:
        ce.run_wordpress(unreviewed, PUBLIC_WP, "editor", "WP_APP_PASSWORD", "publish", confirm=False,
                         engine="builtin", session_factory=forbidden_factory)
    assert exc.value.result["gates"] == "publish"


def test_wordpress_error_messages_never_leak_password(tmp_path, monkeypatch):
    monkeypatch.setenv("WP_APP_PASSWORD", "super secret pw")
    doc = doc_with(tmp_path, tags=[])
    session = FakeSession([FakeResponse(401, {"message": "bad auth for super secret pw"})])
    with pytest.raises(ce.ExportError) as exc:
        ce.run_wordpress(doc, PUBLIC_WP, "editor", "WP_APP_PASSWORD", None, confirm=True,
                         engine="builtin", session_factory=factory_for(session))
    assert "super secret pw" not in str(exc.value) and "[redacted]" in str(exc.value)


def test_wordpress_requires_https(tmp_path):
    doc = ce.load_document(write(tmp_path, GOOD_DOC))
    with pytest.raises(ce.ExportError, match="https"):
        ce.run_wordpress(doc, "http://93.184.215.14", "editor", "WP_APP_PASSWORD", None, confirm=False,
                         engine="builtin", session_factory=forbidden_factory)


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------

def cal_item(i, **kw):
    item = {"date": f"2026-11-{i + 1:02d}", "keyword": f"crm topic {i}", "intent": "informational",
            "funnel": "TOFU", "article_type": "guide", "expected_length": "1200-1600",
            "slug": f"crm-topic-{i}", "internal_links": ["/pricing"], "instructions": "Answer first.",
            "quality_questions": ["Does it answer the query in the first paragraph?"], "status": "planned"}
    item.update(kw)
    return item


def test_calendar_valid_and_volume_guard():
    cal = {"cadence_per_week": 2, "items": [cal_item(i) for i in range(12)]}
    res = ce.validate_calendar(cal, indexed_pages=10)
    assert res["status"] == "pass"
    assert res["volume"]["peak_new_pages_30d"] == 12
    msgs = " ".join(f["message"] for f in res["findings"] if f["gate"] == "volume_guard")
    assert "HIGH" in msgs and "cadence" in msgs


def test_calendar_duplicates_and_bad_fields_block():
    cal = {"items": [cal_item(0), cal_item(1, keyword="CRM  topic 0", slug="crm-topic-0"),
                     cal_item(2, intent="buy", funnel="top", status="done", date="11/03/2026")]}
    res = ce.validate_calendar(cal, indexed_pages=500)
    g = gates(res)
    assert res["status"] == "blocked"
    assert ("calendar_duplicate", "error") in g and ("calendar_field", "error") in g


def test_calendar_cannibalization_precheck_and_existing_urls():
    cal = {"items": [cal_item(0, keyword="crm pricing", slug="crm-pricing")]}
    rows = [{"query": "CRM pricing", "page": "https://ex.com/pricing", "impressions": 900, "position": 8.2}]
    res = ce.validate_calendar(cal, indexed_pages=500, existing_urls=["https://ex.com/blog/crm-pricing/"],
                               query_page_rows=rows)
    g = gates(res)
    assert ("cannibalization_precheck", "warning") in g and ("existing_url", "warning") in g
    assert res["status"] == "pass"


def test_cli_calendar(tmp_path):
    path = tmp_path / "cal.json"
    path.write_text(json.dumps({"items": [cal_item(0)], "cadence_per_week": 2}))
    r = subprocess.run([PY, SCRIPT, "calendar", str(path), "--indexed-pages", "200", "--json"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(r.stdout)["status"] == "pass"


def test_check_aeo_reports_section_citability_without_gating(tmp_path):
    body = ("# T\n\nIntro paragraph. " + BODY_WORDS + "\n\n## What is a CRM?\n\n"
            "A CRM is a system that stores every customer interaction. According to Gartner, 65% of "
            "sales teams use one. For example, a five-person agency can track 300 leads with it. "
            + BODY_WORDS)
    doc = doc_with(tmp_path, _body=body)
    aeo = ce.citability_sections(doc, engine="builtin")
    assert [s["heading"] for s in aeo["sections"]] == ["Introduction", "What is a CRM?"]
    assert all(0 <= s["score"] <= 100 for s in aeo["sections"])
    assert aeo["average_citability"] is not None
    post = write(tmp_path, GOOD_DOC, "aeo.md")
    r = subprocess.run([PY, SCRIPT, "check", str(post), "--aeo", "--json", "--engine", "builtin"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    out = json.loads(r.stdout)
    assert "aeo" in out and out["status"] == "pass"
