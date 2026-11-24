# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

import asyncio
import contextvars
import json
import logging
import os
import sys
from typing import Optional
from urllib.parse import urlparse

from mitmproxy import http, tcp

from redpool import metrics
from redpool.access import TargetPolicy
from redpool.config import cfg
from redpool.proxy import RedfishProxy
from redpool.queue_logging import AsyncAppendWriter, install_queue_logging
from redpool.responses import encode_body, header_safe, redfish_error_body

RESPONSE_LOG_PATH = os.environ.get("REDPOOL_RESPONSE_LOG", "")
# When set, use this as the Redfish backend for all requests (so collector can target the proxy directly).
REDPOOL_BACKEND_URL = os.environ.get("REDPOOL_BACKEND_URL", "").rstrip("/")

# Per-request BMC target, prepended to every log message via a custom
# LogRecord factory.  This survives mitmproxy overriding root handlers.
_bmc_target: contextvars.ContextVar[str] = contextvars.ContextVar(
    "_bmc_target", default=""
)

_original_record_factory = logging.getLogRecordFactory()


def _bmc_record_factory(*args, **kwargs):
    record = _original_record_factory(*args, **kwargs)
    target = _bmc_target.get()
    if target:
        record.msg = f"[{target}] {record.msg}"
    return record


logging.setLogRecordFactory(_bmc_record_factory)

log_level = getattr(logging, cfg.log_level, logging.INFO)
install_queue_logging(
    level=log_level,
    fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
_RESPONSE_LOG_WRITER: Optional[AsyncAppendWriter] = (
    AsyncAppendWriter(RESPONSE_LOG_PATH) if RESPONSE_LOG_PATH else None
)
logger = logging.getLogger("redpool.mitm_proxy")
logger.setLevel(log_level)

redfish_proxy = RedfishProxy()
target_policy = TargetPolicy(
    allowed_targets=cfg.allowed_targets,
    require_redfish_path=cfg.require_redfish_path,
)
logger.debug("MITM Proxy initialized")

metrics.start_metrics_server(cfg.metrics_port, cfg.metrics_host)
metrics.BUILD_INFO.info({"version": "0.1.0", "proxy": "mitmproxy"})


def _denied_response(denial: str) -> http.Response:
    return http.Response.make(
        status_code=403,
        content=json.dumps(
            redfish_error_body(
                f"Redpool refused this request: {denial}.",
                "This Redpool instance does not serve that target or path. "
                "Ask its operator.",
            )
        ).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Redpool-Status": "denied",
        },
    )


def http_connect(flow: http.HTTPFlow) -> None:
    """Apply the host allowlist to a CONNECT tunnel before it is opened.

    Requests inside the tunnel still reach ``request()`` and get the path rule.
    With a fixed backend the caller cannot pick the host, so only the allowlist
    of a caller-named host applies.
    """
    if REDPOOL_BACKEND_URL or flow.response is not None:
        return
    denial = (
        None
        if target_policy.host_allowed(flow.request.host)
        else "target host is not on the allowlist"
    )
    if denial:
        logger.info(
            "Refused CONNECT %s:%s: %s",
            (flow.request.host or "")[:255],
            flow.request.port,
            denial,
        )
        flow.response = _denied_response(denial)


def tcp_start(flow: tcp.TCPFlow) -> None:
    """Kill raw TCP flows: Redpool serves HTTP only, never a byte relay."""
    logger.info("Refused raw TCP flow to %s", flow.server_conn.address)
    flow.kill()


