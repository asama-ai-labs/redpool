# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Command line for DMTF Redfish-Mockup-Server serving one fixture model.

The server is the ``third_party/Redfish-Mockup-Server`` submodule (BSD-3). It
serves ``fixtures/<Vendor>/<Model>/original`` (DMTF mockup layout) on loopback.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MOCKUP_SERVER_DIR = REPO_ROOT / "third_party" / "Redfish-Mockup-Server"


def mockup_server_command(
    fixtures: Path, vendor: str, model: str, port: int
) -> list[str]:
    """argv that serves one model's ``original/`` tree on ``127.0.0.1:<port>``."""
    return [
        "uv",
        "run",
        "--no-project",
        "--with-requirements",
        str(MOCKUP_SERVER_DIR / "requirements.txt"),
        "python",
        str(MOCKUP_SERVER_DIR / "redfishMockupServer.py"),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--dir",
        str(Path(fixtures) / vendor / model / "original"),
    ]
