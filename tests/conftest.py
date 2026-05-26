"""Shared fixtures for the trust-check test suite."""
from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Strip INPUT_*, GOULBURN_*, GITHUB_* env from prior tests so each
    case starts from a known-clean slate.
    """
    for k in list(os.environ.keys()):
        if k.startswith(("INPUT_", "GOULBURN_", "GITHUB_")) and k not in {
            # Some CI inherits these from the host; tolerate.
            "GITHUB_ACTIONS",
        }:
            monkeypatch.delenv(k, raising=False)


@pytest.fixture
def gha_io_files(tmp_path, monkeypatch):
    """Stub GITHUB_OUTPUT + GITHUB_STEP_SUMMARY to writable tmp files.

    Yields a dict with the file Paths so tests can read what was written.
    """
    out = tmp_path / "outputs.txt"
    summary = tmp_path / "summary.md"
    out.touch()
    summary.touch()
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    yield {"output": out, "summary": summary}


@pytest.fixture
def fake_profile():
    """Returns a callable building a Profile-shaped object the SDK would yield."""
    class _Layer:
        def __init__(self, score):
            self._d = {"score": score}
        def __getitem__(self, k):
            return self._d[k]
        def get(self, k, default=None):
            return self._d.get(k, default)
        def keys(self):
            return self._d.keys()

    class _Profile:
        def __init__(self, overall=75, tier="verified", layers=None):
            self.overall_score = overall
            self.tier = tier
            self.layers = layers if layers is not None else {
                "identity": {"score": 80},
                "capability": {"score": 70},
                "track_record": {"score": 60},
                "social": {"score": 50},
                "compliance": {"score": 85},
            }

    def _make(overall=75, tier="verified", layers=None):
        return _Profile(overall=overall, tier=tier, layers=layers)
    return _make
