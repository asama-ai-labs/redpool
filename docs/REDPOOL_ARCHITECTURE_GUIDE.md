# Redpool Architecture Guide

This document explains how the project fits together and what each part is responsible for.

## What Redpool Is

Redpool is a normalization proxy for Redfish APIs.

At a high level:

- A Redfish client sends requests to Redpool instead of directly to the BMC.
- Redpool forwards or rewrites requests, fetches the original Redfish responses, normalizes them, and returns cleaned-up JSON.
- The goal is not to invent data. The goal is to make the same data more consistent, easier to consume, and more comparable across vendors and models.

Redpool is especially useful for:

- stabilizing vendor-specific Redfish payloads
- filling in obvious missing fields from related resources
- fixing naming inconsistencies
- rewriting broken or awkward paths
- smoothing over schema version differences

## Request path

A client request enters through the mitmproxy addon and `RedfishProxy`.

- Session paths (`skip_prefixes`, the SessionService) and the service root (`skip_paths`) are returned as the BMC sent them. Login and service discovery stay in the BMC's own shape.
- The proxy keeps one Redfish client per BMC and credential. Vendor and model come from the service root, then from the Systems collection once the client is authenticated.
- A vendor request rewrite may map the client's path onto the path the BMC actually serves. URIs in the response body are rewritten back.
- The proxy fetches that path. On a 404 it tries the reverse segment aliases, such as `PCIeDevices` and `PCIDevices`.
- The path becomes a registry pattern. Prefetch may call Redfish and write `ctx.prefetched`. The field map then builds the body. If normalization fails, the original body is returned.
- A vendor system expander may enrich a ComputerSystem after that.

Which normalizer runs is fixed at import time: `register_base`, then `register_resource` for a vendor, `register_collection` for the collection document, and `register_collection_override` when one vendor replaces that collection mapping. The details are under The Normalization Model.

Caches:

- GET bodies use `response:{base}:{credential}:{path}` and `response_ttl`. Paths in `non_cacheable_patterns` are not stored, and a request with its own query or headers is not served from this cache.
- Vendor, model, and hostname use `metadata:{base}` and `metadata_ttl`.
- Collection versus resource, while a URL is turned into a pattern, uses `objecttype:{base}:{path}` and `objecttype_ttl`.
- `ctx.prefetched` lasts for one request. Field maps read it after prefetch.

## Main Subprojects

### `redpool/`

The core Python proxy and normalization engine.

Important concepts:

- `RedfishProxy`: handles request interception, response rewriting, and normalization.
- `NormalizationContext`: the data bundle passed to normalizers.
- `ResourceNormalizer`: base contract for all normalizers.
- `prefetch`: the only phase allowed to make extra Redfish API calls.
- `field_map`: pure mapping logic that turns raw data into normalized output.
- `version_overrides`: optional exact-`@odata.type` overrides.

### Mock BMC: DMTF Redfish-Mockup-Server

`third_party/Redfish-Mockup-Server` (DMTF, BSD-3) serves a fixture model as a Redfish service. The fixtures use the DMTF mockup layout, so it needs no adapter.

This project is used to:

- serve the captured `fixtures/<vendor>/<model>/original/` trees
- provide deterministic Redfish responses for local runs and golden generation
- make it possible to compare direct-vs-redpool behavior without talking to real hardware

Why it matters:

- It is the source of truth for many test and golden-generation workflows.
- If a raw fixture is wrong or incomplete, the mock will faithfully reproduce that problem.

### `redfish-snapshot/`

Workspace package that captures a BMC Redfish tree into the DMTF mockup layout.

This project is used to:

- capture or clone Redfish payload trees
- preserve structure for later normalization and fixtures regeneration

Why it matters:

- It is part of how fixture data is created and refreshed.
- It is not the place to encode normalization rules; it is the source material that Redpool normalizes.

### `third_party/redfish-inventory-exporter/`

Go collector that scrapes Redfish and emits Prometheus metrics.

Important note:

- Treat this as an external consumer of Redpool-normalized data.
- It is intentionally not the main place for normalization logic.
- Use it mainly as a consumer and validation target.
- If a field can be normalized in Redpool instead of changing the collector, prefer that.

### `third_party/fishymetrics/`

Third-party metrics consumer used in the test matrix.

Important note:

- Treat this as an external tool.
- Keep its metric expectations in mind when changing shared fixture data.
- Prefer Redpool-side normalization when a change can improve its inputs without altering its schema.

### `scripts/`

Golden generation and testing helpers.

These scripts are the canonical way to:

- regenerate normalized fixture outputs
- run collector scrapes against mock Redfish data
- compare redpool vs direct behavior
- build test artifacts from the `original/` fixtures

### `fixtures/`

Fixture corpus and golden outputs.

Layout pattern:

- `original/` contains the raw captured Redfish tree
- `normalized/` contains redpool-normalized JSON outputs
- `redfish_inventory_exporter_*.prom` and `fishymetrics_*.prom` contain scrape outputs
- `redfish-snapshot` captures a BMC into `original/`; DMTF Redfish-Mockup-Server replays that tree as a Redfish service

## The Normalization Model

Normalization is intentionally split into two phases.

### Phase 1: `prefetch`

Prefetch may:

- make Redfish API calls
- walk linked resources
- cache intermediate results in `ctx.prefetched`

Prefetch should:

- stay vendor-aware only when necessary
- avoid expensive recursion unless the data benefit is obvious
- never mutate raw response data in place

### Phase 2: `field_map`

The field map must be pure.

That means:

