# Nakima Sandbox Runner Image
#
# CRITICAL CONSTRAINT: this container runs with network_mode="none" (see
# orchestrator/main.py). That means NOTHING can be pip/npm/apt installed at
# runtime — no dependency fetch, no internet access at all, by design. Every
# tool the self-healing loop might need across supported languages must be
# pre-baked into this image at build time, when the build process itself
# still has network access.
#
# This is a real cost: the image will be large and needs rebuilding whenever
# you add support for a new language/framework. That cost is the price of
# the isolation guarantee — accept it rather than punching a network hole
# "just for dependency installs," which is exactly the kind of exception
# that quietly erodes an isolation boundary over time.

FROM python:3.12-slim AS base

# Pre-baked language toolchains for CI reproduction across common stacks.
# Extend this list deliberately — every addition grows the image and the
# attack surface inside the sandbox, so only add what you've actually seen
# in a real target repo.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    curl \
    ca-certificates \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Python deps needed by the sandbox entrypoint itself (not the target repo's
# deps — those come from the repo's own lockfile, resolved from a pre-warmed
# local package cache baked in below, never fetched live).
RUN pip install --no-cache-dir \
    requests==2.32.3 \
    pyyaml==6.0.2

# Pre-warm a pip/npm cache for common dependency sets so that installing a
# target repo's requirements.txt / package.json works OFFLINE. This is a
# known-gap placeholder: real implementation should pre-warm caches based on
# an audit of what Nakima-connected repos actually use, not a guess.
# TODO(known-gap): build a cache-warming step keyed off observed repo
# manifests before this image is used against real user repos.

WORKDIR /workspace

COPY entrypoint.py /opt/nakima/entrypoint.py
COPY self_healing.py /opt/nakima/self_healing.py

# No CMD shell — entrypoint is the only thing that runs, no interactive
# shell access is baked in as a default execution path.
ENTRYPOINT ["python3", "/opt/nakima/entrypoint.py"]
