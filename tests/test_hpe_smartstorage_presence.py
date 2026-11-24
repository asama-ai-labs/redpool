# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""SmartStorage presence is a fact about one BMC, cached only when it is known."""

import unittest
from unittest.mock import MagicMock, patch

from normalizers.systems.storage import hpe as storage_hpe


class FakeRest:
    def __init__(self, status, body=None):
        self.status = status
        self.dict = body if body is not None else {}
        self._http_response = None


def _bmc(base_url, status=None, body=None, raises=None):
    client = MagicMock()
    client.get_base_url.return_value = base_url
    if raises is not None:
        client.get.side_effect = raises
    else:
        client.get.return_value = FakeRest(status, body)
    return client


SMARTSTORAGE = {"Id": "SmartStorage", "ArrayControllers": {"@odata.id": "/x"}}


class SmartStoragePresenceTests(unittest.TestCase):
    def setUp(self) -> None:
        with storage_hpe._SMARTSTORAGE_PRESENT_LOCK:
            storage_hpe._SMARTSTORAGE_PRESENT.clear()

    def test_gen10_answer_is_not_applied_to_another_bmc(self) -> None:
        gen10 = _bmc("https://gen10.example.invalid", 200, SMARTSTORAGE)
        gen11 = _bmc("https://gen11.example.invalid", 404)
        self.assertTrue(storage_hpe._hpe_smartstorage_present(gen10, "1"))
        # Same system id "1", different BMC: must ask this BMC, not reuse gen10's answer.
        self.assertFalse(storage_hpe._hpe_smartstorage_present(gen11, "1"))
        gen11.get.assert_called_once()

    def test_definitive_answer_is_cached_per_bmc(self) -> None:
        bmc = _bmc("https://cached.example.invalid", 200, SMARTSTORAGE)
        self.assertTrue(storage_hpe._hpe_smartstorage_present(bmc, "1"))
        self.assertTrue(storage_hpe._hpe_smartstorage_present(bmc, "1"))
        bmc.get.assert_called_once()

    def test_timeout_is_not_cached_as_absent(self) -> None:
        bmc = MagicMock()
        bmc.get_base_url.return_value = "https://flaky.example.invalid"
        bmc.get.side_effect = [TimeoutError("slow BMC"), FakeRest(200, SMARTSTORAGE)]
        self.assertFalse(storage_hpe._hpe_smartstorage_present(bmc, "1"))
        # The next request probes again and gets the real answer.
        self.assertTrue(storage_hpe._hpe_smartstorage_present(bmc, "1"))
        self.assertEqual(bmc.get.call_count, 2)

    def test_unauthorized_probe_is_not_cached(self) -> None:
        bmc = MagicMock()
        bmc.get_base_url.return_value = "https://locked.example.invalid"
        bmc.get.side_effect = [FakeRest(401), FakeRest(200, SMARTSTORAGE)]
        self.assertFalse(storage_hpe._hpe_smartstorage_present(bmc, "1"))
        self.assertTrue(storage_hpe._hpe_smartstorage_present(bmc, "1"))
        self.assertEqual(bmc.get.call_count, 2)

    def test_server_error_is_not_cached(self) -> None:
        bmc = MagicMock()
        bmc.get_base_url.return_value = "https://broken.example.invalid"
        bmc.get.side_effect = [FakeRest(500), FakeRest(404)]
        self.assertFalse(storage_hpe._hpe_smartstorage_present(bmc, "1"))
        self.assertFalse(storage_hpe._hpe_smartstorage_present(bmc, "1"))
        self.assertEqual(bmc.get.call_count, 2)

    def test_cached_answer_expires_after_ttl(self) -> None:
        bmc = _bmc("https://ttl.example.invalid", 200, SMARTSTORAGE)
        ttl = storage_hpe._SMARTSTORAGE_PRESENCE_TTL
        # First call stores the answer at t=0. Second call looks it up after the TTL
        # has passed (and stores again when it re-probes).
        with patch.object(
            storage_hpe.time, "monotonic", side_effect=[0.0, ttl + 1, ttl + 1]
        ):
            self.assertTrue(storage_hpe._hpe_smartstorage_present(bmc, "1"))
            self.assertTrue(storage_hpe._hpe_smartstorage_present(bmc, "1"))
        self.assertEqual(bmc.get.call_count, 2)

    def test_no_client_means_no_smartstorage(self) -> None:
        self.assertFalse(storage_hpe._hpe_smartstorage_present(None, "1"))


if __name__ == "__main__":
    unittest.main()
