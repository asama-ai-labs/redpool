# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""
Shared helpers for redfish-inventory-exporter golden generation and tests.
Run from repo root; callers should ensure REPO_ROOT is set and redfish-inventory-exporter is built.
"""

from __future__ import annotations

import json
import os
import re
import signal
import socket
import subprocess
from collections import defaultdict
import tempfile
import time
import shutil
from pathlib import Path

from mockup_server import mockup_server_command
from third_party_paths import REDFISH_INVENTORY_EXPORTER_ROOT, REPO_ROOT


# Readiness / teardown polling. Keep short: scrapes are sub-second on local fixtures;
# wall time was previously dominated by 0.5s polls, sleep(3)/sleep(1), and 15s bind waits.
_READY_POLL_S = 0.1
_READY_TIMEOUT_S = 15.0


def _port_accepting_connections(port: int) -> bool:
    """True if something on 127.0.0.1:port accepts a TCP connection."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            return True
    except OSError:
        return False


def _wait_for_port_released(
    port: int, timeout_seconds: float = _READY_TIMEOUT_S
) -> None:
    """Wait until nothing is accepting connections on *port*.

    Uses connect-refused (not bind-without-REUSEADDR): after teardown the listen socket
    often sits in TIME_WAIT where bind fails for ~15s even though no process is listening.
    Golden runs pick a fresh ephemeral port per model, so callers should skip this wait
    unless they intentionally reuse a fixed port.
    """
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not _port_accepting_connections(port):
            return
        time.sleep(_READY_POLL_S)
    # Proceed anyway; next run may fail with clear "address already in use"


def _wait_until(
    predicate,
    *,
    timeout_seconds: float = _READY_TIMEOUT_S,
    poll_s: float = _READY_POLL_S,
) -> bool:
    """Poll *predicate* until true or timeout. Returns whether it became true."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(poll_s)
    return False


def _curl_http_code(
    url: str, *, proxy: str | None = None, timeout: int = 2
) -> str | None:
    """Return response status code string, or None on curl failure."""
    cmd = [
        "curl",
        "-s",
        "-o",
        "/dev/null",
        "-w",
        "%{http_code}",
        "--max-time",
        str(timeout),
    ]
    if proxy:
        cmd.extend(["-x", proxy])
    cmd.append(url)
    r = run_cmd(cmd, timeout=timeout + 2)
    if r.returncode != 0:
        return None
    return (r.stdout or "").strip()


def _pick_free_tcp_port() -> int:
    """Return an ephemeral TCP port suitable for redpool mitm_proxy metrics (bind then release)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return int(s.getsockname()[1])


# REDPOOL_FIXTURES points the scripts at another corpus checkout.
FIXTURES = Path(os.environ.get("REDPOOL_FIXTURES") or REPO_ROOT / "fixtures")
EXPORTER_BIN = REDFISH_INVENTORY_EXPORTER_ROOT / "build" / "redfish-inventory-exporter"
MITMDUMP_BIN = REPO_ROOT / ".venv" / "bin" / "mitmdump"
ADDON_PATH = REPO_ROOT / "redpool" / "mitm_proxy.py"


def get_models():
    """Yield (vendor, model) for each fixtures vendor/model that has original/."""
    for vendor in sorted(FIXTURES.iterdir()):
        if not vendor.is_dir():
            continue
        for model in sorted(vendor.iterdir()):
            if not model.is_dir():
                continue
            if (model / "original").is_dir():
                yield vendor.name, model.name


def run_cmd(cmd, env=None, cwd=None, timeout=300, capture=True):
    proc_env = os.environ.copy()
    if env:
        proc_env.update(env)
    return subprocess.run(
        cmd,
        env=proc_env,
        cwd=str(cwd or REPO_ROOT),
        timeout=timeout,
        capture_output=capture,
        text=True,
    )


