# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""HPE Storage normalizer and request rewrites for SmartStorage-only BMCs."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from redpool.redfish_client import redfish_get_json, release_rest_response

from ..._shared.system_chassis import begin_system_chassis_memo
from ...apply import normalize_resource
from ...request_rewrites import (
    RequestRewriteRule,
    RewriteCall,
    register_request_rewrite,
    rewrite_response_body,
)
from ...types import NormalizationContext
from ._hpe_smartstorage import (
    native_controller,
    native_member,
    native_storage_path,
    safe_redfish_get,
    DEFAULT_HPE_CHASSIS,
    build_battery_collection,
    build_battery_resource,
    build_drive_resource,
    build_storage_collection_from_array_controllers,
    build_storage_controller_resource,
    build_storage_resource,
    build_volume_resource,
    canonical_storage_path,
    collection_body,
    fetch_hpe_storage_related,
    hpe_batteries_from_chassis,
    hpe_chassis_path,
    hpe_smartstorage_path,
    hpe_storage_request_parts,
    member_links,
    storage_id_from_array_controller,
)
from .base import BaseStorageNormalizer
from .volumes.base import BaseVolumeNormalizer

# SmartStorage presence, keyed by BMC (base URL) and system id. A definitive answer
# (200 or 404) is cached for _SMARTSTORAGE_PRESENCE_TTL seconds. Anything else (a
# timeout, 401, 5xx) is not cached, so one failed probe cannot change how a BMC is
# normalized for the rest of the process.
_SMARTSTORAGE_PRESENCE_TTL = 3600.0
_SMARTSTORAGE_PRESENT: Dict[Tuple[str, str], Tuple[bool, float]] = {}
_SMARTSTORAGE_PRESENT_LOCK = threading.Lock()


def _bmc_key(client: Any) -> Optional[str]:
    """Identity of the BMC behind *client* (its base URL), or None when unknown."""
    try:
        base = client.get_base_url()
    except Exception:  # noqa: BLE001
        return None
    return base if isinstance(base, str) and base else None


def _probe_smartstorage(client: Any, system_id: str) -> Optional[bool]:
    """Ask the BMC whether ``Systems/{id}/SmartStorage`` exists. None when it cannot say."""
    response = None
    try:
        response = client.get(hpe_smartstorage_path(system_id))
        status = int(getattr(response, "status", 0) or 0)
        if status == 404:
            return False
        if status != 200:
            return None
        data = response.dict
        return isinstance(data, dict) and bool(data) and "error" not in data
    except Exception:  # noqa: BLE001
        return None
    finally:
        release_rest_response(response)


def _hpe_smartstorage_present(client: Any, system_id: str) -> bool:
    """Return True when ``Systems/{id}/SmartStorage`` exists (Gen10); Gen11 is native-only."""
    if client is None:
        return False
    bmc = _bmc_key(client)
    if bmc is None:
        # No identity to cache under: ask the BMC and do not remember the answer.
        return bool(_probe_smartstorage(client, system_id))
    key = (bmc, system_id)
    with _SMARTSTORAGE_PRESENT_LOCK:
        entry = _SMARTSTORAGE_PRESENT.get(key)
    if entry is not None and entry[1] > time.monotonic():
        return entry[0]
    answer = _probe_smartstorage(client, system_id)
    if answer is None:
        return False
    with _SMARTSTORAGE_PRESENT_LOCK:
        _SMARTSTORAGE_PRESENT[key] = (
            answer,
            time.monotonic() + _SMARTSTORAGE_PRESENCE_TTL,
        )
    return answer


def _is_native_hpe_storage_payload(data: Dict[str, Any]) -> bool:
    """True when the body is already a DMTF Storage resource (not an ArrayController)."""
    otype = data.get("@odata.type")
    if (
        isinstance(otype, str)
        and "Storage." in otype
        and "ArrayController" not in otype
    ):
        return True
    if isinstance(data.get("Drives"), list) and isinstance(
        data.get("Controllers"), dict
    ):
        return True
    return False


