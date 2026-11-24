# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Unit tests for shard front proxy parsing and stable sharding."""

import hashlib
import socket
import threading
import unittest

from redpool.shard_supervisor import (
    ShardSupervisor,
    _handle_client,
    force_connection_close,
    parse_connect_authority,
    parse_forward_proxy_authority,
    stable_shard_index,
)


class TestShardSupervisor(unittest.TestCase):
    def test_parse_connect_ipv4(self) -> None:
        buf = b"CONNECT 10.0.0.1:443 HTTP/1.1\r\nHost: x\r\n\r\n"
        self.assertEqual(parse_connect_authority(buf), "10.0.0.1:443")

    def test_parse_connect_host_only(self) -> None:
        buf = b"CONNECT bmc.example.com HTTP/1.1\r\n\r\n"
        self.assertEqual(parse_connect_authority(buf), "bmc.example.com:443")

    def test_parse_connect_ipv6(self) -> None:
        buf = b"CONNECT [2001:db8::1]:443 HTTP/1.1\r\n\r\n"
        self.assertEqual(parse_connect_authority(buf), "2001:db8::1:443")

    def test_stable_shard_deterministic(self) -> None:
        a = stable_shard_index("10.0.0.1:443", 4)
        b = stable_shard_index("10.0.0.1:443", 4)
        self.assertEqual(a, b)
        self.assertIn(a, (0, 1, 2, 3))

    def test_stable_shard_case_insensitive(self) -> None:
        self.assertEqual(
            stable_shard_index("HOST:443", 8),
            stable_shard_index("host:443", 8),
        )

    def test_stable_shard_is_sha256_mod_n(self) -> None:
        auth = "10.0.0.1:443"
        key = auth.strip().lower().encode("utf-8")
        h = int.from_bytes(hashlib.sha256(key).digest()[:8], "big")
        self.assertEqual(stable_shard_index(auth, 4), h % 4)
        self.assertEqual(stable_shard_index(auth, 17), h % 17)

    def test_parse_forward_absolute_uri(self) -> None:
        buf = (
            b"GET http://127.0.0.1:18888/redfish/v1/ HTTP/1.1\r\n"
            b"Host: 127.0.0.1:18888\r\n\r\n"
        )
        self.assertEqual(parse_forward_proxy_authority(buf), "127.0.0.1:18888")

    def test_parse_forward_host_only_relative(self) -> None:
        buf = b"GET /redfish/v1/ HTTP/1.1\r\nHost: 127.0.0.1:18888\r\n\r\n"
        self.assertEqual(parse_forward_proxy_authority(buf), "127.0.0.1:18888")

    def test_parse_forward_still_handles_connect(self) -> None:
        buf = b"CONNECT 10.0.0.1:443 HTTP/1.1\r\nHost: x\r\n\r\n"
        self.assertEqual(parse_forward_proxy_authority(buf), "10.0.0.1:443")


if __name__ == "__main__":
    unittest.main()


class TestForceConnectionClose(unittest.TestCase):
    def test_replaces_connection_headers_and_keeps_the_rest(self) -> None:
        buf = (
            b"GET http://10.0.0.1/redfish/v1 HTTP/1.1\r\n"
            b"Host: 10.0.0.1\r\nConnection: keep-alive\r\n"
            b"Proxy-Connection: keep-alive\r\nKeep-Alive: timeout=5\r\n"
            b"X-Auth-Token: t\r\n\r\nBODY"
        )
        self.assertEqual(
            force_connection_close(buf),
            b"GET http://10.0.0.1/redfish/v1 HTTP/1.1\r\nHost: 10.0.0.1\r\n"
            b"X-Auth-Token: t\r\nConnection: close\r\n\r\nBODY",
        )

    def test_incomplete_headers_are_left_alone(self) -> None:
        buf = b"GET / HTTP/1.1\r\nHost: x"
        self.assertEqual(force_connection_close(buf), buf)


class TestShardFrontSockets(unittest.TestCase):
    def _front_to_backend(self, request: bytes) -> bytes:
        """Send *request* through ``_handle_client`` and return what the worker received."""
        backend = socket.socket()
        backend.bind(("127.0.0.1", 0))
        backend.listen(1)
        received: list[bytes] = []

        def worker() -> None:
            conn, _ = backend.accept()
            with conn:
                conn.settimeout(5)
                received.append(conn.recv(65536))
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        client, server_side = socket.socketpair()
        client.settimeout(5)
        client.sendall(request)
        handler = threading.Thread(
            target=_handle_client,
            args=(server_side, [backend.getsockname()[1]], "127.0.0.1", 1),
            daemon=True,
        )
        handler.start()
        client.recv(65536)
        handler.join(timeout=5)
        t.join(timeout=5)
        client.close()
        backend.close()
        self.assertFalse(handler.is_alive(), "front must close after the response")
        return received[0]

    def test_plain_http_request_is_sent_with_connection_close(self) -> None:
        got = self._front_to_backend(
            b"GET http://10.0.0.1/redfish/v1 HTTP/1.1\r\nHost: 10.0.0.1\r\n"
            b"Connection: keep-alive\r\n\r\n"
        )
        self.assertIn(b"Connection: close", got)
        self.assertNotIn(b"keep-alive", got)

    def test_connect_request_is_forwarded_unchanged(self) -> None:
        request = b"CONNECT 10.0.0.1:443 HTTP/1.1\r\nHost: 10.0.0.1:443\r\n\r\n"
        self.assertEqual(self._front_to_backend(request), request)

    def test_connections_over_the_limit_get_503(self) -> None:
        sup = ShardSupervisor(
            num_workers=1,
            front_host="127.0.0.1",
            front_port=0,
            worker_host="127.0.0.1",
            worker_port_base=1,
            metrics_port_base=1,
            mitm_args=[],
            manage_workers=False,
            max_connections=1,
        )
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(8)
        sup._server_sock = server
        loop = threading.Thread(target=sup._accept_loop, daemon=True)
        loop.start()
        port = server.getsockname()[1]
        first = socket.create_connection(("127.0.0.1", port))  # holds the only slot
        second = socket.create_connection(("127.0.0.1", port))
        second.settimeout(5)
        try:
            self.assertTrue(second.recv(4096).startswith(b"HTTP/1.1 503"))
        finally:
            sup._shutdown.set()
            first.close()
            second.close()
            server.close()
            loop.join(timeout=3)

    def test_zero_connections_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ShardSupervisor(
                num_workers=1,
                front_host="127.0.0.1",
                front_port=0,
                worker_host="127.0.0.1",
                worker_port_base=1,
                metrics_port_base=1,
                mitm_args=[],
                max_connections=0,
            )
