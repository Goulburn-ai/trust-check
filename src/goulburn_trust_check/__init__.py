"""goulburn-trust-check — pip-installable CLI for gating CI/CD on goulburn.ai trust scores.

Same logic as the goulburn-ai/trust-check GitHub Action, packaged so it can run
from any CI system (GitLab CI, CircleCI, Jenkins, Buildkite, pre-commit, local).

Two entry points:

  goulburn-trust-check   — argparse CLI (use this in any CI)
  python -m goulburn_trust_check.github_action  — reads INPUT_* env vars
                                                  (used by the Docker Action)
"""
from __future__ import annotations

__version__ = "1.1.0"
__all__ = ["__version__"]
