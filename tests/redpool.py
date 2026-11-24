# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

import argparse
import difflib
import json
import logging
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from redfish.rest.v1 import HttpClient

from normalizers.url_rewrites import reverse_rewrite_path
from redpool.cache import InMemoryCache
from redpool.mockup import iter_mockup_files, relpath_to_uri, uri_to_relpath
from redpool.proxy import RedfishProxy

pytestmark = pytest.mark.requires_fixtures

# Global variables for filtering tests
TARGET_VENDOR = None
TARGET_MODEL = None

loglevel = logging.INFO

logging.basicConfig(
    level=loglevel, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("test_redpool")
logger.setLevel(loglevel)

root_logger = logging.getLogger()
root_logger.setLevel(loglevel)
for handler in root_logger.handlers:
    handler.setLevel(loglevel)


class MockRedfishClient(HttpClient):
    """Mock Redfish client that returns responses from test data files."""

    def __init__(self, vendor_dir):
        self.vendor_dir = vendor_dir
        self.input_dir = os.path.join(vendor_dir, "original")
        base_url = f"https://mock-{os.path.basename(vendor_dir)}.example.com"

        super().__init__(
            base_url=base_url,
            username="mock_user",
            password="mock_password",
            default_prefix="/redfish/v1/",
            check_connectivity=False,
        )

        self._original_rest_request = self._rest_request
        self._rest_request = self._mock_rest_request

    def _mock_rest_request(
        self,
        path="",
        method="GET",
        args=None,
        body=None,
        headers=None,
        allow_redirects=True,
        timeout=None,
        max_retry=None,
    ):
        if method.upper() == "GET":
            return self._create_mock_response(path)
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.dict = {}
        # Mirror a real RestResponse: .dict is parsed from the decoded text.
        mock_response.text = "{}"
        mock_response.getheader.return_value = "application/json"
        return mock_response

    def _create_mock_response(self, path):
        file_path = os.path.join(self.input_dir, uri_to_relpath(path))

        logger.debug(f"MockRedfishClient: Attempting to get file: {file_path}")

        if not os.path.exists(file_path):
            alt_path = reverse_rewrite_path(file_path)
            if alt_path != file_path and os.path.exists(alt_path):
                file_path = alt_path
            else:
                # A real BMC answers a missing resource with 404, not a Python error.
                logger.debug(f"Test data file not found, returning 404: {file_path}")
                mock_response = MagicMock()
                mock_response.status = 404
                mock_response.dict = {}
                mock_response.text = "{}"
                mock_response.getheader.return_value = "application/json"
                return mock_response

        with open(file_path, "r") as f:
            data = json.load(f)

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.dict = data
        mock_response.text = json.dumps(data)
        mock_response.getheader.return_value = "application/json"

        odata_type = data.get("@odata.type", "No @odata.type found")
        logger.debug(
            f"MockRedfishClient: Loaded data for {path} with @odata.type: {odata_type}"
        )
        return mock_response

    def get(self, path, args=None, headers=None):
        """Match gofish ``HttpClient.get`` arity so ``redfish_get_json`` prefetch works in tests."""
        return self._create_mock_response(path)

    def get_base_url(self):
        return getattr(self, "base_url", "") or self.vendor_dir


def print_json_diff(expected, actual):
    """Print a unified diff between two JSON objects."""
    expected_lines = json.dumps(expected, indent=2, sort_keys=True).splitlines()
    actual_lines = json.dumps(actual, indent=2, sort_keys=True).splitlines()

    diff = difflib.unified_diff(
        expected_lines,
        actual_lines,
        fromfile="expected",
        tofile="actual",
        lineterm="",
    )

    diff_text = "\n".join(diff)
    return diff_text if diff_text else "No differences found (may be ordering issue)"


def _rel_to_redfish_path(rel: Path) -> str:
    """Convert a path relative to normalized/ into a Redfish API path.

    Applies reverse URL rewrites (e.g. PCIeDevices → PCIDevices) so the
    resulting Redfish path matches the original vendor URL that the
    normalizer is registered under.
    """
    return reverse_rewrite_path(relpath_to_uri(rel))


class TestRedfishNormalization(unittest.TestCase):
    """Verify every normalized golden file is reproducible from its original.

    The test is driven from the *normalized* side: every ``.json`` file under
    ``fixtures/<Vendor>/<Model>/normalized/`` is treated as an expected output.
    The corresponding original file is loaded, run through the normalizer, and
    compared against the expected output.

    This guarantees that:
    * Every stored golden file has a matching normalizer.
    * Regressions in the normalizer are caught immediately.
    * Stale or orphaned golden files are surfaced as failures.
    """

    def setUp(self):
        self.redfish_proxy = RedfishProxy()
        self.redfish_proxy.objecttype_cache = InMemoryCache(ttl_seconds=60)

        self.metadata_patcher = patch.object(
            self.redfish_proxy,
            "_extract_server_metadata",
            autospec=True,
        )
        self.mock_extract_metadata = self.metadata_patcher.start()

        self.test_data_dir = str(Path(__file__).resolve().parent.parent / "fixtures")

    def tearDown(self):
        self.metadata_patcher.stop()

    def test_all_normalized_outputs(self):
        """Every normalized golden file must be reproducible from its original."""
        from redpool.proxy import ServerMetadata

        vendor_dirs = sorted(
            [
                d
                for d in Path(self.test_data_dir).iterdir()
                if d.is_dir()
                and (TARGET_VENDOR is None or d.name.lower() == TARGET_VENDOR.lower())
            ]
        )

        if TARGET_VENDOR and not vendor_dirs:
            self.fail(f"No test data found for vendor: {TARGET_VENDOR}")

        tested = 0
        for vendor_dir in vendor_dirs:
            vendor_name = vendor_dir.name
            model_dirs = sorted(
                [
                    d
                    for d in vendor_dir.iterdir()
                    if d.is_dir()
                    and (TARGET_MODEL is None or d.name.lower() == TARGET_MODEL.lower())
                ]
            )

            if TARGET_MODEL and not model_dirs:
                self.fail(
                    f"No test data found for model: {TARGET_MODEL} "
                    f"under vendor: {vendor_name}"
                )

            for model_dir in model_dirs:
                model_name = model_dir.name
                original_dir = model_dir / "original"
                normalized_dir = model_dir / "normalized"

                if not original_dir.is_dir() or not normalized_dir.is_dir():
                    continue

                mock_client = MockRedfishClient(str(model_dir))
                self.mock_extract_metadata.return_value = ServerMetadata(
                    hostname=f"{model_name.lower()}.example.com",
                    vendor=vendor_name,
                    model=model_name.replace("_", " "),
                )

                golden_files = list(iter_mockup_files(normalized_dir))
                if not golden_files:
                    continue

                for golden_path in golden_files:
                    rel = golden_path.relative_to(normalized_dir)
                    original_rel = Path(reverse_rewrite_path(str(rel)))
                    original_path = original_dir / original_rel
                    redfish_path = _rel_to_redfish_path(rel)
                    tag = f"{vendor_name}/{model_name} {redfish_path}"

                    with self.subTest(tag=tag):
                        if not original_path.exists():
                            logger.info(
                                "[%s/%s] SKIP %s (synthetic, no original)",
                                vendor_name,
                                model_name,
                                redfish_path,
                            )
                            continue

                        normalizer = self.redfish_proxy.get_normalizer_for_path(
                            redfish_path,
                            mock_client,
                        )
                        self.assertIsNotNone(
                            normalizer,
                            f"No normalizer resolved for {redfish_path}",
                        )

                        with open(original_path) as f:
                            input_data = json.load(f)
                        with open(golden_path) as f:
                            expected = json.load(f)

                        actual = self.redfish_proxy.normalize_redfish_response(
                            response_data=input_data,
                            response_normalizer=normalizer,
                            vendor=vendor_name,
                            redfish_client=mock_client,
                            resource_path=redfish_path,
                        )

                        if actual != expected:
                            diff = print_json_diff(expected, actual)
                            self.fail(
                                f"Normalizer output differs from golden file "
                                f"for {redfish_path}:\n{diff}"
                            )

                        tested += 1
                        logger.info(
                            "[%s/%s] OK  %s",
                            vendor_name,
                            model_name,
                            redfish_path,
                        )

        self.assertGreater(
            tested,
            0,
            "No normalized outputs were tested — check fixtures layout",
        )
        logger.info("Verified %d normalized golden files", tested)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Test Redfish normalization",
        add_help=False,
    )
    parser.add_argument("--vendor", help="Test only the specified vendor")
    parser.add_argument("--model", help="Test only the specified model")

    args, remaining = parser.parse_known_args()
    args.remaining = remaining
    return args


if __name__ == "__main__":
    args = parse_args()
    TARGET_VENDOR = args.vendor
    TARGET_MODEL = args.model

    if TARGET_VENDOR or TARGET_MODEL:
        filters = []
        if TARGET_VENDOR:
            filters.append(f"vendor='{TARGET_VENDOR}'")
        if TARGET_MODEL:
            filters.append(f"model='{TARGET_MODEL}'")
        print(f"Running tests with filter: {' and '.join(filters)}")

    unittest.main(argv=[sys.argv[0]] + args.remaining)