def start_process(
    cmd, env=None, cwd=None, stdout=None, stderr=None, *, new_session: bool = False
):
    proc_env = os.environ.copy()
    if env:
        proc_env.update(env)
    return subprocess.Popen(
        cmd,
        env=proc_env,
        cwd=cwd or str(REPO_ROOT),
        stdout=stdout or subprocess.DEVNULL,
        stderr=stderr or subprocess.PIPE,
        start_new_session=new_session,
    )


def _terminate_proc(proc, *, timeout: float = 2.0) -> None:
    """SIGTERM (process group if any), then SIGKILL. Handles ``uv run`` child trees."""
    if proc is None or proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, OSError):
        try:
            proc.terminate()
        except ProcessLookupError:
            return
    try:
        proc.wait(timeout=timeout)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, OSError):
        try:
            proc.kill()
        except ProcessLookupError:
            return
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        pass


def _prom_family_from_help_line(line: str) -> str | None:
    if not line.startswith("# HELP "):
        return None
    rest = line[7:].strip()
    if not rest:
        return None
    return rest.split(None, 1)[0]


def _prom_family_from_type_line(line: str) -> str | None:
    if not line.startswith("# TYPE "):
        return None
    parts = line[7:].strip().split()
    if len(parts) < 2:
        return None
    return parts[0]


def _prom_family_from_sample_line(line: str) -> str | None:
    if not line or line.startswith("#"):
        return None
    parts = line.split()
    if not parts:
        return None
    return parts[0].split("{", 1)[0]


# Ephemeral scrape meta-metrics: timings and success flag change every run (and embed
# ephemeral target ports). Drop from goldens so regen does not churn .prom commits.
_EXPORTER_GOLDEN_DROP_FAMILIES = frozenset(
    {
        "redfish_inventory_exporter_scrape_collector_duration_seconds",
        "redfish_inventory_exporter_scrape_duration_seconds",
        "redfish_inventory_exporter_up",
    }
)


def _keep_exporter_golden_prom_family(family: str) -> bool:
    if family in _EXPORTER_GOLDEN_DROP_FAMILIES:
        return False
    return family.startswith("redfish_")


_TARGET_LABEL_RE = re.compile(r'target="[^"]*"')
# Families whose ``target`` label is the scrape URL's ephemeral mock port.
_EPHEMERAL_TARGET_FAMILIES = frozenset({"redfish_inventory_exporter_collector_success"})


def _fix_ephemeral_target(family: str, line: str) -> str:
    if family in _EPHEMERAL_TARGET_FAMILIES:
        return _TARGET_LABEL_RE.sub('target="mock"', line, count=1)
    return line


def has_redfish_data(metrics_text: str) -> bool:
    """True when the scrape holds a Redfish gauge, not only the exporter's own stats."""
    return any(
        line.startswith("redfish_")
        and not line.startswith("redfish_inventory_exporter_")
        for line in metrics_text.splitlines()
    )


def _strip_sample_timestamp(line: str) -> str:
    if line.startswith("#"):
        return line
    parts = line.rsplit(None, 2)
    if len(parts) == 3 and parts[2].isdigit() and int(parts[2]) >= 100000000:
        return parts[0] + " " + parts[1]
    return line


