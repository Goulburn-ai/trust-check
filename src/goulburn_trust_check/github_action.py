"""GitHub Actions entry point — reads INPUT_* env vars, writes GITHUB_OUTPUT.

Invoked from the Action's Dockerfile via:
    python -m goulburn_trust_check.github_action

Identical behaviour to the legacy entrypoint.py — outputs, summary, PR
comments, and exit codes are all preserved so existing customers see no
visible change after the package refactor.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

from .core import (
    EXIT_AGENT_FAILED,
    EXIT_CALLER_ERROR,
    EXIT_OK,
    CheckRequest,
    format_markdown_summary,
    parse_layer_thresholds,
    parse_required_tier,
    parse_threshold,
    run,
)


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
        pass


def _maybe_pr_comment(summary: str) -> None:
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
    except Exception as exc:
        print(f"::warning::PR comment failed: {exc}")


def main() -> int:
    agent = _input("agent", required=True)
    api_key = _input("api-key", required=True)
    try:
        threshold = parse_threshold(_input("threshold", default="60"))
        required_tier = parse_required_tier(_input("required-tier", default=""))
        layer_thresholds = parse_layer_thresholds(_input("layer-thresholds", default=""))
    except ValueError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return EXIT_CALLER_ERROR

    base_url = _input("base-url", default="https://api.goulburn.ai").rstrip("/")
    req = CheckRequest(
        agent=agent,
        api_key=api_key,
        threshold=threshold,
        required_tier=required_tier,
        layer_thresholds=layer_thresholds,
        base_url=base_url,
    )
    res = run(req)

    _set_output("overall-score", res.overall_score)
    _set_output("tier", res.tier)
    _set_output("passed", "true" if res.passed else "false")
    _set_output("decision", res.decision)

    summary = format_markdown_summary(req, res)
    _set_step_summary(summary)
    _maybe_pr_comment(summary)

    if res.passed:
        print(res.decision)
        return EXIT_OK

    # Surface SDK/network/auth errors as ::error:: too (not just gate failures).
    if res.error:
        print(f"::error::{res.error}", file=sys.stderr)
    print(f"::error::{res.decision}", file=sys.stderr)
    return res.exit_code if res.exit_code != EXIT_OK else EXIT_AGENT_FAILED


if __name__ == "__main__":
    sys.exit(main())
