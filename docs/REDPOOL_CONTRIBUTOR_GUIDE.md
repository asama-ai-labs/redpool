# Redpool Contributor and LLM Guide

This guide is for contributors and for LLMs that generate or edit code in this repository. For a step-by-step vendor walkthrough written for people, read [ADDING_A_VENDOR.md](ADDING_A_VENDOR.md) first.

## Working Rules

### Prefer normalization over collector changes

If the raw fixture already contains the data, normalize it in Redpool.

Only change collectors when:

- the source data truly does not exist in the original Redfish payload
- the metric schema itself must change
- a consumer bug cannot be solved any other way

### Keep changes narrow

Make the smallest edit that solves the inconsistency.

Good changes:

- canonicalize a vendor string
- trim a noisy suffix from a name
- move a derived value from one field to another
- normalize a label value for stability

Bad changes:

- redesigning a collector just to compensate for a missing normalizer
- inventing data that the source does not provide
- broad schema changes unless they are explicitly requested

### Check the raw data first

Before implementing a fix, inspect:

- the relevant `original/` fixture
- the current `normalized/` JSON
- the current golden scrape output

This is the quickest way to tell whether the issue is:

- a missing source field
- a dropped normalization field
- a naming inconsistency
- a collector-only behavior difference

## What to Normalize

### Good candidates

Use Redpool for values that are:

- clearly recoverable from the source data
- noisy but semantically obvious
- vendor-specific spellings of the same concept
- duplicated across multiple resources

Examples:

- `Dell Inc.` -> `Dell`
- `Hpe` -> `HPE`
- trailing whitespace in memory part numbers
- PCIe names with trailing bus/device/function text
- derived processor speed and part number

### Poor candidates

Do not normalize values that:

- require guessing
- are absent from the raw fixtures
- would erase a real hardware distinction
- are better handled by the collector or the consumer

## Code Shape to Prefer

### Normalizers

Normalizers should be:

- small
- explicit
- readable
- deterministic

Use helper functions when a field needs non-trivial cleanup.

### Prefetch

Use `prefetch` only when you need to fetch linked resources to complete the output.

Good prefetch uses:

- processor memory linking
- BIOS-derived enrichment
- vendor-specific linked collections

Bad prefetch:

- broad recursive crawling
- expensive network calls when the same result is already in the resource

### Field maps

Field maps should be mostly declarative.

Prefer:

- direct field passthrough
- small helper calls
- explicit vendor overrides

Avoid:

- hidden side effects
- complicated branching in lambdas
- logic that is impossible to test from fixture diffs

## Project-Specific Conventions

### Vendor identity

Canonical vendor labels should be stable and human-friendly. `canonical_server_vendor()` in `normalizers/vendor_id.py` maps what a BMC sends (`Dell Inc.`, `Hpe`, `Intel Corporation`) to one label. Register normalizers under that label. To add a vendor or change one, follow [ADDING_A_VENDOR.md](ADDING_A_VENDOR.md).

Common examples:

- `Dell`
- `HPE`
- `Lenovo`
- `Supermicro`

### Processor metrics

Processor normalization is often about deriving missing inventory values from related fields.

Examples:

- fill base speed when the BMC omits it
- derive part number from model
- normalize vendor ID strings
- keep per-processor and summary metrics separate

### Memory metrics

Memory normalization is often about trimming and canonicalizing:

- part numbers
- manufacturer names
- slot / locator naming

### PCIe metrics

PCIe normalization often requires:

- class-code canonicalization
- path normalization
- human-readable name cleanup
- vendor-specific path handling for HPE / Lenovo

### Thermal metrics

Thermal normalization often involves:

- fan name cleanup
- stripping suffix noise like `Tach`
- keeping status values stable and readable

### Storage metrics

Storage normalization should keep inventory joinability stable:

- preserve controller association
- normalize drive identifiers
- avoid adding duplicate representations of the same drive

## When Not to Normalize

If a field is missing in both the raw fixture and the normalized output, do not paper over it.

Examples of true absence:

- empty `Storage` collections
- missing PCIe devices from a vendor’s Redfish API
- power metrics that are not reported by the device

## Testing Strategy

For most normalization changes:

- regenerate the affected `normalized/` JSON outputs and run schema validation
- regenerate the affected `redfish_inventory_exporter_*.prom` and `fishymetrics_*.prom` goldens
- run lints on modified Python code
- run `go build` / `go test` if collector-facing behavior changed

For broader changes:

