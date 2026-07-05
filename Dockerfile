# check=skip=SecretsUsedInArgOrEnv
# ^ False positive: SERVICENOW_AUTH_TYPE is a MODE SELECTOR (basic/api_key/
#   browser), not a credential — the name merely contains "AUTH". Actual
#   secrets (SERVICENOW_API_KEY etc.) are never baked into the image; they
#   arrive at runtime via `docker run -e ...` (see usage block below).

# ServiceNow MCP Server - Production Dockerfile
# Multi-stage build with security best practices
# stdio transport only — MCP clients connect over stdin/stdout, not HTTP.

# ============================================
# Stage 1: Builder
# ============================================
FROM python:3.11-slim AS builder

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install uv for faster dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy the full source so a regular (non-editable) install vendors everything —
# package modules, config/, and the force-included skills/ — into the venv.
# An editable install would instead drop skills/ at site-packages/servicenow_mcp/
# and shadow the real package as a namespace dir (servicenow_mcp.__file__=None).
COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/
COPY config/ ./config/
COPY skills/ ./skills/

# Create virtual environment and install the package (non-editable)
RUN uv venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN uv pip install --no-cache .

# ============================================
# Stage 2: Runtime
# ============================================
FROM python:3.11-slim AS runtime

# Build-arg version flows in from CI (e.g. --build-arg VERSION=1.9.34)
ARG VERSION=dev

# Labels for container metadata
LABEL maintainer="jshsakura"
LABEL description="ServiceNow MCP Server - Model Context Protocol for ServiceNow"
LABEL version="${VERSION}"

# Security: Create non-root user
RUN groupadd --gid 1000 appgroup \
    && useradd --uid 1000 --gid appgroup --shell /bin/bash --create-home appuser

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Copy application code
COPY --chown=appuser:appgroup pyproject.toml README.md LICENSE ./
COPY --chown=appuser:appgroup src/ ./src/
COPY --chown=appuser:appgroup config/ ./config/
# Skills load at runtime from /app/skills (skill_resources repo fallback);
# the editable install does not vendor them into the venv.
COPY --chown=appuser:appgroup skills/ ./skills/

# Switch to non-root user
USER appuser

# Default environment variables
ENV SERVICENOW_AUTH_TYPE=api_key
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# stdio MCP server. The MCP client (Claude Desktop, Codex, etc.) launches
# this container and speaks JSON-RPC over stdin/stdout.
ENTRYPOINT ["servicenow-mcp"]

# ============================================
# Usage:
#
# Build:
#   docker build --target runtime --build-arg VERSION=1.9.34 -t mfa-servicenow-mcp .
#
# Run (API Key auth — recommended for headless/Docker):
#   docker run -i --rm \
#     -e SERVICENOW_INSTANCE_URL=https://instance.service-now.com \
#     -e SERVICENOW_AUTH_TYPE=api_key \
#     -e SERVICENOW_API_KEY=your-api-key \
#     mfa-servicenow-mcp
#
# For MFA/SSO browser auth, run on a local machine via uvx (Docker has no
# display server, so interactive MFA is not possible inside a container):
#   uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp \
#     --instance-url https://instance.service-now.com --auth-type browser
# ============================================
