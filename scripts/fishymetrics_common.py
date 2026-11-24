# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""
Shared helpers for fishymetrics golden generation and tests.
Run from repo root; callers should ensure REPO_ROOT is set and fishymetrics is built.
"""

from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import time
import shutil
from pathlib import Path

from mockup_server import mockup_server_command
from third_party_paths import FISHYMETRICS_ROOT, REPO_ROOT

# REDPOOL_FIXTURES points the scripts at another corpus checkout.
FIXTURES = Path(os.environ.get("REDPOOL_FIXTURES") or REPO_ROOT / "fixtures")
FISHY_BIN = FISHYMETRICS_ROOT / "build" / "usr" / "bin" / "fishymetrics"
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


def start_process(cmd, env=None, cwd=None, stdout=None, stderr=None):
    proc_env = os.environ.copy()
    if env:
        proc_env.update(env)
    return subprocess.Popen(
        cmd,
        env=proc_env,
        cwd=cwd or str(REPO_ROOT),
        stdout=stdout or subprocess.DEVNULL,
        stderr=stderr or subprocess.PIPE,
    )


def normalize_prom_metrics(text: str) -> str:
    """Normalize Prometheus exposition format for stable comparison.

    - Keeps # HELP and # TYPE lines as-is.
    - Strips optional trailing timestamp (Unix sec/ms integer) from metric lines only.
    - Sorts lines so order differences do not cause failures.
    """
    if not text:
        return ""
    lines = []
    for line in text.splitlines():
        line = line.rstrip()
        if not line:
            continue
        # Metric line: name{labels} value [timestamp]
        if line and not line.startswith("#"):
            parts = line.rsplit(None, 2)
            if len(parts) == 3 and parts[2].isdigit() and int(parts[2]) >= 100000000:
                line = parts[0] + " " + parts[1]
        lines.append(line)
    return "\n".join(sorted(lines))


def run_one_model_metrics(
    vendor: str,
    model: str,
    *,
    mock_port: int = 18888,
    proxy_port: int = 18080,
    fishy_port: int = 10023,
    scrape_timeout: int = 180,
    partial_scrape: bool = False,
) -> tuple[str | None, str | None]:
    """Run mock + proxy + fishymetrics for one model, trigger scrape, fetch /metrics.

    Returns (metrics_text, None) on success, or (None, error_message) on failure.
    """
    log_file = tempfile.NamedTemporaryFile(mode="w+", suffix=".tsv", delete=False)
    log_path = log_file.name
    log_file.close()
    try:
        os.unlink(log_path)
    except FileNotFoundError:
        pass

    from redpool.config import (
        mitmdump_log_extra_args,
        write_temp_redpool_config_for_tests,
    )

    tmp_cfg_path = write_temp_redpool_config_for_tests(19101)

    proxy_env = {
        "REDPOOL_RESPONSE_LOG": log_path,
        "REDPOOL_CONFIG": tmp_cfg_path,
        "HTTP_PROXY": "",
        "HTTPS_PROXY": "",
        "http_proxy": "",
        "https_proxy": "",
        "NO_PROXY": "127.0.0.1,localhost",
        "no_proxy": "127.0.0.1,localhost",
    }

    mock_proc = None
    proxy_proc = None
    fishy_proc = None
    proxy_stdout_file = None
    proxy_stderr_file = None
    proxy_stdout_handle = None
    proxy_stderr_handle = None

    try:
        mock_proc = start_process(
            mockup_server_command(FIXTURES, vendor, model, mock_port),
            cwd=str(REPO_ROOT),
            stderr=subprocess.DEVNULL,
        )
        for attempt in range(20):
            time.sleep(0.5)
            r = run_cmd(
                [
                    "curl",
                    "-s",
                    "-o",
                    "/dev/null",
                    "-w",
                    "%{http_code}",
                    f"http://127.0.0.1:{mock_port}/redfish/v1/",
                ],
                timeout=2,
            )
            r1 = run_cmd(
                [
                    "curl",
                    "-s",
                    "-o",
                    "/dev/null",
                    "-w",
                    "%{http_code}",
                    f"http://127.0.0.1:{mock_port}/redfish/v1",
                ],
                timeout=2,
            )
            if (
                r.returncode == 0
                and r.stdout.strip() == "200"
                and r1.returncode == 0
                and r1.stdout.strip() == "200"
            ):
                break
            if attempt == 19:
                return None, "Mock server did not become ready"
        time.sleep(0.5)

        proxy_stdout_file = tempfile.NamedTemporaryFile(delete=False, suffix=".log")
        proxy_stderr_file = tempfile.NamedTemporaryFile(delete=False, suffix=".log")
        proxy_stdout_file.close()
        proxy_stderr_file.close()
        proxy_stdout_handle = open(proxy_stdout_file.name, "wb")
        proxy_stderr_handle = open(proxy_stderr_file.name, "wb")
        mitmdump = (
            MITMDUMP_BIN
            if MITMDUMP_BIN.exists()
            else Path(shutil.which("mitmdump") or "mitmdump")
        )
        proxy_proc = subprocess.Popen(
            [
                str(mitmdump),
                "-s",
                str(ADDON_PATH),
                *mitmdump_log_extra_args(),
                "--listen-host",
                "0.0.0.0",
                "--listen-port",
                str(proxy_port),
                "-k",
            ],
            env={**os.environ, **proxy_env},
            cwd=str(REPO_ROOT),
            stdout=proxy_stdout_handle,
            stderr=proxy_stderr_handle,
            start_new_session=True,
        )
        time.sleep(2)
        if proxy_proc.poll() is not None:
            err_detail = ""
            if Path(proxy_stderr_file.name).exists():
                try:
                    err_detail = (
                        Path(proxy_stderr_file.name)
                        .read_text(encoding="utf-8", errors="replace")
                        .strip()
                    )
                    if len(err_detail) > 800:
                        err_detail = err_detail[:400] + "\n...\n" + err_detail[-400:]
                except OSError:
                    pass
            detail = f" {err_detail}" if err_detail else ""
            return (
                None,
                f"Proxy failed to start{detail} (check ports: lsof -i :{proxy_port} -i :19101)",
            )

        for attempt in range(10):
            time.sleep(0.5)
            r = run_cmd(
                [
                    "curl",
                    "-s",
                    "-o",
                    "/dev/null",
                    "-w",
                    "%{http_code}",
                    "--max-time",
                    "5",
                    "-x",
                    f"http://127.0.0.1:{proxy_port}",
                    f"http://127.0.0.1:{mock_port}/redfish/v1/Systems",
                ],
                timeout=8,
            )
            if r.returncode == 0 and r.stdout.strip() in ("200", "500"):
                break
            if attempt == 9:
                return None, (
                    f"Proxy not accepting connections "
                    f"(curl exit={r.returncode}, http_code={r.stdout.strip()!r})"
                )
        time.sleep(0.5)

        fishy_proc = start_process(
            [
                str(FISHY_BIN),
                "--port",
                str(fishy_port),
                "--user",
                "admin",
                "--password",
                "password",
                "--scheme",
                "http",
                "--insecure-skip-verify",
            ],
            env={
                **os.environ,
                "HTTP_PROXY": f"http://127.0.0.1:{proxy_port}",
                "HTTPS_PROXY": f"http://127.0.0.1:{proxy_port}",
                "FISHYMETRICS_DISABLE_404_RETRY": "1",
            },
            cwd=str(REPO_ROOT),
            stderr=subprocess.DEVNULL,
        )
        for attempt in range(30):
            time.sleep(0.5)
            r = run_cmd(
                [
                    "curl",
                    "-s",
                    "-o",
                    "/dev/null",
                    "-w",
                    "%{http_code}",
                    f"http://127.0.0.1:{fishy_port}/",
                ],
                timeout=3,
            )
            if r.returncode == 0:
                break
            if attempt == 29:
                return None, "Fishymetrics did not become ready"
        time.sleep(0.5)

        if partial_scrape:
            components = "thermal,power,memory,processor,drives,storage_controller,firmware,system"
            scrape_url = (
                f"http://127.0.0.1:{fishy_port}/scrape/partial"
                f"?target=127.0.0.1:{mock_port}&model=generic"
                f"&proxy_host=127.0.0.1:{proxy_port}&components={components}"
            )
        else:
            scrape_url = (
                f"http://127.0.0.1:{fishy_port}/scrape"
                f"?target=127.0.0.1:{mock_port}&model=generic"
                f"&proxy_host=127.0.0.1:{proxy_port}"
            )
        r = run_cmd(
            [
                "curl",
                "-s",
                "-S",
                "--max-time",
                str(scrape_timeout),
                scrape_url,
            ],
            timeout=scrape_timeout + 15,
        )
        if r.returncode != 0:
            return None, f"Scrape failed: {r.stderr or r.stdout or 'timeout'}"
        metrics_text = r.stdout or ""
        if not metrics_text.strip():
            return None, "Scrape returned empty body"
        if "redfish_up" not in metrics_text and "redfish_thermal" not in metrics_text:
            hint = f" Scrape body (first 200 chars): {metrics_text[:200]!r}"
            return (
                None,
                f"No Redfish metrics in output (scrape may have failed or not used proxy).{hint}",
            )
        return metrics_text, None
    finally:
        for p in (fishy_proc, mock_proc):
            if p and p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
        if proxy_proc and proxy_proc.poll() is None:
            try:
                os.killpg(os.getpgid(proxy_proc.pid), signal.SIGTERM)
            except (ProcessLookupError, OSError):
                proxy_proc.terminate()
            try:
                proxy_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(proxy_proc.pid), signal.SIGKILL)
                except (ProcessLookupError, OSError):
                    pass
                proxy_proc.kill()
                proxy_proc.wait()
        if proxy_stdout_handle is not None:
            try:
                proxy_stdout_handle.close()
            except OSError:
                pass
        if proxy_stderr_handle is not None:
            try:
                proxy_stderr_handle.close()
            except OSError:
                pass
        for f in (proxy_stdout_file, proxy_stderr_file):
            if f is not None and Path(f.name).exists():
                try:
                    Path(f.name).unlink()
                except OSError:
                    pass
        try:
            Path(tmp_cfg_path).unlink()
        except OSError:
            pass
        try:
            if os.path.exists(log_path):
                os.unlink(log_path)
        except OSError:
            pass
        time.sleep(0.5)


def run_one_model_metrics_direct(
    vendor: str,
    model: str,
    *,
    mock_port: int = 18889,
    fishy_port: int = 10024,
    scrape_timeout: int = 180,
) -> tuple[str | None, str | None]:
    """Run mock + fishymetrics (no proxy) for one model, trigger scrape, return metrics.

    Returns (metrics_text, None) on success, or (None, error_message) on failure.
    """
    mock_proc = None
    fishy_proc = None

    try:
        mock_proc = start_process(
            mockup_server_command(FIXTURES, vendor, model, mock_port),
            cwd=str(REPO_ROOT),
            stderr=subprocess.DEVNULL,
        )
        for attempt in range(20):
            time.sleep(0.5)
            r = run_cmd(
                [
                    "curl",
                    "-s",
                    "-o",
                    "/dev/null",
                    "-w",
                    "%{http_code}",
                    f"http://127.0.0.1:{mock_port}/redfish/v1/",
                ],
                timeout=2,
            )
            r1 = run_cmd(
                [
                    "curl",
                    "-s",
                    "-o",
                    "/dev/null",
                    "-w",
                    "%{http_code}",
                    f"http://127.0.0.1:{mock_port}/redfish/v1",
                ],
                timeout=2,
            )
            if (
                r.returncode == 0
                and r.stdout.strip() == "200"
                and r1.returncode == 0
                and r1.stdout.strip() == "200"
            ):
                break
            if attempt == 19:
                return None, "Mock server did not become ready"
        time.sleep(0.5)

        fishy_proc = start_process(
            [
                str(FISHY_BIN),
                "--port",
                str(fishy_port),
                "--user",
                "admin",
                "--password",
                "password",
                "--scheme",
                "http",
                "--insecure-skip-verify",
            ],
            env={
                **os.environ,
                "HTTP_PROXY": "",
                "HTTPS_PROXY": "",
                "http_proxy": "",
                "https_proxy": "",
                "NO_PROXY": "127.0.0.1,localhost",
                "no_proxy": "127.0.0.1,localhost",
                "FISHYMETRICS_DISABLE_404_RETRY": "1",
            },
            cwd=str(REPO_ROOT),
            stderr=subprocess.DEVNULL,
        )
        for attempt in range(30):
            time.sleep(0.5)
            r = run_cmd(
                [
                    "curl",
                    "-s",
                    "-o",
                    "/dev/null",
                    "-w",
                    "%{http_code}",
                    f"http://127.0.0.1:{fishy_port}/",
                ],
                timeout=3,
            )
            if r.returncode == 0:
                break
            if attempt == 29:
                return None, "Fishymetrics did not become ready"
        time.sleep(0.5)

        scrape_url = (
            f"http://127.0.0.1:{fishy_port}/scrape"
            f"?target=127.0.0.1:{mock_port}&model=generic"
        )
        r = run_cmd(
            [
                "curl",
                "-s",
                "-S",
                "--max-time",
                str(scrape_timeout),
                scrape_url,
            ],
            timeout=scrape_timeout + 15,
        )
        if r.returncode != 0:
            return None, f"Scrape failed: {r.stderr or r.stdout or 'timeout'}"
        metrics_text = r.stdout or ""
        if not metrics_text.strip():
            return None, "Scrape returned empty body"
        if "redfish_up" not in metrics_text and "redfish_thermal" not in metrics_text:
            hint = f" Scrape body (first 200 chars): {metrics_text[:200]!r}"
            return None, f"No Redfish metrics in output.{hint}"
        return metrics_text, None
    finally:
        for p in (fishy_proc, mock_proc):
            if p and p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
        time.sleep(0.5)
