# syntax=docker/dockerfile:1
FROM python:3.11-slim

# Install the goulburn-trust-check package from PyPI (it pulls in the
# goulburn SDK as a transitive dep). No more git+ install — drops the
# apt-install of git that was needed by v1.0.x.
ENV PIP_NO_CACHE_DIR=1
RUN pip install --upgrade pip \
 && pip install "goulburn-trust-check==1.1.0"

# entrypoint.py is a thin shim that calls into the package; we ship it
# in the image so legacy invokers that exec /entrypoint.py still work.
COPY entrypoint.py /entrypoint.py

# GitHub Actions runs entrypoints with the inputs as env vars
# (INPUT_AGENT, INPUT_API_KEY, ...). The shim reads them.
ENTRYPOINT ["python", "/entrypoint.py"]
