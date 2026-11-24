# Adding a vendor or fixing a vendor's output

This is the walkthrough for a person. It covers a new vendor and a change to an existing one. [REDPOOL_CONTRIBUTOR_GUIDE.md](REDPOOL_CONTRIBUTOR_GUIDE.md) holds the project rules and is also read by LLM tools. Start here.

## How Redpool picks a vendor

Redpool reads the vendor from the BMC's ServiceRoot: `Vendor` when it is there, otherwise the first key under `Oem`. BMCs spell the same maker several ways (`Dell` and `Dell Inc.`, `HPE` and `Hpe`, `Intel` and `Intel Corporation`). Every lookup goes through `canonical_server_vendor()` in [normalizers/vendor_id.py](../normalizers/vendor_id.py), so one canonical name reaches one set of normalizers.

| BMC sends | Canonical key |
|---|---|
| `Dell`, `Dell Inc.` | `Dell` |
| `HPE`, `Hpe`, `Hewlett Packard Enterprise` | `HPE` |
| `Lenovo` | `Lenovo` |
| `Supermicro`, `Super Micro Computer, Inc.` | `Supermicro` |
| `Intel`, `Intel Corporation` | `Intel` |
| anything else | the string itself, trimmed |

Always register under the canonical key. `register_resource` canonicalizes what you pass, and it raises if that vendor already has a different normalizer class for the same path. A vendor that has no override for a resource gets the base normalizer.

## Pick the extension point

Most vendor work is the first row. Use a later row only when the first cannot express the change.

| The BMC's problem | Extension point | Where it lives |
|---|---|---|
| A field is missing, misnamed, or in the wrong place (including `Oem`) | Resource field map and `prefetch` | `normalizers/<area>/<resource>/<vendor>.py`, registered with `register_resource` |
| A collection's `Members` need changing (blank links, id-only rows) | Collection override | `register_collection_override(pattern, vendor, mapping)` next to the resource |
| The resource is served at a different URL than a standard client asks for | Request rewrite | `RequestRewriteRule` in the vendor module, registered with `register_request_rewrite` |
| A path segment is renamed on every BMC (`PCIDevices` for `PCIeDevices`) | URL segment rewrite | `SEGMENT_REWRITES` in [normalizers/url_rewrites.py](../normalizers/url_rewrites.py). Global aliases only. |
| A ComputerSystem response needs data that lives in other resources | System expander | `register_system_response_expander(vendor, fn)` in the vendor module |

Keep each rule next to the vendor module that needs it. Do not add vendor branches to `redpool/proxy.py` or to a shared `base.py`.

## Walkthrough: fix one resource for one vendor

The example is a vendor `Acme` whose Drive reports its predicted failure under `Oem.Acme` and leaves the standard `FailurePredicted` empty. Real code to copy from:

- A small field override: [normalizers/systems/storage/drives/intel.py](../normalizers/systems/storage/drives/intel.py).
- Oem promotion into `Oem.Redpool`: [normalizers/chassis/drives/dell.py](../normalizers/chassis/drives/dell.py).
- Collection override: [normalizers/systems/ethernet_interfaces/hpe.py](../normalizers/systems/ethernet_interfaces/hpe.py).
- Request rewrite: [normalizers/systems/pci_devices/hpe.py](../normalizers/systems/pci_devices/hpe.py).

### 1. Get a fixture

