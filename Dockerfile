# ── Stage 0: builder ──────────────────────────────────────────────
# Install Python 3.14 + dependencies into a venv. The runtime stage
# only gets the compiled venv, not the build toolchain.

FROM pgvector/pgvector:pg18 AS builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# uv manages both Python and package installation.
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Install a standalone Python 3.14 into a shared location so both
# root (builder) and the 'app' user (runtime) can access it.
ENV UV_PYTHON_INSTALL_DIR=/opt/python
RUN uv python install 3.14
# UV_PROJECT_ENVIRONMENT overrides the default .venv location so
# uv sync installs into our staged path instead of a local .venv.
ENV UV_PROJECT_ENVIRONMENT="/opt/corti/venv"
ENV VIRTUAL_ENV="/opt/corti/venv"
ENV PATH="/opt/corti/venv/bin:$PATH"

WORKDIR /build

# Copy all build inputs and do a single sync.  Layer caching still
# helps: if uv.lock + pyproject.toml + src/ haven't changed, Docker
# reuses the cached layer.
COPY uv.lock pyproject.toml README.md ./
COPY src/ ./src/
RUN uv sync --frozen --no-dev --no-editable


# ── Stage 1: runtime ──────────────────────────────────────────────
FROM pgvector/pgvector:pg18 AS runtime

LABEL maintainer="Corti"
LABEL description="Corti memory framework — PG 18 + pgvector + app"

# Runtime deps: curl for HEALTHCHECK, supervisor for process management.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl supervisor \
    && rm -rf /var/lib/apt/lists/*

# Install uv + Python 3.14 into shared location (matches builder exactly).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -LsSf https://astral.sh/uv/install.sh | sh \
    && rm -rf /var/lib/apt/lists/*
ENV PATH="/root/.local/bin:$PATH"
ENV UV_PYTHON_INSTALL_DIR=/opt/python
RUN uv python install 3.14

# Create non-root user for the corti app process.
# The base image already provides the 'postgres' user.
RUN groupadd --system app \
    && useradd --system --gid app --home-dir /home/app --create-home app

# Copy the Python environment from the builder stage.
COPY --from=builder /opt/corti/venv /opt/corti/venv
# Make venv world-readable/executable so the 'app' user can run it.
RUN chmod -R a+rX /opt/corti/venv
ENV VIRTUAL_ENV="/opt/corti/venv"
ENV PATH="/opt/corti/venv/bin:$PATH"

# Copy supervisord config and entrypoint script.
COPY docker/supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY docker/entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

# Stage default config templates for first-run copy.
COPY src/corti/config/default.toml /opt/corti/config/default.toml
COPY src/corti/config/default_ome.toml /opt/corti/config/default_ome.toml

# Stage agent-integration plugin bundles for install.sh to extract.
COPY src/integrations/hermes /opt/corti/integrations/hermes
COPY src/integrations/claude-code /opt/corti/integrations/claude-code

# Create data directory structure.
RUN mkdir -p /home/app/.corti/.index/pg \
             /home/app/.corti/.index/sqlite \
             /home/app/.corti/.tmp

# ── Environment defaults (overridable via docker run -e) ───────────
ENV CORTI_ROOT=/home/app/.corti
ENV CORTI_API__HOST=0.0.0.0
ENV CORTI_API__PORT=5473
ENV DB_HOST=127.0.0.1
ENV DB_PORT=5432
ENV DB_NAME=corti
ENV DB_USER=corti
ENV DB_PASSWORD=corti_local_2026
ENV PGDATA=/home/app/.corti/.index/pg
ENV LC_ALL=C.UTF-8
ENV LANG=C.UTF-8
ENV TZ=UTC

# Only the HTTP API port is exposed to the host.
# PG listens on container loopback only (127.0.0.1:5432).
EXPOSE 5473

# Health check — probes the /health endpoint every 30s.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5473/health')" || exit 1

# All persistent data lives in one volume.
VOLUME ["/home/app/.corti"]

ENTRYPOINT ["/docker-entrypoint.sh"]
