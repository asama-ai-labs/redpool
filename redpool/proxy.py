# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

import base64
import hashlib
import http
import json
import logging
import os
import threading
import time
import traceback
from enum import Enum
from typing import Any, Dict, Optional, Tuple
from urllib.parse import ParseResult, parse_qs, urlparse

import redfish
from pydantic import BaseModel
from redfish.rest.v1 import HttpClient, InvalidCredentialsError, RestResponse

from normalizers._shared.redpool_oem import stamp_redpool_oem_types
from normalizers.pci_class_code import normalize_pcie_function_class_code_inplace
from normalizers.service_root import product_names_bmc
from normalizers.request_rewrites import (
    RewriteCall,
    get_request_rewrite,
    rewrite_response_body,
)
from normalizers.system_expanders import get_system_response_expander
from normalizers.url_rewrites import REVERSE_SEGMENT_REWRITES
from redpool import metrics
from redpool.cache import InMemoryCache
from redpool.config import bmc_tls_cafile, cfg
from redpool.gofish_compat import ensure_gofish_compat
from redpool.redfish_client import (
    CachedRedfishClient,
    limit_session_to_one_connection,
    release_rest_response,
)
from redpool.responses import RawBody, header_safe

# Upstream response headers clients need for Redfish session create (and similar 2xx).
_PASSTHROUGH_RESPONSE_HEADERS = (
    "X-Auth-Token",
    "Location",
    "ETag",
    "Retry-After",
    "WWW-Authenticate",
)
# Upstream methods the proxy forwards: method -> (client call, sends a request body).
# Anything else is refused before it reaches the BMC.
_UPSTREAM_METHODS = {
    "GET": ("get", False),
    "POST": ("post", True),
    "PUT": ("put", True),
    "PATCH": ("patch", True),
    "DELETE": ("delete", False),
}
# Request headers forwarded on writes so conditional updates keep working.
_FORWARDED_WRITE_HEADERS = ("If-Match", "If-None-Match")


def _forwarded_write_headers(
    request_headers: Optional[Dict[str, str]],
) -> Dict[str, str]:
    """Pick the conditional headers a write must carry to the BMC (case-insensitive)."""
    if not request_headers:
        return {}
    wanted = {name.lower(): name for name in _FORWARDED_WRITE_HEADERS}
    return {
        wanted[k.lower()]: v for k, v in request_headers.items() if k.lower() in wanted
    }


def _upstream_write_body(body: Any, request_headers: Optional[Dict[str, str]]) -> Any:
    """Decode a JSON request body so the client sends it as ``application/json``.

    The upstream client labels raw bytes ``application/octet-stream``, which BMCs
    reject for Redfish writes. Other content types are sent as received.
    """
    if not isinstance(body, (bytes, str)):
        return body
    content_type = next(
        (v for k, v in (request_headers or {}).items() if k.lower() == "content-type"),
        "",
    )
    if content_type and "json" not in content_type.lower():
        return body
    try:
        return json.loads(body)
    except ValueError:
        return body


# Generic or unknown model results (iDRAC Product, Systems 401). Short so a
# later authenticated request can retry the Systems probe.
_UNRESOLVED_METADATA_TTL = 60


def _apply_collector_response_compat(body: Dict[str, Any]) -> None:
    """Gofish field aliases + PCIeFunction ClassCode (when rewrites skip full field_map)."""
    ensure_gofish_compat(body, enabled=cfg.ensure_gofish_compat)
    normalize_pcie_function_class_code_inplace(body, enabled=cfg.ensure_gofish_compat)


def _apply_select(body: Any, path: str) -> Any:
    """Honor ``$select`` by keeping only the named top-level properties.

    ``@odata.*`` annotations are always kept. A body with no ``$select`` (or a
    non-dict body) is returned unchanged.
    """
    if not isinstance(body, dict) or "?" not in path:
        return body
    query = parse_qs(urlparse(path).query, keep_blank_values=True)
    values = query.get("$select")
    if not values:
        return body
    wanted = {name.strip() for v in values for name in v.split(",") if name.strip()}
    if not wanted:
        return body
    return {k: v for k, v in body.items() if k in wanted or k.startswith("@odata.")}


def _strip_redfish_v1_prefix(parts: list[str]) -> list[str]:
    """Return path components after a leading 'redfish'/'v1' prefix, or unchanged if absent."""
    if len(parts) >= 2 and parts[:2] == ["redfish", "v1"]:
        return parts[2:]
    return parts


def _metrics_target_host(base_url: str) -> str:
    """Hostname only for Prometheus ``target`` label (no scheme or port)."""
    host = urlparse(base_url).hostname
    return host if host else "unknown"


def _record_error_response_metric(target: str, status_code: str) -> None:
    """Record one 4xx/5xx into the in-process rolling 5-minute window for *target* (``redpool_error_responses_last_5m*``)."""
    try:
        code = int(status_code)
    except ValueError:
        return
    if code < 400:
        return
    metrics.observe_error_response(target, status_code)


# Define resource type enum
class ResourceType(str, Enum):
    ROOT = "root"
    RESOURCE = "resource"
    COLLECTION = "collection"


class ServerMetadata(BaseModel):
    hostname: str
    vendor: str
    model: str = "unknown"


class BmcAuthError(Exception):
    """Raised when the BMC returns 401 or 403 (authentication or authorization required)."""


class BmcCredentialsError(BmcAuthError):
    """The caller's credentials are unusable: the BMC rejected them, or the header is malformed.

    Not retried: a second login with the same bad password only counts toward the BMC's
    lockout. The proxy answers 401.
    """


def _raise_if_unauthorized(response: Optional[RestResponse], path: str) -> None:
    """Raise BmcAuthError if the response status is 401 or 403."""
    if response is None:
        return
    status = getattr(response, "status", None)
    if status in (http.HTTPStatus.UNAUTHORIZED.value, http.HTTPStatus.FORBIDDEN.value):
        raise BmcAuthError(f"BMC returned {status} for {path}")


