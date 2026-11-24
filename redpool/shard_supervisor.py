# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Spawn N mitmdump workers and a front HTTP proxy that shards by upstream host:port."""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import select
import signal
import socket
import subprocess
import sys
import threading
import time
from http.server import HTTPServer
from typing import List, Optional, Sequence
from urllib.parse import urlparse

from redpool.shard_mitm import mitmdump_worker_argv, mitmdump_worker_environ

logger = logging.getLogger("redpool.shard")

# A client has this long to send its request headers, so a stalled connection frees its thread.
CLIENT_HEADER_TIMEOUT = 30.0
# A relayed connection with no traffic in either direction for this long is closed.
RELAY_IDLE_TIMEOUT = 300.0
# Client connections served at once. Each one holds a thread, so this bounds the thread count.
DEFAULT_MAX_CONNECTIONS = 1024


def _coalesce_workers(cli_workers: Optional[int]) -> int:
    """CLI ``-n`` if set; else ``REDPOOL_SHARD_NUM_WORKERS``; else 4."""
    if cli_workers is not None:
        return cli_workers
    raw = os.environ.get("REDPOOL_SHARD_NUM_WORKERS", "").strip()
    if raw.isdigit():
        return max(1, int(raw))
    return 4


def stable_shard_index(authority: str, num_workers: int) -> int:
    """Deterministic worker index for upstream *authority* ``host:port``.

    Uses ``sha256(authority)[:8] %% num_workers`` (authority normalized to lower case).
    """
    if num_workers <= 0:
        return 0
    key = authority.strip().lower().encode("utf-8", errors="replace")
    digest = hashlib.sha256(key).digest()
    h = int.from_bytes(digest[:8], "big")
    return h % num_workers


def parse_connect_authority(header_block: bytes) -> Optional[str]:
    """Return ``host:port`` from the first ``CONNECT`` line, or *None*."""
    try:
        text = header_block.decode("utf-8", errors="replace")
    except Exception:
        return None
    first_line = text.split("\r\n", 1)[0].strip()
    parts = first_line.split()
    if len(parts) < 2 or parts[0].upper() != "CONNECT":
        return None
    authority = parts[1].strip()
    if not authority:
        return None
    if authority.startswith("["):
        end = authority.find("]")
        if end < 0:
            return None
        host = authority[1:end]
        rest = authority[end + 1 :].lstrip()
        if rest.startswith(":"):
            port = rest[1:].split()[0] if rest[1:] else "443"
        else:
            port = "443"
    else:
        if ":" not in authority:
            return f"{authority}:443"
        host, _, port = authority.rpartition(":")
        if not port or not port.isdigit():
            return f"{host}:443" if host else None
    return f"{host}:{port}"


def _authority_from_host_header(host_value: str) -> Optional[str]:
    """``host:port`` from a ``Host`` header value (IPv4, name, or bracketed IPv6)."""
    if not host_value:
        return None
    v = host_value.split()[0]
    if v.startswith("["):
        end = v.find("]")
        if end < 0:
            return None
        host = v[1:end]
        after = v[end + 1 :].lstrip()
        if after.startswith(":"):
            port = after[1:].split(";")[0]
            if port.isdigit():
                return f"{host}:{port}"
            return None
        return f"{host}:80"
    if ":" in v:
        host, _, port = v.rpartition(":")
        if port.isdigit():
            return f"{host}:{port}"
    return f"{v}:80"


def parse_forward_proxy_authority(header_block: bytes) -> Optional[str]:
    """Routing key ``host:port`` for CONNECT or HTTP proxy (absolute-form URI or ``Host`` header)."""
    auth = parse_connect_authority(header_block)
    if auth is not None:
        return auth
    try:
        text = header_block.decode("utf-8", errors="replace")
    except Exception:
        return None
    first_line, _, rest = text.partition("\r\n")
    first_line = first_line.strip()
    parts = first_line.split()
    if len(parts) < 2:
        return None
    method = parts[0].upper()
    request_target = parts[1]
    if method == "CONNECT":
        return None
    if request_target.startswith(("http://", "https://")):
        u = urlparse(request_target)
        if not u.hostname:
            return None
        port = u.port
        if port is None:
            port = 443 if u.scheme == "https" else 80
        return f"{u.hostname}:{port}"
    if request_target.startswith("/") or request_target == "*":
        for line in rest.split("\r\n"):
            if not line.strip():
                break
            if ":" not in line:
                continue
            name, _, value = line.partition(":")
            if name.strip().lower() == "host":
                return _authority_from_host_header(value)
        return None
    return None


