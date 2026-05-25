# syntax=docker/dockerfile:1
FROM python:3.11-slim

# Install the goulburn SDK (pinned by tag in production releases)
ENV PIP_NO_CACHE_DIR=1
RUN pip install --upgrade pip \
 && pip install "goulburn>=0.2,<1" "httpx>=0.27,<1"

COPY entrypoint.py /entrypoint.py

# GitHub Actions runs entrypoints with the inputs as env vars
# (INPUT_AGENT, INPUT_API_KEY, ...). entrypoint.py reads them.
ENTRYPOINT ["python", "/entrypoint.py"]
