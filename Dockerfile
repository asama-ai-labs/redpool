# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

# Base images are pinned by digest. Dependabot (.github/dependabot.yml) proposes updates.
# Multi-stage Dockerfile: build a venv per package, then copy only runtime files.
# Build: docker build --target redpool -t redpool .
#        docker build --target redfish-snapshot -t redfish-snapshot .
#
# A mock BMC is DMTF Redfish-Mockup-Server (dmtf/redfish-mockup-server) serving
# fixtures/<Vendor>/<Model>/original, which uses the DMTF mockup layout.

# -----------------------------------------------------------------------------
# Stage: src — workspace files shared by the per-package builders.
# -----------------------------------------------------------------------------
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b AS src

# uv stays in the builder. The runtime stages do not copy it.
COPY --from=ghcr.io/astral-sh/uv:0.5@sha256:7bff3c3776ec467fc1437960f2c469d8beb30f536a6465a3350c647ccd260ec2 /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock redpool.yaml README.md LICENSE NOTICE ./
COPY redpool redpool
COPY normalizers normalizers
COPY redfish-snapshot redfish-snapshot
COPY third_party/pciids/pci.ids third_party/pciids/pci.ids

# Copy wheels into the venv so the runtime stage does not need the uv cache.
ENV UV_NO_CACHE=1 \
    UV_LINK_MODE=copy

# -----------------------------------------------------------------------------
# Builders — one venv per package so images do not inherit each other's deps.
# -----------------------------------------------------------------------------
FROM src AS redpool-build
RUN uv sync --frozen --no-dev --package redpool

FROM src AS redfish-snapshot-build
RUN uv sync --frozen --no-dev --package redfish-snapshot


# -----------------------------------------------------------------------------
# Stage: redpool — Redfish normalizing MITM proxy
# -----------------------------------------------------------------------------
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b AS redpool

LABEL org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.vendor="Asama Inc." \
      org.opencontainers.image.source="https://github.com/asama-ai-labs/redpool"

WORKDIR /app

# License texts, including the pci.ids BSD-3-Clause notice in NOTICE.
COPY --from=src /app/LICENSE /app/NOTICE /licenses/

COPY --from=redpool-build /app/.venv /app/.venv
COPY --from=redpool-build /app/redpool /app/redpool
COPY --from=redpool-build /app/normalizers /app/normalizers
COPY --from=redpool-build /app/redpool.yaml /app/redpool.yaml
COPY --from=redpool-build /app/third_party/pciids/pci.ids /app/third_party/pciids/pci.ids

# Run as an unprivileged user. Its home holds mitmproxy's certificate directory (~/.mitmproxy).
RUN groupadd --system redpool \
    && useradd --system --gid redpool --create-home --home-dir /home/redpool redpool
USER redpool

ENV PATH="/app/.venv/bin:$PATH"
# Inside the container /metrics must listen on all interfaces so a published port reaches it.
ENV REDPOOL_METRICS_HOST=0.0.0.0

EXPOSE 8080 9101
# Inside the container the proxy must listen on all interfaces so a published port reaches
# it. docker-compose.yml publishes the ports on 127.0.0.1 only.
ENTRYPOINT ["redpool-proxy", "--listen-host", "0.0.0.0", "--listen-port", "8080"]

# -----------------------------------------------------------------------------
# Stage: snapshot — Redfish API snapshot/capture (one-shot CLI)
# -----------------------------------------------------------------------------
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b AS redfish-snapshot

LABEL org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.vendor="Asama Inc." \
      org.opencontainers.image.source="https://github.com/asama-ai-labs/redpool"

WORKDIR /app

COPY --from=src /app/LICENSE /app/NOTICE /licenses/

COPY --from=redfish-snapshot-build /app/.venv /app/.venv
COPY --from=redfish-snapshot-build /app/redfish-snapshot /app/redfish-snapshot

ENV PATH="/app/.venv/bin:$PATH"

ENTRYPOINT ["redfish-snapshot"]
