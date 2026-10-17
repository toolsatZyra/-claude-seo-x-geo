"""Banana fallback scripts must not default to a retired Gemini image model.

Google shut down ``gemini-3.1-flash-image-preview`` (2026-06-25) and
``gemini-2.5-flash-image`` (2026-10-02). Upstream AgriciDaniel/claude-seo (MIT)
fixed the standalone scripts to read the model from ``NANOBANANA_MODEL`` (or
``--model``) instead of hard-coding one, and made ``batch.py`` take the default
model and unit cost from the caller. These tests pin that behaviour in this
fork. They never touch the network or the real home directory: every CLI run
gets a scrubbed environment with HOME pointed at ``tmp_path`` and exits on
argument validation before any request would be built.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "extensions" / "banana" / "scripts"
RETIRED_IMAGE_MODELS = (
    "gemini-3.1-flash-image-preview",
    "gemini-3-pro-image-preview",
    "gemini-2.5-flash-image",
)
SKILL_COPIES = (
    REPO_ROOT / "skills" / "seo-image-gen" / "SKILL.md",
    REPO_ROOT / "extensions" / "banana" / "skills" / "seo-image-gen" / "SKILL.md",
)


def _load(name: str, monkeypatch, model: str | None):
    if model is None:
        monkeypatch.delenv("NANOBANANA_MODEL", raising=False)
    else:
        monkeypatch.setenv("NANOBANANA_MODEL", model)
    spec = importlib.util.spec_from_file_location(f"banana_{name}_defaults", SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(script: str, tmp_path: Path, *argv: str, env_extra: dict | None = None):
    env = {k: v for k, v in os.environ.items()
           if k not in {"NANOBANANA_MODEL", "GOOGLE_AI_API_KEY", "GOOGLE_API_KEY"}}
    env["HOME"] = str(tmp_path)
    env["USERPROFILE"] = str(tmp_path)
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *argv],
        capture_output=True, text=True, env=env, cwd=str(tmp_path), timeout=60,
    )


@pytest.mark.parametrize("script", ["batch.py", "cost_tracker.py", "edit.py",
                                    "generate.py", "presets.py"])
def test_no_retired_model_id_is_hard_coded(script: str) -> None:
    source = (SCRIPTS / script).read_text(encoding="utf-8")
    for model in RETIRED_IMAGE_MODELS:
        assert model not in source, f"{script} still hard-codes retired model {model}"


@pytest.mark.parametrize("name", ["generate", "edit"])
def test_default_model_comes_from_nanobanana_model(name: str, monkeypatch) -> None:
    assert _load(name, monkeypatch, "gemini-3.1-flash-image").DEFAULT_MODEL == "gemini-3.1-flash-image"
    assert _load(name, monkeypatch, None).DEFAULT_MODEL is None


def test_generate_without_any_model_fails_before_any_request(tmp_path: Path) -> None:
    result = _run("generate.py", tmp_path, "--prompt", "a lighthouse at dusk")
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["error"] is True
    assert "NANOBANANA_MODEL" in payload["message"]


def test_edit_without_any_model_fails_before_any_request(tmp_path: Path) -> None:
    image = tmp_path / "in.png"
    image.write_bytes(b"not really a png")
    result = _run("edit.py", tmp_path, "--image", str(image), "--prompt", "remove background")
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["error"] is True
    assert "NANOBANANA_MODEL" in payload["message"]


def test_generate_with_model_but_no_key_stops_at_the_key_check(tmp_path: Path) -> None:
    """With a model set, the next gate is the API key, still before any request."""
    result = _run("generate.py", tmp_path, "--prompt", "x",
                  env_extra={"NANOBANANA_MODEL": "gemini-3.1-flash-image"})
    assert result.returncode == 1
    assert "No API key" in json.loads(result.stdout)["message"]


def _write_csv(tmp_path: Path) -> Path:
    csv_path = tmp_path / "requests.csv"
    csv_path.write_text(
        "prompt,ratio,resolution,model\n"
        "hero for pricing page,16:9,2K,\n"
        "product shot,4:3,1K,gemini-3-pro-image\n",
        encoding="utf-8",
    )
    return csv_path


def test_batch_requires_a_default_model(tmp_path: Path) -> None:
    result = _run("batch.py", tmp_path, "--csv", str(_write_csv(tmp_path)))
    assert result.returncode == 2
    assert "--model" in result.stderr


def test_batch_rows_inherit_the_caller_model_and_skip_unverified_estimates(tmp_path: Path) -> None:
    result = _run("batch.py", tmp_path, "--csv", str(_write_csv(tmp_path)),
                  "--model", "gemini-3.1-flash-image")
    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout[result.stdout.index("{"):])
    assert [r["model"] for r in plan["rows"]] == ["gemini-3.1-flash-image", "gemini-3-pro-image"]
    assert plan["estimated_cost"] is None
    assert "--unit-cost" in plan["pricing_note"]


def test_batch_estimate_uses_the_caller_supplied_unit_cost(tmp_path: Path) -> None:
    result = _run("batch.py", tmp_path, "--csv", str(_write_csv(tmp_path)),
                  "--model", "gemini-3.1-flash-image", "--unit-cost", "0.05")
    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout[result.stdout.index("{"):])
    assert plan["total_count"] == 2
    assert plan["estimated_cost"] == pytest.approx(0.1)


@pytest.mark.parametrize("skill", SKILL_COPIES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_skill_model_routing_does_not_pin_a_model_id(skill: Path) -> None:
    """Routing rows must defer to a verified model, not name a (soon) retired ID."""
    text = skill.read_text(encoding="utf-8")
    routing = re.search(r"^## Model Routing\n(.*?)(?=^## )", text, re.S | re.M)
    assert routing, f"{skill}: no Model Routing section"
    rows = [line for line in routing.group(1).splitlines() if line.startswith("|")]
    assert rows, f"{skill}: Model Routing has no table"
    assert not [r for r in rows if re.search(r"`gemini-[^`]*`", r)], rows


@pytest.mark.parametrize("skill", SKILL_COPIES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_skill_does_not_quote_fixed_per_image_prices(skill: Path) -> None:
    text = skill.read_text(encoding="utf-8")
    assert not re.search(r"~\$0\.\d+/image", text)