def force_connection_close(header_block: bytes) -> bytes:
    """Return *header_block* with ``Connection: close`` in place of any connection headers.

    The front picks a worker from the first request on a connection. Closing after that request
    makes a client open a new connection, and so be routed again, for the next one, which may
    name a different host. Any bytes after the blank line (a request body) are kept as they are.
    """
    head, sep, tail = header_block.partition(b"\r\n\r\n")
    if not sep:
        return header_block
    request_line, *fields = head.split(b"\r\n")
    kept = [
        f
        for f in fields
        if f.partition(b":")[0].strip().lower()
        not in (b"connection", b"proxy-connection", b"keep-alive")
    ]
    return b"\r\n".join([request_line, *kept, b"Connection: close"]) + sep + tail


def _read_until_headers(sock: socket.socket, limit: int = 65536) -> bytes:
    buf = b""
    while len(buf) < limit:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buf += chunk
        if b"\r\n\r\n" in buf:
            break
    return buf


def _relay_bidirectional(a: socket.socket, b: socket.socket) -> None:
    sockets = [a, b]
    try:
        while True:
            r, _, _ = select.select(sockets, [], [], RELAY_IDLE_TIMEOUT)
            if not r:
                break
            for s in r:
                data = s.recv(65536)
                if not data:
                    return
                other = b if s is a else a
                other.sendall(data)
    except OSError:
        pass
    finally:
        try:
            a.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            b.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass


def _handle_client(
    client_sock: socket.socket,
    worker_ports: Sequence[int],
    worker_host: str,
    num_workers: int,
) -> None:
    try:
        client_sock.settimeout(CLIENT_HEADER_TIMEOUT)
        buf = _read_until_headers(client_sock)
        if not buf:
            return
        authority = parse_forward_proxy_authority(buf)
        if authority is None:
            logger.warning("Unrecognized proxy request; closing client")
            try:
                client_sock.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
            except OSError:
                pass
            return
        idx = stable_shard_index(authority, num_workers)
        backend_port = worker_ports[idx]
        backend = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        backend.settimeout(30)
        try:
            backend.connect((worker_host, backend_port))
        except OSError as e:
            logger.error(
                "Worker %s (%s:%s) unreachable: %s", idx, worker_host, backend_port, e
            )
            try:
                client_sock.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            except OSError:
                pass
            return
        client_sock.settimeout(RELAY_IDLE_TIMEOUT)
        if parse_connect_authority(buf) is None:
            buf = force_connection_close(buf)
        backend.sendall(buf)
        _relay_bidirectional(client_sock, backend)
    except Exception as exc:
        logger.debug("Client handler error: %s", exc)
    finally:
        try:
            client_sock.close()
        except OSError:
            pass