def normalize_prom_metrics(text: str) -> str:
    """Normalize Prometheus exposition for stable golden comparison.

    - Keeps ``redfish_*``, which includes ``redfish_inventory_exporter_*`` (drops ``go_*``, ``process_*``, etc.).
    - Drops scrape duration / ``redfish_inventory_exporter_up`` (non-deterministic timings and ports).
    - Rewrites the ephemeral ``target`` label of ``redfish_inventory_exporter_collector_success`` to ``mock``.
    - Preserves ``# HELP`` / ``# TYPE`` for those families when present (redpool goldens use
      ``--expose-prometheus-metadata`` on the collector).
    - Strips trailing timestamps from sample lines.
    - Orders by metric family: HELP, TYPE, then sorted sample lines.
    """
    if not text:
        return ""
    help_by_family: dict[str, str] = {}
    type_by_family: dict[str, str] = {}
    samples_by_family: dict[str, list[str]] = defaultdict(list)

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line:
            continue
        if line.startswith("# HELP "):
            fam = _prom_family_from_help_line(line)
            if fam and _keep_exporter_golden_prom_family(fam):
                help_by_family[fam] = line
            continue
        if line.startswith("# TYPE "):
            fam = _prom_family_from_type_line(line)
            if fam and _keep_exporter_golden_prom_family(fam):
                type_by_family[fam] = line
            continue
        if line.startswith("#"):
            continue
        fam = _prom_family_from_sample_line(line)
        if not fam or not _keep_exporter_golden_prom_family(fam):
            continue
        samples_by_family[fam].append(
            _fix_ephemeral_target(fam, _strip_sample_timestamp(line))
        )

    families = sorted(
        set(help_by_family) | set(type_by_family) | set(samples_by_family)
    )
    out_lines: list[str] = []
    for fam in families:
        if fam in help_by_family:
            out_lines.append(help_by_family[fam])
        if fam in type_by_family:
            out_lines.append(type_by_family[fam])
        for s in sorted(samples_by_family.get(fam, [])):
            out_lines.append(s)
    return "\n".join(out_lines)


def _write_exporter_config(config_path: Path) -> None:
    """Write JSON config with default admin/password for mock."""
    config_path.write_text(
        json.dumps(
            {
                "default": {"username": "admin", "password": "password"},
                "hosts": {},
            }
        ),
        encoding="utf-8",
    )


