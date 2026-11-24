# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Background logging: QueueHandler + QueueListener, and async line append for response logs."""

from __future__ import annotations

import atexit
import logging
import logging.handlers
import sys
import threading
from queue import Queue
from typing import Optional, TextIO

_listener: Optional[logging.handlers.QueueListener] = None
_listener_lock = threading.Lock()
_listener_atexit_registered = False


def install_queue_logging(
    level: int = logging.INFO,
    fmt: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream: Optional[TextIO] = None,
    *,
    queue_maxsize: int = -1,
) -> logging.handlers.QueueListener:
    """Route root logging through a queue so emitters do not block on I/O.

    Replaces existing root handlers with a single ``QueueHandler``. A
    background ``QueueListener`` drains the queue and writes to *stream*
    (default stdout).
    """
    global _listener, _listener_atexit_registered
    stream = stream or sys.stdout

    with _listener_lock:
        if _listener is not None:
            _listener.stop()
            _listener = None

        root = logging.getLogger()
        root.handlers.clear()
        root.setLevel(level)
        # python-redfish logs request and response headers, including X-Auth-Token, at DEBUG.
        logging.getLogger("redfish").setLevel(logging.WARNING)

        que: Queue[logging.LogRecord] = Queue(queue_maxsize)
        root.addHandler(logging.handlers.QueueHandler(que))

        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter(fmt))
        handler.setLevel(level)

        listener = logging.handlers.QueueListener(
            que, handler, respect_handler_level=True
        )
        listener.start()
        _listener = listener

    if not _listener_atexit_registered:
        atexit.register(_stop_queue_listener)
        _listener_atexit_registered = True
    return listener


def _stop_queue_listener() -> None:
    global _listener
    with _listener_lock:
        if _listener is not None:
            try:
                _listener.stop()
            except Exception:
                pass
            _listener = None


class AsyncAppendWriter:
    """Append lines to a file from a dedicated thread (non-blocking ``write``)."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._q: Queue[Optional[str]] = Queue(-1)
        self._stopped = False
        self._thread = threading.Thread(
            target=self._run,
            name="redpool-async-append-log",
            daemon=True,
        )
        self._thread.start()
        atexit.register(self.shutdown)

    def write(self, line: str) -> None:
        """Enqueue *line* (should include trailing newline if desired)."""
        if self._stopped:
            return
        self._q.put(line)

    def _run(self) -> None:
        while True:
            item = self._q.get()
            try:
                if item is None:
                    break
                try:
                    with open(self._path, "a", encoding="utf-8") as f:
                        f.write(item)
                except OSError:
                    pass
            finally:
                self._q.task_done()

    def shutdown(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self._q.put(None)
        self._thread.join(timeout=5.0)