class ShardSupervisor:
    """Runs a TCP front that shards CONNECT/HTTP proxy to N mitmdump workers.

    With ``manage_workers=True`` (default), starts and stops mitmdump children in-process.
    With ``manage_workers=False`` (``--front-only``), expects workers to be started
    separately (e.g. ``redpool-shard-worker@N`` under systemd).
    """

    def __init__(
        self,
        *,
        num_workers: int,
        front_host: str,
        front_port: int,
        worker_host: str,
        worker_port_base: int,
        metrics_port_base: int,
        mitm_args: Sequence[str],
        parent_admin_host: str = "127.0.0.1",
        parent_admin_port: Optional[int] = None,
        manage_workers: bool = True,
        max_connections: int = DEFAULT_MAX_CONNECTIONS,
    ) -> None:
        if num_workers < 1:
            raise ValueError("num_workers must be >= 1")
        if max_connections < 1:
            raise ValueError("max_connections must be >= 1")
        self._slots = threading.BoundedSemaphore(max_connections)
        self._num_workers = num_workers
        self._manage_workers = manage_workers
        self._front_host = front_host
        self._front_port = front_port
        self._worker_host = worker_host
        self._worker_port_base = worker_port_base
        self._metrics_port_base = metrics_port_base
        self._mitm_args = list(mitm_args)
        self._children: List[subprocess.Popen] = []
        self._server_sock: Optional[socket.socket] = None
        self._shutdown = threading.Event()
        self._accept_thread: Optional[threading.Thread] = None
        self._parent_admin_host = parent_admin_host
        self._parent_admin_port = parent_admin_port
        self._admin_httpd: Optional[HTTPServer] = None

    @property
    def worker_ports(self) -> List[int]:
        return [self._worker_port_base + i for i in range(self._num_workers)]

    def worker_metrics_ports(self) -> List[int]:
        return [self._metrics_port_base + i for i in range(self._num_workers)]

    def _spawn_mitmdump(self, worker_index: int) -> subprocess.Popen:
        listen_port = self._worker_port_base + worker_index
        metrics_port = self._metrics_port_base + worker_index
        cmd = mitmdump_worker_argv(
            worker_index,
            worker_host=self._worker_host,
            worker_port_base=self._worker_port_base,
            metrics_port_base=self._metrics_port_base,
            mitm_args=self._mitm_args,
        )
        env = mitmdump_worker_environ(self._metrics_port_base, worker_index)
        logger.info(
            "Starting worker %s mitmdump on %s:%s metrics=%s",
            worker_index,
            self._worker_host,
            listen_port,
            metrics_port,
        )
        return subprocess.Popen(cmd, env=env)

    def _start_children(self) -> None:
        if not self._manage_workers:
            logger.info(
                "Not spawning mitmdump workers (external/systemd); expect ports %s..%s",
                self._worker_port_base,
                self._worker_port_base + self._num_workers - 1,
            )
            return
        for i in range(self._num_workers):
            self._children.append(self._spawn_mitmdump(i))

    def _stop_children(self, *, timeout: float = 8.0) -> None:
        if not self._manage_workers:
            return
        for p in self._children:
            if p.poll() is None:
                p.terminate()
        deadline = time.monotonic() + timeout
        for p in self._children:
            remaining = max(0.1, deadline - time.monotonic())
            try:
                p.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                p.kill()
                try:
                    p.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
        self._children.clear()

    def _accept_loop(self) -> None:
        assert self._server_sock is not None
        self._server_sock.settimeout(1.0)
        ports = self.worker_ports
        while not self._shutdown.is_set():
            try:
                client, _addr = self._server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            if not self._slots.acquire(blocking=False):
                logger.warning("Connection limit reached; refusing a client")
                try:
                    client.sendall(
                        b"HTTP/1.1 503 Service Unavailable\r\nRetry-After: 1\r\n"
                        b"Connection: close\r\n\r\n"
                    )
                except OSError:
                    pass
                client.close()
                continue
            t = threading.Thread(
                target=self._serve,
                args=(client, ports),
                daemon=True,
            )
            t.start()

    def _serve(self, client: socket.socket, ports: Sequence[int]) -> None:
        try:
            _handle_client(client, ports, self._worker_host, self._num_workers)
        finally:
            self._slots.release()

    def run(self) -> int:
        self._start_children()
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self._server_sock.bind((self._front_host, self._front_port))
            self._server_sock.listen(256)
        except OSError as e:
            logger.error(
                "Front bind %s:%s failed: %s", self._front_host, self._front_port, e
            )
            self._stop_children()
            return 1

        logger.info(
            "Shard front listening on %s:%s (%s workers, ports %s..%s, manage_workers=%s)",
            self._front_host,
            self._front_port,
            self._num_workers,
            self._worker_port_base,
            self._worker_port_base + self._num_workers - 1,
            self._manage_workers,
        )

        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept_thread.start()

        if self._parent_admin_port is not None:
            from redpool.shard_parent_admin import start_shard_parent_admin_http

            _, self._admin_httpd = start_shard_parent_admin_http(
                self._parent_admin_host,
                self._parent_admin_port,
                self._worker_host,
                self.worker_metrics_ports(),
            )

        stop_event = threading.Event()

        def _on_signal(signum: int, _frame: object) -> None:
            logger.info("Signal %s, shutting down…", signum)
            stop_event.set()
            self._shutdown.set()

        signal.signal(signal.SIGINT, _on_signal)
        signal.signal(signal.SIGTERM, _on_signal)

        stop_event.wait()

        self._shutdown.set()
        if self._server_sock:
            try:
                self._server_sock.close()
            except OSError:
                pass
            self._server_sock = None
        if self._accept_thread:
            self._accept_thread.join(timeout=3.0)

        if self._admin_httpd is not None:
            try:
                self._admin_httpd.shutdown()
            except OSError:
                pass
            self._admin_httpd = None

        self._stop_children()
        if self._manage_workers:
            logger.info("All workers stopped.")
        return 0


