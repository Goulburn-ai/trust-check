import pytest


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    for k in list(monkeypatch.delenv for _ in [0]):
        pass
    # Clear any leftover INPUT_* / GOULBURN_* env vars from previous tests.
    import os
    for k in list(os.environ.keys()):
        if k.startswith("INPUT_") or k.startswith("GOULBURN_"):
            monkeypatch.delenv(k, raising=False)
