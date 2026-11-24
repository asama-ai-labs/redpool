#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

# Install Redpool sharded-proxy systemd units. Intended for Linux production hosts.
# Writes only under /etc/systemd/; does not modify files in the repository tree. systemd creates
# /var/lib/redpool (the service user's home, for the uv cache and mitmproxy's config) on start.
# Usage: sudo ./install.sh   (from the repository root)
set -euo pipefail

# =============================================================================
# Configuration — edit here, then run: sudo ./install.sh
# =============================================================================

# Repository root (default: directory containing this script)
REPO="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

# Unix user:group for the shard front and workers (created if missing)
RUN_AS=redpool

# Sharded proxy ports, worker count, etc.: edit deploy/systemd/redpool-shard.env (not touched here)

# After install, enable and start the target
ENABLE_NOW=true

# =============================================================================

SD="${REPO}/deploy/systemd"
GEN_SRC="${SD}/system-generators/redpool-shard-generator"
SHARD_ENV="${SD}/redpool-shard.env"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

if [[ ! -f "${REPO}/pyproject.toml" ]]; then
  echo "REPO=${REPO} does not look like the redpool root (no pyproject.toml)." >&2
  exit 1
fi

if [[ ! -r "${SHARD_ENV}" ]]; then
  echo "Missing or unreadable ${SHARD_ENV} — it ships with the repo (deploy/systemd/redpool-shard.env)." >&2
  exit 1
fi

# The repo path is written into root-run files, so allow only plain path characters.
if [[ ! "${REPO}" =~ ^[A-Za-z0-9_./-]+$ ]]; then
  echo "REPO=${REPO} has characters other than letters, digits, and _ . / -" >&2
  exit 1
fi

if ! getent group "${RUN_AS}" >/dev/null; then
  groupadd --system "${RUN_AS}"
  echo "Created system group ${RUN_AS}"
fi
if ! getent passwd "${RUN_AS}" >/dev/null; then
  useradd --system \
    --gid "${RUN_AS}" \
    --no-create-home \
    --home-dir /nonexistent \
    --shell /usr/sbin/nologin \
    "${RUN_AS}"
  echo "Created system user ${RUN_AS}"
fi
# The user's passwd home is /nonexistent. systemd creates this directory for it (StateDirectory=).
STATE_HOME=/var/lib/redpool

num_workers=4
line="$(grep -E '^[[:space:]]*REDPOOL_SHARD_NUM_WORKERS=' "${SHARD_ENV}" | tail -n1 || true)"
if [[ -n "${line}" ]]; then
  num_workers="${line#*=}"
  num_workers="${num_workers//[[:space:]]/}"
fi
if ! [[ "${num_workers}" =~ ^[1-9][0-9]*$ ]]; then
  echo "Invalid REDPOOL_SHARD_NUM_WORKERS in ${SHARD_ENV}, using 4" >&2
  num_workers=4
fi

install -m 644 "${SD}/redpool-shard.target" /etc/systemd/system/
install -m 644 "${SD}/redpool-shard-front.service" /etc/systemd/system/
install -m 644 "${SD}/redpool-shard-worker@.service" /etc/systemd/system/

# Copy the generator so the file root runs is root-owned. Remove the target first: an older
# install left a symlink here, and writing through it would overwrite the file in the clone.
install -d /etc/systemd/system-generators
rm -f /etc/systemd/system-generators/redpool-shard-generator
sed "s|^CONF_OVERRIDE=.*|CONF_OVERRIDE='${SHARD_ENV}'|" "${GEN_SRC}" \
  >/etc/systemd/system-generators/redpool-shard-generator
chmod 755 /etc/systemd/system-generators/redpool-shard-generator

mkdir -p /etc/systemd/system/redpool-shard-front.service.d \
  /etc/systemd/system/redpool-shard-worker@.service.d

# Drop-ins live only under /etc; set machine-specific cwd, PATH, and repo path for processes.
DROP_IN="[Service]
User=${RUN_AS}
Group=${RUN_AS}
WorkingDirectory=${REPO}
StateDirectory=redpool
Environment=HOME=${STATE_HOME}
Environment=PYTHONUNBUFFERED=1
Environment=REDPOOL_REPO=${REPO}
Environment=REDPOOL_CONFIG=${REPO}/redpool.yaml
# /snap/bin: Ubuntu snap installs uv there; systemd has no login PATH.
Environment=PATH=${REPO}/.venv/bin:/snap/bin:${STATE_HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin
EnvironmentFile=-${SHARD_ENV}
"

printf '%s\n' "${DROP_IN}" >/etc/systemd/system/redpool-shard-front.service.d/10-repo.conf
printf '%s\n' "${DROP_IN}" >/etc/systemd/system/redpool-shard-worker@.service.d/10-repo.conf

systemctl daemon-reload

if [[ "${ENABLE_NOW}" == "true" ]]; then
  systemctl enable --now redpool-shard.target
  echo "Started redpool-shard.target (front + ${num_workers} workers; env from ${SHARD_ENV})."
else
  systemctl enable redpool-shard.target
  echo "Enabled redpool-shard.target. Start with: systemctl start redpool-shard.target"
fi

echo "Drop-ins: /etc/systemd/system/redpool-shard-*.service.d/10-repo.conf — re-run this script after moving the clone, changing RUN_AS, or editing the generator."
