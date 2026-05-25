"""Unit tests for the trust-check entrypoint.

These exercise the input-parsing and exit-code logic directly. The
network path is exercised indirectly via SDK mocks (httpx/respx).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
import respx

# Make the entrypoint importable as a module.
_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
sys.path.insert(0, str(_REPO))

# Stub out GITHUB_OUTPUT to a tmpdir so _set_output writes don't error.
@pytest.fixture(autouse=True)
def _gha_env(tmp_path, monkeypatch):
    out_file = tmp_path / "outputs.txt"
    out_file.touch()
    summary_file = tmp_path / "summary.md"
    summary_file.touch()
    monkeypatch.setenv("GITHUB_OUTPUT", str(out_file))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))
    yield



@pytest.fixture(autouse=True)
def _reload_entrypoint(monkeypatch):
    """entrypoint reads env at import time only via top-level constants.
    Force a re-import per test so monkeypatch'd inputs take effect."""
    import sys
    sys.modules.pop("entrypoint", None)
    yield
    sys.modules.pop("entrypoint", None)


@pytest.fixture
def respx_mock():
    with respx.mock(base_url="https://api.example.com", assert_all_called=False) as r:
        yield r


def _set_inputs(monkeypatch, **kwargs):
    """Stamp INPUT_* env vars per the GitHub Actions runner convention."""
    for k, v in kwargs.items():
        monkeypatch.setenv(f"INPUT_{k.upper().replace('-', '_')}", str(v))
    # Always include the base URL for the test environment.
    monkeypatch.setenv("INPUT_BASE_URL", "https://api.example.com")


def _make_profile(score: int = 75, tier: str = "verified", **layers) -> dict:
    base_layers = {
        "identity": {"score": 80},
        "capability": {"score": 70},
        "track_record": {"score": 60},
        "social": {"score": 50},
        "compliance": {"score": 85},
    }
    base_layers.update(layers)
    return {
        "agent": "myagent",
        "tier": tier,
        "overall_score": score,
        "layers": base_layers,
    }


# ── Threshold ───────────────────────────────────────────────────────


def test_pass_when_score_above_threshold(respx_mock, monkeypatch):
    respx_mock.get("/api/v1/trust/profile/myagent").mock(
        return_value=httpx.Response(200, json=_make_profile(score=75))
    )
    _set_inputs(monkeypatch, agent="myagent", api_key="gbok_x", threshold="60")
    from entrypoint import main
    assert main() == 0


def test_fail_when_score_below_threshold(respx_mock, monkeypatch):
    respx_mock.get("/api/v1/trust/profile/myagent").mock(
        return_value=httpx.Response(200, json=_make_profile(score=50))
    )
    _set_inputs(monkeypatch, agent="myagent", api_key="gbok_x", threshold="60")
    from entrypoint import main
    assert main() == 4  # EXIT_AGENT_FAILED


# ── Required tier ───────────────────────────────────────────────────


def test_required_tier_pass(respx_mock, monkeypatch):
    respx_mock.get("/api/v1/trust/profile/myagent").mock(
        return_value=httpx.Response(200, json=_make_profile(score=75, tier="verified"))
    )
    _set_inputs(monkeypatch, agent="myagent", api_key="gbok_x", threshold="60", required_tier="verified")
    from entrypoint import main
    assert main() == 0


def test_required_tier_fail(respx_mock, monkeypatch):
    respx_mock.get("/api/v1/trust/profile/myagent").mock(
        return_value=httpx.Response(200, json=_make_profile(score=75, tier="identified"))
    )
    _set_inputs(monkeypatch, agent="myagent", api_key="gbok_x", threshold="60", required_tier="verified")
    from entrypoint import main
    assert main() == 4


def test_required_tier_invalid_value_is_caller_error(respx_mock, monkeypatch):
    _set_inputs(monkeypatch, agent="myagent", api_key="gbok_x", threshold="60", required_tier="banana")
    from entrypoint import main
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1


# ── Per-layer thresholds ────────────────────────────────────────────


def test_layer_thresholds_pass(respx_mock, monkeypatch):
    respx_mock.get("/api/v1/trust/profile/myagent").mock(
        return_value=httpx.Response(200, json=_make_profile(score=75))
    )
    _set_inputs(
        monkeypatch,
        agent="myagent",
        api_key="gbok_x",
        threshold="60",
        layer_thresholds="identity=70,compliance=60",
    )
    from entrypoint import main
    assert main() == 0


def test_layer_thresholds_fail(respx_mock, monkeypatch):
    respx_mock.get("/api/v1/trust/profile/myagent").mock(
        return_value=httpx.Response(
            200, json=_make_profile(score=75, identity={"score": 30})
        )
    )
    _set_inputs(
        monkeypatch,
        agent="myagent",
        api_key="gbok_x",
        threshold="60",
        layer_thresholds="identity=70",
    )
    from entrypoint import main
    assert main() == 4


def test_layer_thresholds_bad_format(respx_mock, monkeypatch):
    _set_inputs(monkeypatch, agent="myagent", api_key="gbok_x", layer_thresholds="identity:70")
    from entrypoint import main
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1


def test_layer_thresholds_unknown_layer(respx_mock, monkeypatch):
    _set_inputs(monkeypatch, agent="myagent", api_key="gbok_x", layer_thresholds="banana=50")
    from entrypoint import main
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1


# ── HTTP error mapping ──────────────────────────────────────────────


def test_auth_failure_exits_2(respx_mock, monkeypatch):
    respx_mock.get("/api/v1/trust/profile/myagent").mock(
        return_value=httpx.Response(401, json={"detail": "Invalid key"})
    )
    _set_inputs(monkeypatch, agent="myagent", api_key="gbok_x")
    from entrypoint import main
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2


def test_unknown_agent_is_caller_error(respx_mock, monkeypatch):
    respx_mock.get("/api/v1/trust/profile/nope").mock(
        return_value=httpx.Response(404, json={"detail": "Agent not found"})
    )
    _set_inputs(monkeypatch, agent="nope", api_key="gbok_x")
    from entrypoint import main
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1


def test_5xx_after_retries_is_api_unreachable(respx_mock, monkeypatch):
    # SDK has retry on 5xx by default — we mock multiple 503 to exhaust retries
    respx_mock.get("/api/v1/trust/profile/myagent").mock(
        side_effect=[httpx.Response(503, json={"detail": "boom"})] * 10
    )
    _set_inputs(monkeypatch, agent="myagent", api_key="gbok_x")
    # Patch sleep so retries don't actually wait
    with patch("goulburn._client._async_sleep") as _:
        from entrypoint import main
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 3


# ── Threshold parsing ───────────────────────────────────────────────


def test_threshold_must_be_integer(respx_mock, monkeypatch):
    _set_inputs(monkeypatch, agent="myagent", api_key="gbok_x", threshold="abc")
    from entrypoint import main
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1


def test_threshold_out_of_range(respx_mock, monkeypatch):
    _set_inputs(monkeypatch, agent="myagent", api_key="gbok_x", threshold="120")
    from entrypoint import main
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1


def test_missing_required_input(respx_mock, monkeypatch):
    # agent omitted
    monkeypatch.setenv("INPUT_API_KEY", "gbok_x")
    monkeypatch.setenv("INPUT_BASE_URL", "https://api.example.com")
    from entrypoint import main
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
