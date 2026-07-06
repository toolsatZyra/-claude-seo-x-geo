# claude-seo × geo-seo-claude Merge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fork `AgriciDaniel/claude-seo` v2.2.0 as the base and graft `zubair-trabzada/geo-seo-claude`'s AEO/GEO modules into it, producing one 32-skill/20-agent plugin where AEO is a first-class, separately-scored dimension — not blended into the SEO score.

**Architecture:** Supersede model. Copy claude-seo's full tree into this repo as the base. Graft 7 geo skills + 2 agents verbatim (with LICENSE/frontmatter fixes). Fold unique logic from 8 overlapping geo skills into their `seo-*` equivalents, then delete the geo originals. Rewire 3 geo Python scorers off geo's own fetcher onto claude-seo's SSRF-hardened `fetch_page`/`url_safety` modules. Two new optional extensions (`geo-dashboard`, `gsc-mcp`) live outside core, never imported by any skill.

**Tech Stack:** Python 3.11+, pytest, BeautifulSoup4/lxml, Playwright (chromium), Flask+rich (dashboard extension only), Claude Code plugin conventions (SKILL.md frontmatter, `.claude-plugin/plugin.json`).

## Global Constraints

- Python `>=3.11` for this fork (spec §2); claude-seo's own `pyproject.toml` currently says `>=3.10` — bump to `>=3.11` as part of Task 19.
- Do not modify `scripts/fetch_page.py`, `scripts/url_safety.py`, or any of claude-seo's existing tests except the ones this plan explicitly names.
- Do not downgrade shared pins below claude-seo's current floors: `lxml>=6.1.1,<7.0.0`, `playwright>=1.59.0,<2.0.0`, `Pillow>=12.2.0,<13.0.0`, `urllib3>=2.7.0,<3.0.0` (claude-seo's floors are all higher than geo's — geo's copies of these must never be used).
- Every grafted/edited `SKILL.md` frontmatter must have a nested `metadata:\n  version: "3.0.0"` field (2-space indent) — required by `tests/test_manifest_consistency.py::test_skill_metadata_versions_match_plugin_json`.
- Target version for this merge is `3.0.0` everywhere version is asserted: `plugin.json`, `marketplace.json` (via plugin.json parity), `pyproject.toml`, `CITATION.cff`, `install.sh`/`install.ps1` `REPO_TAG`/`RepoTag` defaults, every `SKILL.md` `metadata.version`.
- Final skill count is exactly 32 (25 kept + 7 grafted); final agent count is exactly 20 (18 kept + 2 grafted). No task may leave a partial count — `tests/test_manifest_consistency.py` and `tests/test_portability.py` are the ground truth and must both be green before Task 22 is considered done.
- No core skill or script may import `flask` or `rich` — those are confined to `extensions/geo-dashboard/`.
- No skill may treat `llms.txt` as a ranking/citation signal — only as a forward-looking, low-confidence, optional artifact gated by `aeo.llmstxt_mode`.
- SEO and AEO scores are reported separately in every audit output — never averaged or blended into one number.
- All work happens on branch `merge/aeo-depth`, local-only (no GitHub fork, no push, no PR — per user decision, spec §0.2 delta).

---

### Task 1: Bootstrap repo from claude-seo base + branch setup

**Files:**
- Create: entire claude-seo tree copied into repo root (`agents/`, `assets/`, `data/`, `docs/` [merge with existing], `extensions/`, `hooks/`, `pdf/`, `schema/`, `screenshots/`, `scripts/`, `skills/`, `tests/`, plus top-level files: `AGENTS.md`, `CHANGELOG.md`, `CITATION.cff`, `CLAUDE.md`, `CODE_OF_CONDUCT.md`, `CONTRIBUTING.md`, `CONTRIBUTORS.md`, `LICENSE`, `PRIVACY.md`, `README.md`, `SECURITY.md`, `install.ps1`, `install.sh`, `pyproject.toml`, `requirements.txt`, `uninstall.ps1`, `uninstall.sh`).
- Create: `.gitignore` (new, add `.graft-src/`)

**Interfaces:**
- Produces: the full claude-seo v2.2.0 tree at repo root, becoming the base every later task edits. All later tasks assume these paths exist relative to repo root `/Users/riyamalik/Library/Mobile Documents/com~apple~CloudDocs/ZYRA/claude-seo-x-geo/`.

- [ ] **Step 1: Clone claude-seo v2.2.0 into a scratch location**

```bash
cd "/Users/riyamalik/Library/Mobile Documents/com~apple~CloudDocs/ZYRA/claude-seo-x-geo"
git clone --depth 1 https://github.com/AgriciDaniel/claude-seo.git /tmp/claude-seo-base
```

- [ ] **Step 2: Copy everything except .git into repo root**

```bash
cd "/Users/riyamalik/Library/Mobile Documents/com~apple~CloudDocs/ZYRA/claude-seo-x-geo"
rsync -a --exclude='.git' /tmp/claude-seo-base/ ./
ls  # sanity check: should show skills/, agents/, scripts/, tests/, docs/, etc. alongside the existing docs/superpowers/
```

- [ ] **Step 3: Create `.gitignore`**

```
.graft-src/
__pycache__/
*.pyc
.pytest_cache/
```

- [ ] **Step 4: Branch, commit the imported base**

```bash
git checkout -b merge/aeo-depth
git add -A
git commit -m "Import claude-seo v2.2.0 upstream as merge base"
```

- [ ] **Step 5: Verify the base's own test suite passes before any grafting**

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
pip install pytest
pytest tests/ -q
```

Expected: all tests pass (this is the pristine upstream base — if anything fails here, stop and investigate before grafting anything on top of a broken base).

---

### Task 2: Clone geo-seo-claude as the grafting source

**Files:**
- Create: `.graft-src/geo-seo-claude/` (gitignored, temporary — deleted in Task 22)

**Interfaces:**
- Produces: `.graft-src/geo-seo-claude/` containing the full geo-seo-claude tree, used as the read-only source for every graft/merge task below.

- [ ] **Step 1: Clone geo-seo-claude**

```bash
mkdir -p "/Users/riyamalik/Library/Mobile Documents/com~apple~CloudDocs/ZYRA/claude-seo-x-geo/.graft-src"
git clone --depth 1 https://github.com/zubair-trabzada/geo-seo-claude.git "/Users/riyamalik/Library/Mobile Documents/com~apple~CloudDocs/ZYRA/claude-seo-x-geo/.graft-src/geo-seo-claude"
```

- [ ] **Step 2: Confirm expected structure**

```bash
ls "/Users/riyamalik/Library/Mobile Documents/com~apple~CloudDocs/ZYRA/claude-seo-x-geo/.graft-src/geo-seo-claude/skills"
```

Expected output (15 dirs): `geo-audit geo-brand-mentions geo-citability geo-compare geo-content geo-crawlers geo-llmstxt geo-platform-optimizer geo-proposal geo-prospect geo-report geo-report-pdf geo-schema geo-technical geo-update`

- [ ] **Step 3: Commit the .gitignore addition takes effect (no tracked changes expected)**

```bash
git status --short  # should show nothing new tracked (`.graft-src/` is ignored)
```

---

### Task 3: License compliance scaffolding

**Files:**
- Create: `NOTICE.md`
- Create: `LICENSES/geo-seo-claude-LICENSE.txt`
- Modify: `CONTRIBUTORS.md`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `NOTICE.md` and `LICENSES/geo-seo-claude-LICENSE.txt` that Task 4's per-skill `LICENSE.txt` files will reference.

- [ ] **Step 1: Copy geo-seo-claude's LICENSE verbatim**

```bash
mkdir -p "/Users/riyamalik/Library/Mobile Documents/com~apple~CloudDocs/ZYRA/claude-seo-x-geo/LICENSES"
cp "/Users/riyamalik/Library/Mobile Documents/com~apple~CloudDocs/ZYRA/claude-seo-x-geo/.graft-src/geo-seo-claude/LICENSE" "/Users/riyamalik/Library/Mobile Documents/com~apple~CloudDocs/ZYRA/claude-seo-x-geo/LICENSES/geo-seo-claude-LICENSE.txt"
```

- [ ] **Step 2: Write `NOTICE.md`**

```markdown
# NOTICE

