"""argparse CLI — `goulburn-trust-check ...` and `gb-trust-check ...`.

For any CI that isn't GitHub Actions (GitLab CI, CircleCI, Jenkins,
Buildkite, pre-commit, local dev). Same exit codes as the GH Action.
"""
from __future__ import annotations

import argparse
import os
import sys

from . import __version__
from .core import (
    EXIT_CALLER_ERROR,
    CheckRequest,
    format_markdown_summary,
    parse_layer_thresholds,
    parse_required_tier,
    parse_threshold,
    run,
)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="goulburn-trust-check",
        description=(
            "Gate CI deploys on goulburn.ai trust scores. "
            "Fails (non-zero exit) if the agent's score drops below the threshold."
        ),
    )
    p.add_argument(
        "--agent",
        default=os.environ.get("GOULBURN_AGENT", ""),
        help="Agent name to check (case-sensitive). Required. Env: GOULBURN_AGENT.",
    )
    p.add_argument(
        "--api-key",
        default=os.environ.get("GOULBURN_API_KEY", ""),
        help="Owner API key (gbok_...). Env: GOULBURN_API_KEY.",
    )
    p.add_argument(
        "--threshold",
        default="60",
        help="Minimum overall_score required to pass (0-100). Default 60.",
    )
    p.add_argument(
        "--required-tier",
        default="",
        help="Optional minimum tier: identified | verified | established | trusted.",
    )
    p.add_argument(
        "--layer-thresholds",
        default="",
        help=(
            "Per-layer minimum scores, e.g. 'identity=70,compliance=60'. "
            "Layers not listed are not checked."
        ),
    )
    p.add_argument(
        "--base-url",
        default=os.environ.get(
            "GOULBURN_API_BASE", "https://api.goulburn.ai"
        ),
        help="Override the API base URL. Defaults to https://api.goulburn.ai.",
    )
    p.add_argument(
        "--format",
        choices=("text", "json", "markdown"),
        default="text",
        help="Output format. text=one-line decision; json=full result; markdown=PR-comment style.",
    )
    p.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not args.agent:
        parser.error("--agent is required (or set GOULBURN_AGENT)")
    if not args.api_key:
        parser.error("--api-key is required (or set GOULBURN_API_KEY)")

    try:
        threshold = parse_threshold(args.threshold)
        required_tier = parse_required_tier(args.required_tier)
        layer_thresholds = parse_layer_thresholds(args.layer_thresholds)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_CALLER_ERROR

    req = CheckRequest(
        agent=args.agent,
        api_key=args.api_key,
        threshold=threshold,
        required_tier=required_tier,
        layer_thresholds=layer_thresholds,
        base_url=args.base_url.rstrip("/"),
    )
    res = run(req)

    if args.format == "json":
        import json
        print(json.dumps(
            {
                "passed": res.passed,
                "exit_code": res.exit_code,
                "overall_score": res.overall_score,
                "tier": res.tier,
                "layers": res.layers,
                "failures": res.failures,
                "decision": res.decision,
                "error": res.error,
            },
            default=str,
            indent=2,
        ))
    elif args.format == "markdown":
        print(format_markdown_summary(req, res))
    else:
        if res.error and not res.passed:
            print(f"error: {res.error}", file=sys.stderr)
        print(res.decision)

    return res.exit_code


if __name__ == "__main__":
    sys.exit(main())