def run_one_model_metrics(
    vendor: str,
    model: str,
    *,
    mock_port: int = 0,
    proxy_port: int = 0,
    collector_port: int = 0,
    scrape_timeout: int = 180,
    disable_collectors: str | None = None,
    proxy_stderr_path: Path | None = None,
    proxy_stdout_path: Path | None = None,
    response_log_path: Path | None = None,
    collector_stderr_path: Path | None = None,
    shard_workers: int | None = None,
    worker_port_base: int | None = None,
    metrics_port_base: int | None = None,
    expose_prometheus_metadata: bool = False,
) -> tuple[str | None, str | None]:
    """Run mock + proxy + redfish-inventory-exporter for one model, trigger scrape, return metrics.

    Pass ``mock_port <= 0``, ``proxy_port <= 0``, or ``collector_port <= 0`` to bind ephemeral
    ports (avoids stale mock/exporter/MITM still listening on fixed ports from a prior run).
    When ``expose_prometheus_metadata`` is True, the collector is started with
    ``--expose-prometheus-metadata`` (``# HELP`` / ``# TYPE`` on ``/redfish``).
    """
    # Only wait for port release on teardown when the caller reused a fixed port.
    fixed_mock_port = mock_port > 0
    fixed_proxy_port = proxy_port > 0
    fixed_collector_port = collector_port > 0
    if mock_port <= 0:
        mock_port = _pick_free_tcp_port()
    if proxy_port <= 0:
        proxy_port = _pick_free_tcp_port()
    if collector_port <= 0:
        collector_port = _pick_free_tcp_port()
    # Only enable per-response TSV logging when the caller asked for a path; writing every
    # normalized response to disk dominates scrape time (~4x) and is unused for golden regen.
    log_path: str | None = None
    if response_log_path is not None:
        response_log_path = Path(response_log_path)
        response_log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path = str(response_log_path)
        try:
            response_log_path.write_text("", encoding="utf-8")
        except OSError:
            pass

    from redpool.config import (
        mitmdump_log_extra_args,
        write_temp_redpool_config_for_tests,
    )

    # Avoid a fixed port: mitm_proxy imports start_http_server(metrics_port); if bind fails,
    # the addon does not load and mitmdump forwards unchanged JSON (no normalization).
    cfg_metrics_port = _pick_free_tcp_port()
    tmp_cfg_path = write_temp_redpool_config_for_tests(cfg_metrics_port)
    w_base = worker_port_base if worker_port_base is not None else (proxy_port + 10000)
    m_base = metrics_port_base if metrics_port_base is not None else cfg_metrics_port

    proxy_env = {
        "REDPOOL_CONFIG": tmp_cfg_path,
        "REDPOOL_BACKEND_URL": f"http://127.0.0.1:{mock_port}",
        "HTTP_PROXY": "",
        "HTTPS_PROXY": "",
        "http_proxy": "",
        "https_proxy": "",
        "NO_PROXY": "127.0.0.1,localhost",
        "no_proxy": "127.0.0.1,localhost",
        "PYTHONPATH": str(REPO_ROOT),
    }
    if log_path is not None:
        proxy_env["REDPOOL_RESPONSE_LOG"] = log_path

    config_path = Path(tempfile.mktemp(suffix=".json"))
    _write_exporter_config(config_path)

    mock_proc = None
    proxy_proc = None
    collector_proc = None
    proxy_stdout_handle = None
    proxy_stderr_handle = None
    proxy_stdout_file = None
    proxy_stderr_file = None

    try:
        mock_proc = start_process(
            mockup_server_command(FIXTURES, vendor, model, mock_port),
            cwd=str(REPO_ROOT),
            stderr=subprocess.DEVNULL,
            new_session=True,
        )
        if not _wait_until(
            lambda: (
                _curl_http_code(f"http://127.0.0.1:{mock_port}/redfish/v1/") == "200"
            )
        ):
            return None, "Mock server did not become ready"

        if proxy_stdout_path is not None:
            proxy_stdout_path = Path(proxy_stdout_path)
            proxy_stdout_path.parent.mkdir(parents=True, exist_ok=True)
            proxy_stdout_handle = open(proxy_stdout_path, "wb")
            proxy_stdout_file = None
        else:
            # Discard mitmdump access/event noise; it only slows scrapes when written to disk.
            proxy_stdout_handle = subprocess.DEVNULL
            proxy_stdout_file = None
        if proxy_stderr_path is not None:
            proxy_stderr_path = Path(proxy_stderr_path)
            proxy_stderr_path.parent.mkdir(parents=True, exist_ok=True)
            proxy_stderr_handle = open(proxy_stderr_path, "wb")
            proxy_stderr_file = None  # do not unlink in finally
        else:
            proxy_stderr_file = tempfile.NamedTemporaryFile(delete=False, suffix=".log")
            proxy_stderr_file.close()
            proxy_stderr_handle = open(proxy_stderr_file.name, "wb")
        mitmdump = (
            MITMDUMP_BIN
            if MITMDUMP_BIN.exists()
            else Path(shutil.which("mitmdump") or "mitmdump")
        )
        # Forward (MITM) proxy: collector uses HTTP_PROXY; target 127.0.0.2 so all requests go through proxy (avoid same-host bypass).
        if shard_workers is not None and shard_workers > 0:
            proxy_cmd = [
                "uv",
                "run",
                "redpool-shard-proxy",
                "-n",
                str(shard_workers),
                "--front-host",
                "0.0.0.0",
                "--front-port",
                str(proxy_port),
                "--worker-host",
                "127.0.0.1",
                "--worker-port-base",
                str(w_base),
                "--metrics-port-base",
                str(m_base),
            ]
        else:
            proxy_cmd = [
                str(mitmdump),
                "-s",
                str(ADDON_PATH),
                *mitmdump_log_extra_args(),
                "--listen-host",
                "0.0.0.0",
                "--listen-port",
                str(proxy_port),
                "-k",
            ]
        proxy_proc = subprocess.Popen(
            proxy_cmd,
            env={**os.environ, **proxy_env},
            cwd=str(REPO_ROOT),
            stdout=proxy_stdout_handle,
            stderr=proxy_stderr_handle,
            start_new_session=True,
        )
        # No fixed sleep: poll until the proxy forwards a Systems GET (or process exits).
        if not _wait_until(
            lambda: (
                proxy_proc.poll() is not None
                or _curl_http_code(
                    f"http://127.0.0.1:{mock_port}/redfish/v1/Systems",
                    proxy=f"http://127.0.0.1:{proxy_port}",
                    timeout=2,
                )
                in ("200", "500")
            )
        ):
            return None, "Proxy not accepting connections"
        if proxy_proc.poll() is not None:
            err_detail = ""
            try:
                stderr_path = (
                    Path(proxy_stderr_path)
                    if proxy_stderr_path is not None
                    else (Path(proxy_stderr_file.name) if proxy_stderr_file else None)
                )
                if stderr_path is not None and stderr_path.exists():
                    err_detail = stderr_path.read_text(
                        encoding="utf-8", errors="replace"
                    ).strip()
                    if len(err_detail) > 600:
                        err_detail = err_detail[:300] + "\n...\n" + err_detail[-300:]
            except (OSError, TypeError, AttributeError):
                pass
            detail = f" {err_detail}" if err_detail else ""
            return None, f"Proxy failed to start{detail} (proxy_port={proxy_port})"

        collector_env = {
            **os.environ,
            "HTTP_PROXY": f"http://127.0.0.1:{proxy_port}",
            "HTTPS_PROXY": f"http://127.0.0.1:{proxy_port}",
            "NO_PROXY": "",
            "no_proxy": "",
            "REDFISH_SCHEME": "http",
        }
        target = f"127.0.0.1:{mock_port}"
        collector_stderr_handle = subprocess.DEVNULL
        if collector_stderr_path is not None:
            Path(collector_stderr_path).parent.mkdir(parents=True, exist_ok=True)
            collector_stderr_handle = open(collector_stderr_path, "wb")
        exporter_cmd = [
            str(EXPORTER_BIN),
            "--config",
            str(config_path),
            "-p",
            str(collector_port),
            "--target-allowlist",
            "127.0.0.1",
        ]
        if disable_collectors:
            exporter_cmd.extend(["--disable-collectors", disable_collectors])
        if expose_prometheus_metadata:
            exporter_cmd.append("--expose-prometheus-metadata")
        collector_proc = start_process(
            exporter_cmd,
            env=collector_env,
            cwd=str(REDFISH_INVENTORY_EXPORTER_ROOT),
            stderr=collector_stderr_handle,
            new_session=True,
        )
        if collector_stderr_path is not None:
            collector_stderr_handle.close()
        if not _wait_until(
            lambda: (
                _curl_http_code(f"http://127.0.0.1:{collector_port}/", timeout=2)
                is not None
            )
        ):
            return None, "redfish-inventory-exporter did not become ready"

        scrape_url = (
            f"http://127.0.0.1:{collector_port}/redfish?target={target}"
            f"&hostname=DUMMY-HostName&serialnumber=DUMMY-SerialNumber"
        )
        r = run_cmd(
            ["curl", "-s", "-S", "--max-time", str(scrape_timeout), scrape_url],
            timeout=scrape_timeout + 30,
        )
        if r.returncode != 0:
            return None, f"Scrape failed: {r.stderr or r.stdout or 'timeout'}"
        metrics_text = r.stdout or ""
        if not metrics_text.strip():
            return None, "Scrape returned empty body"
        # redfish-inventory-exporter may use different metric prefixes
        if not has_redfish_data(metrics_text):
            return (
                None,
                f"No Redfish metrics. First 200 chars: {metrics_text[:200]!r}",
            )
        return metrics_text, None
    finally:
        _terminate_proc(collector_proc)
        _terminate_proc(mock_proc)
        # Only block for port reuse when the caller pinned fixed ports (or shard bases).
        # Ephemeral ports are never reused by the next model, and bind-wait used to cost ~15s
        # per port due to TIME_WAIT even when nothing was listening.
        if fixed_mock_port:
            _wait_for_port_released(mock_port)
        if fixed_collector_port:
            _wait_for_port_released(collector_port)
        _terminate_proc(proxy_proc)
        if proxy_proc is not None and (
            fixed_proxy_port or (shard_workers is not None and shard_workers > 0)
        ):
            if fixed_proxy_port:
                _wait_for_port_released(proxy_port)
            if shard_workers is not None and shard_workers > 0:
                for i in range(shard_workers):
                    _wait_for_port_released(w_base + i)
                for i in range(shard_workers):
                    _wait_for_port_released(m_base + i)
        for h in (proxy_stdout_handle, proxy_stderr_handle):
            if h is not None and h is not subprocess.DEVNULL:
                try:
                    h.close()
                except OSError:
                    pass
        for f in (proxy_stdout_file, proxy_stderr_file):
            if f is not None and hasattr(f, "name") and Path(f.name).exists():
                try:
                    Path(f.name).unlink()
                except OSError:
                    pass
        try:
            Path(tmp_cfg_path).unlink()
        except OSError:
            pass
        try:
            config_path.unlink()
        except OSError:
            pass