- compare multiple models, not just one
- look for label/value drift across vendors
- check both `redpool` and direct paths when proxy behavior is relevant

Commands are in the next section. All of them run from the repository root with `uv run`.

## Changing an existing model

Use this when a model is already under `fixtures/<Vendor>/<Model>/` and a metric, label, or schema check is wrong. `fixtures/` is the lab-only `redpool-fixtures` submodule. For a model outside it, a maintainer runs these steps with the full corpus.

1. Read `original/` for the resource. Confirm the value is in the capture before writing a rule.
2. Read the matching `normalized/` file when one exists. A path with no file there was served unchanged.
3. Compare `redfish_inventory_exporter_direct.prom` with `redfish_inventory_exporter_redpool.prom`, and the fishymetrics pair, for that model. A series missing on both paths is usually absent from the capture. A series only on one path is a normalization difference.
4. Put the rule in that vendor's module for the resource (`register_resource`, `field_map`, `prefetch`, `version_overrides`, or the rewrite hook next to it). A behavior shared by more than one vendor stays in `base.py`. Leave vendor `Oem` objects as the BMC sent them. Copy a needed value onto a standard property or `Oem.Redpool`.
5. Regenerate and check that model only:

```bash
uv run python scripts/generate_normalized_outputs.py --vendor Dell --model PowerEdge_R740
uv run python scripts/validate_redfish_schema.py --vendor Dell --model PowerEdge_R740
uv run python scripts/generate_redfish_inventory_exporter_golden.py --model Dell/PowerEdge_R740
uv run python scripts/generate_redfish_inventory_exporter_golden.py --no-proxy --model Dell/PowerEdge_R740
uv run python scripts/generate_fishymetrics_golden.py --model Dell/PowerEdge_R740
uv run python scripts/generate_fishymetrics_golden.py --no-proxy --model Dell/PowerEdge_R740
```

Regenerate both the direct and redpool `.prom` files. Editing a `.prom` file by hand attributes collector behavior to Redpool. If the schema check fails, fix the normalizer and run the same commands again.

## Adding a new model

A new model is a sanitized capture plus generated outputs. Only captures of lab or test servers belong in the public `redpool-fixtures` repository. Do not commit raw production data.

1. Capture the BMC. Sanitization is on by default (serials, MACs, hostnames, and addresses are replaced on write):

```bash
# The password comes from the environment, or a prompt when run from a terminal.
REDFISH_SNAPSHOT_PASSWORD=<pass> uv run --project redfish-snapshot redfish-snapshot \
  --host <bmc> \
  --username <user> \
  --vendor <Vendor> \
  --model <Model>
```

Output is `fixtures/<Vendor>/<Model>/original/`, in the submodule's working tree. Review it for identifiers the sanitizer missed, then open a pull request in `redpool-fixtures` and move the `fixtures` pointer here. See `fixtures/README.md` and `docs/FIXTURES.md`.

2. Generate normalized JSON and validate it against the DMTF schema named by `@odata.type`:

```bash
uv run python scripts/generate_normalized_outputs.py --vendor <Vendor> --model <Model>
uv run python scripts/validate_redfish_schema.py --vendor <Vendor> --model <Model>
```

3. Generate both Prometheus golden pairs:

```bash
uv run python scripts/generate_redfish_inventory_exporter_golden.py --model <Vendor>/<Model>
uv run python scripts/generate_redfish_inventory_exporter_golden.py --no-proxy --model <Vendor>/<Model>
uv run python scripts/generate_fishymetrics_golden.py --model <Vendor>/<Model>
uv run python scripts/generate_fishymetrics_golden.py --no-proxy --model <Vendor>/<Model>
```

4. Read the direct-versus-redpool diff for that model. Add a vendor rule only where the capture has the data and the redpool path drops or mislabels it. Then repeat steps 2 and 3 for that model.

`<Vendor>` and `<Model>` must match the directory names (`Dell`, `PowerEdge_R760`). The golden scripts take them as one `Vendor/Model` argument. The normalize and schema scripts take them separately.

See also:

- [ADDING_A_VENDOR.md](ADDING_A_VENDOR.md)
- [REDPOOL_ARCHITECTURE_GUIDE.md](REDPOOL_ARCHITECTURE_GUIDE.md)
- [SCHEMA_VALIDATION.md](SCHEMA_VALIDATION.md)
- [FIXTURES.md](FIXTURES.md)
- [GOLDEN_FILES.md](GOLDEN_FILES.md)
