"""Tests for the pure-logic core (no GitHub I/O, no real network)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from goulburn_trust_check import core


# ── parse_threshold ──────────────────────────────────────────────────

def test_parse_threshold_ok():
    assert core.parse_threshold("0") == 0
    assert core.parse_threshold("60") == 60
    assert core.parse_threshold(" 100 ") == 100


@pytest.mark.parametrize("bad", ["", "abc", "-1", "101", "12.5"])
def test_parse_threshold_bad(bad):
    with pytest.raises(ValueError):
        core.parse_threshold(bad)


# ── parse_required_tier ──────────────────────────────────────────────

@pytest.mark.parametrize("tier", core.VALID_TIERS)
def test_parse_required_tier_ok(tier):
    assert core.parse_required_tier(tier) == tier
    assert core.parse_required_tier(tier.upper()) == tier


def test_parse_required_tier_empty_is_none():
    assert core.parse_required_tier("") is None
    assert core.parse_required_tier(None) is None
    assert core.parse_required_tier("   ") is None


def test_parse_required_tier_bad():
    with pytest.raises(ValueError):
        core.parse_required_tier("godlike")


# ── parse_layer_thresholds ───────────────────────────────────────────

def test_parse_layer_thresholds_ok():
    out = core.parse_layer_thresholds("identity=70, compliance=60")
    assert out == {"identity": 70, "compliance": 60}


def test_parse_layer_thresholds_empty():
    assert core.parse_layer_thresholds("") == {}
    assert core.parse_layer_thresholds(None) == {}


def test_parse_layer_thresholds_unknown_layer():
    with pytest.raises(ValueError):
        core.parse_layer_thresholds("ghost=50")


def test_parse_layer_thresholds_missing_equals():
    with pytest.raises(ValueError):
        core.parse_layer_thresholds("identity70")


def test_parse_layer_thresholds_non_int_value():
    with pytest.raises(ValueError):
        core.parse_layer_thresholds("identity=high")


def test_parse_layer_thresholds_out_of_range():
    with pytest.raises(ValueError):
        core.parse_layer_thresholds("identity=200")


# ── run() — happy + failure paths ────────────────────────────────────

def _patched_run(profile_obj):
    """Helper: return (None error, profile_obj) like _fetch_profile does."""
    return profile_obj, None


def test_run_passes_when_above_threshold(fake_profile):
    profile = fake_profile(overall=80, tier="verified")
    with patch.object(core, "_fetch_profile", return_value=(profile, None)):
        res = core.run(core.CheckRequest(agent="a", api_key="k", threshold=60))
    assert res.passed is True
    assert res.exit_code == core.EXIT_OK
    assert res.overall_score == 80
    assert "PASS" in res.decision
    assert res.failures == []


def test_run_fails_when_below_threshold(fake_profile):
    profile = fake_profile(overall=40)
    with patch.object(core, "_fetch_profile", return_value=(profile, None)):
        res = core.run(core.CheckRequest(agent="a", api_key="k", threshold=60))
    assert res.passed is False
    assert res.exit_code == core.EXIT_AGENT_FAILED
    assert "overall_score 40 < threshold 60" in "; ".join(res.failures)


def test_run_fails_when_tier_below_required(fake_profile):
    profile = fake_profile(overall=80, tier="identified")
    with patch.object(core, "_fetch_profile", return_value=(profile, None)):
        res = core.run(
            core.CheckRequest(
                agent="a",
                api_key="k",
                threshold=10,
                required_tier="verified",
            )
        )
    assert res.passed is False
    assert any("tier" in f for f in res.failures)


def test_run_fails_when_layer_below_min(fake_profile):
    profile = fake_profile(overall=80, layers={"identity": {"score": 30}})
    with patch.object(core, "_fetch_profile", return_value=(profile, None)):
        res = core.run(
            core.CheckRequest(
                agent="a",
                api_key="k",
                threshold=10,
                layer_thresholds={"identity": 70},
            )
        )
    assert res.passed is False
    assert any("identity" in f for f in res.failures)


def test_run_fails_when_layer_missing(fake_profile):
    profile = fake_profile(overall=80, layers={"identity": {"score": 80}})
    with patch.object(core, "_fetch_profile", return_value=(profile, None)):
        res = core.run(
            core.CheckRequest(
                agent="a",
                api_key="k",
                threshold=10,
                layer_thresholds={"compliance": 50},
            )
        )
    assert res.passed is False
    assert any("compliance" in f and "missing" in f for f in res.failures)


def test_run_handles_fetch_error_short_circuits():
    err = core.CheckResult(
        passed=False, exit_code=core.EXIT_AUTH_FAIL, error="bad key"
    )
    with patch.object(core, "_fetch_profile", return_value=(None, err)):
        res = core.run(core.CheckRequest(agent="a", api_key="k"))
    assert res.passed is False
    assert res.exit_code == core.EXIT_AUTH_FAIL
    assert res.error == "bad key"
    assert "ERROR" in res.decision


def test_run_handles_malformed_profile():
    class _Bad: pass
    with patch.object(core, "_fetch_profile", return_value=(_Bad(), None)):
        res = core.run(core.CheckRequest(agent="a", api_key="k"))
    assert res.passed is False
    assert res.exit_code == core.EXIT_API_UNREACHABLE


# ── format_markdown_summary ──────────────────────────────────────────

def test_format_markdown_summary_pass(fake_profile):
    profile = fake_profile()
    with patch.object(core, "_fetch_profile", return_value=(profile, None)):
        req = core.CheckRequest(agent="myagent", api_key="k", threshold=10)
        res = core.run(req)
    md = core.format_markdown_summary(req, res)
    assert "PASS" in md
    assert "`myagent`" in md
    assert "| identity | 80 |" in md


def test_format_markdown_summary_fail_lists_failures(fake_profile):
    profile = fake_profile(overall=20)
    with patch.object(core, "_fetch_profile", return_value=(profile, None)):
        req = core.CheckRequest(agent="myagent", api_key="k", threshold=60)
        res = core.run(req)
    md = core.format_markdown_summary(req, res)
    assert "FAIL" in md
    assert "**Failures:**" in md
    assert "overall_score 20 < threshold 60" in md