class HPEStorageNormalizer(BaseStorageNormalizer):
    """Normalize an HPE SmartStorage array controller as a Redfish Storage resource.

    When the BMC already exposes native ``Storage`` (e.g. Gen11), pass through via
    the base field map — do not rewrite as SmartStorage.
    """

    def prefetch(self, ctx: NormalizationContext) -> None:
        parts = ctx.odata_id.split("/Systems/", 1)
        if len(parts) != 2 or "/Storage/" not in parts[1]:
            return
        system_id = parts[1].split("/", 1)[0]
        if not _hpe_smartstorage_present(ctx.client, system_id):
            return
        if _is_native_hpe_storage_payload(ctx.data):
            return
        storage_id = storage_id_from_array_controller(ctx.data)
        if ctx.client is not None:
            ctx.prefetched.update(
                fetch_hpe_storage_related(ctx.client, system_id, storage_id)
            )

    def normalized_body_from_prefetch(
        self,
        ctx: NormalizationContext,
    ) -> Optional[Dict[str, Any]]:
        parts = ctx.odata_id.split("/Systems/", 1)
        if len(parts) != 2 or "/Storage/" not in parts[1]:
            return None
        system_id = parts[1].split("/", 1)[0]
        if not _hpe_smartstorage_present(ctx.client, system_id):
            return None
        if _is_native_hpe_storage_payload(ctx.data):
            return None
        return build_storage_resource(
            ctx.odata_id,
            system_id,
            ctx.data,
            disk_collection=ctx.prefetched.get("drives"),
        )


def _hpe_storage_matches(path: str) -> bool:
    parsed = hpe_storage_request_parts(path)
    if parsed is None:
        return False
    _, parts = parsed
    if not parts:
        return True
    if len(parts) == 1:
        return True
    if len(parts) in (2, 3) and parts[1] in ("Drives", "Volumes", "Controllers"):
        return True
    if len(parts) in (4, 5) and parts[1] == "Controllers" and parts[3] == "Batteries":
        return True
    return False


def _hpe_storage_backend_path(path: str, chassis: Optional[str] = None) -> str:
    """Backend path; ``chassis`` (Battery requests) defaults to Chassis/1 only when no client resolved it."""
    parsed = hpe_storage_request_parts(path)
    if parsed is None:
        return path
    system_id, parts = parsed
    if not parts:
        return hpe_smartstorage_path(system_id, "ArrayControllers")
    storage_id = parts[0]
    if len(parts) == 1:
        return hpe_smartstorage_path(system_id, "ArrayControllers", storage_id)
    kind = parts[1]
    if kind == "Drives":
        base = hpe_smartstorage_path(
            system_id, "ArrayControllers", storage_id, "DiskDrives"
        )
        return "/".join([base, *parts[2:]])
    if kind == "Volumes":
        base = hpe_smartstorage_path(
            system_id, "ArrayControllers", storage_id, "LogicalDrives"
        )
        return "/".join([base, *parts[2:]])
    if kind == "Controllers":
        if len(parts) >= 4 and parts[3] == "Batteries":
            return chassis or DEFAULT_HPE_CHASSIS
        if len(parts) == 2:
            return hpe_smartstorage_path(system_id, "ArrayControllers")
        return hpe_smartstorage_path(system_id, "ArrayControllers", parts[2])
    return path


