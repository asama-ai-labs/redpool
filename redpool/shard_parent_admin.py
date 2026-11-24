# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Parent-process HTTP: Prometheus HTTP SD for shard worker /metrics targets."""

from __future__ import annotations

import ipaddress
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from typing import Any, Dict, List, Sequence

logger = logging.getLogger("redpool.shard_parent_admin")


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _log_admin_bind(listen_host: str, listen_port: int) -> None:
    """Log the admin bind, and warn when it is not loopback.

    ``/prometheus-sd`` and ``/health`` have no authentication.
    """
    if _is_loopback(listen_host):
        logger.info(
            "Shard parent admin on %s:%s (/prometheus-sd, /health)",
            listen_host,
            listen_port,
        )
        return
    logger.warning(
        "Shard parent admin on %s:%s (/prometheus-sd, /health) is not loopback. "
        "Those endpoints are not authenticated and list worker addresses; "
        "limit who can reach them.",
        listen_host,
        listen_port,
    )


def _sd_target_hostport(host: str, port: int) -> str:
    """Format ``host:port`` for Prometheus HTTP SD (bracket IPv6)."""
    h = host.strip()
    if h.startswith("["):
        return f"{h}:{port}"
    if h.count(":") >= 2:
        return f"[{h}]:{port}"
    return f"{h}:{port}"


def prometheus_http_sd_payload(
    worker_host: str,
    metrics_ports: Sequence[int],
    *,
    job: str = "redpool-shard-worker",
) -> List[Dict[str, Any]]:
    """Prometheus HTTP service discovery: one target group per worker with ``redpool_shard`` label."""
    return [
        {
            "targets": [_sd_target_hostport(worker_host, port)],
            "labels": {
                "redpool_shard": str(shard),
                "job": job,
            },
        }
        for shard, port in enumerate(metrics_ports)
    ]


class _ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class _ShardParentAdminHandler(BaseHTTPRequestHandler):
    server_version = "RedpoolShardParent/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        logger.debug("%s - %s", self.address_string(), fmt % args)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        host: str = self.server.worker_host  # type: ignore[attr-defined]
        ports: List[int] = self.server.metrics_ports  # type: ignore[attr-defined]

        if path == "/prometheus-sd":
            payload = prometheus_http_sd_payload(host, ports)
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return

        if path in ("/", "/health"):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            msg = b"redpool-shard-parent: GET /prometheus-sd\n"
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)
            return

        self.send_error(404, "Not Found")


def start_shard_parent_admin_http(
    listen_host: str,
    listen_port: int,
    worker_host: str,
    metrics_ports: Sequence[int],
) -> tuple[threading.Thread, HTTPServer]:
    """Bind *listen_port* and serve /prometheus-sd in a daemon thread."""

    class _Server(_ThreadingHTTPServer):
        """Threaded HTTP server; ``worker_host`` / ``metrics_ports`` set on the instance."""

    httpd = _Server((listen_host, listen_port), _ShardParentAdminHandler)
    httpd.worker_host = worker_host  # type: ignore[attr-defined]
    httpd.metrics_ports = list(metrics_ports)  # type: ignore[attr-defined]

    def _run() -> None:
        _log_admin_bind(listen_host, listen_port)
        logger.info(
            "Shard parent admin workers %s",
            metrics_ports,
        )
        try:
            httpd.serve_forever()
        except Exception as e:
            logger.error("Shard parent admin server stopped: %s", e)

    t = threading.Thread(target=_run, name="redpool-shard-parent-admin", daemon=True)
    t.start()
    return t, httpd
