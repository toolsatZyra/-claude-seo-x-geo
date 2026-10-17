#!/usr/bin/env python3
"""
KPI envelope contract shared by every script that produces trackable numbers.

A KPI envelope is the one hand-off format between producers (rank_tracker,
ai_referrals, ai_visibility, aeo_score, ...) and the KPI history kept by
performance_tracker.py. Keeping the contract here — not inside any one
producer or consumer — means a value is validated with the same rules when it
is written (``write_envelope``) and when it is ingested (``validate_envelope``),
so a producer bug (a percent where a fraction belongs, a NaN, a typo'd metric
name) fails at the source instead of leaking into a client's trend report.

Envelope (version 1):
    {"kpi_envelope": 1, "project": "example.com", "date": "YYYY-MM-DD",
     "source": "ai_visibility.py", "metrics": {"ai.mention_rate": 0.32},
     "meta": {...}}

Reserved metric names and their value kinds are listed in RESERVED_METRICS and
documented in skills/seo-track/references/kpi-definitions.md.

Usage:
    python seo_kpi.py validate envelope.json [--json]
    python seo_kpi.py metrics            # list reserved metric names and kinds
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Optional

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from seo_store import normalize_domain, today  # noqa: E402

ENVELOPE_VERSION = 1
METRIC_NAME_RE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Reserved metric names and the value kind each must satisfy.
#   count     >= 0
#   fraction  0..1 (rates and shares are fractions, never percents)
#   rate      >= 0 (key events per session can exceed 1 when the basis is events)
#   score     0..100
#   position  > 0 (lower is better)
RESERVED_METRICS: dict[str, str] = {
    "gsc.clicks": "count", "gsc.impressions": "count", "gsc.ctr": "fraction",
    "gsc.position": "position", "gsc.clicks_nonbrand": "count",
    "gsc.impressions_nonbrand": "count",
    "rank.tracked": "count", "rank.top3": "count", "rank.top10": "count",
    "rank.striking": "count", "rank.visibility": "score",
    "ga4.organic_sessions": "count", "ga4.organic_key_events": "count",
    "ga4.organic_cvr": "rate", "ga4.ai_sessions": "count",
    "ga4.ai_key_events": "count", "ga4.ai_cvr": "rate",
    "ai.mention_rate": "fraction", "ai.mention_rate_ci_low": "fraction",
    "ai.mention_rate_ci_high": "fraction", "ai.citation_rate": "fraction",
    "ai.sov": "fraction", "ai.retrieval_rate": "fraction", "ai.n": "count",
    "aeo.score": "score", "aeo.citability": "score", "aeo.brand_authority": "score",
    "aeo.content_eeat": "score", "aeo.crawler_access": "score", "aeo.schema": "score",
    "aeo.platform": "score",
    "seo.health": "score",
    "leads.total": "count", "leads.organic": "count",
}
RESERVED_PREFIXES = frozenset(name.split(".")[0] for name in RESERVED_METRICS)

# Metrics whose movement says nothing about performance (configuration or
# sample size): reported, never judged better/worse, never trip --fail-on-drop.
NEUTRAL_METRICS = frozenset({"rank.tracked", "ai.n"})


class EnvelopeError(ValueError):
    """Raised when a KPI envelope fails validation."""


# ---------------------------------------------------------------------------
# Envelope contract
# ---------------------------------------------------------------------------

def lower_is_better(metric: str) -> bool:
    """Direction of 'good' for a metric: positions improve when they fall."""
    return RESERVED_METRICS.get(metric) == "position" or metric.endswith("position")


def _valid_date(value: Any) -> Optional[str]:
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def _check_range(name: str, value: float) -> Optional[str]:
    kind = RESERVED_METRICS.get(name)
    if kind in ("count", "rate") and value < 0:
        return f"{name} must be >= 0 (got {value})"
    if kind == "fraction" and not 0 <= value <= 1:
        return f"{name} must be a 0-1 fraction, not a percent (got {value})"
    if kind == "score" and not 0 <= value <= 100:
        return f"{name} must be a 0-100 score (got {value})"
    if kind == "position" and value <= 0:
        return f"{name} must be a positive average position (got {value})"
    return None


def validate_envelope(env: Any) -> dict:
    """Validate a KPI envelope.

    Returns {"ok", "errors", "warnings", "skipped_null", "envelope"} where
    ``envelope`` is the cleaned envelope (normalized project, float values,
    nulls removed) when ok, else None. Any invalid metric rejects the whole
    envelope so a producer bug cannot leak half a snapshot into history.
    """
    errors: list[str] = []
    warnings: list[str] = []
    skipped: list[str] = []
    if not isinstance(env, dict):
        return {"ok": False, "errors": ["envelope must be a JSON object"], "warnings": [],
                "skipped_null": [], "envelope": None}

    version = env.get("kpi_envelope")
    if isinstance(version, bool) or version != ENVELOPE_VERSION:
        errors.append(f"kpi_envelope must be {ENVELOPE_VERSION} (got {version!r})")

    project_raw = env.get("project")
    project = normalize_domain(project_raw) if isinstance(project_raw, str) else ""
    if not project:
        errors.append("project is required (a domain such as example.com)")

    day = _valid_date(env.get("date"))
    if day is None:
        errors.append(f"date must be YYYY-MM-DD (got {env.get('date')!r})")

    source = env.get("source")
    if not isinstance(source, str) or not source.strip():
        warnings.append("source missing; stored as 'unknown'")
        source = "unknown"

    meta = env.get("meta", {})
    if meta is None:
        meta = {}
    if not isinstance(meta, dict):
        errors.append("meta must be an object when present")
        meta = {}

    metrics = env.get("metrics")
    clean: dict[str, float] = {}
    if not isinstance(metrics, dict) or not metrics:
        errors.append("metrics must be a non-empty object")
    else:
        for name, value in metrics.items():
            if not isinstance(name, str) or not METRIC_NAME_RE.match(name):
                errors.append(f"invalid metric name {name!r} (expected namespace.metric, "
                              "lowercase letters, digits, underscores)")
                continue
            if value is None:
                skipped.append(name)
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                errors.append(f"{name}: value must be a number (got {type(value).__name__})")
                continue
            fval = float(value)
            if not math.isfinite(fval):
                errors.append(f"{name}: value must be finite")
                continue
            problem = _check_range(name, fval)
            if problem:
                errors.append(problem)
                continue
            if name not in RESERVED_METRICS and name.split(".")[0] in RESERVED_PREFIXES:
                warnings.append(f"{name} is not a reserved name under a reserved prefix "
                                "(typo? see kpi-definitions.md)")
            clean[name] = fval
        if not clean and not errors:
            warnings.append("every metric was null; nothing to store")

    ok = not errors
    return {
        "ok": ok,
        "errors": errors,
        "warnings": warnings,
        "skipped_null": skipped,
        "envelope": ({"kpi_envelope": ENVELOPE_VERSION, "project": project, "date": day,
                      "source": source.strip(), "metrics": clean, "meta": meta} if ok else None),
    }


def build_envelope(project: str, source: str, metrics: dict, day: Optional[str] = None,
                   meta: Optional[dict] = None) -> dict:
    """Build (and validate) a version-1 KPI envelope. Raises EnvelopeError."""
    env = {"kpi_envelope": ENVELOPE_VERSION, "project": normalize_domain(project),
           "date": day or today(), "source": source, "metrics": dict(metrics),
           "meta": meta or {}}
    result = validate_envelope(env)
    if not result["ok"]:
        raise EnvelopeError("; ".join(result["errors"]))
    return env


def write_envelope(path: str, project: str, source: str, metrics: dict,
                   day: Optional[str] = None, meta: Optional[dict] = None) -> dict:
    """Validate and atomically write a KPI envelope to ``path``; returns it.

    ``null`` metric values are written as null (the ingest skips them), so a
    producer can say "not measured" without faking a zero.
    """
    env = build_envelope(project, source, metrics, day, meta)
    target = Path(path).expanduser()
    if target.parent and not target.parent.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(env, fh, indent=2, sort_keys=False)
        fh.write("\n")
    os.replace(tmp, target)
    return env


# ---------------------------------------------------------------------------
# GSC regex helpers (brand filters)
# ---------------------------------------------------------------------------

def re2_escape(term: str) -> str:
    """Escape RE2 metacharacters (GSC regex filters use RE2 syntax)."""
    return re.sub(r"([\\.^$|?*+()\[\]{}])", r"\\\1", term)


def brand_regex(terms: Iterable[str]) -> str:
    """Case-insensitive RE2 alternation of brand terms for GSC excludingRegex."""
    cleaned = sorted({" ".join(t.lower().split()) for t in terms if t and t.strip()},
                     key=lambda t: (-len(t), t))
    return "(?i)(" + "|".join(re2_escape(t) for t in cleaned) + ")" if cleaned else ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate KPI envelopes / list reserved metrics")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("validate", help="Validate one or more envelope files")
    p.add_argument("files", nargs="+")
    p.add_argument("--json", action="store_true")
    sub.add_parser("metrics", help="List reserved metric names and value kinds")
    args = parser.parse_args()

    if args.cmd == "metrics":
        print(json.dumps(RESERVED_METRICS, indent=2))
        return 0
    results = []
    for path in args.files:
        try:
            with open(path, encoding="utf-8") as fh:
                env = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            results.append({"file": path, "ok": False, "errors": [f"cannot read JSON: {exc}"],
                            "warnings": []})
            continue
        check = validate_envelope(env)
        results.append({"file": path, "ok": check["ok"], "errors": check["errors"],
                        "warnings": check["warnings"]})
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for r in results:
            print(f"{'OK  ' if r['ok'] else 'FAIL'} {r['file']}")
            for msg in r["errors"]:
                print(f"     error: {msg}")
            for msg in r["warnings"]:
                print(f"     warning: {msg}")
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
