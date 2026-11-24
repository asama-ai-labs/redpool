# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Per-BMC state is bounded: the least recently used targets are dropped."""

import threading
import unittest
from unittest import mock

from redpool.proxy import RedfishProxy


def _url(i: int) -> str:
    return f"https://bmc{i}.example"


class TestTargetEviction(unittest.TestCase):
    def test_state_stays_under_the_cap(self) -> None:
        proxy = RedfishProxy(max_targets=10)
        for i in range(500):
            proxy._bmc_io_lock(_url(i))
        self.assertLessEqual(len(proxy._bmc_io_locks), 10)
        self.assertLessEqual(len(proxy._target_last_used), 10)

    def test_least_recently_used_goes_first(self) -> None:
        proxy = RedfishProxy(max_targets=10)
        with mock.patch(
            "redpool.proxy.time.monotonic", side_effect=iter(range(10_000))
        ):
            for i in range(10):
                proxy._bmc_io_lock(_url(i))
            proxy._bmc_io_lock(_url(0))  # refresh the oldest
            proxy._bmc_io_lock(_url(10))  # now over the cap
        self.assertIn(_url(0), proxy._bmc_io_locks)
        self.assertNotIn(_url(1), proxy._bmc_io_locks)
        self.assertIn(_url(10), proxy._bmc_io_locks)

    def test_a_target_in_flight_is_never_evicted(self) -> None:
        # A request holds its BMC lock from its own thread; an RLock is re-entrant
        # for the thread that owns it, so the holder must be a different thread.
        proxy = RedfishProxy(max_targets=5)
        held = proxy._bmc_io_lock(_url(0))
        acquired, release = threading.Event(), threading.Event()

        def hold() -> None:
            with held:
                acquired.set()
                release.wait(5)

        t = threading.Thread(target=hold)
        t.start()
        self.assertTrue(acquired.wait(5))
        try:
            for i in range(1, 50):
                proxy._bmc_io_lock(_url(i))
            self.assertIn(_url(0), proxy._bmc_io_locks)
        finally:
            release.set()
            t.join()

    def test_clients_are_closed_and_the_gauge_drops(self) -> None:
        proxy = RedfishProxy(max_targets=3)
        clients = {}
        for i in range(3):
            url = _url(i)
            proxy._bmc_io_lock(url)
            clients[url] = (mock.Mock(), mock.Mock())
            proxy.redfish_clients[(url, "anon")] = clients[url][0]
            proxy.redfish_clients[(url, "auth")] = clients[url][1]
        with mock.patch("redpool.proxy.metrics.ACTIVE_BMC_CONNECTIONS") as gauge:
            for i in range(3, 6):
                proxy._bmc_io_lock(_url(i))
        evicted = [u for u in clients if u not in proxy._bmc_io_locks]
        self.assertTrue(evicted)
        for url in evicted:
            self.assertNotIn((url, "anon"), proxy.redfish_clients)
            self.assertNotIn((url, "auth"), proxy.redfish_clients)
            clients[url][0].close.assert_called_once()
            clients[url][1].close.assert_called_once()
        self.assertEqual(gauge.dec.call_count, 2 * len(evicted))


if __name__ == "__main__":
    unittest.main()