def run_one_model_metrics_direct(
    vendor: str,
    model: str,
    *,
    mock_port: int = 0,
    collector_port: int = 0,
    scrape_timeout: int = 180,
    disable_collectors: str | None = None,
    expose_prometheus_metadata: bool = False,
) -> tuple[str | None, str | None]:
    """Run mock + redfish-inventory-exporter (no proxy) for one model, trigger scrape, return metrics."""
    fixed_mock_port = mock_port > 0
    fixed_collector_port = collector_port > 0
    if mock_port <= 0:
        mock_port = _pick_free_tcp_port()
    if collector_port <= 0:
        collector_port = _pick_free_tcp_port()
    config_path = Path(tempfile.mktemp(suffix=".json"))
    _write_exporter_config(config_path)

    mock_proc = None
    collector_proc = None

    try:
        mock_proc = start_process(
            mockup_server_command(FIXTURES, vendor, model, mock_port),
            cwd=str(REPO_ROOT),
            stderr=subprocess.DEVNULL,
            new_session=True,
        )
        if not _wait_until(
            lambda: (
                _curl_http_code(f"http://127.0.0.1:{mock_port}/redfish/v1/") == "200"
            )
        ):
            return None, "Mock server did not become ready"

        collector_env = {
            **os.environ,
            "HTTP_PROXY": "",
            "HTTPS_PROXY": "",
            "REDFISH_SCHEME": "http",
        }
        exporter_cmd = [
            str(EXPORTER_BIN),
            "--config",
            str(config_path),
            "-p",
            str(collector_port),
            "--target-allowlist",
            "127.0.0.1",
        ]
        if disable_collectors:
            exporter_cmd.extend(["--disable-collectors", disable_collectors])
        if expose_prometheus_metadata:
            exporter_cmd.append("--expose-prometheus-metadata")
        collector_proc = start_process(
            exporter_cmd,
            env=collector_env,
            cwd=str(REDFISH_INVENTORY_EXPORTER_ROOT),
            stderr=subprocess.DEVNULL,
            new_session=True,
        )
        if not _wait_until(
            lambda: (
                _curl_http_code(f"http://127.0.0.1:{collector_port}/", timeout=2)
                is not None
            )
        ):
            return None, "redfish-inventory-exporter did not become ready"

        target = f"127.0.0.1:{mock_port}"
        scrape_url = (
            f"http://127.0.0.1:{collector_port}/redfish?target={target}"
            f"&hostname=DUMMY-HostName&serialnumber=DUMMY-SerialNumber"
        )
        r = run_cmd(
            ["curl", "-s", "-S", "--max-time", str(scrape_timeout), scrape_url],
            timeout=scrape_timeout + 30,
        )
        if r.returncode != 0:
            return None, f"Scrape failed: {r.stderr or r.stdout or 'timeout'}"
        metrics_text = r.stdout or ""
        if not metrics_text.strip():
            return None, "Scrape returned empty body"
        if not has_redfish_data(metrics_text):
            return (
                None,
                f"No Redfish metrics. First 200 chars: {metrics_text[:200]!r}",
            )
        return metrics_text, None
    finally:
        _terminate_proc(collector_proc)
        _terminate_proc(mock_proc)
        if fixed_mock_port:
            _wait_for_port_released(mock_port)
        if fixed_collector_port:
            _wait_for_port_released(collector_port)
        try:
            config_path.unlink()
        except OSError:
            pass
