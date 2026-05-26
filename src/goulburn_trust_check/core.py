"""Pure logic for the trust-check tool.

This module is intentionally free of all I/O surface that's specific to
GitHub Actions (no INPUT_* env reads, no GITHUB_OUTPUT writes, no PR
comments). It accepts plain Python args + returns a Result dataclass.

Callers:
  - cli.py            — argparse → core.run(...) → exit code + stdout
  - github_action.py  — env vars → core.run(...) → exit code + GH-specific
                                                   step outputs / summary

This split lets us unit-test the gating logic without GitHub-specific shims
and means non-GitHub users (GitLab, CircleCI, Jenkins, pre-commit) get the
exact same threshold semantics as the Action.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any

# Exit codes — kept identical to the original GitHub Action so existing
# customers don't see a behaviour change after the refactor.
EXIT_OK = 0
EXIT_CALLER_ERROR = 1
EXIT_AUTH_FAIL = 2
EXIT_API_UNREACHABLE = 3
EXIT_AGENT_FAILED = 4

VALID_TIERS = ("identified", "verified", "established", "trusted")
TIER_RANK = {t: i for i, t in enumerate(VALID_TIERS)}
VALID_LAYERS = ("identity", "capability", "track_record", "social", "compliance")


@dataclass
class CheckRequest:
    """Inputs to a single trust-check invocation."""

    agent: str
    api_key: str
    threshold: int = 60
    required_tier: str | None = None
    layer_thresholds: dict[str, int] = field(default_factory=dict)
    base_url: str = "https://api.goulburn.ai"


@dataclass
class CheckResult:
    """Outcome of a trust-check invocation."""

    passed: bool
    exit_code: int
    overall_score: int = 0
    tier: str = ""
    layers: dict[str, Any] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    decision: str = ""
    error: str | None = None


# ── Parsing helpers (raise ValueError on bad input — callers translate) ─

def parse_threshold(raw: str) -> int:
    try:
        n = int(str(raw).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"threshold not an integer: {raw!r}") from exc
    if not (0 <= n <= 100):
        raise ValueError(f"threshold must be 0-100, got {n}")
    return n


def parse_required_tier(raw: str | None) -> str | None:
    if not raw:
        return None
    val = str(raw).strip().lower()
    if not val:
        return None
    if val not in VALID_TIERS:
        raise ValueError(
            f"required-tier must be one of {VALID_TIERS}, got {val!r}"
        )
    return val


def parse_layer_thresholds(raw: str | None) -> dict[str, int]:
    out: dict[str, int] = {}
    if not raw:
        return out
    for pair in str(raw).split(","):
        pair = pair.strip()
        if not pair:
            continue
        if "=" not in pair:
            raise ValueError(
                f"layer-thresholds malformed near {pair!r} (expected key=value)"
            )
        key, val = pair.split("=", 1)
        key = key.strip()
        try:
            ival = int(val.strip())
        except ValueError as exc:
            raise ValueError(
                f"layer-thresholds value for {key!r} not an integer: {val!r}"
            ) from exc
        if not (0 <= ival <= 100):
            raise ValueError(
                f"layer-thresholds value for {key!r} must be 0-100, got {ival}"
            )
        if key not in VALID_LAYERS:
            raise ValueError(f"unknown layer {key!r} in layer-thresholds")
        out[key] = ival
    return out


# ── Core: fetch + check ────────────────────────────────────────────────

def _fetch_profile(req: CheckRequest):
    """Fetch the live trust profile or raise a CheckResult-shaped exception.

    Returns the SDK profile object. On error, returns (None, error_result).
    """
    # Lazy import so the package can be imported without httpx if a caller
    # is using their own transport / mocking.
    try:
        from goulburn import (
            APIError,
            AuthenticationError,
            GoulburnError,
            SyncClient,
        )
    except ImportError as exc:
        return None, CheckResult(
            passed=False,
            exit_code=EXIT_CALLER_ERROR,
            error=f"goulburn SDK not importable: {exc}",
        )

    try:
        with SyncClient(api_key=req.api_key, base_url=req.base_url) as gb:
            return gb.trust.profile(req.agent), None
    except AuthenticationError as exc:
        return None, CheckResult(
            passed=False,
            exit_code=EXIT_AUTH_FAIL,
            error=f"Auth failed: {getattr(exc, 'detail', exc)}",
        )
    except APIError as exc:
        status = getattr(exc, "status_code", 0)
        if status == 404:
            return None, CheckResult(
                passed=False,
                exit_code=EXIT_CALLER_ERROR,
                error=f"Agent {req.agent!r} not found",
            )
        return None, CheckResult(
            passed=False,
            exit_code=EXIT_API_UNREACHABLE,
            error=f"goulburn API error ({status}): {getattr(exc, 'detail', exc)}",
        )
    except GoulburnError as exc:
        return None, CheckResult(
            passed=False,
            exit_code=EXIT_API_UNREACHABLE,
            error=str(exc),
        )
    except Exception as exc:  # pragma: no cover — defensive
        return None, CheckResult(
            passed=False,
            exit_code=EXIT_API_UNREACHABLE,
            error=f"Unexpected error contacting goulburn: {exc}",
        )


def run(req: CheckRequest) -> CheckResult:
    """Fetch the live profile and apply the threshold + tier + layer checks.

    Never raises — always returns a CheckResult with a well-defined exit_code.
    """
    profile, err = _fetch_profile(req)
    if err is not None:
        # Network/auth/SDK-level errors short-circuit before any check runs.
        err.decision = f"trust-check: ERROR for {req.agent} — {err.error}"
        return err

    try:
        overall = int(profile.overall_score)
        tier = str(profile.tier)
        layers = profile.layers or {}
    except AttributeError as exc:
        return CheckResult(
            passed=False,
            exit_code=EXIT_API_UNREACHABLE,
            error=f"malformed profile response: {exc}",
            decision=f"trust-check: ERROR for {req.agent} — malformed response",
        )

    failures: list[str] = []
    if overall < req.threshold:
        failures.append(f"overall_score {overall} < threshold {req.threshold}")

    if req.required_tier is not None:
        live_rank = TIER_RANK.get(tier, -1)
        need_rank = TIER_RANK[req.required_tier]
        if live_rank < need_rank:
            failures.append(
                f"tier {tier!r} below required {req.required_tier!r}"
            )

    for layer_name, min_score in req.layer_thresholds.items():
        layer = layers.get(layer_name) if isinstance(layers, dict) else None
        if not isinstance(layer, dict):
            failures.append(f"layer {layer_name!r} missing in profile response")
            continue
        score = layer.get("score")
        try:
            score_int = int(score)
        except (TypeError, ValueError):
            failures.append(
                f"layer {layer_name!r} has non-integer score {score!r}"
            )
            continue
        if score_int < min_score:
            failures.append(
                f"layer {layer_name!r} score {score_int} < {min_score}"
            )

    passed = not failures
    if passed:
        decision = (
            f"trust-check: PASS for {req.agent} — score {overall} (tier {tier!r})"
        )
    else:
        decision = (
            f"trust-check: FAIL for {req.agent} — {'; '.join(failures)}"
        )

    return CheckResult(
        passed=passed,
        exit_code=EXIT_OK if passed else EXIT_AGENT_FAILED,
        overall_score=overall,
        tier=tier,
        layers=layers if isinstance(layers, dict) else {},
        failures=failures,
        decision=decision,
    )


def format_markdown_summary(req: CheckRequest, res: CheckResult) -> str:
    """Render the same markdown step-summary the Action used to print."""
    lines = [
        f"### goulburn trust-check: {'PASS' if res.passed else 'FAIL'}",
        "",
        f"**Agent:** `{req.agent}`",
        f"**Score:** {res.overall_score}",
        f"**Tier:** {res.tier}",
        "",
        "| Layer | Score |",
        "|---|---|",
    ]
    for layer_name in VALID_LAYERS:
        layer = res.layers.get(layer_name) if isinstance(res.layers, dict) else None
        if isinstance(layer, dict) and "score" in layer:
            lines.append(f"| {layer_name} | {layer['score']} |")
    if res.failures:
        lines.extend(["", "**Failures:**"])
        for f in res.failures:
            lines.append(f"- {f}")
    return "\n".join(lines)
