"""Tests for the argparse CLI surface."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from goulburn_trust_check import cli, core


def test_missing_agent_errors(capsys, monkeypatch):
    monkeypatch.delenv("GOULBURN_AGENT", raising=False)
    monkeypatch.delenv("GOULBURN_API_KEY", raising=False)
    with pytest.raises(SystemExit) as exc:
        cli.main(["--api-key", "k"])
    assert exc.value.code == 2  # argparse error
    err = capsys.readouterr().err
    assert "--agent is required" in err


def test_missing_api_key_errors(capsys, monkeypatch):
    monkeypatch.delenv("GOULBURN_API_KEY", raising=False)
    with pytest.raises(SystemExit) as exc:
        cli.main(["--agent", "foo"])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "--api-key is required" in err


def test_bad_threshold_returns_caller_error(capsys):
    rc = cli.main(["--agent", "foo", "--api-key", "k", "--threshold", "9999"])
    assert rc == core.EXIT_CALLER_ERROR
    assert "threshold must be 0-100" in capsys.readouterr().err


def test_bad_layer_thresholds_returns_caller_error(capsys):
    rc = cli.main(
        ["--agent", "foo", "--api-key", "k", "--layer-thresholds", "ghost=10"]
    )
    assert rc == core.EXIT_CALLER_ERROR
    assert "unknown layer 'ghost'" in capsys.readouterr().err


def test_happy_path_exit_0_text(capsys, fake_profile):
    profile = fake_profile(overall=80)
    with patch.object(core, "_fetch_profile", return_value=(profile, None)):
        rc = cli.main(["--agent", "a", "--api-key", "k", "--threshold", "60"])
    assert rc == core.EXIT_OK
    out = capsys.readouterr().out
    assert "PASS" in out


def test_failure_path_exit_4(capsys, fake_profile):
    profile = fake_profile(overall=20)
    with patch.object(core, "_fetch_profile", return_value=(profile, None)):
        rc = cli.main(["--agent", "a", "--api-key", "k", "--threshold", "60"])
    assert rc == core.EXIT_AGENT_FAILED
    out = capsys.readouterr().out
    assert "FAIL" in out


def test_json_format(capsys, fake_profile):
    profile = fake_profile(overall=80)
    with patch.object(core, "_fetch_profile", return_value=(profile, None)):
        rc = cli.main(
            ["--agent", "a", "--api-key", "k", "--threshold", "10", "--format", "json"]
        )
    assert rc == core.EXIT_OK
    data = json.loads(capsys.readouterr().out)
    assert data["passed"] is True
    assert data["overall_score"] == 80
    assert data["tier"] == "verified"


def test_markdown_format(capsys, fake_profile):
    profile = fake_profile(overall=80)
    with patch.object(core, "_fetch_profile", return_value=(profile, None)):
        rc = cli.main(
            ["--agent", "a", "--api-key", "k", "--threshold", "10", "--format", "markdown"]
        )
    assert rc == core.EXIT_OK
    out = capsys.readouterr().out
    assert "### goulburn trust-check: PASS" in out


def test_env_var_fallbacks(monkeypatch, capsys, fake_profile):
    monkeypatch.setenv("GOULBURN_AGENT", "envagent")
    monkeypatch.setenv("GOULBURN_API_KEY", "envkey")
    profile = fake_profile(overall=80)
    with patch.object(core, "_fetch_profile", return_value=(profile, None)):
        rc = cli.main(["--threshold", "10"])
    assert rc == core.EXIT_OK
    out = capsys.readouterr().out
    assert "envagent" in out


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    from goulburn_trust_check import __version__
    assert __version__ in out
