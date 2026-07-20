# ─── Build stage ──────────────────────────────────────────────────────────────
FROM python:3.14-slim AS builder

WORKDIR /build

# Install build tools only in builder
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ─── Runtime stage ────────────────────────────────────────────────────────────
FROM python:3.14-slim AS runtime

# Security: run as non-root
RUN groupadd --gid 1001 nakima && \
    useradd --uid 1001 --gid nakima --shell /bin/bash --create-home nakima

WORKDIR /app

# Runtime deps only (libpq for asyncpg)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

# Copy pre-built packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY --chown=nakima:nakima . .

# Remove dev/test artefacts from the image
RUN rm -rf tests/ scripts/ attached_assets/ .github/ .git/ \
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
     "--workers", "4", \
     "--log-config", "/dev/null"]
