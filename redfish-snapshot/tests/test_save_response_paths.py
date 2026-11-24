# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""save_response must never write outside the output directory."""

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from redfish_snapshot.main import RedfishCloner


@pytest.fixture
def sandbox():
    """A private temp directory. Everything a test writes is removed with it,
    including anything written outside the output directory by a regression."""
    with tempfile.TemporaryDirectory() as td:
        yield td


@pytest.fixture
def base_dir(sandbox):
    path = os.path.join(sandbox, "base")
    os.makedirs(path)
    return path


@pytest.fixture
def cloner(base_dir):
    with patch("redfish_snapshot.main.HttpClient") as mock_http:
        mock_http.return_value = MagicMock()
        yield RedfishCloner(
            host="127.0.0.1",
            username="u",
            password="p",
            output_path=os.path.join(base_dir, "out"),
            sanitize=False,
        )


def test_normal_resource_is_written_inside_output_dir(cloner, base_dir):
    cloner.save_response("/redfish/v1/Systems/1", {"Id": "1"})
    assert os.path.isfile(
        os.path.join(base_dir, "out", "redfish", "v1", "Systems", "1", "index.json")
    )


def test_service_root_is_written_inside_output_dir(cloner, base_dir):
    cloner.save_response("/redfish/v1/", {"Id": "root"})
    assert os.path.isfile(os.path.join(base_dir, "out", "redfish", "v1", "index.json"))


@pytest.mark.parametrize(
    "url, levels_up, relative_target",
    [
        # A BMC-supplied @odata.id walks up out of the output directory.
        ("/redfish/v1/../../../escape", 1, os.path.join("escape", "index.json")),
        (
            "/redfish/v1/../../../../evil/x",
            2,
            os.path.join("evil", "x", "index.json"),
        ),
    ],
)
def test_escaping_odata_id_writes_nothing_outside(
    cloner, base_dir, url, levels_up, relative_target
):
    out = os.path.join(base_dir, "out")
    escaped = os.path.normpath(
        os.path.join(out, *([".."] * levels_up), relative_target)
    )
    # The first path component outside the output directory: the file itself, or the
    # first directory the escaping path would have created.
    first_created = os.path.normpath(
        os.path.join(out, *([".."] * levels_up), relative_target.split(os.sep)[0])
    )

    cloner.save_response(url, {"Id": "x"})

    assert not os.path.exists(escaped)
    assert not os.path.exists(first_created)
    assert os.path.isdir(out)