async def request(flow: http.HTTPFlow) -> None:
    """Intercepts the request and normalizes it using RedfishProxy.

    Upstream ``requests`` I/O runs in a worker thread so the mitmproxy asyncio
    loop stays responsive for other flows. Per-BMC serialization is unchanged:
    ``RedfishProxy.proxy_request`` still holds ``_bmc_io_lock`` for that BMC.
    """
    # An earlier addon (mitmproxy's proxyauth answers 407) may already have refused
    # this flow. Do not overwrite that response, or the refusal is lost.
    if flow.response is not None:
        return
    if not (
        flow.request.pretty_url.startswith("http://")
        or flow.request.pretty_url.startswith("https://")
    ):
        return

    parsed_url = urlparse(flow.request.pretty_url)
    port = f":{parsed_url.port}" if parsed_url.port else ""
    redfish_endpoint = f"{parsed_url.scheme}://{parsed_url.hostname}{port}"

    bmc_label = (
        f"{parsed_url.hostname}{port}"
        if not REDPOOL_BACKEND_URL
        else REDPOOL_BACKEND_URL
    )
    _bmc_target.set(bmc_label)

    if REDPOOL_BACKEND_URL:
        redfish_endpoint = REDPOOL_BACKEND_URL
    # When client uses proxy, path can be absolute URL; use path component for normalizer lookup.
    path = parsed_url.path or flow.request.path

    # An operator-fixed backend cannot be redirected by the caller, so only the
    # path rule applies there. Otherwise the caller names the host.
    denial = (
        target_policy.check_path(path)
        if REDPOOL_BACKEND_URL
        else target_policy.check(parsed_url.hostname, path)
    )
    if denial:
        logger.info(
            "Refused %s %s for %s: %s",
            flow.request.method,
            path[:200],
            (parsed_url.hostname or "")[:255],
            denial,
        )
        flow.response = _denied_response(denial)
        return
    if parsed_url.query:
        # Keep the query: $expand, $select, $top and $filter change the answer.
        path = f"{path}?{parsed_url.query}"
    method = flow.request.method
    # Snapshot flow fields on the event-loop thread (flow is not thread-safe).
    headers = dict(flow.request.headers)
    body = flow.request.content
    passthrough_logs = bool(REDPOOL_BACKEND_URL and "/Logs" in path)

    logger.debug(f"path= {path}")
    logger.debug(f"method= {method}")
    logger.debug(f"redfish_endpoint= {redfish_endpoint}")

    # All Redfish paths (including /redfish/v1/ and SessionService) are handled here so
    # mitmproxy never opens its own BMC upstream; one shared client session per BMC.
    (
        normalized_response,
        server_metadata,
        status_code,
        norm_status,
        upstream_headers,
    ) = await asyncio.to_thread(
        redfish_proxy.proxy_request,
        path=path,
        method=method,
        redfish_endpoint=redfish_endpoint,
        headers=headers,
        body=body,
        passthrough_logs=passthrough_logs,
    )
    logger.info("%s %s -> %s %s", method, path, status_code, norm_status)

    resp_headers = {
        "Content-Type": "application/json",
        "X-Redpool-Status": norm_status,
    }
    if server_metadata:
        resp_headers["X-Redpool-Vendor"] = header_safe(server_metadata.vendor)
        resp_headers["X-Redpool-Model"] = header_safe(server_metadata.model)
    if upstream_headers:
        resp_headers.update(upstream_headers)

    if normalized_response is not None:
        # Upstream bodies (including error bodies and non-JSON ones) are sent as the
        # BMC returned them; the Content-Type comes from RawBody when it is not JSON.
        content, content_type = encode_body(normalized_response)
        if content_type:
            resp_headers["Content-Type"] = content_type
        flow.response = http.Response.make(
            status_code=status_code, content=content, headers=resp_headers
        )
    else:
        # No upstream response at all: synthesize a DMTF-style error object.
        if status_code == 401:
            message = "Redpool requires Basic auth or X-Auth-Token."
        else:
            message = (
                f"Redpool could not get a response from the BMC (status {status_code})."
            )
        resp_headers["Content-Type"] = "application/json"
        flow.response = http.Response.make(
            status_code=status_code,
            content=json.dumps(redfish_error_body(message)).encode("utf-8"),
            headers={**resp_headers, "X-Redpool-Status": "error"},
        )
    if RESPONSE_LOG_PATH and path.startswith("/redfish/"):
        _log_response(path, norm_status)


def response(flow: http.HTTPFlow) -> None:
    """Log passthrough responses when REDPOOL_RESPONSE_LOG is set (handled requests logged in request())."""
    if not RESPONSE_LOG_PATH:
        return
    path = urlparse(flow.request.pretty_url).path or flow.request.path
    if not path.startswith("/redfish/"):
        return
    if flow.response and flow.response.headers.get("X-Redpool-Status"):
        return  # already logged in request()
    _log_response(path, "passthrough")


def _log_response(path: str, norm_status: str) -> None:
    """Enqueue path and normalization status for async append when REDPOOL_RESPONSE_LOG is set."""
    if _RESPONSE_LOG_WRITER is None:
        return
    _RESPONSE_LOG_WRITER.write(f"{path}\t{norm_status}\n")


def configure(_updated) -> None:
    """Apply redpool mitmproxy defaults (lazy upstream + log level)."""
    try:
        from mitmproxy import ctx

        from redpool.config import mitmproxy_option_updates

        opts = mitmproxy_option_updates()
        if opts:
            ctx.options.update(**opts)
    except Exception:
        pass
