# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Centralized configuration for the Redpool proxy.

Loads settings from a YAML file (path given by ``REDPOOL_CONFIG`` env var,
defaulting to ``redpool.yaml`` in the working directory).  Every setting
has a built-in default so the proxy works out-of-the-box without a config
file.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from redpool.access import parse_target_list

_logger = logging.getLogger("redpool.config")

# ── Built-in defaults (must match repo-root redpool.yaml comments) ───────

_DEFAULTS: Dict[str, Any] = {
    "cache": {
        "response_ttl": 60,
        "metadata_ttl": 86400,
        "objecttype_ttl": 86400,
    },
    "proxy": {
        "metrics_host": "127.0.0.1",
        "metrics_port": 9101,
        "log_level": "INFO",
        "backend_connect_timeout": 10,
        "backend_read_timeout": 60,
        "backend_request_timeout": 60,
        "allowed_targets": [],
        "require_redfish_path": True,
        "max_targets": 2048,
        "tls_verify": False,
        "ca_file": "",
        "skip_prefixes": [
            "/redfish/v1/Sessions",
            "/redfish/v1/SessionService",
        ],
        "skip_paths": [
            "/redfish/v1/",
            "/redfish/v1",
        ],
        "non_cacheable_patterns": [
            "/redfish/v1/SessionService",
            "/redfish/v1/Systems/*/Actions",
            "/redfish/v1/Managers/*/Actions",
            "/redfish/v1/Chassis/*/Actions",
            "/redfish/v1/TaskService",
            "/redfish/v1/UpdateService",
        ],
    },
    "normalization": {
        "derive_part_number": True,
        "derive_base_speed": True,
        "build_processor_links": True,
        "build_memory_summary": True,
        "build_processor_summary_status": True,
        "enrich_ampere_model": True,
        "strip_memory_part_number": True,
        "use_vendor_oem_overrides": True,
        "ensure_gofish_compat": True,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into *base*, returning a new dict."""
    merged = dict(base)
    for key, val in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(val, dict):
            merged[key] = _deep_merge(merged[key], val)
        else:
            merged[key] = val
    return merged


class ConfigError(ValueError):
    """The config file cannot be trusted. Redpool refuses to start rather than guess.

    Falling back to defaults would drop settings such as ``allowed_targets``, and an
    empty allowlist means every host is allowed.
    """


def _unknown_keys(values: Dict[str, Any]) -> List[str]:
    """Dotted names of keys in *values* that the built-in defaults do not define."""
    unknown: List[str] = []
    for section, body in values.items():
        if section not in _DEFAULTS:
            unknown.append(str(section))
        elif isinstance(body, dict):
            unknown.extend(
                f"{section}.{k}" for k in body if k not in _DEFAULTS[section]
            )
        elif body is not None:
            unknown.append(f"{section} (expected a mapping)")
    return unknown


def _load_yaml(path: Path) -> Dict[str, Any]:
    """Load YAML from *path*; a missing file gives ``{}``.

    A file that cannot be parsed, is not a mapping, or holds a key Redpool does not
    know (usually a typo such as ``allowed_target``) raises ``ConfigError``.
    """
    try:
        with open(path) as fh:
            data = yaml.safe_load(fh)
    except FileNotFoundError:
        _logger.debug("No config file at %s, using built-in defaults", path)
        return {}
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must hold a YAML mapping, not {type(data).__name__}")
    unknown = _unknown_keys(data)
    if unknown:
        raise ConfigError(
            f"{path} has unknown settings: {', '.join(unknown)}. "
            "Check the spelling against redpool.yaml."
        )
    return data


class RedpoolConfig:
    """Read-only accessor for Redpool configuration values."""

    def __init__(self, overrides: Dict[str, Any] | None = None):
        config_path = Path(os.environ.get("REDPOOL_CONFIG", "redpool.yaml"))
        file_values = _load_yaml(config_path)
        merged = _deep_merge(_DEFAULTS, file_values)
        if overrides:
            merged = _deep_merge(merged, overrides)
        self._cfg = merged

    # ── Cache ────────────────────────────────────────────────────────────

    @property
    def response_ttl(self) -> int:
        return int(self._cfg["cache"]["response_ttl"])

    @property
    def metadata_ttl(self) -> int:
        return int(self._cfg["cache"]["metadata_ttl"])

    @property
    def objecttype_ttl(self) -> int:
        return int(self._cfg["cache"]["objecttype_ttl"])

    # ── Proxy ────────────────────────────────────────────────────────────

    @property
    def metrics_port_from_config(self) -> int:
        """``proxy.metrics_port`` from defaults + YAML only (ignores ``REDPOOL_METRICS_PORT``)."""
        return int(self._cfg["proxy"]["metrics_port"])

    @property
    def metrics_port(self) -> int:
        """Prometheus listen port; override per worker with ``REDPOOL_METRICS_PORT``."""
        env = os.environ.get("REDPOOL_METRICS_PORT", "").strip()
        if env.isdigit():
            return int(env)
        return self.metrics_port_from_config

    @property
    def metrics_host(self) -> str:
        """Address the Prometheus listener binds; override with ``REDPOOL_METRICS_HOST``.

        Loopback by default: ``/metrics`` is not authenticated and names every BMC the proxy
        has reached. Set ``0.0.0.0`` (or an interface address) to let a remote Prometheus scrape it.
        """
        env = os.environ.get("REDPOOL_METRICS_HOST", "").strip()
        if env:
            return env
        return str(self._cfg["proxy"].get("metrics_host") or "127.0.0.1").strip()

    @property
    def log_level(self) -> str:
        return str(self._cfg["proxy"]["log_level"]).upper()

    @property
    def backend_connect_timeout(self) -> int:
        return int(self._cfg["proxy"].get("backend_connect_timeout", 10))

    @property
    def backend_read_timeout(self) -> int:
        return int(self._cfg["proxy"].get("backend_read_timeout", 60))

    @property
    def backend_request_timeout(self) -> tuple[int, int]:
        """(connect, read) timeout tuple for requests."""
        return (self.backend_connect_timeout, self.backend_read_timeout)

    @property
    def allowed_targets(self) -> List[str]:
        """Hosts, globs and CIDRs a caller may target. Empty allows any host.

        ``REDPOOL_ALLOWED_TARGETS`` (comma-separated) replaces the YAML list.
        """
        env = os.environ.get("REDPOOL_ALLOWED_TARGETS")
        if env is not None and env.strip():
            return parse_target_list(env)
        return parse_target_list(self._cfg["proxy"].get("allowed_targets"))

    @property
    def require_redfish_path(self) -> bool:
        return bool(self._cfg["proxy"].get("require_redfish_path", True))

    @property
    def max_targets(self) -> int:
        """Most BMCs tracked at once before the least recently used are dropped."""
        return max(1, int(self._cfg["proxy"].get("max_targets", 2048)))

    @property
    def tls_verify(self) -> bool:
        """Verify each BMC's TLS certificate. Off by default: BMCs usually use self-signed ones.

        When on, the chain must verify against ``ca_file`` (or the system bundle when
        ``ca_file`` is empty). Turning it on changes behavior for every BMC.
        """
        return bool(self._cfg["proxy"].get("tls_verify", False))

    @property
    def ca_file(self) -> str:
        """PEM file of CA certificates used when ``tls_verify`` is on."""
        return str(self._cfg["proxy"].get("ca_file") or "").strip()

    @property
    def skip_prefixes(self) -> List[str]:
        return list(self._cfg["proxy"]["skip_prefixes"])

    @property
    def skip_paths(self) -> List[str]:
        return list(self._cfg["proxy"]["skip_paths"])

    @property
    def non_cacheable_patterns(self) -> List[str]:
        return list(self._cfg["proxy"]["non_cacheable_patterns"])

    # ── Normalization feature flags ──────────────────────────────────────

    @property
    def derive_part_number(self) -> bool:
        return bool(self._cfg["normalization"]["derive_part_number"])

    @property
    def derive_base_speed(self) -> bool:
        return bool(self._cfg["normalization"]["derive_base_speed"])

    @property
    def build_processor_links(self) -> bool:
        return bool(self._cfg["normalization"]["build_processor_links"])

    @property
    def build_memory_summary(self) -> bool:
        return bool(self._cfg["normalization"]["build_memory_summary"])

    @property
    def build_processor_summary_status(self) -> bool:
        return bool(
            self._cfg["normalization"].get("build_processor_summary_status", True)
        )

    @property
    def enrich_ampere_model(self) -> bool:
        return bool(self._cfg["normalization"]["enrich_ampere_model"])

    @property
    def strip_memory_part_number(self) -> bool:
        return bool(self._cfg["normalization"]["strip_memory_part_number"])

    @property
    def use_vendor_oem_overrides(self) -> bool:
        return bool(self._cfg["normalization"]["use_vendor_oem_overrides"])

    @property
    def ensure_gofish_compat(self) -> bool:
        """When True, apply response tweaks for gofish client compatibility (e.g. DeviceID alias for PCIeFunction)."""
        return bool(self._cfg["normalization"].get("ensure_gofish_compat", True))


# Module-level singleton — importable as ``from redpool.config import cfg``
cfg = RedpoolConfig()


def mitmproxy_option_updates() -> Dict[str, Any]:
    """Mitmproxy options redpool always applies (via argv and ``configure``).

    Default mitmproxy ``connection_strategy`` is ``eager``; we force ``lazy`` so
    upstream BMC TLS is deferred until needed (avoids a second keep-alive when
    the addon sets ``flow.response``).

    DEBUG uses ``flow_detail`` 1 (URL and status). Level 2 and above print request and
    response headers, which include ``Authorization`` and ``X-Auth-Token``.
    """
    opts: Dict[str, Any] = {"connection_strategy": "lazy"}
    name = (cfg.log_level or "INFO").upper()
    if name == "DEBUG":
        opts["termlog_verbosity"] = "debug"
        opts["flow_detail"] = 1
    elif name == "WARNING":
        opts["termlog_verbosity"] = "warn"
        opts["flow_detail"] = 0
    elif name in ("ERROR", "CRITICAL"):
        opts["termlog_verbosity"] = "error"
        opts["flow_detail"] = 0
    return opts


def mitmdump_log_extra_args() -> list[str]:
    """Extra argv for ``mitmdump`` from ``mitmproxy_option_updates``."""
    out: list[str] = []
    for k, v in mitmproxy_option_updates().items():
        out.extend(["--set", f"{k}={v}"])
    return out


def write_temp_redpool_config_for_tests(metrics_port: int) -> str:
    """Write a temp YAML path: repo-root ``redpool.yaml`` merged with ``proxy.metrics_port``.

    Used by integration/golden scripts so ``log_level`` and other settings match the repo file
    while avoiding metrics port collisions with a running proxy.
    """
    import tempfile

    repo_root = Path(__file__).resolve().parent.parent
    repo_yaml = repo_root / "redpool.yaml"
    merged = _deep_merge(
        _load_yaml(repo_yaml), {"proxy": {"metrics_port": metrics_port}}
    )
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    )
    try:
        yaml.safe_dump(merged, tmp, default_flow_style=False, sort_keys=False)
        tmp.close()
        return tmp.name
    except Exception:
        tmp.close()
        try:
            Path(tmp.name).unlink(missing_ok=True)
        except OSError:
            pass
        raise


def bmc_tls_cafile() -> Optional[str]:
    """What to pass as ``cafile`` to the Redfish client for BMC connections.

    ``None`` keeps the library's default, which skips certificate verification.
    With ``proxy.tls_verify`` on, the result is the CA file, or the bundle that
    requests uses when ``ca_file`` is empty.
    """
    if not cfg.tls_verify:
        return None
    if cfg.ca_file:
        return cfg.ca_file
    import requests.certs

    return requests.certs.where()