class RedfishProxy:
    def __init__(self, max_targets=None):
        """Initialize the Redfish proxy"""
        self._max_targets = max_targets if max_targets is not None else cfg.max_targets
        self._target_last_used: Dict[str, float] = {}
        self.logger = logging.getLogger("redpool.proxy")
        self.logger.debug("RedfishProxy initialized")
        if cfg.tls_verify:
            if cfg.ca_file and not os.path.isfile(cfg.ca_file):
                raise ValueError(f"proxy.ca_file does not exist: {cfg.ca_file}")
            self.logger.info(
                "BMC TLS verification is on (%s)",
                cfg.ca_file or "system CA bundle",
            )
        else:
            self.logger.warning(
                "BMC TLS certificates are NOT verified (proxy.tls_verify is false). "
                "Basic-auth credentials sent to a BMC can be read by anyone on the path "
                "between Redpool and that BMC. See SECURITY.md."
            )
            if cfg.ca_file:
                self.logger.warning(
                    "proxy.ca_file is ignored while tls_verify is false"
                )
        self.redfish_clients = {}
        self._clients_lock = threading.Lock()
        # Serialize all upstream I/O per BMC (RLock: nested proxy_request / prefetch OK).
        self._bmc_io_locks: Dict[str, threading.RLock] = {}
        self._bmc_io_locks_guard = threading.Lock()

        self.metadata_cache = InMemoryCache(
            ttl_seconds=cfg.metadata_ttl, name="metadata"
        )
        self._unresolved_metadata_cache = InMemoryCache(
            ttl_seconds=_UNRESOLVED_METADATA_TTL, name="metadata_unresolved"
        )
        self.objecttype_cache = InMemoryCache(
            ttl_seconds=cfg.objecttype_ttl, name="objecttype"
        )
        self.redfish_response_cache = InMemoryCache(
            ttl_seconds=cfg.response_ttl, name="response"
        )

    def _bmc_io_lock(self, base_url: str) -> threading.RLock:
        """Return the re-entrant I/O lock for *base_url* (one lock per BMC)."""
        with self._bmc_io_locks_guard:
            lock = self._bmc_io_locks.get(base_url)
            if lock is None:
                lock = threading.RLock()
                self._bmc_io_locks[base_url] = lock
            self._target_last_used[base_url] = time.monotonic()
            evicted = self._evict_idle_targets(keep=base_url)
        for client in evicted:
            client.close()
        return lock

    def _evict_idle_targets(self, keep: str) -> list:
        """Drop the least recently used targets once more than ``max_targets`` are tracked.

        Caller holds ``_bmc_io_locks_guard``. A target whose lock is held (a request
        is in flight) is skipped. Returns the clients to close; the caller closes
        them outside the guard. ``keep`` is the target being requested now.
        A thread that already fetched an evicted lock can briefly overlap with a
        new thread on the same cold BMC; that only happens past the cap.
        """
        if len(self._bmc_io_locks) <= self._max_targets:
            return []
        goal = max(1, int(self._max_targets * 0.9))
        stale = sorted(
            (u for u in self._bmc_io_locks if u != keep),
            key=lambda u: self._target_last_used.get(u, 0.0),
        )
        closing: list = []
        for url in stale:
            if len(self._bmc_io_locks) <= goal:
                break
            lock = self._bmc_io_locks[url]
            if not lock.acquire(blocking=False):
                continue
            try:
                del self._bmc_io_locks[url]
                self._target_last_used.pop(url, None)
                with self._clients_lock:
                    for slot in ("anon", "auth"):
                        client = self.redfish_clients.pop((url, slot), None)
                        if client is not None:
                            metrics.ACTIVE_BMC_CONNECTIONS.dec()
                            closing.append(client)
            finally:
                lock.release()
        return closing

    @staticmethod
    def _is_session_passthrough_path(path: str) -> bool:
        """True for SessionService / Sessions paths (raw passthrough, no normalization)."""
        return any(path.startswith(prefix) for prefix in cfg.skip_prefixes)

    def _extract_server_metadata(
        self, base_url: str, client: HttpClient
    ) -> Optional[ServerMetadata]:
        """Extract metadata from server

        Args:
            base_url: The base URL of the Redfish API
            client: An authenticated Redfish client

        Returns:
            ServerMetadata object containing server metadata or None if extraction fails
        """
        # Validated platform models live in the long-lived cache. A generic
        # result (iDRAC Product, Systems 401) is a short-lived fallback so a
        # scrape does not re-probe Systems on every request, and so it expires
        # and a later request can discover the real model.
        cache_key = f"metadata:{base_url}"
        cached_metadata = self.metadata_cache.get(cache_key)
        if cached_metadata and self._product_is_server_model(cached_metadata.model):
            return cached_metadata
        unresolved = self._unresolved_metadata_cache.get(cache_key)
        if unresolved is not None:
            return unresolved

        try:
            self.logger.info("Fetching service root for metadata")
            response: RestResponse = client.get("/redfish/v1/")
            try:
                _raise_if_unauthorized(response, "/redfish/v1/")
            except BmcAuthError:
                release_rest_response(response)
                raise
            data: Optional[Dict[str, Any]] = self._safe_response_dict(response)
            if not data:
                self.logger.warning("Service root response has no body")
                return None

            vendor: str = "unknown"
            if "Vendor" in data:
                vendor = data["Vendor"]
            else:
                try:
                    vendor = next(iter(data.get("Oem", {}).keys()))
                except StopIteration:
                    self.logger.warning("Could not determine vendor from Oem object")

            # Prefer ServiceRoot.Product (public on /redfish/v1/) over Systems,
            # which often requires a session. Dell's Product is the iDRAC name,
            # not the platform; those hosts use Systems.Model.
            model = self._model_from_service_root(data, client)

            parsed_url: ParseResult = urlparse(base_url)
            metadata = ServerMetadata(
                hostname=parsed_url.hostname or "",
                vendor=vendor,
                model=model,
            )

            if self._product_is_server_model(model):
                self.metadata_cache.set(cache_key, metadata)
                self._unresolved_metadata_cache.delete(cache_key)
            else:
                self._unresolved_metadata_cache.set(cache_key, metadata)
            self.logger.info(
                f"Extracted metadata: host={metadata.hostname}, "
                f"vendor={metadata.vendor}, model={metadata.model}"
            )
            return metadata
        except BmcAuthError:
            raise
        except Exception as e:
            self.logger.error(f"Error extracting metadata: {e}")
            self.logger.info(traceback.format_exc())
            return None

    @staticmethod
    def _product_is_server_model(product: str) -> bool:
        """True when ServiceRoot.Product (or a resolved model) names the platform.

        Dell publishes ``Integrated Dell Remote Access Controller`` here. That
        string is shared by every PowerEdge, so it cannot select a memory map.
        """
        p = (product or "").strip().lower()
        if not p or p == "unknown":
            return False
        if product_names_bmc(p):
            return False
        return True

    def _model_from_service_root(self, data: Dict[str, Any], client: HttpClient) -> str:
        """Platform model from Product, or Systems.Model when Product is the BMC name."""
        product = data.get("Product")
        if isinstance(product, str) and self._product_is_server_model(product):
            return product.strip()
        system_model = self._extract_system_model(client)
        if self._product_is_server_model(system_model):
            return system_model
        if isinstance(product, str) and product.strip():
            return product.strip()
        return system_model or "unknown"

    def _extract_system_model(self, client: HttpClient) -> str:
        """Best-effort extraction of the server model from the first Systems member.

        Systems often requires auth; never raise — callers use ServiceRoot
        without a session (``/redfish/v1/`` is public).
        """
        try:
            systems_resp = client.get("/redfish/v1/Systems")
            try:
                _raise_if_unauthorized(systems_resp, "/redfish/v1/Systems")
            except BmcAuthError:
                release_rest_response(systems_resp)
                return "unknown"
            sys_dict = self._safe_response_dict(systems_resp)
            members = (sys_dict or {}).get("Members", [])
            if not members:
                return "unknown"
            first_uri = members[0].get("@odata.id", "")
            if not first_uri:
                return "unknown"
            system_resp = client.get(first_uri)
            try:
                _raise_if_unauthorized(system_resp, first_uri)
            except BmcAuthError:
                release_rest_response(system_resp)
                return "unknown"
            sys_body = self._safe_response_dict(system_resp)
            return (sys_body or {}).get("Model", "unknown") or "unknown"
        except BmcAuthError:
            return "unknown"
        except Exception as e:
            self.logger.debug(f"Could not extract system model: {e}")
            return "unknown"

    @staticmethod
    def _header_get(headers: Optional[Dict[str, str]], name: str) -> Optional[str]:
        """Case-insensitive header lookup (mitm/HTTP/2 may lowercase names)."""
        if not headers:
            return None
        if name in headers:
            return headers[name]
        want = name.lower()
        for key, value in headers.items():
            if key.lower() == want:
                return value
        return None

    @staticmethod
    def _auth_scope(headers: Optional[Dict[str, str]]) -> str:
        """Credential scope for a request: ``anon``, or a digest of its credential.

        A client or a cached response is never reused across scopes, so one
        caller's credentials are not used for another caller's request. The
        digest keeps raw credentials out of cache keys and logs. The token is
        preferred, matching ``_get_or_create_backend_client``.
        """
        credential = RedfishProxy._header_get(headers, "X-Auth-Token") or (
            RedfishProxy._header_get(headers, "Authorization")
        )
        if not credential:
            return "anon"
        return "c:" + hashlib.sha256(credential.encode("utf-8")).hexdigest()[:16]

    def _create_client(
        self,
        base_url: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        sessionkey: Optional[str] = None,
        scope: str = "anon",
    ) -> HttpClient:
        """Create or reuse the Redfish client for *base_url* and *scope*.

        Each BMC has two client slots: ``anon`` for requests with no credentials,
        and ``auth`` for requests that carry credentials. A request reuses the
        ``auth`` client only when its scope matches; otherwise the new client
        replaces it. Thread-safe: concurrent calls for the same scope do not
        create duplicate clients.

        Args:
            base_url: The base URL of the Redfish API
            username: Optional username for authentication
            password: Optional password for authentication
            sessionkey: Optional session key for authentication
            scope: Credential scope from ``_auth_scope`` (``anon`` when unauthenticated)

        Returns:
            A Redfish client with response caching for this scope
        """
        want_auth = bool(sessionkey or (username and password))
        key = (base_url, "auth" if want_auth else "anon")

        def usable(client: Any) -> bool:
            return client is not None and (not want_auth or client.auth_scope == scope)

        with self._clients_lock:
            existing = self.redfish_clients.get(key)
            if usable(existing):
                return existing

        # Build the client outside the lock (network I/O).
        timeout = cfg.backend_request_timeout
        client = None
        try:
            if sessionkey:
                client = redfish.redfish_client(
                    base_url=base_url,
                    sessionkey=sessionkey,
                    cafile=bmc_tls_cafile(),
                    default_prefix="/redfish/v1",
                    timeout=timeout,
                    max_retry=2,
                    check_connectivity=False,
                )
            else:
                client = redfish.redfish_client(
                    base_url=base_url,
                    username=username,
                    cafile=bmc_tls_cafile(),
                    password=password,
                    default_prefix="/redfish/v1",
                    timeout=timeout,
                    max_retry=2,
                    check_connectivity=False,
                )

            # Cap pool before any login/GET so we never open a multi-conn pool first.
            limit_session_to_one_connection(client)

            if not sessionkey and username and password:
                client.login(auth="basic")

            cached_client = CachedRedfishClient(
                base_client=client,
                cache=self.redfish_response_cache,
                logger=self.logger,
                auth_scope=scope,
            )

            with self._clients_lock:
                current = self.redfish_clients.get(key)
                if usable(current):
                    # Another thread built a client for this scope first.
                    winner, discard = current, cached_client
                else:
                    # Empty slot, or a client for a different credential: replace it.
                    self.redfish_clients[key] = cached_client
                    winner, discard = cached_client, current
                    if current is None:
                        metrics.ACTIVE_BMC_CONNECTIONS.inc()
            if discard is not None:
                discard.close()
            return winner

        except InvalidCredentialsError as e:
            session = getattr(client, "_session", None)
            if session:
                session.close()
            self.logger.warning("BMC rejected the credentials for %s", base_url)
            raise BmcCredentialsError(
                f"BMC rejected the credentials for {base_url}"
            ) from e
        except Exception as e:
            # client is a raw HttpClient not yet wrapped — close its session directly.
            session = getattr(client, "_session", None)
            if session:
                session.close()
            self.logger.error(f"Failed to create client for {base_url}: {e}")
            self.logger.info(traceback.format_exc())
            with self._clients_lock:
                current = self.redfish_clients.get(key)
                if usable(current):
                    return current
            raise

    def _drop_client(self, base_url: str) -> None:
        """Remove and close the cached authenticated client for *base_url*.

        Called only for requests that carry credentials, so the ``anon`` client
        is left alone.
        """
        with self._clients_lock:
            old_client = self.redfish_clients.pop((base_url, "auth"), None)
        if old_client is not None:
            metrics.ACTIVE_BMC_CONNECTIONS.dec()
            old_client.close()

    @classmethod
    def _recycle_client_on_auth_error(cls, headers: Optional[Dict[str, str]]) -> bool:
        """Only Basic / X-Auth-Token paths use the per-base_url client cache."""
        return bool(
            cls._header_get(headers, "X-Auth-Token")
            or cls._header_get(headers, "Authorization")
        )

    @staticmethod
    def _is_upstream_auth_error(status: int) -> bool:
        return status in (
            http.HTTPStatus.UNAUTHORIZED.value,
            http.HTTPStatus.FORBIDDEN.value,
        )

    @staticmethod
    def _basic_credentials(auth_header: str) -> Tuple[str, str]:
        """Username and password from a Basic ``Authorization`` header.

        Raises ``BmcCredentialsError`` for another scheme or a value that does not decode
        to ``user:password``. The header is never put in the message.
        """
        try:
            scheme, encoded = auth_header.split(" ", 1)
            if scheme.lower() != "basic":
                raise ValueError("not a Basic Authorization header")
            decoded = base64.b64decode(encoded.strip(), validate=True).decode("utf-8")
            username, password = decoded.split(":", 1)
        except ValueError as exc:  # also covers binascii.Error and UnicodeDecodeError
            raise BmcCredentialsError("Malformed Authorization header") from exc
        return username, password

    def _get_or_create_backend_client(
        self, base_url: str, headers: Optional[Dict[str, str]]
    ) -> HttpClient:
        """Build the Redfish HttpClient for this request (may return a cached client).

        The client is selected by the request's credential scope, so a request
        never runs on another caller's session or credentials.
        """
        scope = self._auth_scope(headers)
        token = self._header_get(headers, "X-Auth-Token")
        if token:
            return self._create_client(base_url=base_url, sessionkey=token, scope=scope)
        auth_header = self._header_get(headers, "Authorization")
        if auth_header:
            self.logger.debug("Using Basic auth")
            username, password = self._basic_credentials(auth_header)
            return self._create_client(
                base_url=base_url, username=username, password=password, scope=scope
            )
        # Unauthenticated — still cache and reuse via _create_client
        # so we don't leak a fresh requests.Session per request.
        return self._create_client(base_url=base_url, scope="anon")

    def normalize_redfish_response(
        self,
        response_data: Dict[str, Any],
        response_normalizer: Any,
        vendor: str,
        redfish_client: HttpClient,
        model: str = "unknown",
        resource_path: str = "",
    ) -> Dict[str, Any]:
        """Normalize a raw Redfish response using the resolved normalizer.

        *response_normalizer* is either a ``NormalizerEntry`` (for individual
        resources) or a plain ``dict`` (for collections).
        """
        from normalizers import NormalizationContext, NormalizerEntry, evaluate

        self.logger.debug(
            f"Starting normalization for vendor: {vendor}, model: {model}"
        )

        if isinstance(response_normalizer, NormalizerEntry):
            body = self._normalize_resource(
                response_data,
                response_normalizer,
                vendor,
                redfish_client,
                model,
                resource_path,
            )
        else:
            # Collection: flat mapping dict (the vendor's, when it has one).
            ctx = NormalizationContext(
                data=response_data,
                client=redfish_client,
                logger=self.logger,
                config=cfg,
                vendor=vendor,
                model=model,
                resource_path=resource_path,
            )
            prefetch = response_normalizer.prefetch_for_vendor(vendor)
            if prefetch is not None:
                prefetch(ctx)
            body = evaluate(response_normalizer.for_vendor(vendor), ctx)
        return body

    def _normalize_resource(
        self,
        response_data: Dict[str, Any],
        entry: Any,
        vendor: str,
        redfish_client: HttpClient,
        model: str = "unknown",
        resource_path: str = "",
    ) -> Dict[str, Any]:
        """Two-phase resource normalization (prefetch → map → version overrides)."""
        from normalizers import NormalizationContext
        from normalizers.apply import normalize_resource

        vendor_normalizer = entry.for_vendor(vendor)

        ctx = NormalizationContext(
            data=response_data,
            client=redfish_client,
            logger=self.logger,
            config=cfg,
            vendor=vendor,
            model=model,
            resource_path=resource_path,
        )

        return normalize_resource(vendor_normalizer, ctx)

    def get_normalizer_for_path(self, path, redfish_client=None):
        """Resolve the appropriate normalizer for a Redfish URL path.

        Walks the path components, classifies each as collection or resource
        (caching the result), and returns the matching entry from the v3
        registry — either a ``NormalizerEntry`` or a collection mapping dict.
        Uses the normalizer registry to infer collection type when possible,
        avoiding a backend GET per segment and speeding up scrapes.
        """
        from normalizers import get_collection_mapping, get_resource_entry

        self.logger.debug(f"Getting normalizer for path: {path}")
        # URI fragment (e.g. …/Power#/Voltages/0) refers to the same GET as the parent path;
        # resolve normalizers against the parent so Chassis/Power applies to embedded-voltage URLs.
        norm_path = path.split("#", 1)[0]
        # The query string (?$expand=*, ?$top=2) is not part of the resource path.
        norm_path = norm_path.split("?", 1)[0]
        parts = norm_path.strip("/").split("/")
        path_components = _strip_redfish_v1_prefix(parts)

        current_path = "/redfish/v1"
        current_path_type = ResourceType.ROOT
        collection_parts: list[str] = []
        resource_depth = 0  # how many resource levels after last collection

        for component in path_components:
            current_path = f"{current_path}/{component}"
            self.logger.debug(f"Navigating to {current_path}")

            try:
                cache_key = f"objecttype:{redfish_client.get_base_url()}:{current_path}"
                current_path_type = self.objecttype_cache.get(cache_key)
                if current_path_type is None:
                    # Infer collection from registry when we have a normalizer for this path pattern
                    candidate_pattern = "/".join(collection_parts + [component])
                    if get_collection_mapping(candidate_pattern) is not None:
                        current_path_type = ResourceType.COLLECTION
                        self.objecttype_cache.set(cache_key, current_path_type)
                    else:
                        parent_response = redfish_client.get(current_path)
                        resp_dict = self._safe_response_dict(parent_response) or {}
                        if "Collection" in (resp_dict.get("@odata.type") or ""):
                            current_path_type = ResourceType.COLLECTION
                        else:
                            current_path_type = ResourceType.RESOURCE
                        self.objecttype_cache.set(cache_key, current_path_type)
            except Exception as e:
                self.logger.debug(
                    f"Error checking resource type at {current_path}: {e}"
                )
                return None

            if current_path_type == ResourceType.COLLECTION:
                collection_parts.append(component)
                resource_depth = 0
            else:
                resource_depth += 1

        path_pattern = "/".join(collection_parts)
        self.logger.debug(
            f"Resolved path pattern: {path_pattern}, type: {current_path_type}, depth: {resource_depth}"
        )

        if current_path_type == ResourceType.COLLECTION:
            return get_collection_mapping(path_pattern)

        if not path_components:
            return None

        if resource_depth == 1:
            entry = get_resource_entry(path_pattern)
            if entry:
                return entry

        # Singleton sub-resource (depth >= 1 with no collection-based match):
        # build pattern by appending the leaf component name.
        leaf = path_components[-1]
        singleton_pattern = f"{path_pattern}/{leaf}" if path_pattern else leaf
        return get_resource_entry(singleton_pattern)

    def _get_client_for_request(
        self, base_url: str, headers: Optional[Dict[str, str]]
    ) -> Tuple[HttpClient, Optional[ServerMetadata]]:
        """Create a Redfish client from request headers and return client plus server metadata."""
        for attempt in range(2):
            try:
                client = self._get_or_create_backend_client(base_url, headers)
                server_metadata = self._extract_server_metadata(base_url, client)
                return client, server_metadata
            except BmcCredentialsError:
                raise
            except BmcAuthError as e:
                if attempt == 0 and self._recycle_client_on_auth_error(headers):
                    self.logger.warning(
                        "BMC auth error during metadata for %s; recreating client "
                        "and retrying once: %s",
                        base_url,
                        e,
                    )
                    self._drop_client(base_url)
                    continue
                raise
        raise RuntimeError("unreachable: client retry loop ended without a result")

    @staticmethod
    def _safe_response_dict(response) -> Optional[Dict[str, Any]]:
        """Extract .dict from a RestResponse, returning None on non-JSON bodies.

        Checks the status code first — BMCs often return HTML for error
        responses (401/403/500 …) which makes the redfish library's .dict
        property raise JsonDecodingError.
        """
        if response is None:
            return None
        try:
            status = getattr(response, "status", 0)
            if status >= 400:
                return None
            try:
                return response.dict
            except Exception:
                return None
        finally:
            release_rest_response(response)

    @staticmethod
    def _upstream_body(response: Any) -> Optional[Any]:
        """The body to return for an upstream response, whatever its status.

        JSON objects and arrays come back parsed, including Redfish error bodies
        (``@Message.ExtendedInfo``). Anything else (XML, HTML, an empty 204) comes
        back as ``RawBody`` with the upstream Content-Type. ``None`` means there was
        no response at all.
        """
        if response is None:
            return None
        try:
            text = response.text
        except Exception:
            release_rest_response(response)
            return None
        try:
            content_type = response.getheader("Content-Type")
        except Exception:
            content_type = None
        content_type = content_type or "application/octet-stream"
        release_rest_response(response)

        if not text or not text.strip():
            return RawBody(content=b"", content_type=content_type)
        try:
            parsed = json.loads(text)
        except ValueError:
            return RawBody(content=text.encode("utf-8"), content_type=content_type)
        if isinstance(parsed, (dict, list)):
            return parsed
        return RawBody(content=text.encode("utf-8"), content_type=content_type)

    @staticmethod
    def _extract_passthrough_headers(response: Any) -> Dict[str, str]:
        """Copy ``X-Auth-Token`` / ``Location`` from a RestResponse when present."""
        if response is None:
            return {}
        out: Dict[str, str] = {}
        getter = getattr(response, "getheader", None)
        for name in _PASSTHROUGH_RESPONSE_HEADERS:
            val = None
            if callable(getter):
                val = getter(name)
                if not val:
                    val = getter(name.lower())
            if not val:
                http_resp = getattr(response, "_http_response", None)
                hdrs = (
                    getattr(http_resp, "headers", None)
                    if http_resp is not None
                    else None
                )
                if hdrs is not None:
                    try:
                        val = hdrs.get(name) or hdrs.get(name.lower())
                    except Exception:
                        val = None
            if val:
                safe = header_safe(val)
                if safe:
                    out[name] = safe
        return out

    def _fetch_upstream(
        self,
        client: HttpClient,
        path: str,
        method: str,
        body: Optional[Any],
        request_headers: Optional[Dict[str, str]] = None,
    ) -> Tuple[Optional[Any], int, Dict[str, str]]:
        """Perform upstream request and return (response_body, response_status, passthrough_headers).

        When the canonical path yields 404 and a reverse URL rewrite exists
        (e.g. ``PCIeDevices`` → ``PCIDevices``), the vendor-specific path
        is tried as a fallback.
        """
        verb = method.upper()
        if verb not in _UPSTREAM_METHODS:
            self.logger.warning(
                "Refusing unsupported upstream method %s for %s", method, path
            )
            return None, http.HTTPStatus.METHOD_NOT_ALLOWED.value, {}
        client_method, carries_body = _UPSTREAM_METHODS[verb]
        send = getattr(client, client_method)
        if verb == "GET":
            response = send(path)
        else:
            # A write is never retried: the library retries on any exception,
            # including a read timeout after the BMC already acted.
            send_kwargs: Dict[str, Any] = {"max_retry": 0}
            write_headers = _forwarded_write_headers(request_headers)
            if write_headers:
                send_kwargs["headers"] = write_headers
            if carries_body and body:
                send_kwargs["body"] = _upstream_write_body(body, request_headers)
            response = send(path, **send_kwargs)
        response_status = getattr(response, "status", 0)
        # Headers clients need (ETag, Retry-After, WWW-Authenticate, Location) are
        # passed back whatever the status.
        passthrough_headers = self._extract_passthrough_headers(response)
        response_body = self._upstream_body(response)

        if response_status == 404 and method.upper() == "GET":
            alt_path = path
            for canon, orig in REVERSE_SEGMENT_REWRITES.items():
                alt_path = alt_path.replace(f"/{canon}/", f"/{orig}/")
                if alt_path.endswith(f"/{canon}"):
                    alt_path = alt_path[: -len(canon)] + orig
            if alt_path != path:
                self.logger.debug(
                    "Retrying with vendor path %s (was %s)", alt_path, path
                )
                alt_response = client.get(alt_path)
                alt_status = getattr(alt_response, "status", 0)
                if alt_status == 200:
                    headers = self._extract_passthrough_headers(alt_response)
                    return self._upstream_body(alt_response), alt_status, headers
                release_rest_response(alt_response)

        return response_body, response_status, passthrough_headers

    def _fetch_upstream_recoverable(
        self,
        base_url: str,
        headers: Optional[Dict[str, str]],
        client: HttpClient,
        path: str,
        method: str,
        body: Optional[Any],
    ) -> Tuple[Optional[Any], int, HttpClient, Dict[str, str]]:
        """Fetch upstream; on 401/403 with a cached authenticated client, recreate and retry once."""
        response_body, response_status, passthrough_headers = self._fetch_upstream(
            client, path, method, body, headers
        )
        if (
            method.upper() == "GET"
            and self._is_upstream_auth_error(response_status)
            and self._recycle_client_on_auth_error(headers)
        ):
            self.logger.warning(
                "Upstream %s for %s; recreating client and retrying once",
                response_status,
                path,
            )
            self._drop_client(base_url)
            client = self._get_or_create_backend_client(base_url, headers)
            response_body, response_status, passthrough_headers = self._fetch_upstream(
                client, path, method, body, headers
            )
        return response_body, response_status, client, passthrough_headers

    def _build_proxy_response(
        self,
        response_body: Optional[Any],
        response_status: int,
        path: str,
        server_metadata: ServerMetadata,
        client: HttpClient,
        target: str,
        vendor_label: str,
        model_label: str,
        method: str,
        start: float,
    ) -> Tuple[Optional[Any], Optional[ServerMetadata], int, str]:
        """Build the 4-tuple proxy response from upstream response, with optional normalization.

        *target* is the BMC hostname only (for Prometheus ``target`` labels).
        """
        if isinstance(response_body, RawBody):
            # Non-JSON or empty upstream body: pass it through unchanged.
            self._record_metrics(
                vendor_label,
                model_label,
                target,
                method,
                str(response_status),
                "passthrough",
                start,
            )
            return response_body, server_metadata, response_status, "passthrough"

        if response_body is None:
            self.logger.warning(
                "Response body missing for %s (status=%s)", path, response_status
            )
            self._record_metrics(
                vendor_label,
                model_label,
                target,
                method,
                str(response_status),
                "passthrough",
                start,
            )
            return None, None, http.HTTPStatus.INTERNAL_SERVER_ERROR.value, "error"

        if response_status != http.HTTPStatus.OK.value:
            self.logger.warning(
                f"Received non-200 response ({response_status}) for {path}"
            )
            self._record_metrics(
                vendor_label,
                model_label,
                target,
                method,
                str(response_status),
                "passthrough",
                start,
            )
            return (
                (response_body or {}),
                server_metadata,
                response_status,
                "passthrough",
            )

        # A write's response is an action result, not the resource: pass it through.
        normalizer = (
            self.get_normalizer_for_path(path, client)
            if method.upper() == "GET"
            else None
        )
        if not normalizer:
            self.logger.debug(f"No normalizer for {method} {path}, passing through")
            self._record_metrics(
                vendor_label,
                model_label,
                target,
                method,
                str(response_status),
                "passthrough",
                start,
            )
            return response_body, server_metadata, response_status, "passthrough"

        try:
            normalized_data: Dict[str, Any] = self.normalize_redfish_response(
                response_data=response_body,
                response_normalizer=normalizer,
                vendor=server_metadata.vendor,
                redfish_client=client,
                model=server_metadata.model,
                resource_path=path,
            )
            normalized_data = _apply_select(normalized_data, path)
            self._record_metrics(
                vendor_label,
                model_label,
                target,
                method,
                str(response_status),
                "normalized",
                start,
            )
            return normalized_data, server_metadata, response_status, "normalized"
        except Exception as e:
            self.logger.error(
                f"Normalization failed for {path}, falling back to original response: {e}"
            )
            self.logger.debug(traceback.format_exc())
            metrics.NORMALIZATION_ERRORS.labels(
                vendor=vendor_label,
                model=model_label,
                target=target,
                path_pattern=path,
            ).inc()
            self._record_metrics(
                vendor_label,
                model_label,
                target,
                method,
                str(response_status),
                "passthrough",
                start,
            )
            return response_body, server_metadata, response_status, "passthrough"

    def proxy_request(
        self,
        path: str,
        method: str = "GET",
        redfish_endpoint: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        body: Optional[Any] = None,
        backend_client: Optional[Any] = None,
        server_metadata: Optional[ServerMetadata] = None,
        passthrough_logs: bool = False,
    ) -> Tuple[
        Optional[Dict[str, Any]], Optional[ServerMetadata], int, str, Dict[str, str]
    ]:
        """Handle Redfish proxy request.

        Args:
            path: The path to request from the Redfish API
            method: HTTP method to use (GET, POST, PUT, DELETE)
            redfish_endpoint: The base URL of the Redfish API (ignored if backend_client is provided)
            headers: HTTP headers to include in the request
            body: Request body for POST/PUT methods
            backend_client: Optional HttpClient to use instead of creating one (e.g. MockRedfishClient)
            server_metadata: Optional server metadata when using backend_client (required if backend_client is set)

        Returns:
            Tuple containing:
            - Response data (normalized if possible, original otherwise)
            - Server metadata
            - HTTP status code (as integer)
            - Normalization status: ``"normalized"``, ``"passthrough"``,
              or ``"error"``
            - Upstream passthrough headers (e.g. ``X-Auth-Token``, ``Location``)
        """
        vendor_label = "unknown"
        model_label = "unknown"
        start = time.monotonic()

        if backend_client is not None and server_metadata is not None:
            base_url = (
                getattr(backend_client, "base_url", "") or "https://mock.example.com"
            )
        else:
            if not redfish_endpoint:
                self.logger.error("Redfish API URL is required")
                _record_error_response_metric("unknown", "400")
                return None, None, http.HTTPStatus.BAD_REQUEST.value, "error", {}
            base_url = redfish_endpoint.rstrip("/")

        metrics_target = _metrics_target_host(base_url)
        path = path.rstrip("/") or path

        with self._bmc_io_lock(base_url):
            result = self._proxy_request_locked(
                path=path,
                method=method,
                headers=headers,
                body=body,
                backend_client=backend_client,
                server_metadata=server_metadata,
                passthrough_logs=passthrough_logs,
                base_url=base_url,
                metrics_target=metrics_target,
                vendor_label=vendor_label,
                model_label=model_label,
                start=start,
            )
        normalized_body, _meta, _status, norm_status, _headers = result
        if norm_status == "normalized" and normalized_body is not None:
            stamp_redpool_oem_types(normalized_body)
        return result

    def _proxy_request_locked(
        self,
        *,
        path: str,
        method: str,
        headers: Optional[Dict[str, str]],
        body: Optional[Any],
        backend_client: Optional[Any],
        server_metadata: Optional[ServerMetadata],
        passthrough_logs: bool,
        base_url: str,
        metrics_target: str,
        vendor_label: str,
        model_label: str,
        start: float,
    ) -> Tuple[
        Optional[Dict[str, Any]], Optional[ServerMetadata], int, str, Dict[str, str]
    ]:
        """Upstream work for one request; caller holds ``_bmc_io_lock(base_url)``."""
        try:
            # Session auth paths: raw passthrough on the shared BMC session (no metadata
            # required) so mitmproxy never opens a second upstream connection.
            # gofish CreateSession POSTs credentials in the body with no auth headers;
            # metadata extract may 401 — that must not block the session create.
            if self._is_session_passthrough_path(path):
                if backend_client is not None:
                    client = backend_client
                else:
                    client = self._get_or_create_backend_client(base_url, headers)
                if server_metadata is None and backend_client is None:
                    try:
                        server_metadata = self._extract_server_metadata(
                            base_url, client
                        )
                    except BmcAuthError:
                        server_metadata = None
                    except Exception:
                        server_metadata = None
                if server_metadata is not None:
                    vendor_label = server_metadata.vendor
                    model_label = server_metadata.model
                response_body, response_status, client, passthrough_headers = (
                    self._fetch_upstream_recoverable(
                        base_url, headers, client, path, method, body
                    )
                )
                if response_body is None and response_status == 0:
                    self._record_metrics(
                        vendor_label,
                        model_label,
                        metrics_target,
                        method,
                        "500",
                        "error",
                        start,
                    )
                    return (
                        None,
                        server_metadata,
                        http.HTTPStatus.INTERNAL_SERVER_ERROR.value,
                        "error",
                        {},
                    )
                self._record_metrics(
                    vendor_label,
                    model_label,
                    metrics_target,
                    method,
                    str(response_status) if response_status else "500",
                    "passthrough",
                    start,
                )
                return (
                    response_body if response_body is not None else {},
                    server_metadata,
                    response_status,
                    "passthrough",
                    passthrough_headers,
                )

            # Service root (skip_paths): public, no auth. Do not probe Systems /
            # metadata before returning — that 401 must not fail this GET.
            if method.upper() == "GET" and path in cfg.skip_paths:
                if backend_client is not None:
                    client = backend_client
                else:
                    client = self._get_or_create_backend_client(base_url, headers)
                response_body, response_status, client, passthrough_headers = (
                    self._fetch_upstream_recoverable(
                        base_url, headers, client, path, method, body
                    )
                )
                if isinstance(response_body, dict):
                    vendor = response_body.get("Vendor")
                    if not vendor:
                        try:
                            vendor = next(iter(response_body.get("Oem", {}).keys()))
                        except StopIteration:
                            vendor = "unknown"
                    product = response_body.get("Product")
                    model = (
                        product.strip()
                        if isinstance(product, str) and product.strip()
                        else "unknown"
                    )
                    if server_metadata is None and vendor:
                        parsed = urlparse(base_url)
                        server_metadata = ServerMetadata(
                            hostname=parsed.hostname or "",
                            vendor=str(vendor),
                            model=model,
                        )
                        # Do not pin a generic iDRAC Product. The next authenticated
                        # request resolves Systems.Model via _extract_server_metadata.
                        if self._product_is_server_model(model):
                            self.metadata_cache.set(
                                f"metadata:{base_url}", server_metadata
                            )
                    if server_metadata is not None:
                        vendor_label = server_metadata.vendor
                        model_label = server_metadata.model
                if response_status == 200 and response_body is not None:
                    self._record_metrics(
                        vendor_label,
                        model_label,
                        metrics_target,
                        method,
                        str(response_status),
                        "passthrough",
                        start,
                    )
                    return (
                        response_body,
                        server_metadata,
                        response_status,
                        "passthrough",
                        passthrough_headers,
                    )
                if response_body is None:
                    err_code = str(response_status) if response_status >= 400 else "500"
                    _record_error_response_metric(metrics_target, err_code)
                    return (
                        None,
                        None,
                        http.HTTPStatus.INTERNAL_SERVER_ERROR.value,
                        "error",
                        {},
                    )
                self._record_metrics(
                    vendor_label,
                    model_label,
                    metrics_target,
                    method,
                    str(response_status),
                    "passthrough",
                    start,
                )
                return (
                    response_body,
                    server_metadata,
                    response_status,
                    "passthrough",
                    passthrough_headers,
                )

            if backend_client is None or server_metadata is None:
                client, server_metadata = self._get_client_for_request(
                    base_url, headers
                )
            else:
                client = backend_client
            if not server_metadata:
                self.logger.error(f"Failed to extract server metadata for {base_url}")
                _record_error_response_metric(metrics_target, "404")
                return None, None, http.HTTPStatus.NOT_FOUND.value, "error", {}

            vendor_label = server_metadata.vendor
            model_label = server_metadata.model

            # Passthrough for Logs paths when using fixed backend (golden script) so client does not loop on log entries.
            if passthrough_logs and method.upper() == "GET":
                response_body, response_status, client, passthrough_headers = (
                    self._fetch_upstream_recoverable(
                        base_url, headers, client, path, method, body
                    )
                )
                if response_body is None and response_status != 200:
                    err_code = str(response_status) if response_status >= 400 else "500"
                    _record_error_response_metric(metrics_target, err_code)
                    return (
                        None,
                        None,
                        http.HTTPStatus.INTERNAL_SERVER_ERROR.value,
                        "error",
                        {},
                    )
                self._record_metrics(
                    vendor_label,
                    model_label,
                    metrics_target,
                    method,
                    str(response_status),
                    "passthrough",
                    start,
                )
                return (
                    response_body if response_body is not None else {},
                    server_metadata,
                    response_status,
                    "passthrough",
                    passthrough_headers,
                )

            # Request rewrite: vendor rule provides backend path and optional hooks (no vendor logic here)
            if method.upper() == "GET":
                rewrite = get_request_rewrite(
                    server_metadata.vendor, path, client=client
                )
                if rewrite:
                    backend_path, from_prefix, to_prefix, rule = rewrite
                    resp = None
                    try:
                        try:
                            resp = client.get(backend_path)
                        except Exception:
                            resp = None
                        resp_status = getattr(resp, "status", 0) if resp else 0
                        if self._is_upstream_auth_error(
                            resp_status
                        ) and self._recycle_client_on_auth_error(headers):
                            self.logger.warning(
                                "Upstream %s on rewrite fetch %s; recreating client and retrying once",
                                resp_status,
                                backend_path,
                            )
                            release_rest_response(resp)
                            resp = None
                            self._drop_client(base_url)
                            client = self._get_or_create_backend_client(
                                base_url, headers
                            )
                            try:
                                resp = client.get(backend_path)
                            except Exception:
                                resp = None
                            resp_status = getattr(resp, "status", 0) if resp else 0
                        call = RewriteCall(
                            client, path, backend_path, from_prefix, to_prefix
                        )
                        if resp_status != 200 and rule.on_backend_error is not None:
                            result = rule.on_backend_error(call, resp_status)
                            if result is not None:
                                body, status = result
                                if isinstance(body, dict):
                                    _apply_collector_response_compat(body)
                                self._record_metrics(
                                    vendor_label,
                                    model_label,
                                    metrics_target,
                                    method,
                                    "200",
                                    "normalized",
                                    start,
                                )
                                return (body, server_metadata, 200, "normalized", {})
                        if resp_status == 200:
                            body = getattr(resp, "dict", None)
                            if isinstance(body, dict):
                                if rule.after_200_merge is not None:
                                    body = rule.after_200_merge(call, body)
                                body = rewrite_response_body(
                                    body, from_prefix, to_prefix
                                )
                                _apply_collector_response_compat(body)
                                if (
                                    rule.should_normalize_single is not None
                                    and rule.should_normalize_single(path, backend_path)
                                ):
                                    normalizer = self.get_normalizer_for_path(
                                        path, client
                                    )
                                    if normalizer:
                                        try:
                                            body = self.normalize_redfish_response(
                                                response_data=body,
                                                response_normalizer=normalizer,
                                                vendor=server_metadata.vendor,
                                                redfish_client=client,
                                                model=server_metadata.model,
                                                resource_path=path,
                                            )
                                        except Exception:
                                            pass
                                self._record_metrics(
                                    vendor_label,
                                    model_label,
                                    metrics_target,
                                    method,
                                    "200",
                                    "normalized",
                                    start,
                                )
                                return (body, server_metadata, 200, "normalized", {})
                    finally:
                        release_rest_response(resp)

            response_body, response_status, client, passthrough_headers = (
                self._fetch_upstream_recoverable(
                    base_url, headers, client, path, method, body
                )
            )
            normalized_data, server_metadata, status, norm_status = (
                self._build_proxy_response(
                    response_body,
                    response_status,
                    path,
                    server_metadata,
                    client,
                    metrics_target,
                    vendor_label,
                    model_label,
                    method,
                    start,
                )
            )
            if normalized_data and status == 200 and norm_status == "normalized":
                expander = (
                    get_system_response_expander(server_metadata.vendor)
                    if server_metadata is not None
                    else None
                )
                if expander is not None:
                    try:
                        normalized_data = expander(
                            normalized_data,
                            path,
                            client,
                            proxy_request=self.proxy_request,
                            backend_client=backend_client,
                            server_metadata=server_metadata,
                        )
                    except Exception:
                        pass
            return (
                normalized_data,
                server_metadata,
                status,
                norm_status,
                passthrough_headers,
            )
        except BmcAuthError as e:
            self.logger.warning(f"Metadata extraction failed (auth required): {e}")
            self._record_metrics(
                vendor_label,
                model_label,
                metrics_target,
                method,
                "401",
                "error",
                start,
            )
            return None, None, http.HTTPStatus.UNAUTHORIZED.value, "error", {}
        except Exception as e:
            self.logger.error(f"Request failed for {path}: {e}")
            self.logger.info(traceback.format_exc())
            self._record_metrics(
                vendor_label,
                model_label,
                metrics_target,
                method,
                "500",
                "error",
                start,
            )
            return None, None, http.HTTPStatus.INTERNAL_SERVER_ERROR.value, "error", {}

    @staticmethod
    def _record_metrics(
        vendor: str,
        model: str,
        target: str,
        method: str,
        status_code: str,
        norm_status: str,
        start: float,
    ) -> None:
        metrics.REQUEST_TOTAL.labels(
            vendor=vendor,
            model=model,
            target=target,
            method=method,
            status_code=status_code,
            norm_status=norm_status,
        ).inc()
        _record_error_response_metric(target, status_code)
        metrics.REQUEST_DURATION.labels(
            vendor=vendor,
            model=model,
            target=target,
            method=method,
        ).observe(time.monotonic() - start)