def _hpe_storage_response_rewrite(
    path: str, chassis: Optional[str] = None
) -> Tuple[str, str]:
    parsed = hpe_storage_request_parts(path)
    if parsed is None:
        return path, path
    system_id, parts = parsed
    if not parts:
        return (
            hpe_smartstorage_path(system_id, "ArrayControllers"),
            f"/redfish/v1/Systems/{system_id}/Storage",
        )
    storage_id = parts[0]
    if len(parts) == 1:
        return (
            hpe_smartstorage_path(system_id, "ArrayControllers", storage_id),
            canonical_storage_path(system_id, storage_id),
        )
    if parts[1] == "Drives":
        return (
            hpe_smartstorage_path(
                system_id, "ArrayControllers", storage_id, "DiskDrives"
            ),
            canonical_storage_path(system_id, storage_id, "Drives"),
        )
    if parts[1] == "Volumes":
        return (
            hpe_smartstorage_path(
                system_id, "ArrayControllers", storage_id, "LogicalDrives"
            ),
            canonical_storage_path(system_id, storage_id, "Volumes"),
        )
    if parts[1] == "Controllers":
        if len(parts) >= 4 and parts[3] == "Batteries":
            return (chassis or DEFAULT_HPE_CHASSIS, path.rstrip("/"))
        return (
            hpe_smartstorage_path(system_id, "ArrayControllers"),
            canonical_storage_path(system_id, storage_id, "Controllers"),
        )
    return path, path


def _hpe_storage_resolve_backend(client: Any, path: str) -> Tuple[str, str, str]:
    """Use SmartStorage rewrite only when SmartStorage exists; else passthrough native Storage."""
    parsed = hpe_storage_request_parts(path)
    if parsed is None:
        return path, path, path
    system_id, _parts = parsed
    if not _hpe_smartstorage_present(client, system_id):
        return path, path, path
    begin_system_chassis_memo()
    chassis = hpe_chassis_path(client, system_id)
    backend = _hpe_storage_backend_path(path, chassis)
    from_prefix, to_prefix = _hpe_storage_response_rewrite(path, chassis)
    return backend, from_prefix, to_prefix


def _native_controller_identifiers(
    client: Any,
    system_id: str,
    array_controller: Dict[str, Any],
) -> list:
    """Copy Identifiers from the native Storage controller when SmartStorage omits them.

    Gen10 serves inventory through ArrayControllers, which have no durable name.
    The same adapter's NAA is on Systems/{id}/Storage/{id}/Controllers/{id}.
    """
    if client is None or not system_id:
        return []
    model = array_controller.get("Model")
    serial = array_controller.get("SerialNumber")
    if isinstance(serial, str):
        serial = serial.strip()
    collection = safe_redfish_get(client, f"/redfish/v1/Systems/{system_id}/Storage")
    found: list = []
    for member in collection.get("Members") or []:
        if not isinstance(member, dict):
            continue
        storage_path = member.get("@odata.id")
        if not storage_path:
            continue
        storage = safe_redfish_get(client, storage_path)
        controllers_link = storage.get("Controllers") or {}
        controllers_path = (
            controllers_link.get("@odata.id")
            if isinstance(controllers_link, dict)
            else None
        )
        if not controllers_path:
            continue
        controllers = safe_redfish_get(client, controllers_path)
        for controller_member in controllers.get("Members") or []:
            if not isinstance(controller_member, dict):
                continue
            controller_path = controller_member.get("@odata.id")
            if not controller_path:
                continue
            controller = safe_redfish_get(client, controller_path)
            identifiers = controller.get("Identifiers") or []
            if not identifiers:
                continue
            controller_serial = controller.get("SerialNumber")
            if isinstance(controller_serial, str):
                controller_serial = controller_serial.strip()
            if (model and controller.get("Model") == model) or (
                serial and controller_serial == serial
            ):
                return identifiers
            found.append(identifiers)
    if len(found) == 1:
        return found[0]
    return []


def _volume_member_id(member: Dict[str, Any]) -> Optional[str]:
    """Return a real volume id. ``Capabilities`` is the collection capability object."""
    oid = member.get("@odata.id")
    leaf = ""
    if isinstance(oid, str) and oid.strip():
        leaf = oid.rstrip("/").split("/")[-1]
    if not leaf:
        raw = member.get("Id")
        if isinstance(raw, str):
            leaf = raw.strip()
    if not leaf or leaf.casefold() == "capabilities":
        return None
    return leaf


