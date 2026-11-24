# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

from __future__ import annotations

import json
import socket
from typing import TYPE_CHECKING, Any, Dict

from redfish.rest.v1 import HttpClient, RestRequest, StaticRestResponse
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection

from redpool.config import cfg

if TYPE_CHECKING:
    from normalizers.types import PrefetchRedfishClient

# Keep idle BMC sockets alive across sequential Redfish GETs in one scrape.
_TCP_KEEPALIVE_OPTS = [
    (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1),
]
if hasattr(socket, "TCP_KEEPIDLE"):
    _TCP_KEEPALIVE_OPTS.append((socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30))
if hasattr(socket, "TCP_KEEPINTVL"):
    _TCP_KEEPALIVE_OPTS.append((socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10))
if hasattr(socket, "TCP_KEEPCNT"):
    _TCP_KEEPALIVE_OPTS.append((socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3))


class _KeepAliveHTTPSAdapter(HTTPAdapter):
    """Single-connection pool with TCP keepalive for BMC HTTPS."""

    def init_poolmanager(self, *args, **kwargs):
        kwargs["socket_options"] = (
            list(HTTPConnection.default_socket_options) + _TCP_KEEPALIVE_OPTS
        )
        return super().init_poolmanager(*args, **kwargs)


def release_rest_response(response: Any) -> None:
    """Return the urllib3 connection to the Session pool (keep-alive).

    Prefer ``release_conn`` over ``Response.close()``: when the body is not
    marked consumed, ``close()`` calls ``raw.close()`` and tears down TCP,
    forcing a reconnect on the next request.
    """
    if response is None:
        return
    http_resp = getattr(response, "_http_response", None)
    if http_resp is None:
        return
    try:
        if not getattr(http_resp, "_content_consumed", True):
            try:
                http_resp.content  # drain so the socket is reusable
            except Exception:
                pass
        raw = getattr(http_resp, "raw", None)
        release_conn = getattr(raw, "release_conn", None) if raw is not None else None
        if release_conn is not None:
            release_conn()
            return
        http_resp.close()
    except Exception:
        pass


def limit_session_to_one_connection(client: Any) -> None:
    """Force the underlying requests.Session to at most one pooled connection.

    Combined with a per-BMC lock in ``RedfishProxy``, this keeps a single TCP
    connection to each BMC even under parallel scrapes.
    """
    session = getattr(client, "_session", None)
    if session is None:
        base = getattr(client, "base_client", None)
        session = getattr(base, "_session", None) if base is not None else None
    if session is None:
        return

    session.headers["Connection"] = "keep-alive"
    adapter = _KeepAliveHTTPSAdapter(
        pool_connections=1, pool_maxsize=1, max_retries=0, pool_block=True
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)


def _json_body_copy(body: Dict[str, Any]) -> Dict[str, Any]:
    """Detach a JSON object for cache storage (avoids shared mutable state)."""
    return json.loads(json.dumps(body))


def _static_response_for_get(path: str, body: Dict[str, Any]) -> StaticRestResponse:
    """Build a connection-free RestResponse from a parsed JSON body."""
    return StaticRestResponse(
        restreq=RestRequest(path, method="GET"),
        Status=200,
        Headers={"Content-Type": "application/json"},
        Content=body,
    )


def redfish_get_json(
    client: "PrefetchRedfishClient",
    path: str,
    args: Any = None,
    headers: Any = None,
) -> Dict[str, Any]:
    """GET *path*, return JSON object, always release the underlying connection."""
    r = client.get(path, args, headers)
    try:
        if getattr(r, "status", 0) >= 400:
            return {}
        return r.dict
    except Exception:
        return {}
    finally:
        release_rest_response(r)


