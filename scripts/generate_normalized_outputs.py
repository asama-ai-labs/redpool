#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Generate normalized Redfish outputs for every server model in fixtures/.

Uses the redpool proxy (with mock backend) so that normalization and
vendor-specific behavior (e.g. HPE PCIeDevices grouping) are identical to
runtime. Walks fixtures/<Vendor>/<Model>/original/ to discover paths, GETs each
path through the proxy, and writes pretty-printed JSON to fixtures/.../normalized/.
A response identical to the original document is omitted; that file is passthrough.

For large collections (e.g. LogServices/Log1/Entries with many items), only a
sample of members is requested and written (first 2, last 1, 2 from middle; default max 50).

Usage:
    uv run python scripts/generate_normalized_outputs.py --fixtures ../fixtures --vendor Dell --model PowerEdge_R740
    uv run python scripts/generate_normalized_outputs.py [--max-collection-sample 50]
"""

import argparse
import json
import logging
import os
import shutil
from pathlib import Path
from urllib.parse import urlparse

from redpool.cache import InMemoryCache
from redpool.mockup import (
    INDEX,
    iter_fixture_models,
    iter_mockup_files,
    relpath_to_uri,
    uri_to_relpath,
)
from redpool.proxy import RedfishProxy, ServerMetadata
from tests.redpool import MockRedfishClient
from normalizers.url_rewrites import reverse_rewrite_path, rewrite_path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
)
log = logging.getLogger("generate")

MAX_COLLECTION_SAMPLE = 50


def _sample_collection_members(member_ids: list[str], max_sample: int) -> set[str]:
    """Return up to ``max_sample`` member ids, spread across the sorted id list (deterministic)."""
    if len(member_ids) <= max_sample:
        return set(member_ids)
    sorted_ids = sorted(member_ids)
    n = len(sorted_ids)
    if max_sample <= 0:
        return set()
    if max_sample == 1:
        return {sorted_ids[0]}
    keep: set[str] = set()
    for k in range(max_sample):
        idx = int(round(k * (n - 1) / (max_sample - 1)))
        idx = min(max(0, idx), n - 1)
        keep.add(sorted_ids[idx])
    return keep


def _odata_member_id(odata_id: str) -> str | None:
    """Last path segment of a Redfish @odata.id (path or absolute URL)."""
    if not odata_id:
        return None
    if odata_id.startswith("http"):
        odata_id = urlparse(odata_id).path or odata_id
    if not odata_id.startswith("/"):
        odata_id = "/redfish/v1/" + odata_id.lstrip("/")
    return odata_id.rstrip("/").split("/")[-1] or None


def _file_rel(file_path: str, root: str) -> str:
    """``<root>/redfish/v1/Systems/1/index.json`` -> ``Systems/1`` (``""`` for the root)."""
    uri = relpath_to_uri(Path(os.path.relpath(file_path, root)))
    return uri[len("/redfish/v1") :].lstrip("/")


def _discover_collections(original_dir: str, max_sample: int) -> dict[str, set[str]]:
    """Map collection container paths to a sample of member ids.

    Only Redfish resources whose JSON has a non-empty ``Members`` array (with
    ``@odata.id`` on each entry) can trigger sampling and the second-stage prune.
    Directories that merely contain many sibling resource JSON files (e.g.
    ``UpdateService/*.json``) are **not** treated as collections.
    """
    keep_map: dict[str, set[str]] = {}
    for abs_path in iter_mockup_files(Path(original_dir)):
        try:
            with open(abs_path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        members = data.get("Members")
        if not isinstance(members, list) or not members:
            continue
        member_ids: list[str] = []
        for m in members:
            if not isinstance(m, dict):
                continue
            mid = _odata_member_id(m.get("@odata.id", ""))
            if mid:
                member_ids.append(mid)
        if len(member_ids) <= max_sample:
            continue
        parent_rel = rewrite_path(_file_rel(str(abs_path), original_dir))
        keep_map[parent_rel] = _sample_collection_members(member_ids, max_sample)
    return keep_map


def _path_to_rel(path: str) -> str:
    """Convert /redfish/v1/Systems/1 -> Systems/1 (normalized path segment)."""
    p = path.strip("/")
    if p.startswith("redfish/v1/"):
        p = p[len("redfish/v1/") :]
    return p.replace("/", os.sep)


def _read_original_body(original_dir: str, redfish_path: str):
    """Load the original JSON the mock would serve for ``redfish_path``."""
    file_path = os.path.join(original_dir, uri_to_relpath(redfish_path))
    if not os.path.isfile(file_path):
        alt_path = reverse_rewrite_path(file_path)
        if alt_path != file_path and os.path.isfile(alt_path):
            file_path = alt_path
        else:
            return None
    try:
        with open(file_path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _is_bmc_error_body(body) -> bool:
    """True for a Redfish error object (``{"error": ...}``) that is not a resource."""
    return isinstance(body, dict) and "error" in body and "@odata.type" not in body


def _rel_to_output_path(rel: str, output_dir: str) -> str:
    """Convert relative path (with os.sep) to output file path; apply rewrite (PCIDevices -> PCIeDevices)."""
    rewritten = rewrite_path(rel.replace(os.sep, "/"))
    return os.path.join(output_dir, uri_to_relpath(rewritten))


def _collect_links(
    data: dict, path: str, collection_keep: dict, max_sample: int
) -> list[str]:
    """Extract Redfish paths to crawl from a response (Members and collection links)."""
    out = []
    # Collection Members
    members = data.get("Members")
    if isinstance(members, list) and members:
        prefix = path.rstrip("/")
        parent_rel = _path_to_rel(prefix).replace(os.sep, "/")
        member_ids = []
        for m in members:
            if not isinstance(m, dict):
                continue
            odata_id = m.get("@odata.id")
            if not odata_id:
                continue
            # @odata.id can be path or full URL; take path part
            if odata_id.startswith("http"):
                odata_id = urlparse(odata_id).path or odata_id
            if not odata_id.startswith("/"):
                odata_id = "/redfish/v1/" + odata_id.lstrip("/")
            member_id = odata_id.rstrip("/").split("/")[-1]
            member_ids.append((member_id, odata_id))
        if len(member_ids) > max_sample and parent_rel in collection_keep:
            keep_set = collection_keep[parent_rel]
            for mid, full_path in member_ids:
                if mid in keep_set:
                    out.append(full_path)
        else:
            out.extend(full_path for _, full_path in member_ids)
    # Single collection links (e.g. PCIeFunctions on a device)
    for key, val in data.items():
        if key.startswith("@"):
            continue
        if isinstance(val, dict) and val.get("@odata.id"):
            link = val["@odata.id"]
            if link.startswith("http"):
                link = urlparse(link).path or link
            if not link.startswith("/"):
                link = "/redfish/v1/" + link.lstrip("/")
            out.append(link)
    return out


def generate_for_model(
    proxy: RedfishProxy,
    vendor_name: str,
    model_dir: str,
    max_collection_sample: int = MAX_COLLECTION_SAMPLE,
):
    model_name = os.path.basename(model_dir)
    original_dir = os.path.join(model_dir, "original")
    output_dir = os.path.join(model_dir, "normalized")

    if not os.path.isdir(original_dir):
        log.warning("[%s/%s] No original/ directory, skipping", vendor_name, model_name)
        return

    collection_keep = _discover_collections(original_dir, max_collection_sample)
    mock_client = MockRedfishClient(model_dir)
    base_url = f"https://{model_name.lower().replace('_', '-')}.example.com"
    mock_client.get_base_url = lambda: base_url
    # Directory names can carry a host suffix (PowerEdge_R630_2). The silk maps
    # key on the platform model the live proxy reads from Product or Systems.Model.
    detected = proxy._extract_server_metadata(base_url, mock_client)
    if detected is not None and proxy._product_is_server_model(detected.model):
        model = detected.model
    else:
        model = model_name.replace("_", " ")
    server_metadata = ServerMetadata(
        hostname=f"{model_name.lower().replace('_', '-')}.example.com",
        vendor=vendor_name,
        model=model,
    )

    # Build initial queue: every path from original/ as canonical Redfish path
    queue = []
    for file_path in iter_mockup_files(Path(original_dir)):
        canonical = rewrite_path(_file_rel(str(file_path), original_dir))
        queue.append(f"/redfish/v1/{canonical}".rstrip("/"))

    visited = set()
    written = 0
    skipped = 0
    unchanged = 0
    written_stems_by_dir: dict[str, set[str]] = {}
    produced: set[str] = set()

    while queue:
        path = queue.pop(0)
        if path in visited:
            continue
        visited.add(path)

        try:
            body, _meta, status, _norm, _headers = proxy.proxy_request(
                path,
                method="GET",
                redfish_endpoint="http://mock.example.com",
                backend_client=mock_client,
                server_metadata=server_metadata,
            )
        except Exception as e:
            log.debug("[%s/%s] %s -> %s", vendor_name, model_name, path, e)
            skipped += 1
            continue

        if status != 200 or body is None:
            skipped += 1
            continue

        # The BMC answered this URL with an error (for example a blank collection member
        # that was captured as an error body). There is no resource to normalize.
        if _is_bmc_error_body(_read_original_body(original_dir, path)):
            skipped += 1
            continue

        rel = _path_to_rel(path)
        out_path = _rel_to_output_path(rel, output_dir)
        out_dir = os.path.dirname(out_path)
        # Track the member name even when the body matches original, so pruning
        # does not remove a member directory that holds its sub-resources.
        canonical_rel = rewrite_path(rel.replace(os.sep, "/"))
        rel_dir, _, stem = canonical_rel.rpartition("/")
        written_stems_by_dir.setdefault(rel_dir, set()).add(stem)

        for link in _collect_links(body, path, collection_keep, max_collection_sample):
            if link not in visited:
                queue.append(link)

        produced.add(os.path.abspath(out_path))
        original_body = _read_original_body(original_dir, path)
        if original_body is not None and original_body == body:
            if os.path.isfile(out_path):
                try:
                    os.unlink(out_path)
                except OSError:
                    pass
            unchanged += 1
            continue

        os.makedirs(out_dir, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as handle:
            json.dump(body, handle, indent=2)
            handle.write("\n")
        written += 1
        log.info(
            "[%s/%s] %-60s -> %s",
            vendor_name,
            model_name,
            path,
            os.path.relpath(out_path, model_dir),
        )

    # Prune: remove normalized files/dirs we didn't write in *collection* dirs (e.g. HPE PCIeDevices 5,6,7)
    # Only prune dirs that look like collection member containers (e.g. Systems/1/PCIeDevices), not top-level (Systems)
    for rel_dir, stems in written_stems_by_dir.items():
        parts = rel_dir.replace("\\", "/").split("/")
        if len(parts) < 3:
            continue
        norm_dir = os.path.dirname(os.path.join(output_dir, uri_to_relpath(rel_dir)))
        if not os.path.isdir(norm_dir):
            continue
        for name in os.listdir(norm_dir):
            path = os.path.join(norm_dir, name)
            if name == INDEX or name in stems:
                continue
            if os.path.isdir(path):
                try:
                    shutil.rmtree(path)
                    log.info("[%s/%s] Pruned dir %s", vendor_name, model_name, path)
                except OSError:
                    pass

    # Prune normalized collection dirs: remove members not in the keep set
    for parent_rel, keep_set in collection_keep.items():
        for candidate in (parent_rel, rewrite_path(parent_rel)):
            norm_dir = os.path.dirname(
                os.path.join(output_dir, uri_to_relpath(candidate))
            )
            if not os.path.isdir(norm_dir):
                continue
            removed = 0
            for name in os.listdir(norm_dir):
                member_file = os.path.join(norm_dir, name, INDEX)
                if name in keep_set or not os.path.isfile(member_file):
                    continue
                try:
                    os.unlink(member_file)
                    removed += 1
                except OSError:
                    pass
            if removed:
                log.info(
                    "[%s/%s] Pruned %d normalized files from %s",
                    vendor_name,
                    model_name,
                    removed,
                    candidate,
                )

    # Remove normalized files this run did not produce (documents that no longer
    # normalize, or whose original was removed). Without this they stay forever.
    stale = 0
    for dirpath, _dirnames, filenames in os.walk(output_dir):
        for name in filenames:
            full = os.path.abspath(os.path.join(dirpath, name))
            if full in produced:
                continue
            try:
                os.unlink(full)
                stale += 1
            except OSError:
                pass
    if stale:
        log.info(
            "[%s/%s] Removed %d stale normalized files", vendor_name, model_name, stale
        )

    for dirpath, _dirnames, _filenames in os.walk(output_dir, topdown=False):
        if dirpath == output_dir:
            continue
        try:
            if not os.listdir(dirpath):
                os.rmdir(dirpath)
        except OSError:
            pass

    log.info(
        "[%s/%s] Wrote %d normalized files (%d unchanged, omitted)",
        vendor_name,
        model_name,
        written,
        unchanged,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    repo_root = Path(__file__).resolve().parent.parent
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=Path(os.environ.get("REDPOOL_FIXTURES") or repo_root / "fixtures"),
        help="Fixtures root (default: $REDPOOL_FIXTURES or the repository's fixtures/)",
    )
    parser.add_argument("--vendor", help="Only process this vendor")
    parser.add_argument("--model", help="Only process this model")
    parser.add_argument(
        "--max-collection-sample",
        type=int,
        default=MAX_COLLECTION_SAMPLE,
        help="Max collection members to normalize per collection (default %d)"
        % MAX_COLLECTION_SAMPLE,
    )
    args = parser.parse_args()

    if not args.fixtures.is_dir():
        parser.error(f"fixtures directory not found: {args.fixtures}")
    models = list(
        iter_fixture_models(args.fixtures, vendor=args.vendor, model=args.model)
    )
    if not models:
        parser.error(f"no fixture models matched under {args.fixtures}")

    proxy = RedfishProxy()
    proxy.objecttype_cache = InMemoryCache(ttl_seconds=60)
    proxy.logger.setLevel(logging.WARNING)

    for model_dir in models:
        generate_for_model(
            proxy, model_dir.parent.name, str(model_dir), args.max_collection_sample
        )


if __name__ == "__main__":
    main()
