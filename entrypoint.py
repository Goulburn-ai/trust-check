#!/usr/bin/env python3
"""trust-check GitHub Action entrypoint.

Reads inputs from the GitHub-Actions-stamped INPUT_* env vars,
queries the goulburn Trust API via the SDK, applies thresholds,
emits step outputs, and exits with a meaningful code.

Exit codes:
  0  — pass: all thresholds met
  1  — caller error: malformed inputs / unknown layer name / bad threshold
  2  — auth failure: API key is invalid or revoked
  3  — API unreachable: network or 5xx from goulburn (after retries)
  4  — agent failed verification: live score is below the threshold
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

# Distinct exit codes so customer pipelines can branch on the failure
# mode (e.g., retry on 3, page on 4, fail-fast on 1).
EXIT_OK = 0
EXIT_CALLER_ERROR = 1
EXIT_AUTH_FAIL = 2
EXIT_API_UNREACHABLE = 3
EXIT_AGENT_FAILED = 4

VALID_TIERS = ("identified", "verified", "established", "trusted")
TIER_RANK = {t: i for i, t in enumerate(VALID_TIERS)}

# Lazy import so a missing SDK surfaces as a clear error message.
try:
    from goulburn import (
        APIError,
        AuthenticationError,
        Client,
        GoulburnError,
        SyncClient,
    )
except Exception as exc:  # pragma: no cover — defensive
    print(f"::error::goulburn SDK not importable: {exc}", file=sys.stderr)
    sys.exit(EXIT_CALLER_ERROR)


def _input(name: str, *, required: bool = False, default: str | None = None) -> str:
    """Read a GitHub Actions input. INPUT_<NAME-UPPER> per the runner convention."""
    key = "INPUT_" + name.upper().replace("-", "_")
    raw = os.environ.get(key, "")
    if raw == "" and default is not None:
        raw = default
    if required and not raw:
        print(f"::error::missing required input '{name}'", file=sys.stderr)
        sys.exit(EXIT_CALLER_ERROR)
    return raw


def _bool_input(name: str, default: bool = False) -> bool:
    raw = _input(name, default="true" if default else "false").strip().lower()
    return raw in ("true", "1", "yes", "on")


def _set_output(name: str, value: Any) -> None:
    """Write a step output via the GitHub-Actions $GITHUB_OUTPUT file."""
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        # Fallback for local runs — print to stdout in the legacy ::set-output format.
        print(f"::set-output name={name}::{value}")
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{name}={value}\n")


def _set_step_summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except Exception:
        # Best-effort — never fail the action on a summary write issue.
        pass


def _parse_layer_thresholds(raw: str) -> dict[str, int]:
    """Parse 'layer=score,layer=score' into a dict, validate values + layer names."""
    out: dict[str, int] = {}
    if not raw.strip():
        return out
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair:
            continue
        if "=" not in pair:
            print(f"::error::layer-thresholds malformed near '{pair}' (expected key=value)", file=sys.stderr)
            sys.exit(EXIT_CALLER_ERROR)
        key, val = pair.split("=", 1)
        key = key.strip()
        try:
            ival = int(val.strip())
        except ValueError:
            print(f"::error::layer-thresholds value for '{key}' not an integer: {val!r}", file=sys.stderr)
            sys.exit(EXIT_CALLER_ERROR)
        if not (0 <= ival <= 100):
            print(f"::error::layer-thresholds value for '{key}' must be 0-100, got {ival}", file=sys.stderr)
            sys.exit(EXIT_CALLER_ERROR)
        if key not in ("identity", "capability", "track_record", "social", "compliance"):
            print(f"::error::unknown layer '{key}' in layer-thresholds", file=sys.stderr)
            sys.exit(EXIT_CALLER_ERROR)
        out[key] = ival
    return out


def _parse_threshold(raw: str) -> int:
    try:
        n = int(raw.strip())
    except ValueError:
        print(f"::error::threshold not an integer: {raw!r}", file=sys.stderr)
        sys.exit(EXIT_CALLER_ERROR)
    if not (0 <= n <= 100):
        print(f"::error::threshold must be 0-100, got {n}", file=sys.stderr)
        sys.exit(EXIT_CALLER_ERROR)
    return n


def _parse_required_tier(raw: str) -> str | None:
    raw = raw.strip().lower()
    if not raw:
        return None
    if raw not in VALID_TIERS:
        print(
            f"::error::required-tier must be one of {VALID_TIERS}, got {raw!r}",
            file=sys.stderr,
        )
        sys.exit(EXIT_CALLER_ERROR)
    return raw


def _fetch_profile(api_key: str, base_url: str, agent: str) -> Any:
    """Returns the trust profile or exits with the appropriate code."""
    try:
        with SyncClient(api_key=api_key, base_url=base_url) as gb:
            return gb.trust.profile(agent)
    except AuthenticationError as e:
        print(f"::error::Auth failed: {e.detail}", file=sys.stderr)
        sys.exit(EXIT_AUTH_FAIL)
    except APIError as e:
        # NotFoundError, RateLimitError, generic 5xx — all surface here.
        # 404 = agent unknown is a CALLER error, not unreachability.
        if e.status_code == 404:
            print(f"::error::Agent '{agent}' not found", file=sys.stderr)
            sys.exit(EXIT_CALLER_ERROR)
        print(f"::error::goulburn API error ({e.status_code}): {e.detail}", file=sys.stderr)
        sys.exit(EXIT_API_UNREACHABLE)
    except GoulburnError as e:
        print(f"::error::{e}", file=sys.stderr)
        sys.exit(EXIT_API_UNREACHABLE)
    except Exception as e:  # pragma: no cover
        print(f"::error::Unexpected error contacting goulburn: {e}", file=sys.stderr)
        sys.exit(EXIT_API_UNREACHABLE)


def _maybe_pr_comment(summary: str) -> None:
    """If running on pull_request and comment-on-pr=true, post a comment.

    Uses the GH_TOKEN provided by the runner; if absent, log and skip.
    """
    if not _bool_input("comment-on-pr"):
        return
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    if event_name not in ("pull_request", "pull_request_target"):
        return
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print("::warning::comment-on-pr requested but no GH_TOKEN/GITHUB_TOKEN available")
        return
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    if not event_path or not os.path.isfile(event_path):
        return
    try:
        with open(event_path, encoding="utf-8") as f:
            event = json.load(f)
        pr_number = event.get("pull_request", {}).get("number")
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        if not pr_number or not repo:
            return
        import httpx
        resp = httpx.post(
            f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments",
            json={"body": summary},
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "goulburn-trust-check",
            },
            timeout=10.0,
        )
        if resp.status_code >= 300:
            print(f"::warning::PR comment failed: HTTP {resp.status_code} — {resp.text[:200]}")
    except Exception as e:
        print(f"::warning::PR comment failed: {e}")


def main() -> int:
    agent = _input("agent", required=True)
    api_key = _input("api-key", required=True)
    threshold = _parse_threshold(_input("threshold", default="60"))
    required_tier = _parse_required_tier(_input("required-tier", default=""))
    layer_thresholds = _parse_layer_thresholds(_input("layer-thresholds", default=""))
    base_url = (_input("base-url", default="https://api.goulburn.ai")).rstrip("/")

    profile = _fetch_profile(api_key, base_url, agent)
    overall = int(profile.overall_score)
    tier = str(profile.tier)
    layers = profile.layers or {}

    # Apply checks
    failures: list[str] = []
    if overall < threshold:
        failures.append(f"overall_score {overall} < threshold {threshold}")

    if required_tier is not None:
        live_rank = TIER_RANK.get(tier, -1)
        need_rank = TIER_RANK[required_tier]
        if live_rank < need_rank:
            failures.append(f"tier '{tier}' below required '{required_tier}'")

    for layer_name, min_score in layer_thresholds.items():
        layer = layers.get(layer_name)
        if not isinstance(layer, dict):
            failures.append(f"layer '{layer_name}' missing in profile response")
            continue
        score = layer.get("score")
        try:
            score_int = int(score)
        except (TypeError, ValueError):
            failures.append(f"layer '{layer_name}' has non-integer score {score!r}")
            continue
        if score_int < min_score:
            failures.append(f"layer '{layer_name}' score {score_int} < {min_score}")

    # Emit outputs + a summary
    passed = not failures
    _set_output("overall-score", overall)
    _set_output("tier", tier)
    _set_output("passed", "true" if passed else "false")

    if passed:
        decision = (
            f"trust-check: PASS for {agent} — score {overall} (tier '{tier}')"
        )
    else:
        decision = (
            f"trust-check: FAIL for {agent} — {'; '.join(failures)}"
        )
    _set_output("decision", decision)

    summary_lines = [
        f"### goulburn trust-check: {'PASS' if passed else 'FAIL'}",
        "",
        f"**Agent:** `{agent}`",
        f"**Score:** {overall}",
        f"**Tier:** {tier}",
        "",
        "| Layer | Score |",
        "|---|---|",
    ]
    for layer_name in ("identity", "capability", "track_record", "social", "compliance"):
        layer = layers.get(layer_name) if isinstance(layers, dict) else None
        if isinstance(layer, dict) and "score" in layer:
            summary_lines.append(f"| {layer_name} | {layer['score']} |")
    if failures:
        summary_lines.extend(["", "**Failures:**"])
        for f in failures:
            summary_lines.append(f"- {f}")
    summary = "\n".join(summary_lines)
    _set_step_summary(summary)

    _maybe_pr_comment(summary)

    if passed:
        print(decision)
        return EXIT_OK
    else:
        print(f"::error::{decision}", file=sys.stderr)
        return EXIT_AGENT_FAILED


if __name__ == "__main__":
    sys.exit(main())
