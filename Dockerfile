# syntax=docker/dockerfile:1
FROM python:3.11-slim

# git is required to install the SDK from its git tag (the package isn't on
# PyPI yet). --no-install-recommends keeps the image small.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*

# Install the goulburn SDK (pinned by tag in production releases)
ENV PIP_NO_CACHE_DIR=1
RUN pip install --upgrade pip \
 && pip install \
      "goulburn @ git+https://github.com/Goulburn-ai/goulburn-sdk-python.git@v0.2.0" \
      "httpx>=0.27,<1"

COPY entrypoint.py /entrypoint.py

# GitHub Actions runs entrypoints with the inputs as env vars
# (INPUT_AGENT, INPUT_API_KEY, ...). entrypoint.py reads them.
ENTRYPOINT ["python", "/entrypoint.py"]