def build_arg_parser() -> argparse.ArgumentParser:
    from redpool.config import RedpoolConfig

    default_metrics_base = RedpoolConfig().metrics_port_from_config
    p = argparse.ArgumentParser(
        description=(
            "Run N mitmdump+redpool workers and a front HTTP proxy (default), or "
            "only the front (--front-only) when workers are managed by systemd "
            "(redpool-shard-worker@.service)."
        )
    )
    p.add_argument(
        "--front-only",
        action="store_true",
        help=(
            "Do not spawn mitmdump children; only run the shard TCP front (and optional "
            "parent admin). Start workers separately, e.g. redpool-shard-worker@N."
        ),
    )
    p.add_argument(
        "-n",
        "--workers",
        type=int,
        default=None,
        metavar="N",
        help="Number of mitmdump worker processes (default: $REDPOOL_SHARD_NUM_WORKERS or 4)",
    )
    p.add_argument(
        "--front-host",
        default="127.0.0.1",
        help=(
            "Address the shard front listens on (default: 127.0.0.1). Redpool does not "
            "authenticate callers; before using 0.0.0.0 set an allowlist or proxyauth."
        ),
    )
    p.add_argument(
        "--front-port",
        type=int,
        default=8080,
        help="Port clients connect to (HTTP proxy / CONNECT) (default: 8080)",
    )
    p.add_argument(
        "--worker-host",
        default="127.0.0.1",
        help="Bind address for each mitmdump (default: 127.0.0.1)",
    )
    p.add_argument(
        "--worker-port-base",
        type=int,
        default=18082,
        help="First mitmdump listen port; workers use base..base+N-1 (default: 18082)",
    )
    p.add_argument(
        "--metrics-port-base",
        type=int,
        default=default_metrics_base,
        help=(
            "First REDPOOL_METRICS_PORT; workers use base..base+N-1 "
            f"(default: proxy.metrics_port from config, currently {default_metrics_base})"
        ),
    )
    p.add_argument(
        "--parent-admin-host",
        default="127.0.0.1",
        help="Address for Prometheus HTTP SD (default: 127.0.0.1)",
    )
    p.add_argument(
        "--parent-admin-port",
        type=int,
        default=-1,
        metavar="PORT",
        help=(
            "Prometheus HTTP SD at /prometheus-sd (worker /metrics targets + redpool_shard label). "
            "Default (-1): metrics_port_base + workers. Set explicitly (e.g. systemd "
            "REDPOOL_SHARD_PARENT_ADMIN_PORT) to decouple from worker metrics ports; use 0 to disable."
        ),
    )
    p.add_argument(
        "--max-connections",
        type=int,
        default=DEFAULT_MAX_CONNECTIONS,
        metavar="N",
        help=(
            "Client connections served at once; more get 503 "
            f"(default: {DEFAULT_MAX_CONNECTIONS})"
        ),
    )
    p.add_argument(
        "mitm_args",
        nargs=argparse.REMAINDER,
        help="Extra arguments for each mitmdump (often after --)",
    )
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = build_arg_parser().parse_args(list(argv) if argv is not None else None)
    mitm_args = list(args.mitm_args)
    if mitm_args and mitm_args[0] == "--":
        mitm_args = mitm_args[1:]

    workers = _coalesce_workers(args.workers)
    if workers < 1:
        print("error: --workers must be >= 1", file=sys.stderr)
        return 2

    admin_port: Optional[int]
    if args.parent_admin_port == -1:
        admin_port = args.metrics_port_base + workers
    elif args.parent_admin_port == 0:
        admin_port = None
    else:
        admin_port = args.parent_admin_port

    sup = ShardSupervisor(
        num_workers=workers,
        front_host=args.front_host,
        front_port=args.front_port,
        worker_host=args.worker_host,
        worker_port_base=args.worker_port_base,
        metrics_port_base=args.metrics_port_base,
        mitm_args=mitm_args,
        parent_admin_host=args.parent_admin_host,
        parent_admin_port=admin_port,
        manage_workers=not args.front_only,
        max_connections=args.max_connections,
    )
    return sup.run()


if __name__ == "__main__":
    sys.exit(main())
