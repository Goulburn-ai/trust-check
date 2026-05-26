"""Smoke tests for the GitHub Action entrypoint (INPUT_* env var reading)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from goulburn_trust_check import core, github_action


def _set_inputs(monkeypatch, **kwargs):
    for k, v in kwargs.items():
        monkeypatch.setenv(f"INPUT_{k.upper().replace('-', '_')}", str(v))


def test_missing_agent_exits_caller_error(monkeypatch, capsys, gha_io_files):
    _set_inputs(monkeypatch, api_key="k")
    with pytest.raises(SystemExit) as exc:
        github_action.main()
    assert exc.value.code == core.EXIT_CALLER_ERROR
    assert "missing required input 'agent'" in capsys.readouterr().err


def test_happy_path_emits_outputs_and_summary(
    monkeypatch, capsys, gha_io_files, fake_profile
):
    _set_inputs(
        monkeypatch,
        agent="myagent",
        api_key="k",
        threshold="60",
    )
    profile = fake_profile(overall=80)
    with patch.object(core, "_fetch_profile", return_value=(profile, None)):
        rc = github_action.main()
    assert rc == core.EXIT_OK
    out_text = gha_io_files["output"].read_text()
    assert "overall-score=80" in out_text
    assert "passed=true" in out_text
    summary_text = gha_io_files["summary"].read_text()
    assert "PASS" in summary_text
    assert "myagent" in summary_text


def test_failure_path_exit_4_and_error_logged(
    monkeypatch, capsys, gha_io_files, fake_profile
):
    _set_inputs(
        monkeypatch,
        agent="myagent",
        api_key="k",
        threshold="90",
    )
    profile = fake_profile(overall=20)
    with patch.object(core, "_fetch_profile", return_value=(profile, None)):
        rc = github_action.main()
    assert rc == core.EXIT_AGENT_FAILED
    err = capsys.readouterr().err
    assert "::error::" in err


def test_bad_threshold_exits_caller_error(monkeypatch, capsys, gha_io_files):
    _set_inputs(monkeypatch, agent="a", api_key="k", threshold="9999")
    rc = github_action.main()
    assert rc == core.EXIT_CALLER_ERROR
    assert "threshold must be 0-100" in capsys.readouterr().err


def test_layer_threshold_failure(monkeypatch, gha_io_files, fake_profile):
    _set_inputs(
        monkeypatch,
        agent="a",
        api_key="k",
        threshold="10",
        layer_thresholds="identity=90,compliance=50",
    )
    profile = fake_profile(overall=80, layers={"identity": {"score": 40}})
    with patch.object(core, "_fetch_profile", return_value=(profile, None)):
        rc = github_action.main()
    assert rc == core.EXIT_AGENT_FAILED
    out_text = gha_io_files["output"].read_text()
    assert "passed=false" in out_text
