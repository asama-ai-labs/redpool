#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Clone a Redfish service and rewrite collection membership on disk."""

import json
import os
import sys
import argparse
import logging
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Set, List, Dict, Any, Optional

from redfish.rest.v1 import (
    BadRequestError,
    InvalidCredentialsError,
    JsonDecodingError,
    RetriesExhaustedError,
    ServerDownOrUnreachableError,
    SessionCreationError,
)

from redfish_snapshot.client import HttpClient
from redfish_snapshot.credentials import PasswordError, read_password
from redfish_snapshot.collections import fix_collections_in_dir
from redfish_snapshot.log_entries import trim_log_entries
from redfish_snapshot.postprocess import SECRET_ENV, sanitize_mockups, state_dir
from redfish_snapshot.sanitize import (
    RedfishSanitizer,
    collect_identifiers,
    sanitize_path,
    sanitize_redfish,
)


class RedfishCloner:  # pylint: disable=too-many-instance-attributes
    """Crawl a Redfish service and write a sanitized snapshot."""

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        host: str,
        username: str,
        password: str,
        output_path: str,
        exclude_prefixes: List[str] = None,
        max_parallel: int = 5,
        compact_json: bool = True,
        sanitize: bool = True,
        member_limit: int = 50,
        bmc_host_header: Optional[str] = None,
        show_tls_warnings: bool = False,
    ):
        self.base_url = f"https://{host}"
        self.username = username
        self.password = password
        self.output_path = output_path
        self.exclude_prefixes = exclude_prefixes or []
        self.visited_urls: Set[str] = set()
        self.skipped_urls: Set[str] = set()
        self.url_queue: asyncio.Queue = asyncio.Queue()
        self.max_parallel = max_parallel
        self.compact_json = compact_json
        self.sanitize = sanitize
        self.member_limit = member_limit
        self.bmc_host_header = bmc_host_header
        # Stable dirgroup* → dirgroupDUMMY-N assignments for this capture.
        self._resource_id_map: Dict[str, str] = {}
        # Real identifiers seen in raw responses, for the identifier pass after the clone.
        self.identifiers: Set[str] = set()

        self.output_dir = os.path.abspath(self.output_path)
        os.makedirs(self.output_dir, exist_ok=True)

        self.redfish_client = HttpClient(
            base_url=self.base_url,
            username=self.username,
            password=self.password,
            default_prefix="/redfish/v1",
            host_header=self.bmc_host_header,
            show_tls_warnings=show_tls_warnings,
        )

        logging.basicConfig(
            level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
        )
        self.logger = logging.getLogger(__name__)

    def connect(self):
        """Establish connection to the Redfish service."""
        try:
            self.redfish_client.login(auth="session")
            self.logger.info("Connected to %s", self.base_url)
        except Exception as e:
            self.logger.error("Failed to connect to %s: %s", self.base_url, e)
            raise

    def disconnect(self):
        """Close the Redfish session."""
        try:
            self.redfish_client.logout()
            self.logger.info("Disconnected from Redfish service")
        except (BadRequestError, RetriesExhaustedError, OSError, ValueError) as e:
            self.logger.error("Error during disconnect: %s", e)

    def should_exclude(self, url: str) -> bool:
        """Check if URL should be excluded based on exclude prefixes."""
        for prefix in self.exclude_prefixes:
            if url.startswith(prefix):
                self.logger.debug("Excluding %s (prefix %s)", url, prefix)
                return True
        return False

    DUMMY_FQDN = RedfishSanitizer.DUMMY_FQDN
    DUMMY_UUID = RedfishSanitizer.DUMMY_UUID
    DUMMY_MAC = RedfishSanitizer.DUMMY_MAC
    DUMMY_COMMON_NAME = RedfishSanitizer.DUMMY_COMMON_NAME

    def sanitize_data(self, data: Any, parent_key: Optional[str] = None) -> Any:
        """Sanitize using this capture's dirgroup map. Prefer :func:`sanitize_redfish`."""
        return sanitize_redfish(
            data, id_map=self._resource_id_map, parent_key=parent_key
        )

    def _inside_output_dir(self, file_path: str) -> bool:
        """True if *file_path* resolves to a location inside the output directory."""
        root = os.path.realpath(self.output_dir)
        target = os.path.realpath(file_path)
        return os.path.commonpath([root, target]) == root

    def save_response(self, url: str, response_data: Dict):
        """Save a response in the DMTF mockup layout: ``<out>/redfish/v1/<path>/index.json``."""
        url_for_path = url
        if self.sanitize:
            self.identifiers |= collect_identifiers(response_data)
            sanitized_data = self.sanitize_data(response_data)
            url_for_path = sanitize_path(url, id_map=self._resource_id_map)
        else:
            sanitized_data = response_data

        relative_path = url_for_path.split("?", 1)[0].strip("/")
        file_path = os.path.join(
            self.output_dir, *relative_path.split("/"), "index.json"
        )

        # The path comes from the BMC (@odata.id). Refuse anything that would be
        # written outside the output directory, before any directory is created.
        if not self._inside_output_dir(file_path):
            self.logger.warning(
                "Skipping response for %s: path escapes the output directory", url
            )
            return
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        try:
            with open(file_path, "w", encoding="utf-8") as handle:
                if self.compact_json:
                    json.dump(sanitized_data, handle, separators=(",", ":"))
                else:
                    json.dump(sanitized_data, handle, indent=4)
            self.logger.info("Saved response to %s", file_path)
        except (OSError, TypeError, ValueError) as e:
            self.logger.error("Failed to save response for %s: %s", url, e)

    def extract_odata_ids(self, data) -> Set[str]:
        """Recursively extract @odata.id values from the response, limited to first N items."""
        odata_ids = set()

        if isinstance(data, dict):
            # Limit processing to first N items
            items = list(data.items())
            limited_items = (
                items[: self.member_limit] if len(items) > self.member_limit else items
            )
            for key, value in limited_items:
                if key == "@odata.id":
                    odata_ids.add(value.rstrip("/"))
                elif isinstance(value, (dict, list)):
                    odata_ids.update(self.extract_odata_ids(value))
        elif isinstance(data, list):
            # Limit processing to first N items
            limited_data = (
                data[: self.member_limit] if len(data) > self.member_limit else data
            )
            for item in limited_data:
                if isinstance(item, (dict, list)):
                    odata_ids.update(self.extract_odata_ids(item))

        return odata_ids

    async def process_url(self, url: str):
        """Process a single URL and queue its children."""
        if (
            url in self.visited_urls
            or url in self.skipped_urls
            or self.should_exclude(url)
        ):
            return

        self.visited_urls.add(url)
        self.logger.info("Accessing: %s", url)

        try:
            response = await asyncio.to_thread(self.redfish_client.get, url)
            status = getattr(response, "status", None)
            if isinstance(status, int) and not 200 <= status < 300:
                # An error body is not a resource: saving it would make a mock serve it as one.
                self.logger.warning("Skipping %s: HTTP %s", url, status)
                self.visited_urls.discard(url)
                self.skipped_urls.add(url)
                return
            response_data = response.dict

            self.save_response(url, response_data)

            odata_ids = self.extract_odata_ids(response_data)
            for odata_id in odata_ids:
                if odata_id not in self.visited_urls and not self.should_exclude(
                    odata_id
                ):
                    await self.url_queue.put(odata_id)

        except (
            BadRequestError,
            InvalidCredentialsError,
            JsonDecodingError,
            RetriesExhaustedError,
            ServerDownOrUnreachableError,
            SessionCreationError,
            OSError,
            TypeError,
            ValueError,
            KeyError,
            AttributeError,
        ) as e:
            self.logger.error("Error accessing %s: %s", url, e)

    async def worker(self):
        """Worker coroutine that pulls URLs from the queue."""
        while True:
            try:
                url = await self.url_queue.get()
            except asyncio.CancelledError:
                break
            try:
                await self.process_url(url)
            finally:
                self.url_queue.task_done()

    async def traverse_redfish_api(self):
        """BFS traversal of the Redfish API with parallel workers."""
        await self.url_queue.put("/redfish/v1/")

        workers = [asyncio.create_task(self.worker()) for _ in range(self.max_parallel)]

        await self.url_queue.join()

        for w in workers:
            w.cancel()
        await asyncio.gather(*workers, return_exceptions=True)

    def metadata_json_path(self) -> str:
        """Path for metadata.json beside ``original/``, or inside the output directory."""
        out = Path(self.output_dir)
        if out.name == "original":
            return str(out.parent / "metadata.json")
        return str(out / "metadata.json")

    def generate_metadata(self):
        """Write collection metadata next to the `original/` tree (fixtures layout convention)."""
        urls = self.visited_urls
        if self.sanitize:
            urls = {
                sanitize_path(u, id_map=self._resource_id_map)
                for u in self.visited_urls
            }
        metadata = {
            # A UTC date only: local time of day and zone would identify the site.
            "collection_timestamp": datetime.now(timezone.utc).date().isoformat(),
            "collected_urls": list(sorted(urls)),
            "excluded_prefixes": self.exclude_prefixes,
            "compact_json": self.compact_json,
            "sanitize": self.sanitize,
        }

        metadata_path = self.metadata_json_path()
        os.makedirs(os.path.dirname(metadata_path), exist_ok=True)
        with open(metadata_path, "w", encoding="utf-8") as handle:
            json.dump(metadata, handle, indent=4)
        self.logger.info("Generated metadata at %s", metadata_path)


