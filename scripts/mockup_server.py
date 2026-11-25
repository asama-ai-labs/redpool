# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Command line for DMTF Redfish-Mockup-Server serving one fixture model.

The server is the ``third_party/Redfish-Mockup-Server`` submodule (BSD-3). It
serves ``fixtures/<Vendor>/<Model>/original`` (DMTF mockup layout) on loopback.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from requests import Session
from requests.adapters import HTTPAdapter
from requests.exceptions import RequestException

REPO_ROOT = Path(__file__).resolve().parent.parent
MOCKUP_SERVER_DIR = REPO_ROOT / "third_party" / "Redfish-Mockup-Server"


class _CaptureFragmentAdapter(HTTPAdapter):
    """Send saved fragment paths as HTTP paths instead of dropping the fragment."""

    def send(self, request, **kwargs):
        request.url = request.url.replace("#", "%23", 1)
        return super().send(request, **kwargs)


def mockup_server_command(
    fixtures: Path,
    vendor: str,
    model: str,
    port: int,
    *,
    capture_fragments: bool = False,
) -> list[str]:
    """argv that serves one model's ``original/`` tree on ``127.0.0.1:<port>``."""
    script = (
        Path(__file__).resolve()
        if capture_fragments
        else MOCKUP_SERVER_DIR / "redfishMockupServer.py"
    )
    return [
        "uv",
        "run",
        "--no-project",
        "--with-requirements",
        str(MOCKUP_SERVER_DIR / "requirements.txt"),
        "python",
        str(script),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--dir",
        str(Path(fixtures) / vendor / model / "original"),
    ]


@contextmanager
def mockup_redfish_client(model_dir: Path):
    """Serve one model over loopback and yield a Redfish client for its lifetime."""
    import redfish

    model_dir = model_dir.resolve()
    if not (model_dir / "original").is_dir():
        raise FileNotFoundError(f"Missing mockup directory: {model_dir / 'original'}")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"
    command = mockup_server_command(
        model_dir.parent.parent,
        model_dir.parent.name,
        model_dir.name,
        port,
        capture_fragments=True,
    )
    with tempfile.TemporaryFile() as logs, Session() as probe:
        probe.trust_env = False
        process = subprocess.Popen(
            command, stdout=logs, stderr=subprocess.STDOUT, start_new_session=True
        )
        try:
            deadline = time.monotonic() + 30
            while process.poll() is None and time.monotonic() < deadline:
                try:
                    with probe.get(f"{base_url}/redfish/v1", timeout=0.5) as response:
                        if response.ok:
                            break
                except RequestException:
                    pass
                time.sleep(0.1)
            else:
                logs.seek(max(0, logs.tell() - 1500))
                detail = logs.read().decode(errors="replace").strip()
                raise RuntimeError(
                    f"Mockup server failed to start for {model_dir}: {detail}"
                )

            client = redfish.redfish_client(
                base_url=base_url, check_connectivity=False, timeout=5, max_retry=2
            )
            client._session.trust_env = False
            client._session.mount(base_url + "/", _CaptureFragmentAdapter())
            try:
                yield client
            finally:
                client._session.close()
        finally:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()


if __name__ == "__main__":
    sys.path.insert(0, str(MOCKUP_SERVER_DIR))
    import redfishMockupServer as server

    upstream_clean_path = server.clean_path

    def capture_clean_path(path, is_short):
        # Decode just the separator used by the fixture client. The server still
        # handles query parameters and ordinary request paths itself.
        return upstream_clean_path(path, is_short).replace("%23", "#", 1)

    server.clean_path = capture_clean_path
    server.main()
