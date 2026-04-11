# ServiceNow MCP Server - Production Dockerfile
# Multi-stage build with security best practices

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

# Copy dependency files first for better caching
COPY pyproject.toml README.md LICENSE ./

# Create virtual environment and install dependencies
RUN uv venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN uv pip install --no-cache -e .

# ============================================
# Stage 2: Runtime (without Playwright)
# ============================================
FROM python:3.11-slim AS runtime

# Labels for container metadata
LABEL maintainer="jshsakura"
LABEL description="ServiceNow MCP Server - Model Context Protocol for ServiceNow"
LABEL version="1.5.1"

# Security: Create non-root user
RUN groupadd --gid 1000 appgroup \
    && useradd --uid 1000 --gid appgroup --shell /bin/bash --create-home appuser

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Copy application code
COPY --chown=appuser:appgroup pyproject.toml README.md LICENSE ./
COPY --chown=appuser:appgroup src/ ./src/
COPY --chown=appuser:appgroup config/ ./config/

# Switch to non-root user
USER appuser

# Expose the default port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/sse || exit 1

# Default environment variables
ENV SERVICENOW_AUTH_TYPE=basic
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Command to run the application
# Use MCP_MODE=stdio for MCP server, MCP_MODE=sse for HTTP SSE server
ENV MCP_MODE=stdio
ENTRYPOINT ["sh", "-c", "if [ \"$MCP_MODE\" = \"sse\" ]; then servicenow-mcp-sse --host=0.0.0.0 --port=8080; else servicenow-mcp; fi"]

# ============================================
# Stage 3: Runtime with Playwright (for Browser Auth)
# ============================================
FROM runtime AS runtime-playwright

USER root

# Install Playwright dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Install Playwright and browsers
RUN pip install playwright && playwright install chromium --with-deps

USER appuser

# ============================================
# Usage:
# 
# Standard build (no Playwright):
#   docker build --target runtime -t servicenow-mcp:latest .
#
# With Playwright (for Browser Auth):
#   docker build --target runtime-playwright -t servicenow-mcp:playwright .
#
# Run:
#   docker run -p 8080:8080 \
#     -e SERVICENOW_INSTANCE_URL=https://instance.service-now.com \
#     -e SERVICENOW_USERNAME=admin \
#     -e SERVICENOW_PASSWORD=password \
#     servicenow-mcp:latest
# ============================================