def _is_hpe_logical_drive(body: Dict[str, Any]) -> bool:
    otype = body.get("@odata.type")
    return (
        isinstance(otype, str) and "LogicalDrive" in otype and "Collection" not in otype
    )


def _extra_native_volume_members(
    client: Any,
    system_id: str,
    storage_id: str,
    seen: Set[str],
) -> List[Dict[str, str]]:
    """Native volumes that SmartStorage LogicalDrives does not list."""
    native = native_storage_path(client, system_id, storage_id)
    if not native:
        return []
    collection = safe_redfish_get(client, f"{native}/Volumes")
    canonical = canonical_storage_path(system_id, storage_id, "Volumes")
    extra: List[Dict[str, str]] = []
    for member in collection.get("Members") or []:
        if not isinstance(member, dict):
            continue
        volume_id = _volume_member_id(member)
        if not volume_id or volume_id in seen:
            continue
        seen.add(volume_id)
        extra.append({"@odata.id": f"{canonical}/{volume_id}"})
    return extra


def _served_native_volume(
    client: Any,
    path: str,
    system_id: str,
    storage_id: str,
    volume_id: str,
) -> Optional[Dict[str, Any]]:
    """Return the native ``#Volume`` when this id is not a SmartStorage logical drive."""
    native = native_storage_path(client, system_id, storage_id)
    if not native:
        return None
    body = safe_redfish_get(client, f"{native}/Volumes/{volume_id}")
    otype = body.get("@odata.type")
    if not isinstance(otype, str) or not otype.startswith("#Volume."):
        return None
    canonical = canonical_storage_path(system_id, storage_id)
    rewritten = rewrite_response_body(body, native, canonical)
    if not isinstance(rewritten, dict):
        return None
    rewritten["@odata.id"] = path.rstrip("/")
    links = rewritten.get("Links")
    if isinstance(links, dict):
        rewritten["Links"] = {
            key: value for key, value in links.items() if not str(key).startswith("@")
        }
    ctx = NormalizationContext(
        data=rewritten,
        client=None,
        logger=logging.getLogger("redpool.hpe.storage"),
        vendor="HPE",
        resource_path=path.rstrip("/"),
    )
    served = normalize_resource(BaseVolumeNormalizer(), ctx)
    return served if isinstance(served, dict) else None


def _fetch_volume_data_drives(
    client: Any, system_id: str, storage_id: str, volume_id: str
) -> Dict[str, Any]:
    return redfish_get_json(
        client,
        hpe_smartstorage_path(
            system_id,
            "ArrayControllers",
            storage_id,
            "LogicalDrives",
            volume_id,
            "DataDrives",
        ),
    )