def main_fix_collections(args):
    """Rewrite collection JSON under the given paths so Members match files on disk."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    logger = logging.getLogger(__name__)

    total = 0
    for p in args.paths:
        path = Path(p).resolve()
        if not path.is_dir():
            logger.warning("Not a directory: %s", path)
            continue
        n = fix_collections_in_dir(
            path,
            dry_run=args.dry_run,
            compact_json=not args.pretty,
            logger=logger,
        )
        total += n
        if n:
            print(path)

    if args.dry_run and total:
        print(f"(dry-run: {total} file(s) would be updated)")
    elif total:
        print(f"Updated {total} collection file(s).")


def main_sanitize(args):
    """Sanitize DMTF-layout mockups in place, e.g. Redfish-Mockup-Creator output."""
    roots = [Path(p).resolve() for p in args.paths]
    missing = [str(r) for r in roots if not r.is_dir()]
    if missing:
        sys.exit(f"Not a directory: {', '.join(missing)}")
    changed, _, renamed = sanitize_mockups(roots)
    print(f"Sanitized {changed} document(s); renamed {renamed} path(s).")


def main_clone(args):
    """Capture a BMC Redfish tree, then align collection membership with saved files."""
    if args.trim_logs < 0:
        sys.exit("--trim-logs must be 0 or greater")
    output_path = args.output_path or os.path.join(
        "fixtures", args.vendor, args.model, "original"
    )
    try:
        password = read_password()
    except PasswordError as exc:
        sys.exit(str(exc))

    cloner = RedfishCloner(
        host=args.host,
        username=args.username,
        password=password,
        output_path=output_path,
        exclude_prefixes=args.exclude,
        max_parallel=args.parallel,
        compact_json=not args.pretty,
        sanitize=not args.no_sanitize,
        member_limit=args.member_limit,
        bmc_host_header=args.host_header,
        show_tls_warnings=args.tls_warnings,
    )

    try:
        cloner.connect()
        asyncio.run(cloner.traverse_redfish_api())
        cloner.generate_metadata()
        # Always fix collections after clone: with --member-limit we only fetch N members,
        # so Members and Members@odata.count must be updated to match what was actually saved.
        n = fix_collections_in_dir(
            Path(cloner.output_dir),
            dry_run=False,
            compact_json=cloner.compact_json,
            logger=cloner.logger,
        )
        if n:
            cloner.logger.info(
                "Fixed %d collection file(s) to match on-disk members", n
            )
        if cloner.sanitize and args.trim_logs > 0:
            # Before the identifier pass, so that pass recomputes etags on the
            # collections this shortens.
            removed, kept = trim_log_entries(
                Path(cloner.output_dir),
                max_varieties=args.trim_logs,
                indent=None if cloner.compact_json else 2,
            )
            cloner.logger.info(
                "Trimmed log entries: kept %d, removed %d", kept, removed
            )
        if cloner.sanitize:
            # Identifier pass: remove the real serials, MACs and names collected from the
            # raw responses from every value, key and path of the capture. The time
            # policy runs in the same pass when the secret is set.
            secret = os.environ.get(SECRET_ENV, "")
            mask_time = bool(secret) and not args.no_mask_time
            if mask_time:
                cloner.logger.info("Applying the time policy")
            elif not args.no_mask_time:
                cloner.logger.info("Time policy skipped: %s is not set", SECRET_ENV)
            sanitize_mockups(
                [Path(cloner.output_dir)],
                [Path(cloner.metadata_json_path())],
                log=cloner.logger.info,
                mask_time=mask_time,
                time_secret=secret.encode() if mask_time else None,
                state=state_dir(),
                extra_identifiers=cloner.identifiers,
            )
        print("\nRedfish data cloning complete!")
        print(f"Data saved to: {cloner.output_dir}")
        print(f"Metadata: {cloner.metadata_json_path()}")
    finally:
        cloner.disconnect()


def build_parser() -> argparse.ArgumentParser:
    """The command-line parser for clone, sanitize and fix-collections."""
    parser = argparse.ArgumentParser(
        description="Redfish Snapshot — capture and sanitize Redfish API from BMCs"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command")

    # clone
    clone_p = subparsers.add_parser("clone", help="Clone Redfish API from a BMC")
    clone_p.add_argument("--host", required=True, help="Redfish endpoint host")
    clone_p.add_argument(
        "--host-header",
        default=None,
        metavar="HOST",
        help=(
            "Value for the HTTP Host header on BMC requests "
            "(e.g. when connecting via IP or tunnel)"
        ),
    )
    clone_p.add_argument(
        "--username", required=True, help="Username for authentication"
    )
    clone_p.add_argument(
        "--tls-warnings",
        action="store_true",
        help=(
            "Show urllib3 warnings about unverified BMC certificates "
            "(hidden by default, because BMCs usually use self-signed ones)"
        ),
    )
    clone_p.add_argument(
        "--vendor",
        required=True,
        help="Vendor name (e.g., Dell, HPE, Lenovo, Supermicro)",
    )
    clone_p.add_argument(
        "--model", required=True, help="Model name (e.g., PowerEdge_R640)"
    )
    clone_p.add_argument(
        "--output-path",
        default=None,
        help="Override output directory (default: fixtures/<vendor>/<model>/original)",
    )
    clone_p.add_argument(
        "--exclude",
        nargs="+",
        default=[],
        help="URL prefixes to exclude (e.g., /redfish/v1/Managers/)",
    )
    clone_p.add_argument(
        "--parallel",
        type=int,
        default=5,
        help="Maximum number of parallel requests (default: 5)",
    )
    clone_p.add_argument(
        "--pretty", action="store_true", help="Pretty-print JSON (compact by default)"
    )
    clone_p.add_argument(
        "--no-sanitize",
        action="store_true",
        help="Disable sanitization of sensitive data, log trimming and the time policy",
    )
    clone_p.add_argument(
        "--trim-logs",
        type=int,
        default=20,
        metavar="N",
        help=(
            "Keep at most N distinct log entries in each collection (default: 20). "
            "0 keeps every entry the crawl saved."
        ),
    )
    clone_p.add_argument(
        "--no-mask-time",
        action="store_true",
        help=(
            "Do not shift timestamps. By default the time policy runs when "
            f"{SECRET_ENV} is set."
        ),
    )
    clone_p.add_argument(
        "--member-limit",
        type=int,
        default=50,
        help="Limit URL extraction to first N items per response (default: 50)",
    )
    clone_p.set_defaults(func=main_clone)

    # sanitize
    san_p = subparsers.add_parser(
        "sanitize",
        help="Sanitize existing mockup directories in place (any DMTF-layout mockup)",
    )
    san_p.add_argument("paths", nargs="+", help="Mockup directory path(s)")
    san_p.set_defaults(func=main_sanitize)

    # fix-collections
    fix_p = subparsers.add_parser(
        "fix-collections", help="Fix collection JSON to match on-disk members"
    )
    fix_p.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="Directory path(s) under which to fix (default: current dir)",
    )
    fix_p.add_argument(
        "--dry-run", action="store_true", help="Only report what would be changed"
    )
    fix_p.add_argument(
        "--pretty", action="store_true", help="Pretty-print JSON (default: compact)"
    )
    fix_p.set_defaults(func=main_fix_collections)
    return parser


def main():
    """Command-line entry point for clone, sanitize, and fix-collections."""
    # Default to "clone" when no subcommand given (backward compatibility)
    if len(sys.argv) > 1 and sys.argv[1] not in (
        "clone",
        "sanitize",
        "fix-collections",
        "--help",
        "-h",
    ):
        sys.argv.insert(1, "clone")

    parser = build_parser()
    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        return
    args.func(args)