This project is a fork of [claude-seo](https://github.com/AgriciDaniel/claude-seo)
(MIT License, Copyright (c) 2026 agricidaniel), grafted with AEO/GEO modules
from [geo-seo-claude](https://github.com/zubair-trabzada/geo-seo-claude)
(MIT License, Copyright (c) 2026 Zubair Trabzada).

Both original licenses are preserved:
- This fork's top-level `LICENSE` is claude-seo's original MIT license, unmodified.
- geo-seo-claude's original MIT license is preserved verbatim at
  `LICENSES/geo-seo-claude-LICENSE.txt`.

Every skill folder grafted or derived from geo-seo-claude carries its own
`LICENSE.txt` noting its origin. See `CONTRIBUTORS.md` for full attribution.

Neither original copyright notice has been removed or rewritten.
```

- [ ] **Step 3: Read and append to `CONTRIBUTORS.md`**

Read the existing file first (`cat CONTRIBUTORS.md`) to match its format, then append a new section:

```markdown

## AEO/GEO merge (v3.0.0)

- Zubair Trabzada — original author of geo-seo-claude, source of all `geo-*`
  skills, `citability_scorer.py`, `brand_scanner.py`, `llmstxt_generator.py`,
  and the schema/white-label contributions folded into this fork.
- GrowthZyra — merge integration (grafting, rewiring onto claude-seo's
  SSRF-hardened fetcher, deduplication, test coverage).
```

- [ ] **Step 4: Commit**

```bash
git add NOTICE.md LICENSES/ CONTRIBUTORS.md
git commit -m "Add license compliance scaffolding for geo-seo-claude graft"
```

---

### Task 4: Graft 7 geo skills as first-class skills

**Files:**
- Create: `skills/geo-citability/SKILL.md`, `skills/geo-citability/LICENSE.txt`
- Create: `skills/geo-platform-optimizer/SKILL.md`, `skills/geo-platform-optimizer/LICENSE.txt`
- Create: `skills/geo-brand-mentions/SKILL.md`, `skills/geo-brand-mentions/LICENSE.txt`
- Create: `skills/geo-crawlers/SKILL.md`, `skills/geo-crawlers/LICENSE.txt`
- Create: `skills/geo-prospect/SKILL.md`, `skills/geo-prospect/LICENSE.txt`
- Create: `skills/geo-proposal/SKILL.md`, `skills/geo-proposal/LICENSE.txt`
- (`geo-compare` is handled separately in Task 10 — it needs a dedup check first.)

**Interfaces:**
- Consumes: `.graft-src/geo-seo-claude/skills/{name}/` (Task 2).
- Produces: 6 new skill directories under `skills/`, each with valid portable frontmatter (`name`, `description`, nested `metadata.version: "3.0.0"`) that `tests/test_portability.py` and `tests/test_manifest_consistency.py` will check in Task 22.

- [ ] **Step 1: Copy the 6 skill folders (excluding geo-compare)**

```bash
cd "/Users/riyamalik/Library/Mobile Documents/com~apple~CloudDocs/ZYRA/claude-seo-x-geo"
for skill in geo-citability geo-platform-optimizer geo-brand-mentions geo-crawlers geo-prospect geo-proposal; do
  cp -r ".graft-src/geo-seo-claude/skills/$skill" "skills/$skill"
done
```

- [ ] **Step 2: For each of the 6, add a per-skill LICENSE.txt**

```bash
cd "/Users/riyamalik/Library/Mobile Documents/com~apple~CloudDocs/ZYRA/claude-seo-x-geo"
for skill in geo-citability geo-platform-optimizer geo-brand-mentions geo-crawlers geo-prospect geo-proposal; do
cat > "skills/$skill/LICENSE.txt" <<'EOF'
MIT License

Portions derived from zubair-trabzada/geo-seo-claude (MIT).
See /LICENSES/geo-seo-claude-LICENSE.txt for the original license text and
/NOTICE.md for full attribution.

Copyright (c) 2026 Zubair Trabzada
Copyright (c) 2026 agricidaniel (fork integration)
EOF
done
```

- [ ] **Step 3: Fix each skill's frontmatter to add nested `metadata.version`**

Each of the 6 `SKILL.md` files currently has a frontmatter block missing a nested `metadata:` block (some have a flat `version: 1.0.0` field instead, some have none). Open each file and normalize the frontmatter to this shape, preserving the existing `name`, `description`, and `allowed-tools` values exactly as they are, only changing/adding the version representation:

```yaml
---
name: geo-citability
description: <keep existing description exactly as-is>
allowed-tools:
  - Read
  - Grep
  - Glob
  - Bash
  - WebFetch
  - Write
metadata:
  version: "3.0.0"
  author: geo-seo-claude (grafted)
---
```

Remove any old flat `version: 1.0.0` or `author: geo-seo-claude` top-level lines once folded into `metadata:`. Repeat for `geo-platform-optimizer`, `geo-brand-mentions`, `geo-crawlers`, `geo-prospect`, `geo-proposal` (some of these already have `tags:` fields — keep those, they're not checked by any test but are harmless).

- [ ] **Step 4: Verify frontmatter is well-formed**

```bash
python3 -c "
import re, sys
from pathlib import Path
for skill in ['geo-citability','geo-platform-optimizer','geo-brand-mentions','geo-crawlers','geo-prospect','geo-proposal']:
    text = Path(f'skills/{skill}/SKILL.md').read_text()
    m = re.match(r'^---\s*\n(.*?)\n---\s*\n', text, re.DOTALL)
    assert m, f'{skill}: no frontmatter block'
    fm = m.group(1)
    assert 'name:' in fm, f'{skill}: missing name'
    assert 'description:' in fm, f'{skill}: missing description'
    assert re.search(r'^  version:\s*\"3.0.0\"', fm, re.MULTILINE), f'{skill}: missing metadata.version 3.0.0'
    print(f'{skill}: OK')
"
```

Expected: `OK` printed for all 6 skills, no `AssertionError`.

- [ ] **Step 5: Commit**

```bash
git add skills/geo-citability skills/geo-platform-optimizer skills/geo-brand-mentions skills/geo-crawlers skills/geo-prospect skills/geo-proposal
git commit -m "Graft 6 first-class geo-* skills from geo-seo-claude (geo-compare pending dedup check)"
```

---

### Task 5: Graft 2 agents, verify 3 excluded agents never copied

**Files:**
- Create: `agents/geo-ai-visibility.md`
- Create: `agents/geo-platform-analysis.md`

**Interfaces:**
- Consumes: `.graft-src/geo-seo-claude/agents/geo-ai-visibility.md`, `.graft-src/geo-seo-claude/agents/geo-platform-analysis.md`.
- Produces: 2 new agent files. `tests/test_manifest_consistency.py::_count_agent_files` only counts files starting with `seo-`, so these two `geo-*` agents will NOT be counted by that function — confirmed this is fine because the spec's target of "20 agents (18 existing + 2 grafted)" is a plain-English count, not what that specific regex-based test enforces. Double-check in Task 22 whether the plugin.json description's sub-agent count needs updating to include these two (see Task 19).

- [ ] **Step 1: Copy exactly these 2 agent files, nothing else**

```bash
cd "/Users/riyamalik/Library/Mobile Documents/com~apple~CloudDocs/ZYRA/claude-seo-x-geo"
cp .graft-src/geo-seo-claude/agents/geo-ai-visibility.md agents/geo-ai-visibility.md
cp .graft-src/geo-seo-claude/agents/geo-platform-analysis.md agents/geo-platform-analysis.md
```

- [ ] **Step 2: Verify the 3 excluded agents were never copied**

```bash
ls agents/ | grep -E "geo-content|geo-schema|geo-technical" && echo "FAIL: excluded agent found" || echo "OK: excluded agents correctly absent"
```

Expected: `OK: excluded agents correctly absent`

- [ ] **Step 3: Commit**

```bash
git add agents/geo-ai-visibility.md agents/geo-platform-analysis.md
git commit -m "Graft geo-ai-visibility and geo-platform-analysis agents"
```

---

### Task 6: Rewire citability_scorer.py onto claude-seo's fetch_page + add safety test

**Files:**
- Create: `scripts/citability_scorer.py`
- Create: `tests/test_geo_citability.py`

**Interfaces:**
- Consumes: `scripts/fetch_page.fetch_page(url, timeout=30, follow_redirects=True, max_redirects=5, user_agent=None) -> dict` (existing claude-seo function; returns `{"url", "status_code", "content", "headers", "redirect_chain", "redirect_details", "error"}`).
- Produces: `analyze_page_citability(url: str) -> dict` and `score_passage(text: str, heading: Optional[str] = None) -> dict` — both used by `skills/geo-citability/SKILL.md` and, later, by `seo-content`'s citability pass (Task 13).

- [ ] **Step 1: Write `scripts/citability_scorer.py`**

`score_passage()` is pure text-scoring with no network calls — copy it verbatim from `.graft-src/geo-seo-claude/scripts/citability_scorer.py` unchanged. Only the imports and `analyze_page_citability()` change:

```python
#!/usr/bin/env python3
"""
Citability Scorer — Analyzes content blocks for AI citation readiness.
Scores passages based on how likely AI models are to cite them.

Based on research showing optimal AI-cited passages are:
- 134-167 words long
- Self-contained (extractable without context)
- Fact-rich with specific statistics
- Structured with clear answer patterns
"""

import sys
import json
import re
import os
from typing import Optional

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("ERROR: Required packages not installed. Run: pip install -r requirements.txt")
    sys.exit(1)

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
from fetch_page import fetch_page  # noqa: E402


def score_passage(text: str, heading: Optional[str] = None) -> dict:
    """Score a single passage for AI citability (0-100)."""
    words = text.split()
    word_count = len(words)

    scores = {
        "answer_block_quality": 0,
        "self_containment": 0,
        "structural_readability": 0,
        "statistical_density": 0,
        "uniqueness_signals": 0,
    }

    # === 1. Answer Block Quality (30%) ===
    abq_score = 0

    definition_patterns = [
        r"\b\w+\s+is\s+(?:a|an|the)\s",
        r"\b\w+\s+refers?\s+to\s",
        r"\b\w+\s+means?\s",
        r"\b\w+\s+(?:can be |are )?defined\s+as\s",
        r"\bin\s+(?:simple|other)\s+(?:terms|words)\s*,",
    ]
    for pattern in definition_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            abq_score += 15
            break

    first_60_words = " ".join(words[:60])
    if any(
        re.search(p, first_60_words, re.IGNORECASE)
        for p in [
            r"\b(?:is|are|was|were|means?|refers?)\b",
            r"\d+%",
            r"\$[\d,]+",
            r"\d+\s+(?:million|billion|thousand)",
        ]
    ):
        abq_score += 15

    if heading and heading.endswith("?"):
        abq_score += 10

    sentences = re.split(r"[.!?]+", text)
    short_clear_sentences = sum(
        1 for s in sentences if 5 <= len(s.split()) <= 25
    )
    if sentences:
        clarity_ratio = short_clear_sentences / len(sentences)
        abq_score += int(clarity_ratio * 10)

    if re.search(
        r"(?:according to|research shows|studies? (?:show|indicate|suggest|found)|data (?:shows|indicates|suggests))",
        text,
        re.IGNORECASE,
    ):
        abq_score += 10

    scores["answer_block_quality"] = min(abq_score, 30)

    # === 2. Self-Containment (25%) ===
    sc_score = 0

    if 134 <= word_count <= 167:
        sc_score += 10
    elif 100 <= word_count <= 200:
        sc_score += 7
    elif 80 <= word_count <= 250:
        sc_score += 4
    elif word_count < 30 or word_count > 400:
        sc_score += 0
    else:
        sc_score += 2

    pronoun_count = len(
        re.findall(
            r"\b(?:it|they|them|their|this|that|these|those|he|she|his|her)\b",
            text,
            re.IGNORECASE,
        )
    )
    if word_count > 0:
        pronoun_ratio = pronoun_count / word_count
        if pronoun_ratio < 0.02:
            sc_score += 8
        elif pronoun_ratio < 0.04:
            sc_score += 5
        elif pronoun_ratio < 0.06:
            sc_score += 3

    proper_nouns = len(re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b", text))
    if proper_nouns >= 3:
        sc_score += 7
    elif proper_nouns >= 1:
        sc_score += 4

    scores["self_containment"] = min(sc_score, 25)

    # === 3. Structural Readability (20%) ===
    sr_score = 0

    if sentences:
        avg_sentence_length = word_count / len(sentences)
        if 10 <= avg_sentence_length <= 20:
            sr_score += 8
        elif 8 <= avg_sentence_length <= 25:
            sr_score += 5
        else:
            sr_score += 2

    if re.search(r"(?:first|second|third|finally|additionally|moreover|furthermore)", text, re.IGNORECASE):
        sr_score += 4

    if re.search(r"(?:\d+[\.\)]\s|\b(?:step|tip|point)\s+\d+)", text, re.IGNORECASE):
        sr_score += 4

    if "\n" in text:
        sr_score += 4

    scores["structural_readability"] = min(sr_score, 20)

    # === 4. Statistical Density (15%) ===
    sd_score = 0

    pct_count = len(re.findall(r"\d+(?:\.\d+)?%", text))
    sd_score += min(pct_count * 3, 6)

    dollar_count = len(re.findall(r"\$[\d,]+(?:\.\d+)?(?:\s*(?:million|billion|M|B|K))?", text))
    sd_score += min(dollar_count * 3, 5)

    number_count = len(re.findall(r"\b\d+(?:,\d{3})*(?:\.\d+)?\s+(?:users|customers|pages|sites|companies|businesses|people|percent|times|x\b)", text, re.IGNORECASE))
    sd_score += min(number_count * 2, 4)

    year_count = len(re.findall(r"\b20(?:2[3-6]|1\d)\b", text))
    if year_count > 0:
        sd_score += 2

    source_patterns = [
        r"(?:according to|per|from|by)\s+[A-Z]",
        r"(?:Gartner|Forrester|McKinsey|Harvard|Stanford|MIT|Google|Microsoft|OpenAI|Anthropic)",
        r"\([A-Z][a-z]+(?:\s+\d{4})?\)",
    ]
    for pattern in source_patterns:
        if re.search(pattern, text):
            sd_score += 2

    scores["statistical_density"] = min(sd_score, 15)

    # === 5. Uniqueness Signals (10%) ===
    us_score = 0

    if re.search(
        r"(?:our (?:research|study|data|analysis|survey|findings)|we (?:found|discovered|analyzed|surveyed|measured))",
        text,
        re.IGNORECASE,
    ):
        us_score += 5

    if re.search(
        r"(?:case study|for example|for instance|in practice|real-world|hands-on)",
        text,
        re.IGNORECASE,
    ):
        us_score += 3

    if re.search(r"(?:using|with|via|through)\s+[A-Z][a-z]+", text):
        us_score += 2

    scores["uniqueness_signals"] = min(us_score, 10)

    total = sum(scores.values())

    if total >= 80:
        grade = "A"
        label = "Highly Citable"
    elif total >= 65:
        grade = "B"
        label = "Good Citability"
    elif total >= 50:
        grade = "C"
        label = "Moderate Citability"
    elif total >= 35:
        grade = "D"
        label = "Low Citability"
    else:
        grade = "F"
        label = "Poor Citability"

    return {
        "heading": heading,
        "word_count": word_count,
        "total_score": total,
        "grade": grade,
        "label": label,
        "breakdown": scores,
        "preview": " ".join(words[:30]) + ("..." if word_count > 30 else ""),
    }


def analyze_page_citability(url: str) -> dict:
    """Analyze all content blocks on a page for citability.

    Fetches via claude-seo's scripts/fetch_page.fetch_page(), which enforces
    SSRF + DNS-rebinding protection through scripts/url_safety.py before any
    connection is opened. Never fetch pages directly with requests/urllib.
    """
    result = fetch_page(url, timeout=30)
    if result["error"]:
        return {"error": f"Failed to fetch page: {result['error']}"}
    if not result["content"]:
        return {"error": "Failed to fetch page: empty response body"}

    soup = BeautifulSoup(result["content"], "lxml")

    for element in soup.find_all(
        ["script", "style", "nav", "footer", "header", "aside", "form"]
    ):
        element.decompose()

    blocks = []
    current_heading = "Introduction"
    current_paragraphs = []

    for element in soup.find_all(["h1", "h2", "h3", "h4", "p", "ul", "ol", "table"]):
        if element.name.startswith("h"):
            if current_paragraphs:
                combined = " ".join(current_paragraphs)
                if len(combined.split()) >= 20:
                    blocks.append(
                        {"heading": current_heading, "content": combined}
                    )
            current_heading = element.get_text(strip=True)
            current_paragraphs = []
        else:
            text = element.get_text(strip=True)
            if text and len(text.split()) >= 5:
                current_paragraphs.append(text)

    if current_paragraphs:
        combined = " ".join(current_paragraphs)
        if len(combined.split()) >= 20:
            blocks.append({"heading": current_heading, "content": combined})

    scored_blocks = []
    for block in blocks:
        score = score_passage(block["content"], block["heading"])
        scored_blocks.append(score)

    if scored_blocks:
        avg_score = sum(b["total_score"] for b in scored_blocks) / len(scored_blocks)
        top_blocks = sorted(scored_blocks, key=lambda x: x["total_score"], reverse=True)[:5]
        bottom_blocks = sorted(scored_blocks, key=lambda x: x["total_score"])[:5]
        optimal_count = sum(
            1 for b in scored_blocks if 134 <= b["word_count"] <= 167
        )
    else:
        avg_score = 0
        top_blocks = []
        bottom_blocks = []
        optimal_count = 0

    grade_dist = {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0}
    for block in scored_blocks:
        grade_dist[block["grade"]] += 1

    return {
        "url": url,
        "total_blocks_analyzed": len(scored_blocks),
        "average_citability_score": round(avg_score, 1),
        "optimal_length_passages": optimal_count,
        "grade_distribution": grade_dist,
        "top_5_citable": top_blocks,
        "bottom_5_citable": bottom_blocks,
        "all_blocks": scored_blocks,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python citability_scorer.py <url>")
        print("Returns JSON with citability analysis for all content blocks.")
        sys.exit(1)

    url = sys.argv[1]
    result = analyze_page_citability(url)
    print(json.dumps(result, indent=2, default=str))
```

- [ ] **Step 2: Write the failing safety test first — `tests/test_geo_citability.py`**

```python
"""
Tests for scripts/citability_scorer.py.

Mirrors tests/test_url_safety.py's pattern: prove the grafted scorer cannot
be used to fetch private/loopback/link-local hosts, and that the scoring
function returns a bounded 0-100 score.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = str(REPO_ROOT / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import citability_scorer  # noqa: E402


def test_score_passage_bounded_zero_to_hundred():
    text = (
        "Citability is a measure of how likely an AI model is to quote a "
        "passage verbatim in a generated answer. According to research from "
        "Princeton, front-loaded, self-contained passages with statistics "
        "score highest. Studies show citations lift AI visibility by "
        "roughly 40 percent, and statistics alone add about 37 percent. "
        "Keyword stuffing, by contrast, reduces citability by roughly 10 "
        "percent, so AI-specific keyword rewriting is not recommended."
    )
    result = citability_scorer.score_passage(text, heading="What is citability?")
    assert 0 <= result["total_score"] <= 100
    assert result["grade"] in {"A", "B", "C", "D", "F"}


def test_score_passage_empty_text_does_not_crash():
    result = citability_scorer.score_passage("", heading=None)
    assert result["total_score"] == 0
    assert result["grade"] == "F"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://2130706433/",
        "https://metadata.google.internal./",
        "http://0.0.0.0/",
    ],
)
def test_analyze_page_citability_rejects_unsafe_urls(url):
    """Every private/loopback/metadata/obfuscated target must be refused
    with an error key, never raise, and never attempt a real connection."""
    result = citability_scorer.analyze_page_citability(url)
    assert "error" in result
    assert "total_blocks_analyzed" not in result


def test_analyze_page_citability_handles_unreachable_public_host():
    """A syntactically valid public URL that can't be reached must return
    a structured error, not raise."""
    result = citability_scorer.analyze_page_citability(
        "https://this-domain-should-not-resolve-aeo-merge-test.invalid/"
    )
    assert "error" in result
```

- [ ] **Step 3: Run the test to confirm it exercises the rewired code**

```bash
cd "/Users/riyamalik/Library/Mobile Documents/com~apple~CloudDocs/ZYRA/claude-seo-x-geo"
source .venv/bin/activate
pytest tests/test_geo_citability.py -v
```

Expected: all tests PASS. If `test_analyze_page_citability_rejects_unsafe_urls` fails with a raised exception instead of a returned error dict, re-check that `fetch_page()`'s `URLSafetyError` path is being surfaced through `result["error"]` (it is, per `scripts/fetch_page.py`'s existing try/except — the rewired scorer just needs to check `result["error"]` before touching `result["content"]`, which Step 1 already does).

- [ ] **Step 4: Commit**

```bash
git add scripts/citability_scorer.py tests/test_geo_citability.py
git commit -m "Graft and rewire citability_scorer.py onto claude-seo's hardened fetch_page"
```

---

### Task 7: Rewire brand_scanner.py onto claude-seo's url_safety + add safety test

**Files:**
- Create: `scripts/brand_scanner.py`
- Create: `tests/test_geo_brand_scanner.py`

**Interfaces:**
- Consumes: `scripts/url_safety.safe_requests_get(url, *, timeout=30, **kwargs) -> requests.Response` and `scripts/url_safety.URLSafetyError` (existing claude-seo module).
- Produces: `generate_brand_report(brand_name: str, domain: Optional[str] = None) -> dict`, used by `skills/geo-brand-mentions/SKILL.md`.

- [ ] **Step 1: Write `scripts/brand_scanner.py`**

Only `check_wikipedia_presence()` makes real network calls (to Wikipedia/Wikidata's own APIs) — every other platform check (`check_youtube_presence`, `check_reddit_presence`, `check_linkedin_presence`, `check_other_platforms`) only builds search URLs and instructions for the calling agent to follow via `WebFetch`, with no direct Python-side request. Copy the whole file verbatim from `.graft-src/geo-seo-claude/scripts/brand_scanner.py` except the imports and `check_wikipedia_presence`:

```python
#!/usr/bin/env python3
"""
Brand Mention Scanner — Checks brand presence across AI-cited platforms.

Brand mentions correlate 3x more strongly with AI visibility than backlinks.
(Ahrefs December 2025 study of 75,000 brands)

Platform importance for AI citations:
1. YouTube mentions (~0.737 correlation - STRONGEST)
2. Reddit mentions (high)
3. Wikipedia presence (high)
4. LinkedIn presence (moderate)
5. Domain Rating/backlinks (~0.266 - weak)
"""

import sys
import json
import re
import os
from urllib.parse import quote_plus

try:
    import requests
except ImportError:
    print("ERROR: Required packages not installed. Run: pip install -r requirements.txt")
    sys.exit(1)

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
from url_safety import safe_requests_get, URLSafetyError  # noqa: E402

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def check_youtube_presence(brand_name: str) -> dict:
    """Check brand presence on YouTube."""
    result = {
        "platform": "YouTube",
        "correlation": 0.737,
        "weight": "25%",
        "has_channel": False,
        "mentioned_in_videos": False,
        "search_url": f"https://www.youtube.com/results?search_query={quote_plus(brand_name)}",
        "recommendations": [],
    }
    result["check_instructions"] = [
        f"Search YouTube for '{brand_name}' and check:",
        "1. Does the brand have an official YouTube channel?",
        "2. Are there videos FROM the brand (tutorials, demos, thought leadership)?",
        "3. Are there videos ABOUT the brand from other creators?",
        "4. What's the view count on brand-related videos?",
        "5. Are there positive reviews or demonstrations?",
    ]
    result["recommendations"] = [
        "Create a YouTube channel if none exists",
        "Publish educational/tutorial content related to your niche",
        "Encourage customers to create review/demo videos",
        "Optimize video titles and descriptions with brand name",
        "Add timestamps and chapters to improve AI parseability",
        "Include transcripts (YouTube auto-generates, but review for accuracy)",
    ]
    return result


def check_reddit_presence(brand_name: str) -> dict:
    """Check brand presence on Reddit."""
    result = {
        "platform": "Reddit",
        "correlation": "High",
        "weight": "25%",
        "has_subreddit": False,
        "mentioned_in_discussions": False,
        "search_url": f"https://www.reddit.com/search/?q={quote_plus(brand_name)}",
        "recommendations": [],
    }
    result["check_instructions"] = [
        f"Search Reddit for '{brand_name}' and check:",
        "1. Does the brand have its own subreddit (r/brandname)?",
        "2. Is the brand discussed in relevant industry subreddits?",
        "3. What's the sentiment (positive, negative, neutral)?",
        "4. Are there recommendation threads mentioning the brand?",
        "5. Does the brand have an official Reddit presence?",
        "6. Are mentions recent (within last 6 months)?",
    ]
    result["recommendations"] = [
        "Monitor relevant subreddits for brand mentions",
        "Participate authentically in industry discussions (no spam)",
        "Create an official Reddit account for customer support",
        "Share valuable content (not just self-promotion)",
        "Respond to questions about your product/service category",
        "Reddit authenticity matters — don't use marketing speak",
    ]
    return result


def check_wikipedia_presence(brand_name: str) -> dict:
    """Check brand/entity presence on Wikipedia and Wikidata.

    Uses claude-seo's scripts/url_safety.safe_requests_get for DNS-rebinding
    protected requests, rather than calling requests.get directly.
    """
    result = {
        "platform": "Wikipedia",
        "correlation": "High",
        "weight": "20%",
        "has_wikipedia_page": False,
        "has_wikidata_entry": False,
        "cited_in_articles": False,
        "search_url": f"https://en.wikipedia.org/wiki/Special:Search?search={quote_plus(brand_name)}",
        "wikidata_url": f"https://www.wikidata.org/w/index.php?search={quote_plus(brand_name)}",
        "recommendations": [],
    }

    try:
        api_url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={quote_plus(brand_name)}&format=json"
        response = safe_requests_get(api_url, timeout=15, headers=DEFAULT_HEADERS)
        if response.status_code == 200:
            data = response.json()
            search_results = data.get("query", {}).get("search", [])
            if search_results:
                top_title = search_results[0].get("title", "").lower()
                if brand_name.lower() in top_title:
                    result["has_wikipedia_page"] = True
                result["wikipedia_search_results"] = len(search_results)
    except (requests.exceptions.RequestException, URLSafetyError):
        pass

    try:
        wikidata_url = f"https://www.wikidata.org/w/api.php?action=wbsearchentities&search={quote_plus(brand_name)}&language=en&format=json"
        response = safe_requests_get(wikidata_url, timeout=15, headers=DEFAULT_HEADERS)
        if response.status_code == 200:
            data = response.json()
            entities = data.get("search", [])
            if entities:
                result["has_wikidata_entry"] = True
                result["wikidata_id"] = entities[0].get("id", "")
                result["wikidata_description"] = entities[0].get("description", "")
    except (requests.exceptions.RequestException, URLSafetyError):
        pass

    result["recommendations"] = [
        "If eligible, create a Wikipedia article (requires notability criteria)",
        "Ensure Wikidata entry exists with complete structured data",
        "Add sameAs links in schema markup pointing to Wikipedia/Wikidata",
        "Get cited in existing Wikipedia articles as a source",
        "Build notability through press coverage and independent reviews",
        "Note: Wikipedia has strict notability guidelines — PR coverage helps establish this",
    ]
    return result


def check_linkedin_presence(brand_name: str) -> dict:
    """Check brand presence on LinkedIn."""
    result = {
        "platform": "LinkedIn",
        "correlation": "Moderate",
        "weight": "15%",
        "has_company_page": False,
        "employee_thought_leadership": False,
        "search_url": f"https://www.linkedin.com/search/results/companies/?keywords={quote_plus(brand_name)}",
        "recommendations": [],
    }
    result["check_instructions"] = [
        f"Search LinkedIn for '{brand_name}' and check:",
        "1. Does the company have a LinkedIn page?",
        "2. How many followers?",
        "3. Is the page active with recent posts?",
        "4. Do employees post thought leadership content?",
        "5. Are there LinkedIn articles about the brand?",
        "6. Is there engagement on posts (likes, comments, shares)?",
    ]
    result["recommendations"] = [
        "Create/optimize LinkedIn company page",
        "Post regular thought leadership content",
        "Encourage employees to share company content",
        "Publish long-form LinkedIn articles",
        "Engage with industry discussions and comments",
        "Add company LinkedIn URL to schema sameAs property",
    ]
    return result


def check_other_platforms(brand_name: str) -> dict:
    """Check brand presence on additional platforms."""
    result = {
        "platform": "Other Platforms",
        "weight": "15%",
        "platforms_checked": {},
        "recommendations": [],
    }
    platforms = {
        "Quora": f"https://www.quora.com/search?q={quote_plus(brand_name)}",
        "Stack Overflow": f"https://stackoverflow.com/search?q={quote_plus(brand_name)}",
        "GitHub": f"https://github.com/search?q={quote_plus(brand_name)}",
        "Crunchbase": f"https://www.crunchbase.com/textsearch?q={quote_plus(brand_name)}",
        "Product Hunt": f"https://www.producthunt.com/search?q={quote_plus(brand_name)}",
        "G2": f"https://www.g2.com/search?utf8=&query={quote_plus(brand_name)}",
        "Trustpilot": f"https://www.trustpilot.com/search?query={quote_plus(brand_name)}",
    }
    result["platforms_checked"] = {
        name: {
            "search_url": url,
            "check_instruction": f"Search for '{brand_name}' on {name}",
        }
        for name, url in platforms.items()
    }
    result["recommendations"] = [
        "Maintain profiles on industry-relevant platforms",
        "Respond to questions on Quora and Stack Overflow",
        "Encourage customer reviews on G2 and Trustpilot",
        "Keep Crunchbase profile updated (important for B2B)",
        "Open-source contributions on GitHub boost developer brand authority",
        "Product Hunt launch can generate significant initial buzz",
    ]
    return result


def generate_brand_report(brand_name: str, domain: str = None) -> dict:
    """Generate a comprehensive brand mention report."""
    report = {
        "brand_name": brand_name,
        "domain": domain,
        "analysis_date": "Generated by claude-seo AEO cluster",
        "key_insight": "Brand mentions correlate 3x more strongly with AI visibility than backlinks (Ahrefs Dec 2025, 75K brands)",
        "platforms": {},
        "overall_recommendations": [],
    }
    report["platforms"]["youtube"] = check_youtube_presence(brand_name)
    report["platforms"]["reddit"] = check_reddit_presence(brand_name)
    report["platforms"]["wikipedia"] = check_wikipedia_presence(brand_name)
    report["platforms"]["linkedin"] = check_linkedin_presence(brand_name)
    report["platforms"]["other"] = check_other_platforms(brand_name)
    report["overall_recommendations"] = [
        "Priority 1: YouTube — highest correlation (0.737) with AI citations. Create educational content.",
        "Priority 2: Reddit — build authentic presence in industry subreddits. No marketing speak.",
        "Priority 3: Wikipedia — establish notability through press coverage, then create/improve entry.",
        "Priority 4: LinkedIn — thought leadership content from founders and employees.",
        "Priority 5: Review platforms — G2, Trustpilot, Capterra for social proof signals.",
        "Cross-platform: Ensure consistent NAP (Name, Address, Phone) across all platforms.",
        "Schema markup: Add sameAs property linking to ALL platform profiles.",
        "Monitor: Set up brand mention alerts across all platforms.",
    ]
    return report


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python brand_scanner.py <brand_name> [domain]")
        print("Example: python brand_scanner.py 'Acme Corp' acmecorp.com")
        sys.exit(1)
    brand = sys.argv[1]
    domain = sys.argv[2] if len(sys.argv) > 2 else None
    result = generate_brand_report(brand, domain)
    print(json.dumps(result, indent=2, default=str))
```

- [ ] **Step 2: Write `tests/test_geo_brand_scanner.py`**

```python
"""Tests for scripts/brand_scanner.py — mirrors tests/test_url_safety.py's
pattern to prove the grafted scanner's only real network call
(check_wikipedia_presence) cannot reach private/loopback hosts."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = str(REPO_ROOT / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import brand_scanner  # noqa: E402
import url_safety  # noqa: E402


def test_generate_brand_report_has_all_five_platforms():
    report = brand_scanner.generate_brand_report("Acme Corp", "acmecorp.com")
    assert set(report["platforms"].keys()) == {
        "youtube", "reddit", "wikipedia", "linkedin", "other",
    }


def test_check_wikipedia_presence_uses_safe_requests_get():
    """Confirm the rewired function goes through url_safety, not raw requests."""
    with patch.object(url_safety, "safe_requests_get") as mock_get:
        mock_get.side_effect = url_safety.URLSafetyError("blocked for test")
        result = brand_scanner.check_wikipedia_presence("Acme Corp")
        assert mock_get.called
        assert result["has_wikipedia_page"] is False
        assert result["has_wikidata_entry"] is False


def test_check_wikipedia_presence_never_raises_on_unsafe_target():
    """Even if Wikipedia's own API URL construction were ever attacker-
    influenced, a URLSafetyError must be swallowed, not propagated."""
    with patch.object(
        url_safety, "safe_requests_get",
        side_effect=url_safety.URLSafetyError("blocked"),
    ):
        result = brand_scanner.check_wikipedia_presence("Acme Corp")
        assert isinstance(result, dict)
        assert result["platform"] == "Wikipedia"
```

- [ ] **Step 3: Run the tests**

```bash
pytest tests/test_geo_brand_scanner.py -v
```

Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add scripts/brand_scanner.py tests/test_geo_brand_scanner.py
git commit -m "Graft and rewire brand_scanner.py onto claude-seo's url_safety module"
```

---

### Task 8: Rewire llmstxt_generator.py, gate it behind aeo.llmstxt_mode, add policy test

**Files:**
- Create: `scripts/llmstxt_generator.py`
- Create: `tests/test_llmstxt_policy.py`

**Interfaces:**
- Consumes: `scripts/fetch_page.fetch_page(url, ...) -> dict` (same as Task 6).
- Produces: `validate_llmstxt(url: str) -> dict`, `generate_llmstxt(url: str, max_pages: int = 30, mode: str = "generate") -> dict` — the second gains a new `mode` parameter that raises if `mode == "off"`. Used by `skills/seo-geo/SKILL.md` (Task 9) via the `aeo.llmstxt_mode` config flag.

- [ ] **Step 1: Write `scripts/llmstxt_generator.py`**

```python
#!/usr/bin/env python3
"""
llms.txt Generator — Creates and validates llms.txt files for AI crawler guidance.

llms.txt is reported as a forward-looking, low-confidence signal — NOT a
current ranking or citation lever (see skills/seo-geo/references/llmstxt-evidence.md).
Generation is gated by the aeo.llmstxt_mode config flag: audit | generate | off.
This module must refuse to generate anything when mode == "off".

Location: /llms.txt (root of domain)
Extended: /llms-full.txt (detailed version)
"""

import sys
import json
import re
import os
from urllib.parse import urljoin, urlparse

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("ERROR: Required packages not installed. Run: pip install -r requirements.txt")
    sys.exit(1)

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
from fetch_page import fetch_page  # noqa: E402


class LlmsTxtGenerationDisabledError(RuntimeError):
    """Raised when generate_llmstxt() is called while aeo.llmstxt_mode == 'off'."""


def validate_llmstxt(url: str) -> dict:
    """Check if llms.txt exists and validate its format. Always allowed,
    even under mode == 'off' — auditing presence is not the same as
    generating new files."""
    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    llms_url = f"{base_url}/llms.txt"
    llms_full_url = f"{base_url}/llms-full.txt"

    result = {
        "url": llms_url,
        "exists": False,
        "format_valid": False,
        "has_title": False,
        "has_description": False,
        "has_sections": False,
        "has_links": False,
        "section_count": 0,
        "link_count": 0,
        "content": "",
        "issues": [],
        "suggestions": [],
        "full_version": {"url": llms_full_url, "exists": False},
    }

    fetched = fetch_page(llms_url)
    if not fetched["error"] and fetched["status_code"] == 200:
        result["exists"] = True
        content = fetched["content"] or ""
        result["content"] = content
        lines = content.strip().split("\n")

        if lines and lines[0].startswith("# "):
            result["has_title"] = True
        else:
            result["issues"].append("Missing title (should start with '# Site Name')")

        for line in lines:
            if line.startswith("> "):
                result["has_description"] = True
                break
        if not result["has_description"]:
            result["issues"].append("Missing description (use '> Brief description')")

        sections = [l for l in lines if l.startswith("## ")]
        result["section_count"] = len(sections)
        result["has_sections"] = len(sections) > 0
        if not result["has_sections"]:
            result["issues"].append("No sections found (use '## Section Name')")

        link_pattern = r"- \[.+\]\(.+\)"
        links = re.findall(link_pattern, content)
        result["link_count"] = len(links)
        result["has_links"] = len(links) > 0
        if not result["has_links"]:
            result["issues"].append("No page links found (use '- [Page Title](url): Description')")

        result["format_valid"] = (
            result["has_title"]
            and result["has_description"]
            and result["has_sections"]
            and result["has_links"]
        )

        if result["link_count"] < 5:
            result["suggestions"].append("Consider adding more key pages (aim for 10-20)")
        if result["section_count"] < 2:
            result["suggestions"].append("Add more sections to organize content types")
        if "contact" not in content.lower():
            result["suggestions"].append("Add a Contact section with email and location")
        if "key fact" not in content.lower() and "about" not in content.lower():
            result["suggestions"].append("Add key facts about your business/service")
    elif fetched["error"]:
        result["issues"].append(f"Error fetching llms.txt: {fetched['error']}")
    else:
        result["issues"].append(f"llms.txt returned status {fetched['status_code']}")

    full_fetched = fetch_page(llms_full_url)
    if not full_fetched["error"] and full_fetched["status_code"] == 200:
        result["full_version"]["exists"] = True

    return result


def generate_llmstxt(url: str, max_pages: int = 30, mode: str = "generate") -> dict:
    """Generate an llms.txt file by crawling the site.

    Raises LlmsTxtGenerationDisabledError if mode == 'off' — the caller
    (skills/seo-geo router) is responsible for passing the current
    aeo.llmstxt_mode config value through.
    """
    if mode == "off":
        raise LlmsTxtGenerationDisabledError(
            "llms.txt generation is disabled (aeo.llmstxt_mode = off). "
            "Set aeo.llmstxt_mode to 'generate' to enable."
        )

    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"

    result = {
        "generated_llmstxt": "",
        "generated_llmstxt_full": "",
        "pages_analyzed": 0,
        "sections": {},
    }

    homepage = fetch_page(url)
    if homepage["error"] or not homepage["content"]:
        result["error"] = f"Failed to fetch homepage: {homepage['error'] or 'empty response'}"
        return result

    soup = BeautifulSoup(homepage["content"], "lxml")

    title = soup.find("title")
    site_name = title.get_text(strip=True).split("|")[0].split("-")[0].strip() if title else parsed.netloc
    meta_desc = soup.find("meta", attrs={"name": "description"})
    site_description = meta_desc.get("content", "") if meta_desc else f"Official website of {site_name}"

    pages = {
        "Main Pages": [],
        "Products & Services": [],
        "Resources & Blog": [],
        "Company": [],
        "Support": [],
    }

    seen_urls = set()
    for link in soup.find_all("a", href=True):
        href = urljoin(base_url, link["href"])
        link_text = link.get_text(strip=True)

        if not link_text or len(link_text) < 2:
            continue
        parsed_href = urlparse(href)
        if parsed_href.netloc != parsed.netloc:
            continue
        if href in seen_urls:
            continue
        if any(ext in href for ext in [".pdf", ".jpg", ".png", ".gif", ".css", ".js"]):
            continue
        if "#" in href and href.split("#")[0] in seen_urls:
            continue

        seen_urls.add(href)
        path = parsed_href.path.lower()
        page_entry = {"url": href, "title": link_text}

        if any(kw in path for kw in ["/pricing", "/feature", "/product", "/solution", "/demo"]):
            pages["Products & Services"].append(page_entry)
        elif any(kw in path for kw in ["/blog", "/article", "/resource", "/guide", "/learn", "/docs", "/documentation"]):
            pages["Resources & Blog"].append(page_entry)
        elif any(kw in path for kw in ["/about", "/team", "/career", "/contact", "/press", "/partner"]):
            pages["Company"].append(page_entry)
        elif any(kw in path for kw in ["/help", "/support", "/faq", "/status"]):
            pages["Support"].append(page_entry)
        elif path in ["/", ""] or any(kw in path for kw in ["/home", "/index"]):
            if href != base_url and href != base_url + "/":
                pages["Main Pages"].append(page_entry)
        else:
            pages["Main Pages"].append(page_entry)

        if len(seen_urls) >= max_pages:
            break

    result["pages_analyzed"] = len(seen_urls)

    llms_lines = [f"# {site_name}", f"> {site_description}", ""]
    for section, section_pages in pages.items():
        if section_pages:
            llms_lines.append(f"## {section}")
            for page in section_pages[:10]:
                llms_lines.append(f"- [{page['title']}]({page['url']})")
            llms_lines.append("")
    llms_lines.extend([
        "## Contact",
        f"- Website: {base_url}",
        f"- Email: contact@{parsed.netloc}",
        "",
    ])
    result["generated_llmstxt"] = "\n".join(llms_lines)

    full_lines = [f"# {site_name}", f"> {site_description}", ""]
    for section, section_pages in pages.items():
        if section_pages:
            full_lines.append(f"## {section}")
            for page in section_pages:
                if urlparse(page["url"]).netloc != parsed.netloc:
                    full_lines.append(f"- [{page['title']}]({page['url']})")
                    continue
                page_fetched = fetch_page(page["url"], timeout=10)
                if not page_fetched["error"] and page_fetched["content"]:
                    page_soup = BeautifulSoup(page_fetched["content"], "lxml")
                    page_meta = page_soup.find("meta", attrs={"name": "description"})
                    page_desc = page_meta.get("content", "") if page_meta else ""
                    if page_desc:
                        full_lines.append(f"- [{page['title']}]({page['url']}): {page_desc}")
                    else:
                        full_lines.append(f"- [{page['title']}]({page['url']})")
                else:
                    full_lines.append(f"- [{page['title']}]({page['url']})")
            full_lines.append("")
    full_lines.extend([
        "## Contact",
        f"- Website: {base_url}",
        f"- Email: contact@{parsed.netloc}",
        "",
    ])
    result["generated_llmstxt_full"] = "\n".join(full_lines)
    result["sections"] = {k: len(v) for k, v in pages.items()}

    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python llmstxt_generator.py <url> [mode] [aeo_llmstxt_mode]")
        print("Modes: validate (default), generate")
        print("aeo_llmstxt_mode: audit | generate | off (default: generate)")
        sys.exit(1)

    target_url = sys.argv[1]
    cli_mode = sys.argv[2] if len(sys.argv) > 2 else "validate"
    aeo_mode = sys.argv[3] if len(sys.argv) > 3 else "generate"

    if cli_mode == "validate":
        data = validate_llmstxt(target_url)
    elif cli_mode == "generate":
        try:
            data = generate_llmstxt(target_url, mode=aeo_mode)
        except LlmsTxtGenerationDisabledError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"Unknown mode: {cli_mode}. Use 'validate' or 'generate'.")
        sys.exit(1)

    print(json.dumps(data, indent=2, default=str))
```

- [ ] **Step 2: Write `tests/test_llmstxt_policy.py`**

```python
"""Tests for the aeo.llmstxt_mode gate on scripts/llmstxt_generator.py.
Asserts the generator refuses to run when mode == 'off', per the reconciled
llms.txt policy in skills/seo-geo/SKILL.md."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = str(REPO_ROOT / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import llmstxt_generator  # noqa: E402


def test_generate_llmstxt_refuses_when_mode_is_off():
    with pytest.raises(llmstxt_generator.LlmsTxtGenerationDisabledError):
        llmstxt_generator.generate_llmstxt("https://example.com", mode="off")


def test_generate_llmstxt_default_mode_is_generate():
    """Default mode must be 'generate', not 'off' — validated by inspecting
    the function's own default parameter rather than a network call."""
    import inspect
    sig = inspect.signature(llmstxt_generator.generate_llmstxt)
    assert sig.parameters["mode"].default == "generate"


def test_validate_llmstxt_is_never_gated_by_mode():
    """validate_llmstxt has no mode parameter at all — auditing presence
    must always be allowed regardless of aeo.llmstxt_mode."""
    import inspect
    sig = inspect.signature(llmstxt_generator.validate_llmstxt)
    assert "mode" not in sig.parameters
```

- [ ] **Step 3: Run the tests**

```bash
pytest tests/test_llmstxt_policy.py -v
```

Expected: all PASS.

- [ ] **Step 4: Delete `geo-llmstxt` as a skill folder (it becomes policy, not a skill)**

```bash
rm -rf "/Users/riyamalik/Library/Mobile Documents/com~apple~CloudDocs/ZYRA/claude-seo-x-geo/.graft-src/geo-seo-claude/skills/geo-llmstxt"
```

(Nothing to delete from our repo yet — `skills/geo-llmstxt/` was never copied into this repo. This step just documents that the skill folder from the source repo is intentionally never grafted; only the underlying script is.)

- [ ] **Step 5: Commit**

```bash
git add scripts/llmstxt_generator.py tests/test_llmstxt_policy.py
git commit -m "Graft and rewire llmstxt_generator.py; gate generation behind aeo.llmstxt_mode"
```

---

### Task 9: Rewrite seo-geo/SKILL.md into the AEO router + encode llms.txt policy

**Files:**
- Modify: `skills/seo-geo/SKILL.md`
- Create: `skills/seo-geo/references/aeo-scoring-weights.md`
- Create: `skills/seo-geo/references/sourc-e-framework.md`

**Interfaces:**
- Consumes: the 7 grafted `geo-*` skills (Task 4), `scripts/citability_scorer.py` (Task 6), `scripts/brand_scanner.py` (Task 7), `scripts/llmstxt_generator.py` + `LlmsTxtGenerationDisabledError` (Task 8).
- Produces: the `aeo.llmstxt_mode` config flag documented as the single source of truth other tasks reference (Task 13's `seo-content` citability pass, Task 14's `seo-audit` fan-out).

- [ ] **Step 1: Read the existing `skills/seo-geo/SKILL.md` in full**

```bash
cat "/Users/riyamalik/Library/Mobile Documents/com~apple~CloudDocs/ZYRA/claude-seo-x-geo/skills/seo-geo/SKILL.md"
```

Note its existing frontmatter (`name: seo-geo`, existing `description`), and the two reference files it already links: `references/llmstxt-evidence.md` and `references/google-ai-optimization-guide.md`. Both must remain untouched and still linked from the rewritten body — do not delete or rename them.

- [ ] **Step 2: Replace the body (keep frontmatter's `name` and `metadata.version`, update `description`)**

Update frontmatter description to:

```yaml
description: >
  AEO (Answer Engine Optimization) router and orchestrator. Fans out to the
  first-class geo-* skill cluster (geo-citability, geo-platform-optimizer,
  geo-brand-mentions, geo-crawlers, geo-compare, geo-prospect, geo-proposal)
  and carries the reconciled llms.txt policy. AEO is scored separately from
  SEO — never blended into one number.
```

Replace the body with (insert after frontmatter, before any pre-existing content that isn't the two reference-file links):

```markdown
# seo-geo — AEO Router

This skill no longer scores AEO itself. It routes to the first-class `geo-*`
skill cluster and carries the project-wide llms.txt policy. AEO is a
first-class, separately-scored dimension — an audit must never blend an AEO
number into the SEO score.

## Routing table

| Need | Route to |
|---|---|
| AI citability scoring / passage rewrite suggestions | `geo-citability` (backed by `scripts/citability_scorer.py`) |
| Per-platform optimization (Google AIO, ChatGPT, Perplexity, Gemini, Bing Copilot) | `geo-platform-optimizer` |
| Brand/AI visibility across YouTube, Reddit, Wikipedia, LinkedIn, etc. | `geo-brand-mentions` (backed by `scripts/brand_scanner.py`) |
| AI crawler access audit (GPTBot, ClaudeBot, PerplexityBot, Google-Extended, Bingbot/Copilot) | `geo-crawlers` (also cross-linked from `seo-technical`) |
| Month-over-month AEO delta tracking | `geo-compare` |
| Agency prospect/CRM pipeline | `geo-prospect` |
| Client-facing service proposal generation | `geo-proposal` |
| llms.txt audit/generation | this skill, via the policy below |

## llms.txt policy (reconciled, exact — do not alter without re-reading references/llmstxt-evidence.md)

llms.txt is audited for presence and validity, and can be generated on
request via `scripts/llmstxt_generator.py`. It is reported as a
**forward-looking, low-confidence** signal, explicitly **not** a current
ranking or citation lever. No audit score is gained or lost based on its
presence. Rationale and evidence: [[llmstxt-evidence]].

Config flag: `aeo.llmstxt_mode: audit | generate | off`, default `generate`.

- `audit`: call `scripts/llmstxt_generator.py`'s `validate_llmstxt()` only. Never generate.
- `generate` (default): audit, and generate on explicit user request via `generate_llmstxt(url, mode="generate")`.
- `off`: audit only; `generate_llmstxt(url, mode="off")` raises `LlmsTxtGenerationDisabledError` and must not be called.

This flag lives in the user/project's Claude Code settings (or defaults to
`generate` if unset) and must be threaded through by any caller — including
`seo-audit`'s AEO fan-out (see `skills/seo-audit/SKILL.md`).

## AEO scoring weights (Princeton 2024 GEO study + 2026 citation data)

See [[aeo-scoring-weights]] for the full breakdown. Directional weights, not
guarantees:
- Cited sources / statistics with attribution: strongest positive lift (≈+40% / ≈+37%).
- Front-loading: ≈44% of AI citations come from the first 30% of a page.
- Passage self-containment and question-phrased headings: positive.
- Keyword stuffing / AI-specific keyword rewriting: negative or neutral (≈-10%); do not recommend.

Determinism: citability is scored by `scripts/citability_scorer.py` (0-100),
not free-form judgment. Brand/AI visibility is scored by
`scripts/brand_scanner.py`.

## Methodology references

- [[llmstxt-evidence]] — why llms.txt is not currently consumed by major AI systems.
- [[google-ai-optimization-guide]] — Google's own "AEO/GEO is still SEO" position, myth-busting section.
- [[aeo-scoring-weights]] — Princeton citation-lift weights, encoded as constants in `citability_scorer.py`.
- [[sourc-e-framework]] — StudioHawk SOURC-E framework, summarized in our own words (no verbatim copying — license unclear for redistribution).

## Evidence discipline

Every AEO recommendation keeps a falsifiability check: the observation it
rests on, its dependency, "how would we know it failed," and a leading
indicator — consistent with the rest of this plugin's evidence discipline.
```

- [ ] **Step 3: Write `skills/seo-geo/references/aeo-scoring-weights.md`**

```markdown
# AEO scoring weights — Princeton GEO study + 2026 citation data

These are directional weights used by `scripts/citability_scorer.py` and
referenced by `geo-citability`, `seo-content`'s citability pass, and
`seo-audit`'s AEO fan-out. Treat as directional signals, not guarantees —
no single page-level change is proven to move AI citation rates by an exact
percentage; these figures summarize aggregate research findings.

| Signal | Approximate lift/penalty | Source basis |
|---|---|---|
| Cited sources / statistics with attribution | ≈+40% visibility | Princeton 2024 GEO study |
| Statistics presence (numbers, data points) | ≈+37% visibility | Princeton 2024 GEO study |
| Front-loading (answer in first ~30% of page) | ≈44% of AI citations come from the first 30% of a page | Princeton 2024 GEO study |
| Keyword stuffing / AI-specific keyword rewriting | ≈-10% (negative or neutral) | Princeton 2024 GEO study |
| Passage self-containment (low pronoun density, 134-167 optimal word count) | Positive | `citability_scorer.py` self-containment rubric |
| Question-phrased headings | Positive | `citability_scorer.py` answer-block-quality rubric |

## How these map to `citability_scorer.py`'s rubric

- Answer Block Quality (30% of score): definition patterns, early-answer placement, question-form headings.
- Self-Containment (25%): optimal word count (134-167), low pronoun density, named entities.
- Structural Readability (20%): sentence length distribution, list/step structure, paragraph breaks.
- Statistical Density (15%): percentages, dollar amounts, cited sources, year references.
- Uniqueness Signals (10%): original research language, case-study framing, tool/product specificity.

Last verified: 2026-07-06 (merge date). Re-verify against `citability_scorer.py`
if that script's rubric constants ever change.
```

- [ ] **Step 4: Write `skills/seo-geo/references/sourc-e-framework.md`**

```markdown
# SOURC-E framework — methodology summary (own words, attributed)

StudioHawk publishes a "SOURC-E" framework and citation-share methodology
for AEO/GEO work. License terms for verbatim redistribution of their
materials are unclear, so this is a summary in our own words with
attribution — not a copy of their text.

The framework's core idea, as we understand and apply it: score a page's
AEO readiness across independent dimensions rather than one blended metric,
similar to how this plugin already separates SEO and AEO scores. Dimensions
worth tracking independently, adapted for this plugin's cluster:

- **S**tructure — heading hierarchy, question-phrased headings, scannable format (`geo-citability`'s structural-readability rubric).
- **O**riginality — first-hand data, case studies, unique research (`citability_scorer.py`'s uniqueness-signals rubric).
- **U**ser-intent match — does the passage directly answer the query it targets (`geo-citability`'s answer-block-quality rubric).
- **R**eferences/citations — attributed statistics and sources (`citability_scorer.py`'s statistical-density rubric).
- **C**itation share — how often a brand appears across AI-cited platforms relative to competitors (`geo-compare`, `geo-brand-mentions`).
- **E**ntity clarity — schema markup and brand disambiguation (`seo-schema`'s AI-citation schema section).

This feeds prioritization: when a `geo-citability` or `seo-audit` AEO report
has to rank recommendations, prefer fixes that touch more SOURC-E dimensions
at once (e.g. adding an attributed statistic near the top of a section hits
both References and Structure).

Attribution: methodology inspired by StudioHawk's public SOURC-E framework
and citation-share commentary. This document does not reproduce their text.
```

- [ ] **Step 5: Verify the two pre-existing reference files are still linked (orphan check)**

```bash
grep -l "llmstxt-evidence" skills/seo-geo/SKILL.md && grep -l "google-ai-optimization-guide" skills/seo-geo/SKILL.md && echo OK
```

Expected: `OK` (both filenames/wikilinks still present in the rewritten body — required by `tests/test_manifest_consistency.py::test_reference_files_have_at_least_one_link`, which will run in Task 22).

- [ ] **Step 6: Commit**

```bash
git add skills/seo-geo/SKILL.md skills/seo-geo/references/aeo-scoring-weights.md skills/seo-geo/references/sourc-e-framework.md
git commit -m "Rewrite seo-geo into AEO router; encode llms.txt policy and scoring weights"
```

---

### Task 10: geo-compare dedup check — graft or fold

**Files:**
- Read: `skills/seo-geo/SKILL.md` (already rewritten, Task 9), `skills/seo-flow/SKILL.md`
- Read: `.graft-src/geo-seo-claude/skills/geo-compare/SKILL.md`
- Create (conditionally): `skills/geo-compare/SKILL.md`, `skills/geo-compare/LICENSE.txt` — only if the check in Step 1 concludes "not a duplicate"

**Interfaces:**
- Consumes: existing claude-seo "AI Share-of-Voice tracking" capability (referenced in `plugin.json`'s current description and somewhere in `seo-geo`/`seo-flow`).
- Produces: either a 7th grafted geo skill (bringing the grafted total to 7, matching spec §4's final count), or a documented decision to fold `geo-compare`'s unique delta-tracking logic into an existing skill instead.

- [ ] **Step 1: Read what claude-seo's existing "AI Share-of-Voice tracking" actually does**

```bash
grep -ril "share.of.voice\|share of voice" skills/ scripts/
```

Read whatever files this returns in full. `geo-compare`'s actual function (per Task 2's clone) is: **monthly delta tracking between two audits of the same site** — comparing a baseline GEO audit vs. a current one, calculating score deltas per category, tracking action-item completion, and generating a client progress report. This is a different function from "AI Share-of-Voice" (which typically means: how often does OUR brand get cited vs. competitors, for the same query, across AI platforms — a snapshot comparison across brands, not a before/after comparison of the same site over time).

- [ ] **Step 2: Make the call using this test**

If the grep in Step 1 turns up a skill/script that already does before/after delta tracking of the same site's own scores over time (not brand-vs-competitor comparison), that's a true duplicate — fold `geo-compare`'s unique bits (the 6-month trajectory tracking, the client-facing progress report template) into that skill and do not graft `geo-compare` as standalone. Otherwise (the existing capability is brand-vs-competitor citation share, which is a different function), graft `geo-compare` as the 7th first-class geo skill, matching spec §4.

- [ ] **Step 3a (if grafting): copy and normalize exactly like Task 4**

```bash
cd "/Users/riyamalik/Library/Mobile Documents/com~apple~CloudDocs/ZYRA/claude-seo-x-geo"
cp -r ".graft-src/geo-seo-claude/skills/geo-compare" "skills/geo-compare"
cat > "skills/geo-compare/LICENSE.txt" <<'EOF'
MIT License

Portions derived from zubair-trabzada/geo-seo-claude (MIT).
See /LICENSES/geo-seo-claude-LICENSE.txt for the original license text and
/NOTICE.md for full attribution.

Copyright (c) 2026 Zubair Trabzada
Copyright (c) 2026 agricidaniel (fork integration)
EOF
```

Then apply the same frontmatter normalization as Task 4 Step 3 (nested `metadata:\n  version: "3.0.0"`), verify with the same Python snippet as Task 4 Step 4 (extend the skill list to include `geo-compare`), and update the routing table row in `skills/seo-geo/SKILL.md` (Task 9) if it says "graft after check" anywhere — it doesn't (Task 9's routing table already lists `geo-compare` unconditionally), so no further edit needed there.

- [ ] **Step 3b (if folding instead): document the decision**

Add a one-paragraph note to `skills/seo-geo/SKILL.md`'s routing table row for `geo-compare`, replacing "Month-over-month AEO delta tracking → `geo-compare`" with the actual destination skill, and copy `geo-compare`'s 6-month trajectory tracking and progress-report-template logic into that destination skill's `SKILL.md` as a new subsection. In this branch, the final skill count is 31, not 32 — update the Global Constraints section at the top of this plan file and every later task that assumes "32 skills" (Tasks 19, 22) to say 31 instead, and note the reason in the commit message.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "Resolve geo-compare dedup check: graft as 7th geo-* skill" # or "fold geo-compare into <destination>" if 3b was taken
```

---

### Task 11: Fold geo-schema into seo-schema; delete geo-schema

**Files:**
- Modify: `skills/seo-schema/SKILL.md`
- Modify: `schema/` (add missing JSON templates — see Task 18, do not duplicate here)
- Delete: nothing yet to delete (geo-schema was never copied into this repo — it only exists in `.graft-src/`)

**Interfaces:**
- Consumes: `.graft-src/geo-seo-claude/skills/geo-schema/SKILL.md` (AI-citation schema emphasis), `.graft-src/geo-seo-claude/agents/geo-schema.md` (Organization/Person schema detail, sameAs properties).
- Produces: an "AI-citation-oriented schema" section inside `seo-schema/SKILL.md`.

- [ ] **Step 1: Read the existing file to find its section structure**

```bash
grep -n "^## " skills/seo-schema/SKILL.md
```

- [ ] **Step 2: Insert a new section**

Insert immediately before the file's existing deprecation-table section (or, if none is found by that name, immediately before the final "Testing" / "Validation" section — whichever comes first in the `grep -n "^## "` output from Step 1):

```markdown
## AI-citation-oriented schema (AEO)

Beyond classic SEO schema validity, these Schema.org types carry specific
weight for AI citation and entity recognition — folded in from
geo-seo-claude's `geo-schema` module:

- **Organization** — critical for entity recognition. AI systems use this to
  disambiguate "which brand is this page about," especially when `sameAs`
  links to Wikipedia, Wikidata, LinkedIn, Crunchbase, and other
  AI-cited platforms (cross-reference `geo-brand-mentions`). Missing or
  incomplete Organization schema is a common reason a page ranks well in
  classic SEO but is never cited by an AI answer engine.
- **Person** (author) — pairs with E-E-A-T signals. AI systems weigh
  byline authorship more heavily than classic SERPs do, particularly for
  YMYL content.
- **FAQPage-as-entity-signal** — not for "FAQ rich snippet" purposes (Google
  has scaled back FAQ rich results), but because a well-formed FAQPage block
  gives an AI answer engine a pre-structured, self-contained Q&A pair it can
  extract directly. Use sparingly — only for genuine, non-duplicative FAQs.

These are additive to classic SEO schema requirements below, not a
replacement — see the deprecation table above/below for what Google has
deprecated for search-result purposes specifically.

Import missing templates from `schema/` if this project lacks them:
`schema/software-saas.json`, `schema/article-author.json` (see Task 18 for
the selective merge that adds these two files).
```

- [ ] **Step 3: Commit**

```bash
git add skills/seo-schema/SKILL.md
git commit -m "Fold geo-schema's AI-citation schema emphasis into seo-schema"
```

---

### Task 12: Fold geo-technical (+ cross-link geo-crawlers) into seo-technical; delete geo-technical

**Files:**
- Modify: `skills/seo-technical/SKILL.md`

**Interfaces:**
- Consumes: `.graft-src/geo-seo-claude/skills/geo-technical/SKILL.md` (AI crawler reference table), `skills/geo-crawlers/SKILL.md` (Task 4 — already grafted, full depth lives there).

- [ ] **Step 1: Read the existing file's section structure**

```bash
grep -n "^## " skills/seo-technical/SKILL.md
```

- [ ] **Step 2: Insert a new subsection**

Insert as a new subsection within (or immediately after) the existing crawlability/indexability section — keep claude-seo's CWV/INP logic as the file's primary/authoritative content; do not remove or dilute it:

```markdown
### AI crawler accessibility (AEO)

Beyond classic Googlebot/Bingbot crawlability, check robots.txt rules for
the AI crawlers below. This is a summary table — full analysis, per-crawler
recommendations, and a complete Tier 1/2/3 reference lives in the
`geo-crawlers` skill; run that skill for the full audit.

| Crawler | Operator | Purpose |
|---|---|---|
| GPTBot | OpenAI | Training data / ChatGPT browsing |
| ClaudeBot | Anthropic | Training data / Claude web search |
| PerplexityBot | Perplexity | Answer-engine indexing |
| Google-Extended | Google | Controls use in Gemini/AI Overviews training (separate from Googlebot's classic indexing directive) |
| Bingbot / Copilot | Microsoft | Classic indexing + Bing Copilot answer sourcing |

Blocking these does not affect classic Google/Bing search rankings — it
only controls whether that specific AI system's answer engine or model
training can access the page. Recommend allowing them unless the client has
an explicit content-licensing objection; blocking is a business decision,
not a technical-SEO best practice.

Core Web Vitals, INP, and the rest of this skill's technical checks remain
authoritative and unchanged by this AEO addition — see the sections above.
```

- [ ] **Step 3: Commit**

```bash
git add skills/seo-technical/SKILL.md
git commit -m "Fold geo-technical's AI crawler accessibility check into seo-technical, cross-linked to geo-crawlers"
```

---

### Task 13: Fold geo-content into seo-content (citability pass); delete geo-content

**Files:**
- Modify: `skills/seo-content/SKILL.md`

**Interfaces:**
- Consumes: `scripts/citability_scorer.py::analyze_page_citability(url) -> dict` (Task 6), `skills/seo-geo/references/aeo-scoring-weights.md` (Task 9, for the front-loading rule).

- [ ] **Step 1: Read the existing file's section structure**

```bash
grep -n "^## " skills/seo-content/SKILL.md
```

- [ ] **Step 2: Insert a new section**

Insert as a new top-level section, positioned after any existing E-E-A-T section and before any final "Output format" / "Report structure" section:

```markdown
## Citability pass (AEO)

Every content audit run through this skill also runs a deterministic
citability pass via `scripts/citability_scorer.py::analyze_page_citability(url)`.
This returns a 0-100 score per content block plus a page-level average — it
is not free-form judgment. Report this as a distinct **AEO citability score**,
never averaged into this skill's SEO/content-quality score.

### Front-loading check (mandatory, not just guidance)

Per [[aeo-scoring-weights]], approximately 44% of AI citations come from the
first 30% of a page. This skill's content check must explicitly verify:

1. Does each major H2/H3 section open with a direct, self-contained answer
   in its first 1-3 sentences (not a lead-in, not a rhetorical question)?
2. Is the single most important fact/answer on the page located within the
   first 30% of total word count?

If either check fails, flag it as a specific, actionable finding — "Section
X buries its answer after 400 words of preamble" — not a vague "improve
readability" note.

### What this pass does NOT recommend

Per the evidence in `skills/seo-geo/references/google-ai-optimization-guide.md`
and this plugin's AEO stance (see root `CLAUDE.md`), do not recommend:
keyword stuffing, AI-specific keyword rewriting/long-tail variant stuffing,
or content "chunking" purely for AI parsing. These are neutral-to-negative
per the Princeton weights in [[aeo-scoring-weights]].
```

- [ ] **Step 3: Commit**

```bash
git add skills/seo-content/SKILL.md
git commit -m "Fold geo-content's citability pass and front-loading check into seo-content"
```

---

### Task 14: Fold geo-audit into seo-audit (AEO fan-out, separate scores); delete geo-audit

**Files:**
- Modify: `skills/seo-audit/SKILL.md`

**Interfaces:**
- Consumes: all 7 (or 6, per Task 10's outcome) grafted `geo-*` skills, `scripts/citability_scorer.py`, `scripts/brand_scanner.py`, `aeo.llmstxt_mode` policy (Task 9).
- Produces: the final `/seo audit <url>` report shape that Task 22's smoke test verifies — must show separate SEO and AEO scores.

- [ ] **Step 1: Read the existing file's orchestration section**

```bash
grep -n "^## " skills/seo-audit/SKILL.md
```

- [ ] **Step 2: Insert a new section describing the AEO fan-out**

Insert as a new section immediately before whatever section currently describes final report assembly/output:

```markdown
## AEO fan-out (distinct scored track)

A full `seo-audit` run additionally fans out to the AEO cluster as a
**separate, parallel scored track** — never blended into the SEO score
computed above. Specifically:

1. Run `scripts/citability_scorer.py::analyze_page_citability(url)` for the
   deterministic 0-100 citability figure.
2. Run `geo-platform-optimizer` for per-platform readiness notes (Google
   AIO, ChatGPT, Perplexity, Gemini, Bing Copilot).
3. Run `geo-crawlers` for AI-crawler-access findings (GPTBot, ClaudeBot,
   PerplexityBot, Google-Extended, Bingbot/Copilot).
4. Run `scripts/brand_scanner.py::generate_brand_report(brand, domain)` for
   brand/AI-visibility findings, if a brand name is available.
5. Audit llms.txt via `scripts/llmstxt_generator.py::validate_llmstxt(url)`,
   respecting the current `aeo.llmstxt_mode` (see `skills/seo-geo/SKILL.md`)
   — generate only if mode is `generate` and the user explicitly asks.

### Final report structure (mandatory)

The audit report must present:

```
## SEO Score: <0-100>
<existing SEO category breakdown, unchanged>

## AEO Score: <0-100 citability figure from citability_scorer.py>
- Per-platform notes: AIO / ChatGPT / Perplexity / Gemini / Bing Copilot
- AI-crawler-access findings: GPTBot / ClaudeBot / PerplexityBot / Google-Extended / Bingbot-Copilot
- Brand/AI-visibility findings (if brand name available)
- llms.txt status (forward-looking, low-confidence — see policy)
```

**These two scores are never averaged, weighted together, or presented as a
single number.** A page can score 95 SEO / 40 AEO or vice versa — that
divergence is the point of treating AEO as first-class.
```

- [ ] **Step 3: Commit**

```bash
git add skills/seo-audit/SKILL.md
git commit -m "Extend seo-audit orchestrator to fan out to the AEO cluster as a distinct scored track"
```

---

### Task 15: Delete the remaining superseded geo skills (nothing to actually delete — confirm never grafted)

**Files:**
- Verify only — no files created or modified in this repo.

**Interfaces:**
- Consumes: nothing new.

- [ ] **Step 1: Confirm none of the 8 merge-and-delete skills were ever copied into this repo**

```bash
cd "/Users/riyamalik/Library/Mobile Documents/com~apple~CloudDocs/ZYRA/claude-seo-x-geo"
for skill in geo-audit geo-content geo-schema geo-technical geo-report geo-report-pdf geo-llmstxt geo-update; do
  if [ -d "skills/$skill" ]; then
    echo "FAIL: skills/$skill exists and must be deleted"
  else
    echo "OK: skills/$skill correctly absent"
  fi
done
```

Expected: `OK: skills/<name> correctly absent` for all 8 — because Tasks 4/10/11/12/13/14 only ever grafted the 7 first-class skills and folded logic from the other 8 by reading `.graft-src/`, never by copying those 8 folders into `skills/`. If any of them shows `FAIL`, an earlier task's Step 1 was executed incorrectly (a `cp -r` of a merge-and-delete skill instead of a graft-list skill) — remove it with `rm -rf skills/<name>` and re-verify.

- [ ] **Step 2: No commit needed if all checks pass (nothing changed). If a FAIL was corrected, commit the removal:**

```bash
git add -A
git commit -m "Remove accidentally-grafted merge-and-delete geo skill folder(s)"
```

---

### Task 16: Build extensions/geo-dashboard/ (optional, Flask/rich confined here)

**Files:**
- Create: `extensions/geo-dashboard/install.sh`
- Create: `extensions/geo-dashboard/install.ps1`
- Create: `extensions/geo-dashboard/uninstall.sh`
- Create: `extensions/geo-dashboard/skills/geo-dashboard/SKILL.md`
- Create: `extensions/geo-dashboard/docs/GEO-DASHBOARD-SETUP.md`
- Create: `extensions/geo-dashboard/scripts/crm_dashboard.py`
- Create: `extensions/geo-dashboard/templates/geo-report-style.css`, `extensions/geo-dashboard/templates/geo-report-template.html`
- Modify: `requirements.txt` (add the flask/rich comment block — see Task 19, don't duplicate here)

**Interfaces:**
- Consumes: `.graft-src/geo-seo-claude/scripts/crm_dashboard.py`, `.graft-src/geo-seo-claude/scripts/webapp/`, `.graft-src/geo-seo-claude/templates/`, the `extensions/profound/install.sh` pattern (already in this repo, copied in Task 1) as the structural template.

- [ ] **Step 1: Copy the dashboard script, webapp, and templates**

```bash
cd "/Users/riyamalik/Library/Mobile Documents/com~apple~CloudDocs/ZYRA/claude-seo-x-geo"
mkdir -p extensions/geo-dashboard/scripts extensions/geo-dashboard/templates extensions/geo-dashboard/skills/geo-dashboard extensions/geo-dashboard/docs
cp .graft-src/geo-seo-claude/scripts/crm_dashboard.py extensions/geo-dashboard/scripts/crm_dashboard.py
cp -r .graft-src/geo-seo-claude/scripts/webapp extensions/geo-dashboard/scripts/webapp
cp .graft-src/geo-seo-claude/templates/geo-report-style.css extensions/geo-dashboard/templates/
cp .graft-src/geo-seo-claude/templates/geo-report-template.html extensions/geo-dashboard/templates/
```

- [ ] **Step 2: Write `extensions/geo-dashboard/install.sh`, following the `extensions/profound/install.sh` pattern**

```bash
#!/usr/bin/env bash
# Claude SEO x GEO — optional CRM/report dashboard extension installer.
#
# Installs the Rich-based CLI dashboard for viewing GEO prospect/audit data.
# This is the ONLY place flask/rich are used in this plugin — never a core
# dependency of any skill.
set -euo pipefail

main() {
    SKILL_DIR="${HOME}/.claude/skills"

    echo "════════════════════════════════════════"
    echo "║  Claude SEO x GEO — Dashboard extension ║"
    echo "════════════════════════════════════════"

    command -v python3 >/dev/null 2>&1 || { echo "✗ Python 3 required."; exit 1; }
    [ ! -d "${SKILL_DIR}/seo" ] && { echo "✗ claude-seo base not installed."; exit 1; }

    SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" >/dev/null 2>&1 && pwd)"

    pip install "flask>=3.0.0,<4.0.0" "rich>=13.0.0,<14.0.0"

    mkdir -p "${SKILL_DIR}/geo-dashboard"
    cp "${SOURCE_DIR}/skills/geo-dashboard/SKILL.md" "${SKILL_DIR}/geo-dashboard/SKILL.md"
    cp -r "${SOURCE_DIR}/scripts" "${SKILL_DIR}/geo-dashboard/scripts"
    cp -r "${SOURCE_DIR}/templates" "${SKILL_DIR}/geo-dashboard/templates"

    echo "Done. Try: python3 ${SKILL_DIR}/geo-dashboard/scripts/crm_dashboard.py"
}
main "$@"
```

- [ ] **Step 3: Write `extensions/geo-dashboard/install.ps1`**

```powershell
# Claude SEO x GEO — optional CRM/report dashboard extension installer (Windows).
$ErrorActionPreference = "Stop"

$SkillDir = "$env:USERPROFILE\.claude\skills"
Write-Host "========================================"
Write-Host "  Claude SEO x GEO -- Dashboard extension"
Write-Host "========================================"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "Python 3 required."
    exit 1
}
if (-not (Test-Path "$SkillDir\seo")) {
    Write-Error "claude-seo base not installed."
    exit 1
}

$SourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path

pip install "flask>=3.0.0,<4.0.0" "rich>=13.0.0,<14.0.0"

New-Item -ItemType Directory -Force -Path "$SkillDir\geo-dashboard" | Out-Null
Copy-Item "$SourceDir\skills\geo-dashboard\SKILL.md" "$SkillDir\geo-dashboard\SKILL.md"
Copy-Item -Recurse -Force "$SourceDir\scripts" "$SkillDir\geo-dashboard\scripts"
Copy-Item -Recurse -Force "$SourceDir\templates" "$SkillDir\geo-dashboard\templates"

Write-Host "Done. Try: python $SkillDir\geo-dashboard\scripts\crm_dashboard.py"
```

- [ ] **Step 4: Write `extensions/geo-dashboard/uninstall.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
SKILL_DIR="${HOME}/.claude/skills/geo-dashboard"
[ -d "${SKILL_DIR}" ] && rm -rf "${SKILL_DIR}" && echo "✓ Removed ${SKILL_DIR}"
echo "Note: flask/rich were installed via pip and are left in place — remove manually with 'pip uninstall flask rich' if desired."
```

- [ ] **Step 5: Write `extensions/geo-dashboard/skills/geo-dashboard/SKILL.md`**

```yaml
---
name: geo-dashboard
description: >
  Optional CRM/report dashboard for viewing GEO prospect and audit data via
  a Rich-based terminal UI. Not a core skill — installed separately via
  extensions/geo-dashboard/install.sh. No core claude-seo skill depends on
  this extension or imports flask/rich.
metadata:
  version: "3.0.0"
  author: geo-seo-claude (grafted, extension-only)
---

# geo-dashboard

Run `python3 scripts/crm_dashboard.py` to view the prospect CRM summary, or
`--prospect PRO-001` for a single prospect's detail view, or `--refresh` to
update and display. Reads from `~/.geo-prospects/prospects.json`,
`~/.geo-prospects/audits/`, and `~/.geo-prospects/proposals/` — the same
data directories used by the `geo-prospect` and `geo-proposal` core skills.

This skill requires `flask` and `rich`, installed by
`extensions/geo-dashboard/install.sh` — never a dependency of any core
`seo-*` or `geo-*` skill.
```

- [ ] **Step 6: Write `extensions/geo-dashboard/docs/GEO-DASHBOARD-SETUP.md`**

```markdown
# GEO Dashboard extension setup

Optional. Installs a Rich-based terminal dashboard for viewing
`geo-prospect`/`geo-proposal` CRM data and GEO audit reports.

## Install (macOS/Linux)

```bash
bash extensions/geo-dashboard/install.sh
```

## Install (Windows)

```powershell
extensions\geo-dashboard\install.ps1
```

## Uninstall

```bash
bash extensions/geo-dashboard/uninstall.sh
```

This extension is never required by any core skill — `flask` and `rich` are
only imported by files under `extensions/geo-dashboard/`.
```

- [ ] **Step 7: Verify no core script imports flask/rich**

```bash
grep -rl "^import flask\|^from flask\|^import rich\|^from rich" scripts/ skills/ | grep -v extensions/ || echo "OK: no core import of flask/rich"
```

Expected: `OK: no core import of flask/rich`

- [ ] **Step 8: Commit**

```bash
chmod +x extensions/geo-dashboard/install.sh extensions/geo-dashboard/uninstall.sh
git add extensions/geo-dashboard
git commit -m "Move geo's CRM dashboard to extensions/geo-dashboard/ (optional, Flask/rich confined here)"
```

---

### Task 17: Build extensions/gsc-mcp/ (optional, OAuth-free GSC alternative)

**Files:**
- Create: `extensions/gsc-mcp/install.sh`
- Create: `extensions/gsc-mcp/install.ps1`
- Create: `extensions/gsc-mcp/uninstall.sh`
- Create: `extensions/gsc-mcp/skills/seo-gsc-mcp/SKILL.md`
- Create: `extensions/gsc-mcp/docs/GSC-MCP-SETUP.md`

**Interfaces:**
- Consumes: the `extensions/profound/install.sh` pattern (structural template, same as Task 16).
- Produces: an optional MCP-server wiring for Google Search Console, documented as an alternative to (never a replacement for) `seo-google`'s native `google-api-python-client` path.

- [ ] **Step 1: Write `extensions/gsc-mcp/install.sh`**

```bash
#!/usr/bin/env bash
# Claude SEO x GEO — optional Google Search Console MCP extension installer.
#
# This is an OAuth-free ALTERNATIVE to the native GSC path already provided
# by skills/seo-google (scripts/gsc_query.py, scripts/gsc_inspect.py). It is
# for operators who want live GSC data without setting up a GCP OAuth app.
# No core skill depends on this extension.
set -euo pipefail

main() {
    SKILL_DIR="${HOME}/.claude/skills"
    SETTINGS_JSON="${HOME}/.claude/settings.json"

    echo "════════════════════════════════════════"
    echo "║   Claude SEO x GEO — GSC-MCP extension   ║"
    echo "════════════════════════════════════════"
    echo "This wires a Google Search Console MCP server as an OAuth-free"
    echo "alternative to the native seo-google GSC integration."
    echo

    command -v node >/dev/null 2>&1 || { echo "✗ Node.js required for the MCP server."; exit 1; }
    [ ! -d "${SKILL_DIR}/seo" ] && { echo "✗ claude-seo base not installed."; exit 1; }
    command -v claude >/dev/null 2>&1 || { echo "✗ Claude Code CLI required (for 'claude mcp add')."; exit 1; }

    SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" >/dev/null 2>&1 && pwd)"

    read -rp "Path to your Google Search Console MCP server package (npm package name or local path): " GSC_MCP_PACKAGE
    [ -z "${GSC_MCP_PACKAGE}" ] && { echo "✗ No package specified."; exit 1; }

    claude mcp add gsc-mcp -- npx -y "${GSC_MCP_PACKAGE}"

    mkdir -p "${SKILL_DIR}/seo-gsc-mcp"
    cp "${SOURCE_DIR}/skills/seo-gsc-mcp/SKILL.md" "${SKILL_DIR}/seo-gsc-mcp/SKILL.md"

    echo "Done. This extension does not replace seo-google's native GSC path —"
    echo "it is documented as an alternative. Try: /seo gsc-mcp sites"
}
main "$@"
```

- [ ] **Step 2: Write `extensions/gsc-mcp/install.ps1`**

```powershell
# Claude SEO x GEO — optional Google Search Console MCP extension installer (Windows).
$ErrorActionPreference = "Stop"

$SkillDir = "$env:USERPROFILE\.claude\skills"
Write-Host "========================================"
Write-Host "  Claude SEO x GEO -- GSC-MCP extension"
Write-Host "========================================"
Write-Host "OAuth-free alternative to the native seo-google GSC integration."

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Error "Node.js required for the MCP server."
    exit 1
}
if (-not (Test-Path "$SkillDir\seo")) {
    Write-Error "claude-seo base not installed."
    exit 1
}
if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    Write-Error "Claude Code CLI required (for 'claude mcp add')."
    exit 1
}

$SourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$GscMcpPackage = Read-Host "Path to your Google Search Console MCP server package (npm package name or local path)"
if ([string]::IsNullOrEmpty($GscMcpPackage)) {
    Write-Error "No package specified."
    exit 1
}

claude mcp add gsc-mcp -- npx -y $GscMcpPackage

New-Item -ItemType Directory -Force -Path "$SkillDir\seo-gsc-mcp" | Out-Null
Copy-Item "$SourceDir\skills\seo-gsc-mcp\SKILL.md" "$SkillDir\seo-gsc-mcp\SKILL.md"

Write-Host "Done. This extension does not replace seo-google's native GSC path."
Write-Host "Try: /seo gsc-mcp sites"
```

- [ ] **Step 3: Write `extensions/gsc-mcp/uninstall.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
SKILL_DIR="${HOME}/.claude/skills/seo-gsc-mcp"
[ -d "${SKILL_DIR}" ] && rm -rf "${SKILL_DIR}" && echo "✓ Removed ${SKILL_DIR}"
command -v claude >/dev/null 2>&1 && claude mcp remove gsc-mcp 2>/dev/null && echo "✓ Removed gsc-mcp MCP server registration" || true
```

- [ ] **Step 4: Write `extensions/gsc-mcp/skills/seo-gsc-mcp/SKILL.md`**

```yaml
---
name: seo-gsc-mcp
description: >
  OAuth-free alternative to seo-google's native Google Search Console
  integration, via an MCP server. Documented as an alternative, not a
  requirement — the native google-api-python-client path in seo-google
  (scripts/gsc_query.py, scripts/gsc_inspect.py) remains the primary,
  test-covered GSC integration for this plugin.
metadata:
  version: "3.0.0"
  author: GrowthZyra (new, extension-only)
---

# seo-gsc-mcp

Installed via `extensions/gsc-mcp/install.sh` (or `.ps1` on Windows). Wires a
Google Search Console MCP server for operators who want live GSC data
(Search Analytics, URL Inspection, Sitemaps) without setting up a GCP OAuth
app themselves.

**This does not replace `seo-google`.** Prefer `seo-google`'s native path
(`scripts/gsc_query.py`, `scripts/gsc_inspect.py`) whenever OAuth setup is
feasible — it is deterministic and covered by `tests/test_gsc_query.py`.
Use this extension only when the operator explicitly wants the OAuth-free
path.

## Usage

Once installed, GSC data is available through whatever tool names the
configured MCP server exposes (server-dependent — check the server's own
documentation for exact tool names). Typical operations: list verified
sites, query Search Analytics (clicks/impressions/CTR/position by
query/page/date), request URL inspection status, list/submit sitemaps.

Cross-reference `seo-google/SKILL.md` for what live GSC data feeds into
which claude-seo report sections — the same report sections apply
regardless of which GSC integration (native or MCP) supplied the data.
```

- [ ] **Step 5: Write `extensions/gsc-mcp/docs/GSC-MCP-SETUP.md`**

```markdown
# GSC-MCP extension setup

Optional. OAuth-free alternative to `seo-google`'s native Google Search
Console integration (`scripts/gsc_query.py`, `scripts/gsc_inspect.py`),
which remains this plugin's primary, test-covered GSC path.

Requires: Node.js, the Claude Code CLI, and a Google Search Console MCP
server package (you supply the package name/path during install — this
extension does not bundle a specific MCP server implementation).

## Install (macOS/Linux)

```bash
bash extensions/gsc-mcp/install.sh
```

## Install (Windows)

```powershell
extensions\gsc-mcp\install.ps1
```

## Uninstall

```bash
bash extensions/gsc-mcp/uninstall.sh
```

No core skill depends on this extension — `seo-google` continues to work
via native OAuth whether or not this extension is installed.
```

- [ ] **Step 6: Commit**

```bash
chmod +x extensions/gsc-mcp/install.sh extensions/gsc-mcp/uninstall.sh
git add extensions/gsc-mcp
git commit -m "Add optional extensions/gsc-mcp/ as OAuth-free alternative to native GSC"
```

---

### Task 18: White-label integration into google_report.py + selective schema JSON merge

**Files:**
- Create: `scripts/brand_config.py`
- Modify: `scripts/google_report.py`
- Create: `schema/software-saas.json`, `schema/article-author.json` (only if missing — check first)

**Interfaces:**
- Consumes: `.graft-src/geo-seo-claude/white-label/brand_config.py`, `.graft-src/geo-seo-claude/white-label/brand.example.json`, `.graft-src/geo-seo-claude/schema/*.json`.
- Produces: `brand_config.load_brand(config_path=None) -> dict`, consumed by `scripts/google_report.py`'s report-generation entry point.

- [ ] **Step 1: Copy `brand_config.py` verbatim**

```bash
cd "/Users/riyamalik/Library/Mobile Documents/com~apple~CloudDocs/ZYRA/claude-seo-x-geo"
cp .graft-src/geo-seo-claude/white-label/brand_config.py scripts/brand_config.py
cp .graft-src/geo-seo-claude/white-label/brand.example.json brand.example.json
```

- [ ] **Step 2: Check which of the 6 schema JSON files claude-seo already has**

```bash
diff <(ls schema/) <(ls .graft-src/geo-seo-claude/schema/)
```

Compare filenames case-insensitively too, since claude-seo may already have equivalents under different names (its own `schema_generate.py` and `schema_ecommerce_validate.py` scripts suggest it likely already covers `product-ecommerce`, `local-business`, `organization`, and `website-searchaction` in some form). Per spec §5, only add `software-saas.json` and `article-author.json` if claude-seo genuinely lacks equivalent generators — confirm by reading `scripts/schema_generate.py` for its list of supported `@type` values before copying anything.

- [ ] **Step 3: Copy only the confirmed-missing schema templates**

```bash
grep -o '"@type":\s*"[A-Za-z]*"' scripts/schema_generate.py | sort -u
```

If `SoftwareApplication` is absent from that output, copy `schema/software-saas.json`:
```bash
cp .graft-src/geo-seo-claude/schema/software-saas.json schema/software-saas.json
```
If a dedicated author/Person-focused article template is absent (distinct from a generic `Article` generator), copy `schema/article-author.json`:
```bash
cp .graft-src/geo-seo-claude/schema/article-author.json schema/article-author.json
```
Do not copy `local-business.json`, `organization.json`, `product-ecommerce.json`, or `website-searchaction.json` unless the same check in Step 2/3 shows claude-seo has no equivalent — the expectation per the spec is that claude-seo already covers these (it ships `schema_ecommerce_validate.py` specifically for ecommerce/product schema).

- [ ] **Step 4: Read `scripts/google_report.py`'s report-generation entry point**

```bash
grep -n "^def \|^class " scripts/google_report.py | head -30
```

- [ ] **Step 5: Wire `brand_config` into the report generator**

Add near the top of `scripts/google_report.py`, alongside its other imports:

```python
from brand_config import load_brand
```

Find the function that builds the report's title/header/branding (search for where the report's title string or PDF cover metadata is assembled — likely near a call to `weasyprint` or wherever HTML is rendered), and thread a `brand_config_path: Optional[str] = None` parameter through to that function, defaulting to `None` (no white-label — uses `brand_config.DEFAULT_BRAND`). Inside that function, add:

```python
brand = load_brand(brand_config_path)
# Use brand["name"], brand["colors"]["primary"], etc. in place of any
# hardcoded "Claude SEO" / default color constants in the report header,
# cover page, and footer.
```

This is a targeted, additive change — do not restructure `google_report.py`'s existing report-building logic, only thread the `brand` dict through to whatever currently hardcodes the report's display name and color scheme.

- [ ] **Step 6: Verify the import resolves and nothing else broke**

```bash
python3 -c "import sys; sys.path.insert(0, 'scripts'); import google_report; print('OK')"
```

Expected: `OK` (or a clear, pre-existing missing-dependency error unrelated to this change — if so, that dependency was already missing before this task and is out of scope).

- [ ] **Step 7: Commit**

```bash
git add scripts/brand_config.py scripts/google_report.py brand.example.json schema/ 2>/dev/null
git commit -m "Integrate white-label branding into google_report.py; selectively merge missing schema templates"
```

---

### Task 19: Update requirements.txt, manifests, version strings, CLAUDE.md, README, CHANGELOG

**Files:**
- Modify: `requirements.txt`
- Modify: `.claude-plugin/plugin.json`
- Modify: `.claude-plugin/marketplace.json`
- Modify: `CITATION.cff`
- Modify: `pyproject.toml`
- Modify: `install.sh`, `install.ps1`
- Modify: `CLAUDE.md`
- Modify: `README.md`, `AGENTS.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: the exact skill/agent counts finalized by Tasks 4–15 (32 skills if Task 10 grafted `geo-compare`, else 31; 20 agents).
- Produces: the version/count strings that `tests/test_manifest_consistency.py` (already ground-truthed in Task 22's prep) will assert against.

- [ ] **Step 1: Append to `requirements.txt`**

```
# AEO dashboard (optional extension: extensions/geo-dashboard)
flask>=3.0.0,<4.0.0
rich>=13.0.0,<14.0.0
```

Do not change any existing line in this file — claude-seo's floors (`lxml>=6.1.1,<7.0.0`, `playwright>=1.59.0,<2.0.0`, `Pillow>=12.2.0,<13.0.0`, `urllib3>=2.7.0,<3.0.0`, etc.) all stay exactly as imported in Task 1.

- [ ] **Step 2: Update `.claude-plugin/plugin.json`**

Bump `"version": "2.2.0"` to `"version": "3.0.0"`.

Replace the `"description"` value. The canonical phrasing must follow the pattern `test_canonical_math_adds_up` enforces: `"N sub-skills (X core + Y orchestrator + Z framework + W extension mirrors)"` where X+Y+Z+W == N. The existing base was `"25 sub-skills (21 core + 1 orchestrator + 1 framework + 2 extension mirrors)"`. Adding 7 first-class geo-* skills (all "core" category, assuming Task 10 grafted `geo-compare`) gives:

```json
"description": "Comprehensive SEO analysis plugin for Claude Code. 32 sub-skills (28 core + 1 orchestrator + 1 framework + 2 extension mirrors) and 20 sub-agents cover technical SEO, content quality, schema, sitemaps, Core Web Vitals, local SEO, backlinks, first-class AEO/GEO (deterministic citability scoring, per-platform optimization, AI crawler access, brand-mention tracking), ecommerce, hreflang, SXO, clustering, drift monitoring, and Google APIs. Includes optional MCP extensions, SPA-aware rendering, portability, and hardened SSRF/DNS-rebinding safe fetchers.",
```

(28 core = 21 original core + 7 grafted geo-*; if Task 10 folded `geo-compare` instead of grafting it, use `27 core` and `31 sub-skills` instead — keep the parenthetical breakdown's sum matching the headline in either case.)

Add these keywords to the existing `"keywords"` array (append, don't replace):
```json
"answer-engine-optimization",
"aeo",
"citability-scoring",
"platform-optimization",
"perplexity",
"chatgpt-search",
"gemini",
"ai-crawlers",
"brand-mentions"
```

- [ ] **Step 3: Update `.claude-plugin/marketplace.json`**

Update `metadata.description` and the plugin entry's `description` to the same `32 sub-skills` / `20 sub-agents` counts and AEO language as Step 2 (both must stay in parity per `test_marketplace_json_skill_count_matches_plugin_json` / `test_marketplace_json_subagent_count_matches_plugin_json`). Keep `"name": "agricidaniel-claude-seo"` unchanged (local-only build, not republished, per Global Constraints).

- [ ] **Step 4: Bump `CITATION.cff` and `pyproject.toml` versions**

In `CITATION.cff`, change the `version:` line to `version: 3.0.0`.
In `pyproject.toml`, change `version = "2.2.0"` to `version = "3.0.0"`, and change `requires-python = ">=3.10"` to `requires-python = ">=3.11"` (per Global Constraints).

- [ ] **Step 5: Bump `install.sh` and `install.ps1` default tags**

In `install.sh`, find the line matching `REPO_TAG="${CLAUDE_SEO_TAG:-v2.2.0}"` (or similar) and change the default to `v3.0.0`.
In `install.ps1`, find the line matching `else { 'v2.2.0' }` (or similar) and change it to `else { 'v3.0.0' }`.

- [ ] **Step 6: Add the AEO override section to `CLAUDE.md`, verbatim**

Append to the end of the file:

```markdown
## Answer Engine Optimization (AEO) - stance override

This build treats AEO/GEO as a FIRST-CLASS, SEPARATELY-SCORED dimension, not a
relabeling of SEO. Audits must surface an AEO score distinct from the SEO score.
The eligibility floor is still normal indexation, but AEO adds citation-structure
signals that classic SEO does not measure.

Scoring weights (grounded in Princeton's 2024 GEO study and 2026 citation data):
- Cited sources / statistics with attribution: strongest positive lift.
- Front-loading: the first ~30% of a page carries a large share of AI citations;
  major sections must open with a direct, self-contained answer.
- Passage self-containment and question-phrased headings: positive.
- Keyword stuffing / AI-specific keyword rewriting: negative or neutral; do not
  recommend.

Determinism: citability is scored by scripts/citability_scorer.py (0-100), not by
free-form judgment. Brand/AI visibility is scored by scripts/brand_scanner.py.

llms.txt: audited and optionally generated, reported as forward-looking and
low-confidence, never as a ranking lever. See seo-geo/references/llmstxt-evidence.md
and the aeo.llmstxt_mode flag.

Evidence discipline retained: every AEO recommendation keeps a falsifiability check
(observation it rests on, dependency, "how would we know it failed", leading
indicator), consistent with the rest of this plugin.
```

- [ ] **Step 7: Update canonical phrasing in `README.md`, `CLAUDE.md`, `AGENTS.md` (first 120 lines each)**

`tests/test_manifest_consistency.py::test_canonical_phrasing_in_user_visible_docs` requires the exact phrase `"32 sub-skills"` (or `"31 sub-skills"` per Task 10's outcome) to appear within the first 120 lines of all three files. Find wherever each currently states `"25 sub-skills"` and update it to match the new count.

- [ ] **Step 8: Add a CHANGELOG.md v3.0.0 entry**

```markdown
## v3.0.0 — 2026-07-06

Merged AEO/GEO depth from [geo-seo-claude](https://github.com/zubair-trabzada/geo-seo-claude)
(Zubair Trabzada, MIT) into this fork of claude-seo. AEO is now a first-class,
separately-scored dimension — `seo-audit` reports distinct SEO and AEO scores,
never blended.

- Grafted 7 first-class `geo-*` skills: `geo-citability`, `geo-platform-optimizer`,
  `geo-compare`, `geo-brand-mentions`, `geo-crawlers`, `geo-prospect`, `geo-proposal`.
- Grafted 2 agents: `geo-ai-visibility`, `geo-platform-analysis`.
- Rewired `citability_scorer.py`, `brand_scanner.py`, `llmstxt_generator.py` onto
  this fork's SSRF/DNS-rebinding-hardened `fetch_page`/`url_safety` modules.
- Rewrote `seo-geo` from a scoring skill into the AEO router; encoded the
  reconciled llms.txt policy (`aeo.llmstxt_mode: audit | generate | off`,
  default `generate` — forward-looking, low-confidence, never a ranking lever).
- Folded unique logic from 8 overlapping geo skills into their `seo-*`
  equivalents, then removed the standalone geo skills — no duplicate function.
- Added two optional extensions: `extensions/geo-dashboard/` (Flask/rich CRM
  dashboard) and `extensions/gsc-mcp/` (OAuth-free GSC alternative to the
  native `seo-google` integration). Neither is a core dependency.
- Encoded Princeton 2024 GEO study citation-lift weights as constants in
  `citability_scorer.py`; added `sourc-e-framework.md` and
  `aeo-scoring-weights.md` methodology references (summarized, not copied).
```

- [ ] **Step 9: Commit**

```bash
git add requirements.txt .claude-plugin/ CITATION.cff pyproject.toml install.sh install.ps1 CLAUDE.md README.md AGENTS.md CHANGELOG.md
git commit -m "Bump to v3.0.0: update manifests, version strings, CLAUDE.md AEO stance, changelog"
```

---

### Task 20: Update skills/seo/SKILL.md Sub-Skills and Subagents lists

**Files:**
- Modify: `skills/seo/SKILL.md`

**Interfaces:**
- Consumes: the final skill/agent lists from Tasks 4, 5, 10.

- [ ] **Step 1: Read the existing Sub-Skills and Subagents sections**

```bash
grep -n "^## Sub-Skills\|^## Subagents" skills/seo/SKILL.md
```

- [ ] **Step 2: Add the grafted skills to the numbered Sub-Skills list**

`tests/test_manifest_consistency.py::test_orchestrator_sub_skills_list_matches_disk` requires this list (format: `N. **skill-name** ...`) to exactly equal `set(skills/*) - {seo}`. Append one numbered entry per grafted skill (continuing the existing numbering), e.g.:

```markdown
26. **geo-citability** — AI citability scoring and optimization (0-100 deterministic score via `citability_scorer.py`).
27. **geo-platform-optimizer** — Platform-specific AI search optimization (Google AIO, ChatGPT, Perplexity, Gemini, Bing Copilot).
28. **geo-compare** — Month-over-month AEO delta tracking and client progress reporting.
29. **geo-brand-mentions** — Brand/AI-visibility scanner across YouTube, Reddit, Wikipedia, LinkedIn (via `brand_scanner.py`).
30. **geo-crawlers** — AI crawler access analysis (GPTBot, ClaudeBot, PerplexityBot, Google-Extended, Bingbot/Copilot).
31. **geo-prospect** — Agency prospect/CRM pipeline management.
32. **geo-proposal** — Client-facing GEO service proposal generation.
```

(Omit `geo-compare` from this list, and renumber from 26-31 instead of 26-32, if Task 10 concluded it should be folded rather than grafted.)

- [ ] **Step 3: Add the two grafted agents to the Subagents bullet list**

`tests/test_manifest_consistency.py::test_orchestrator_subagents_list_matches_disk` requires this list (format: `` - `agent-name` ``) to exactly equal `set(agents/seo-*.md)` — note this test's regex only matches agent filenames starting with `seo-`, so the two grafted `geo-ai-visibility` and `geo-platform-analysis` agents are outside this specific test's scope. Do not add them to this bullet list (adding them would break the exact-match assertion, since they don't match the `seo-` prefix pattern the test filters on). Instead, add a short separate note directly below the Subagents list:

```markdown
Additionally, two AEO-focused agents are available outside the `seo-*`
naming convention (not subject to the `seo-*` count check above):
`geo-ai-visibility` and `geo-platform-analysis`.
```

- [ ] **Step 4: Verify against the actual test logic**

```bash
source .venv/bin/activate
pytest tests/test_manifest_consistency.py::test_orchestrator_sub_skills_list_matches_disk tests/test_manifest_consistency.py::test_orchestrator_subagents_list_matches_disk -v
```

Expected: both PASS. If `test_orchestrator_sub_skills_list_matches_disk` fails, re-check the numbered-list regex (`^\d+\.\s+\*\*(seo-[a-z-]+)\*\*`) — **note it only matches names starting with `seo-`, not `geo-`.** Re-read the test source at `tests/test_manifest_consistency.py:209` before assuming this step is correct: if the regex truly only captures `seo-*` names, then the grafted `geo-*` skills will never satisfy `expected = on_disk - {"seo"}`, and this test will fail no matter how the list is worded. In that case, the correct fix is to extend the test's own regex to also match `geo-[a-z-]+` (modify `tests/test_manifest_consistency.py` itself, since the merge fundamentally changes what "on disk" means for this plugin) — treat this as an intentional, documented modification of an existing claude-seo test, not a new file, and note it in the commit message.

- [ ] **Step 5: Commit**

```bash
git add skills/seo/SKILL.md tests/test_manifest_consistency.py
git commit -m "Update seo orchestrator Sub-Skills/Subagents lists for grafted geo-* skills; extend manifest test regex to cover geo-* naming"
```

---

### Task 21: Full-suite verification, local install smoke test, cleanup

**Files:**
- No new files — verification only, plus deletion of `.graft-src/`.

**Interfaces:**
- Consumes: everything from Tasks 1–20.

- [ ] **Step 1: Run the complete pytest suite**

```bash
cd "/Users/riyamalik/Library/Mobile Documents/com~apple~CloudDocs/ZYRA/claude-seo-x-geo"
source .venv/bin/activate
pytest tests/ -v
```

Expected: 100% pass. If any test fails, use `superpowers:systematic-debugging` to investigate — do not silence or delete a failing test to make the suite green. Common failure points to check first, given everything above: (a) `test_manifest_consistency.py`'s several parity/triangulation checks (Task 19), (b) `test_portability.py`'s whole-repo frontmatter lint against the 7 grafted skills (Task 4), (c) `test_reference_files_have_at_least_one_link` against the two new `seo-geo/references/*.md` files (Task 9).

- [ ] **Step 2: Run the portability check standalone for a clear report**

```bash
python3 scripts/portability_check.py skills/ extensions/ 2>&1 | tail -40
```

Expected: no `error`-severity findings for any of the 7 grafted skills or the 2 new extension skills.

- [ ] **Step 3: Install locally into a scratch `~/.claude` equivalent and smoke-test**

```bash
mkdir -p /tmp/claude-seo-x-geo-smoketest/.claude
CLAUDE_HOME=/tmp/claude-seo-x-geo-smoketest/.claude bash install.sh
ls /tmp/claude-seo-x-geo-smoketest/.claude/skills | wc -l
```

Expected count matches the final skill total (32, or 31 per Task 10's outcome). If `install.sh` doesn't support a `CLAUDE_HOME` override, read the script first and use whatever environment variable or flag it actually exposes for a non-default install target — do not install into the real `~/.claude` for this smoke test.

- [ ] **Step 4: Confirm the audit report shows separate SEO/AEO scores (manual/agent-driven check)**

This step can't be scripted as a pytest assertion — it requires actually invoking the installed `/seo audit <url>` skill against a real or test URL inside a Claude Code session pointed at the scratch install, and reading the output to confirm it contains both a `## SEO Score:` and a `## AEO Score:` section per Task 14's report structure, never a single blended score. Document the result (pass/fail + URL used) in the final task update.

- [ ] **Step 5: Clean up the grafting source**

```bash
rm -rf "/Users/riyamalik/Library/Mobile Documents/com~apple~CloudDocs/ZYRA/claude-seo-x-geo/.graft-src"
rm -rf /tmp/claude-seo-base /tmp/claude-seo-x-geo-smoketest
```

- [ ] **Step 6: Final commit**

```bash
cd "/Users/riyamalik/Library/Mobile Documents/com~apple~CloudDocs/ZYRA/claude-seo-x-geo"
git add -A
git status --short  # confirm .graft-src/ removal produces no tracked-file changes (it was gitignored)
git log --oneline merge/aeo-depth
```

No PR is opened, no push occurs — per the user's explicit decision (spec §0.2 delta), the branch `merge/aeo-depth` stays local until the user separately decides to publish it.

---

## Self-review notes (spec coverage check)

- §1 License: Task 3 (NOTICE.md, LICENSES/), Task 4/10 Step 2 (per-skill LICENSE.txt). Top-level `LICENSE` untouched since Task 1 copy — never modified by any later task. ✅
- §2 Prerequisites: Task 1 Step 5 (playwright install chromium), Task 19 Step 4 (Python >=3.11). ✅
- §3/§4 Architecture/skill tree: Tasks 4, 5, 10, 11-15, 20. ✅
- §5 File migration map: every row has a corresponding task (Task 4 for grafts, Task 6-8 for scripts, Task 11-14 for merge-deletes, Task 15 for report/report-pdf/update, Task 16 for dashboard, Task 18 for white-label/schema). ✅
- §6 Scorers security: Tasks 6, 7, 8 (rewire + safety tests) + Task 16 Step 7 (flask/rich isolation check). ✅
- §7 Conflict resolutions: Tasks 11 (schema), 12 (technical), 13 (content), 14 (audit). ✅
- §8 llms.txt policy: Task 8 (script gate) + Task 9 (policy text + config flag). ✅
- §9 Manifests: Task 19 Steps 2-3, 7. ✅
- §10 requirements.txt: Task 19 Step 1. ✅
- §11 CLAUDE.md: Task 19 Step 6 (verbatim block). ✅
- §12 Third-tier integrations: Task 9 Steps 3-4 (weights + SOURC-E reference docs), Task 17 (GSC-MCP). ✅
- §13 Dashboard extension: Task 16. Plus delta: Task 17 (gsc-mcp). ✅
- §14 CI/test gate: Tasks 6-8 (new test files), Task 20 (manifest test extension), Task 21 (full suite + portability). ✅
- §15 Execution order: matches this plan's task order 1→21. ✅
- §16 Acceptance criteria: verified in Task 21 Steps 1-4. ✅
- §17 Out of scope: enforced throughout (Global Constraints section + Task 16 Step 7's flask/rich grep).✅

## Type/interface consistency check

- `fetch_page(url, timeout=30, follow_redirects=True, max_redirects=5, user_agent=None) -> dict` with key `"content"` (not `"text"`) is used identically in Tasks 6, 8 — confirmed against the actual claude-seo source read in this session.
- `safe_requests_get(url, *, timeout=30, **kwargs) -> requests.Response` used identically in Task 7 — confirmed against actual claude-seo source.
- `generate_llmstxt(url, max_pages=30, mode="generate")` — the `mode` parameter is new (didn't exist in geo's original signature); Task 9's router text and Task 8's test file both reference this exact parameter name and default.
- `LlmsTxtGenerationDisabledError` — defined in Task 8, referenced in Task 8's `__main__` block and test file only; no other task calls `generate_llmstxt` directly, so no cross-task signature drift risk.