def _hpe_storage_after_200_merge(call: RewriteCall, body: Any) -> Any:
    client, path, backend_path = call.client, call.path, call.backend_path
    from_prefix, to_prefix = call.from_prefix, call.to_prefix
    if not isinstance(body, dict):
        return body
    parsed = hpe_storage_request_parts(path)
    if parsed is None:
        return body
    system_id, parts = parsed
    if not _hpe_smartstorage_present(client, system_id):
        return body
    if backend_path.rstrip("/") == path.rstrip("/"):
        return body

    if not parts:
        return build_storage_collection_from_array_controllers(
            path.rstrip("/"), system_id, body
        )

    storage_id = parts[0]
    if len(parts) == 1:
        related = fetch_hpe_storage_related(client, system_id, storage_id)
        return build_storage_resource(
            path.rstrip("/"),
            system_id,
            body,
            disk_collection=related.get("drives"),
        )

    kind = parts[1]
    canonical_base = canonical_storage_path(system_id, storage_id, kind)
    if kind == "Drives":
        if len(parts) == 2:
            members = member_links(body, from_prefix, to_prefix)
            return collection_body(
                path.rstrip("/"),
                members,
                "DriveCollection",
                "Collection of Drives",
                "/redfish/v1/$metadata#DriveCollection.DriveCollection",
                "#DriveCollection.DriveCollection",
            )
        native = native_member(client, system_id, storage_id, "Drives", parts[2])
        return build_drive_resource(path.rstrip("/"), body, native=native)

    if kind == "Volumes":
        if len(parts) == 2:
            members = member_links(body, from_prefix, to_prefix)
            seen: Set[str] = set()
            for member in members:
                volume_id = _volume_member_id(member)
                if volume_id:
                    seen.add(volume_id)
            members.extend(
                _extra_native_volume_members(client, system_id, storage_id, seen)
            )
            return collection_body(
                path.rstrip("/"),
                members,
                "VolumeCollection",
                "Collection of Volumes",
                "/redfish/v1/$metadata#VolumeCollection.VolumeCollection",
                "#VolumeCollection.VolumeCollection",
            )
        volume_id = parts[2]
        if not _is_hpe_logical_drive(body):
            native = _served_native_volume(
                client, path, system_id, storage_id, volume_id
            )
            if native is not None:
                return native
        return build_volume_resource(
            path.rstrip("/"),
            body,
            data_drives=_fetch_volume_data_drives(
                client, system_id, storage_id, volume_id
            ),
            system_id=system_id,
            storage_id=storage_id,
            native=native_member(client, system_id, storage_id, "Volumes", volume_id),
        )

    if kind == "Controllers":
        if len(parts) >= 4 and parts[3] == "Batteries":
            batteries = hpe_batteries_from_chassis(body)
            if len(parts) == 4:
                return build_battery_collection(path.rstrip("/"), body)
            try:
                index = int(parts[4]) - 1
            except (ValueError, IndexError):
                index = -1
            if index < 0 or index >= len(batteries):
                return {}
            return build_battery_resource(path.rstrip("/"), batteries[index])

        if len(parts) == 2:
            member_id = storage_id
            members = [{"@odata.id": f"{canonical_base}/{member_id}"}]
            return collection_body(
                path.rstrip("/"),
                members,
                "StorageControllerCollection",
                "Collection of Storage Controllers",
                "/redfish/v1/$metadata#StorageControllerCollection.StorageControllerCollection",
                "#StorageControllerCollection.StorageControllerCollection",
            )
        chassis = redfish_get_json(client, hpe_chassis_path(client, system_id))
        identifiers = body.get("Identifiers") if isinstance(body, dict) else None
        if not identifiers:
            identifiers = _native_controller_identifiers(client, system_id, body)
        return build_storage_controller_resource(
            path.rstrip("/"),
            body,
            battery_count=len(hpe_batteries_from_chassis(chassis)),
            system_id=system_id,
            storage_id=storage_id,
            identifiers=identifiers or [],
            native=native_controller(client, system_id, storage_id),
        )

    return body


def _hpe_storage_on_backend_error(
    call: RewriteCall, status: int
) -> Optional[Tuple[Dict[str, Any], int]]:
    """Serve a native Volume when SmartStorage has no logical drive at this id."""
    client, path = call.client, call.path
    parsed = hpe_storage_request_parts(path)
    if parsed is None:
        return None
    system_id, parts = parsed
    if len(parts) < 3 or parts[1] != "Volumes":
        return None
    if not _hpe_smartstorage_present(client, system_id):
        return None
    body = _served_native_volume(client, path, system_id, parts[0], parts[2])
    if body is None:
        return None
    return body, 200


register_request_rewrite(
    RequestRewriteRule(
        vendor="HPE",
        matches=_hpe_storage_matches,
        get_backend_path=_hpe_storage_backend_path,
        get_response_rewrite=_hpe_storage_response_rewrite,
        resolve_backend=_hpe_storage_resolve_backend,
        on_backend_error=_hpe_storage_on_backend_error,
        after_200_merge=_hpe_storage_after_200_merge,
    )
)
