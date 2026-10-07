"""Smoke tests for the GitHub Action entrypoint (INPUT_* env var reading)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from goulburn_trust_check import core, github_action


def _parse_outputs(text: str) -> dict[str, str]:
    """Parse GITHUB_OUTPUT the way the runner does (name=value and name<<DELIM)."""
    out: dict[str, str] = {}
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if "<<" in line and ("=" not in line or line.index("<<") < line.index("=")):
            name, delim = line.split("<<", 1)
            j = lines.index(delim, i + 1)
            out[name] = "\n".join(lines[i + 1 : j])
            i = j + 1
            continue
        if "=" in line:
            name, value = line.split("=", 1)
            out[name] = value
        i += 1
    return out


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
    outs = _parse_outputs(gha_io_files["output"].read_text())
    assert outs["overall-score"] == "80"
    assert outs["passed"] == "true"
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
    outs = _parse_outputs(gha_io_files["output"].read_text())
    assert outs["passed"] == "false"


def test_newline_in_value_cannot_forge_outputs(monkeypatch, gha_io_files):
    """Regression: a newline in a value used to inject `passed=true`."""
    github_action._set_output("decision", "FAIL for x\npassed=true")
    github_action._set_output("passed", "false")
    outs = _parse_outputs(gha_io_files["output"].read_text())
    assert outs["passed"] == "false"
    assert outs["decision"] == "FAIL for x\npassed=true"


@pytest.mark.parametrize("bad", ["../owner/me", "a?x=1", "a#f", "a/b", "..", "a%2Fb", "a\nb"])
def test_hostile_agent_name_rejected_before_any_request(monkeypatch, gha_io_files, bad):
    _set_inputs(monkeypatch, agent=bad, api_key="k")
    with patch.object(core, "_fetch_profile") as fetch:
        rc = github_action.main()
    assert rc == core.EXIT_CALLER_ERROR
    fetch.assert_not_called()
    assert _parse_outputs(gha_io_files["output"].read_text())["passed"] == "false"
