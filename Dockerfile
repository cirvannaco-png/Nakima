# ─── Diff-review frontend build stage ─────────────────────────────────────────
FROM node:20-bookworm-slim AS diff_review_builder

WORKDIR /build/nakima_diff_review

COPY nakima_diff_review/package*.json ./
RUN npm ci

COPY nakima_diff_review/ ./
RUN npm run build

# ─── Python build stage ───────────────────────────────────────────────────────
FROM python:3.13-slim-trixie AS builder

WORKDIR /build

# Install build tools only in builder. Security patches are applied first so a
# stale base-image layer can't ship known-fixed CVEs.
RUN apt-get update && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends \
    gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ─── Runtime stage ────────────────────────────────────────────────────────────
FROM python:3.13-slim-trixie AS runtime

# Security: run as non-root
RUN groupadd --gid 1001 nakima && \
    useradd --uid 1001 --gid nakima --shell /bin/bash --create-home nakima

WORKDIR /app

# Apply the distro's security updates (util-linux et al. are patched after the
# base image is cut), then install runtime deps only: libpq for asyncpg and git
# for gitpython clone_from.
RUN apt-get update && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends \
    libpq5 curl git \
    && rm -rf /var/lib/apt/lists/*

# Copy pre-built packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY --chown=nakima:nakima . .

# Publish the built diff-review frontend through FastAPI's /static mount.
COPY --from=diff_review_builder --chown=nakima:nakima \
    /build/nakima_diff_review/dist /app/static/diff-review

# Remove dev/test artefacts from the image
RUN rm -rf tests/ scripts/ attached_assets/ .github/ .git/ nakima_diff_review/ \
    && find . -name "*.pyc" -delete \
    && find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

USER nakima

# Liveness / readiness probe port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "api.router:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--log-level", "info"]