- no API calls
- no side effects
- only use `ctx.data`, `ctx.prefetched`, and configuration flags

This separation matters because it keeps normalization predictable and testable.

`version_overrides()` keys are exact `@odata.type` strings. Prefer the base field map. Use an override only when that schema version needs a different shape.

Registration happens at import time. `register_base` comes first, then `register_resource` for a vendor, and `register_collection` for the collection. A vendor can replace a collection's mapping with `register_collection_override`.

Vendor keys are canonicalized by `canonical_server_vendor()` in `normalizers/vendor_id.py`, both when a normalizer registers and when the proxy looks one up. `Dell Inc.` and `Dell` reach the same normalizers, as do `Hpe` and `HPE`. A vendor with no registered override gets the base normalizer. Package `__init__.py` files import the resource modules so the registry is populated before the proxy serves traffic. Path patterns are the slash-separated collection segments the proxy resolver uses (`Systems/Processors`, `Chassis/Drives`). A typo silently skips normalization.

## Normalizer rules

### One `@odata.type` per resource

Each resource has one schema version. Redpool writes that version as a string literal in the field map. Older payloads of the same resource migrate to it. The version is not chosen from the BMC payload, from which properties are filled, or from the BMC version string.

`#Port` and `#NetworkPort` are different resources. A Port document is `#Port.v1_20_0.Port`. A NetworkPort document is `#NetworkPort.v1_4_3.NetworkPort`.

The field map is that version's property set. Every standard name in the map exists in that DMTF schema. When an older BMC omits a mapped property, copy the value from another standard field, a linked resource, or OEM when the payload has it. Otherwise emit `""`, `{}`, or `[]`. Use `null` only when the schema type rejects an empty value, such as an enum. Do not fabricate a reading. Inventory, topology, or telemetry with no standard property goes in `Oem.Redpool`.

### The base map is what the captures share

The base field map is the shape the fixtures have in common. A property that no model sends is absent from that map. It is not defaulted to `[]` because the key happens to be optional in the schema.

When one vendor sends a value under the wrong name or place, map it in that vendor's module for the resource. The shared `base.py` does not branch on whether the payload contains the key.

### One vendor stays in that vendor's module

A rule that applies to a single vendor is that vendor's `field_map`, `prefetch`, `version_overrides`, or the request-rewrite hook registered beside it. The shared `base.py` holds behavior that more than one vendor shares.

A client path the BMC does not serve is handled by that rewrite hook. HPE `Systems/PCIeDevices/{id}` is served from `Chassis/PCIeDevices/{id}` inside `normalizers/systems/pci_devices/hpe.py`, which merges the chassis device and evaluates the HPE field map.

### The proxy does not normalize

`redpool/proxy.py` fetches, rewrites URLs, and calls the registered normalizer. Vendor branches, property fixes, enum mapping, OEM relocation, and schema cleanup stay in `normalizers/`. `redfish-inventory-exporter` stays a generic scrape. Fishymetrics is a third-party tree: confirm before editing it, and prefer a normalizer when the raw payload already has the data.

If redfish-inventory-exporter metrics look wrong — empty series, `Unknown` labels, zeros, or a missing rollup — treat that first as a normalization gap. The payload may omit the field, use a vendor shape, or need canonicalization before gofish sees it.

## Common Data Sources

Redpool normalizers often rely on data from:

- the resource itself
- its `Links`
- `Oem` sections
- sibling collections such as Memory, Storage, PCIeDevices, or Thermal
- BIOS resources and registries where vendors hide useful inventory data

Examples of good cross-resource use:

- processor part number and speed from BIOS/OEM or related processor records
- memory identifiers from BIOS attributes when DIMM records are incomplete
- PCIe device context from function/device links
- storage controller association from parent storage resources

## Working With Goldens

The golden generation scripts are the authoritative way to validate behavior. Run them with `uv run` from the repository root. Do not hand-edit `redfish_inventory_exporter_*.prom` or `fishymetrics_*.prom`. If the generated output is wrong, change the normalizer and regenerate.

Typical workflow:

- regenerate goldens after a normalization change, both the direct and redpool files when the collector behavior is part of the comparison
- compare output against the expected raw-vs-normalized behavior
- keep the redfish-inventory-exporter runs focused by disabling unrelated collectors when useful

```bash
uv run python scripts/generate_redfish_inventory_exporter_golden.py
uv run python scripts/generate_redfish_inventory_exporter_golden.py --no-proxy
uv run python scripts/generate_fishymetrics_golden.py
uv run python scripts/generate_fishymetrics_golden.py --no-proxy
```

`--model Vendor/Model` limits a run to one model.

Useful options:

- disable `logs` when testing inventory and health normalization
- disable `bios` when the change is unrelated to BIOS-derived values

When a generated file contains only process metrics, the manual scrape is in [GOLDEN_FILES.md](GOLDEN_FILES.md).

See also:

- [SCHEMA_VALIDATION.md](SCHEMA_VALIDATION.md)
- [REDFISH_INVENTORY_EXPORTER_DIRECT_VS_REDPOOL.md](REDFISH_INVENTORY_EXPORTER_DIRECT_VS_REDPOOL.md)
- [FISHYMETRICS_DIRECT_VS_REDPOOL.md](FISHYMETRICS_DIRECT_VS_REDPOOL.md)
- [GOLDEN_FILES.md](GOLDEN_FILES.md)
- [REDPOOL_CONTRIBUTOR_GUIDE.md](REDPOOL_CONTRIBUTOR_GUIDE.md)
