# syntax=docker/dockerfile:1
# Base image pinned by digest (python:3.11-slim, resolved 2026-10-07).
# Dependabot (docker ecosystem) proposes digest bumps.
FROM python:3.11-slim@sha256:0dd364ba7e10242f07755449e3a3d0e35f9efd987952737b90def6709ab0c5ce

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

# Install from the checked-out source at the ref the caller pinned, not from
# PyPI at run time. Every dependency, transitive included, is hash-locked, so
# a compromised or re-uploaded package fails the build instead of running.
WORKDIR /opt/trust-check
COPY requirements.lock ./
COPY src ./src
RUN pip install --require-hashes --no-deps -r requirements.lock
# The package itself runs from source on PYTHONPATH: no build step, so no
# unhashed build backend (hatchling) is fetched at image build time.
ENV PYTHONPATH=/opt/trust-check/src

# entrypoint.py is a thin shim that calls into the package; shipped so
# legacy invokers that exec /entrypoint.py still work.
COPY entrypoint.py /entrypoint.py

# GitHub Actions passes inputs as env vars (INPUT_AGENT, INPUT_API_KEY, ...).
ENTRYPOINT ["python", "/entrypoint.py"]
