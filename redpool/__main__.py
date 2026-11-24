# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Run the Redpool proxy (mitmdump with addon). macOS and Linux only."""

import signal
import subprocess
import sys
from pathlib import Path

_addon_path = Path(__file__).resolve().parent / "mitm_proxy.py"

# Redpool does not authenticate callers, so it listens on loopback unless told otherwise.
DEFAULT_LISTEN_HOST = "127.0.0.1"


def _has_listen_host(argv: list[str]) -> bool:
    """True when argv sets mitmproxy's ``listen_host`` in any spelling."""
    for i, arg in enumerate(argv):
        if arg == "--listen-host" or arg.startswith("--listen-host="):
            return True
        if arg.startswith("--set=listen_host=") or arg.startswith("--set=listen_host:"):
            return True
        if (
            arg == "--set"
            and i + 1 < len(argv)
            and argv[i + 1].startswith("listen_host=")
        ):
            return True
        # ``@host:port`` sets listen_host and listen_port together.
        if arg.startswith("@"):
            return True
    return False


def main() -> int:
    import shutil

    from redpool.config import mitmdump_log_extra_args

    mitmdump = shutil.which("mitmdump") or "mitmdump"
    extra = mitmdump_log_extra_args()
    args = sys.argv[1:]
    if not _has_listen_host(args):
        args = ["--listen-host", DEFAULT_LISTEN_HOST, *args]
    proc = subprocess.Popen([mitmdump, "-s", str(_addon_path), *extra, *args])

    def _terminate_child(_signum, _frame):
        if proc.poll() is None:
            proc.terminate()
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _terminate_child)
    try:
        return proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        sys.exit(130)  # 128 + SIGINT


if __name__ == "__main__":
    sys.exit(main())
