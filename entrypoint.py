#!/usr/bin/env python3
"""trust-check GitHub Action entrypoint.

Thin shim. All logic now lives in the goulburn_trust_check package.
We keep this file so the Dockerfile entrypoint and any external invokers
that called `python /entrypoint.py` continue to work after v1.1.0.
"""
from __future__ import annotations

import sys

from goulburn_trust_check.github_action import main

if __name__ == "__main__":
    sys.exit(main())