class CachedRedfishClient(HttpClient):
    """Redfish client with JSON-body response caching (no cached RestResponse objects)."""

    def __init__(self, base_client, cache, logger, auth_scope: str = "anon"):
        """Initialize with a base Redfish client and cache

        Args:
            base_client: The base Redfish client to wrap
            cache: The cache to use for responses
            logger: Logger for debug messages
            auth_scope: Credential scope this client serves (``anon`` or a
                credential digest). Responses are cached per scope.
        """
        # Copy attributes from the base client
        self.__dict__.update(base_client.__dict__)

        # Store base URL once for cache keys; makes the wrapper self-contained
        self._base_url = base_client.get_base_url()

        # Add our own attributes
        self.base_client = base_client
        self.cache = cache
        self.logger = logger
        self.auth_scope = auth_scope

    def get_base_url(self):
        """Return the base URL (stored at init) for cache keys and callers."""
        return self._base_url

    def close(self):
        """Close the underlying requests.Session to free TCP sockets."""
        session = getattr(self.base_client, "_session", None)
        if session is None:
            return
        try:
            session.close()
        except Exception as exc:
            self.logger.debug("Error closing session for %s: %s", self._base_url, exc)

    def _is_cacheable(self, path):
        """Check if a path should be cached

        Args:
            path: The path to check

        Returns:
            True if the path should be cached, False otherwise
        """
        for prefix in cfg.non_cacheable_patterns:
            # Handle wildcards in prefixes
            if "*" in prefix:
                parts = prefix.split("*")
                if path.startswith(parts[0]) and all(
                    part in path for part in parts[1:]
                ):
                    return False
            elif path.startswith(prefix):
                return False
        return True

    def _invalidate_written_path(self, path: str) -> None:
        """Drop cached reads of *path* and its parent, for every credential scope."""
        resource = path.split("?", 1)[0].split("#", 1)[0].rstrip("/")
        parent = resource.rsplit("/", 1)[0]
        prefix = f"response:{self._base_url}:"
        targets = tuple(f":{p}" for p in {resource, parent} if p)

        def stale(key: Any) -> bool:
            # The path itself, or the path with a query string (?$select, ?$expand).
            return (
                isinstance(key, str)
                and key.startswith(prefix)
                and (key.endswith(targets) or any(f"{t}?" in key for t in targets))
            )

        self.cache.delete_matching(stale)

    def _write(self, verb: str, path, *args, **kwargs):
        """Send a write, then invalidate what it may have changed."""
        try:
            return getattr(self.base_client, verb)(path, *args, **kwargs)
        finally:
            self._invalidate_written_path(path)

    def patch(self, path, *args, **kwargs):
        return self._write("patch", path, *args, **kwargs)

    def post(self, path, *args, **kwargs):
        return self._write("post", path, *args, **kwargs)

    def put(self, path, *args, **kwargs):
        return self._write("put", path, *args, **kwargs)

    def delete(self, path, *args, **kwargs):
        return self._write("delete", path, *args, **kwargs)

    def get(self, path, args=None, headers=None):
        """Get a resource, using cache if available

        Args:
            path: The path to request
            args: Optional query parameters
            headers: Optional headers

        Returns:
            The response from the Redfish API
        """
        # The cache key holds the path only, so a request with its own args or headers
        # must not share an entry with one without.
        if self._is_cacheable(path) and not args and not headers:
            # Scope in the key: a response read with one credential is never served to another.
            cache_key = f"response:{self._base_url}:{self.auth_scope}:{path}"
            cached_body = self.cache.get(cache_key)
            if cached_body is not None:
                self.logger.debug(f"Cache hit for {path}")
                return _static_response_for_get(path, cached_body)

            self.logger.debug(f"Cache miss for {path}")
            response = self.base_client.get(path, args, headers)

            status = getattr(response, "status", None)
            if status == 200:
                try:
                    body = response.dict
                except Exception:
                    body = None
                if isinstance(body, dict):
                    self.cache.set(cache_key, _json_body_copy(body))
                    release_rest_response(response)
                    return _static_response_for_get(path, body)
                # Not a JSON object (XML, an array, no body): the caller gets the upstream
                # response as it is, and nothing is cached.

            return response
        else:
            self.logger.debug(f"Non-cacheable path: {path}")
            return self.base_client.get(path, args, headers)