Capture a lab or test BMC with `redfish-snapshot` and add it under `fixtures/Acme/<Model>/original/`. `fixtures/` is the [redpool-fixtures](https://github.com/asama-ai-labs/redpool-fixtures) submodule, so the capture goes in a pull request there. See [FIXTURES.md](FIXTURES.md) and "Adding a new model" in the contributor guide. Sanitize it before it leaves your machine.

### 2. Name the vendor

If `ServiceRoot.Vendor` for your BMC is not already in `_SERVER_VENDOR_ALIASES`, add its spellings to that table in [normalizers/vendor_id.py](../normalizers/vendor_id.py), and add a case to `tests/test_vendor_registry.py`. A vendor you leave out still works when the string you register matches what the BMC sends, but it will miss any other spelling.

### 3. Find the gap

Generate the goldens for the new model and compare the direct scrape with the one through Redpool (commands are in the contributor guide). Fix only a difference whose data is in the capture. Never invent a value.

### 4. Write the vendor normalizer

Subclass the resource's base normalizer and change only the keys that differ:

```python
# normalizers/chassis/drives/acme.py
from typing import Any, Dict

from ...types import NormalizationContext
from .base import BaseChassisDriveNormalizer


def _acme_failure_predicted(ctx: NormalizationContext) -> Any:
    fp = ctx.data.get("FailurePredicted")
    if isinstance(fp, bool):
        return fp
    return (ctx.data.get("Oem", {}).get("Acme", {}) or {}).get("PredictFail", fp)


class AcmeChassisDriveNormalizer(BaseChassisDriveNormalizer):
    def field_map(self) -> Dict[str, Any]:
        mapping = super().field_map()
        mapping["FailurePredicted"] = _acme_failure_predicted
        return mapping
```

Then register it in the package `__init__.py`, in the order base, then vendors, then collection:

```python
register_base("Chassis/Drives", BaseChassisDriveNormalizer())
register_resource("Chassis/Drives", "Acme", AcmeChassisDriveNormalizer())
register_collection("Chassis/Drives", COLLECTION_MAPPING)
```

Rules for the field map:

- It is pure. It reads only `ctx.data` and `ctx.prefetched`. A call to the BMC belongs in `prefetch(ctx)`, which writes only to `ctx.prefetched`.
- Name functions that take more than a line. Do not write a long lambda.
- Do not set `@odata.type` from the payload. Each resource has one fixed version, written as a string literal in its base field map.
- When the data has no standard property, put it in `Oem.Redpool` and leave the BMC's own `Oem` alone. See [REDPOOL_OEM_SCHEMA.md](REDPOOL_OEM_SCHEMA.md).

A path pattern is the slash-separated collection names the proxy builds (`Chassis/Drives`, `Systems/Storage/Drives`). A typo does not fail. It silently skips normalization, so check the pattern against an existing `__init__.py`.

### 5. Collections, URLs, expanders

- A collection override is the complete mapping for that vendor. Build it from the base one: `{**COLLECTION_MAPPING, "Members": my_members_fn}`, then `register_collection_override("Systems/EthernetInterfaces", "Acme", MAPPING)`.
- A request rewrite is for a resource that sits at a different URL on this BMC. Put the `RequestRewriteRule` and its helpers in the vendor module. The proxy calls the hooks without knowing the vendor.
- A system expander returns the (possibly changed) ComputerSystem body. It decides itself whether the response applies.

### 6. Prove it

```bash
uv run python scripts/generate_normalized_outputs.py --vendor Acme --model <Model>
uv run python scripts/validate_redfish_schema.py --vendor Acme --model <Model>
uv run python scripts/generate_redfish_inventory_exporter_golden.py --model Acme/<Model>
uv run python scripts/generate_redfish_inventory_exporter_golden.py --no-proxy --model Acme/<Model>
uv run python scripts/generate_fishymetrics_golden.py --model Acme/<Model>
uv run python scripts/generate_fishymetrics_golden.py --no-proxy --model Acme/<Model>
uv run pytest
uv run ruff check . && uv run ruff format --check . && uv run mypy redpool
```

Then regenerate every other vendor's outputs once (`generate_normalized_outputs.py` with no filter). A change to a base normalizer or the registry must leave them unchanged. Never edit a `.prom` file by hand. Always regenerate it with the scripts above.

Add a unit test for the rule next to the existing `tests/test_*.py` files. The fixtures show the output is stable. The test shows why.

## Where a rule belongs

- **One vendor:** that vendor's module. This holds even when it is small.
- **Two or more vendors:** `base.py`, or `normalizers/_shared/` when several resources share it.
- **Never:** `redpool/`, the collectors, or `third_party/` (ask first).

If you are about to write `if vendor == "X"` in a shared file, stop. Register a vendor normalizer instead.

## Submitting

Follow [CONTRIBUTING.md](../CONTRIBUTING.md). The pull request template asks for the regenerated outputs, the matching redpool-fixtures pull request, and the checks above.
