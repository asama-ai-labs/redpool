# Redpool

A transparent MITM proxy that normalizes Redfish BMC responses across vendors (Dell, HPE, Lenovo, Supermicro, Intel) into a consistent schema. Drop it between any Redfish client and BMC — the client sees uniform data without any code changes.

## Why

Every server vendor implements the Redfish API differently. The same logical field (e.g., processor speed) lives in different paths, uses different names, or is missing entirely depending on the vendor and firmware version. Redpool sits transparently in front of BMCs and normalizes responses so downstream tools (Prometheus exporters, inventory systems, monitoring dashboards) don't need per-vendor logic.

**When does redpool matter?** The value shows up against **real BMCs** (or simulators that mimic vendor quirks), not in the mock golden comparison. The mock server serves from `fixtures/.../original/` — **captured JSON from lab servers of commonly used makes** (Dell PowerEdge, HPE ProLiant, Lenovo ThinkSystem, Supermicro). That data may already be compliant or from a single firmware. Real deployments often mix Dell iDRAC, HPE iLO, Lenovo XCC, Supermicro, Intel BMCs, and multiple firmware versions; the same field is in different paths, under OEM, or missing. Redpool fills in derived fields (e.g. PartNumber from Model, BaseSpeedMHz fallback), strips vendor-specific noise (e.g. HPE PartNumber padding), and builds consistent structures (e.g. MemorySummary, processor–DIMM links). So: **direct vs redpool goldens can look similar** when the mock data is already clean; use redpool in front of fishymetrics when scraping real, mixed-vendor BMCs.

## Architecture

```
Redfish Client  ──>  mitmproxy + redpool  ──>  BMC (iDRAC / iLO / XCC / IPMI)
                         │
                         ├── Normalizes over 50 resource types, 40 collection types
                         ├── Preserves Oem fields for vendor tools
                         ├── Caches responses (configurable TTL)
                         └── Exposes Prometheus /metrics on :9101
```

Redpool runs as a [mitmproxy](https://mitmproxy.org/) addon. Clients (like [fishymetrics](https://github.com/comcast/fishymetrics)) point their HTTPS proxy to redpool. Authentication, TLS, and URL routing are handled transparently by mitmproxy.

**Sharded mode:** `redpool-shard-proxy` runs several mitmdump workers behind one **front** port. CONNECT / HTTP proxy traffic is routed by upstream `host:port` with **`sha256(host:port)[:8] % N`**. Each worker has its own mitm port and metrics port (`proxy.metrics_port` + *i* from `redpool.yaml`, or `--metrics-port-base`). Arguments after `--` go to every mitmdump. **Production:** **`redpool-shard-worker@N`**, **`redpool-shard-front`**, **`redpool-shard.target`** (see below).

## Quick Start

Git submodules for the collectors and exporters (`redfish-inventory-exporter`, `fishymetrics`, plus `third_party/pciids`) live in this tree. After clone, run `git submodule update --init --recursive`. `fixtures/` is a submodule too: [redpool-fixtures](https://github.com/asama-ai-labs/redpool-fixtures), captures of lab servers under CC0 1.0 (its `NOTICE.md` says which rights stay with the vendors). The same command fetches it. See [docs/FIXTURES.md](docs/FIXTURES.md), [docs/THIRD_PARTY.md](docs/THIRD_PARTY.md), and the [schema validation report](docs/SCHEMA_VALIDATION.md). Redpool's own OEM extension is documented in [docs/REDPOOL_OEM_SCHEMA.md](docs/REDPOOL_OEM_SCHEMA.md).

```bash
# Install dependencies
uv sync

# Single process: mitmdump + redpool on port 7000
uv run redpool-proxy -p 7000

# Or: N workers; clients still use the front port (/metrics at proxy.metrics_port, +1, … from redpool.yaml)
uv run redpool-shard-proxy -n 4 --front-port 7000

# Query a BMC through the proxy
https_proxy=http://127.0.0.1:7000 \
  curl -sku user:pass -x http://127.0.0.1:7000 https://bmc.example/redfish/v1/Systems/1/Processors/CPU.Socket.1 | jq .
```

Single-process proxy: `deploy/systemd/redpool-proxy.service`. **Sharded proxy (recommended on servers):** set worker count, ports, and related env in [`deploy/systemd/redpool-shard.env`](deploy/systemd/redpool-shard.env) (tracked in git; **`install.sh` does not modify the repo**). `install.sh` copies units to `/etc/systemd/system/`, copies the unit generator to `/etc/systemd/system-generators/` as a root-owned file (not a symlink into the clone), and writes **`10-repo.conf`** drop-ins there with `User`, `WorkingDirectory`, `Environment=` (`PYTHONUNBUFFERED`, `REDPOOL_REPO`, `PATH` for this host), and **`EnvironmentFile=-…/redpool-shard.env`**. The unit files under `deploy/systemd/` stay free of machine-specific `Environment=`. Set `RUN_AS` at the top of [`install.sh`](install.sh) if needed (repo root is inferred from the script location; `install.sh` creates that user and group if they do not exist). The service user's home is `/var/lib/redpool`, which systemd creates, so `uv` and `mitmdump` have a writable cache and certificate directory. Run `uv sync`, then **`sudo ./install.sh`**. Start/stop: `systemctl start|stop redpool-shard.target`. After editing **`redpool-shard.env`**, run **`systemctl daemon-reload && systemctl restart redpool-shard.target`** (daemon-reload is required when **`REDPOOL_SHARD_NUM_WORKERS`** changes). Re-run **`install.sh`** after moving the clone or changing `RUN_AS` (refreshes `/etc/.../10-repo.conf`). Each **`redpool-shard-worker@N`** exposes Prometheus on **`REDPOOL_SHARD_METRICS_PORT_BASE + N`** (e.g. base `6101` → `6101`, `6102`, … — one `/metrics` listener per worker). **`redpool-shard-front`** serves Prometheus HTTP SD on **`REDPOOL_SHARD_PARENT_ADMIN_PORT`** at **`/prometheus-sd`**, independent of worker metrics ports. For local development you can still run `uv run redpool-shard-proxy -n 4 ...` in one process (no `--front-only`); omit **`--parent-admin-port`** there to keep the CLI default `metrics_port_base + workers`.

## Configuration

All settings live in `redpool.yaml` (or set `REDPOOL_CONFIG` env var to a custom path). The proxy works out-of-the-box with sensible defaults — override only what you need.

### Cache TTLs


| Setting                | Default | Description                           |
| ---------------------- | ------- | ------------------------------------- |
| `cache.response_ttl`   | 60s     | Raw Redfish GET response cache        |
| `cache.metadata_ttl`   | 24h     | Server vendor/model (doesn't change)  |
| `cache.objecttype_ttl` | 24h     | Collection vs resource classification |


### Proxy Behavior


| Setting                        | Default                  | Description                                                                             |
| ------------------------------ | ------------------------ | --------------------------------------------------------------------------------------- |
| `proxy.metrics_host`           | 127.0.0.1                | Address `/metrics` binds (`REDPOOL_METRICS_HOST`); set `0.0.0.0` for a remote Prometheus |
| `proxy.metrics_port`           | 9101                     | Prometheus `/metrics` port; with `redpool-shard-proxy`, worker *i* uses this port + *i* |
| `proxy.log_level`              | INFO                     | DEBUG, INFO, WARNING, ERROR, CRITICAL                                                   |
| `proxy.skip_prefixes`          | Sessions, SessionService | Paths passed through without normalization                                              |
| `proxy.non_cacheable_patterns` | Actions, SessionService, TaskService, UpdateService | Paths never cached                                                                      |


### Normalization Feature Flags

Toggle individual field-derivation behaviors. Set to `false` to return only raw BMC values.


| Flag                       | Default | What it does                                                          |
| -------------------------- | ------- | --------------------------------------------------------------------- |
| `derive_part_number`       | true    | Extract Intel Xeon / AMD EPYC SKU from Model string                   |
| `derive_base_speed`        | true    | Fallback chain: BaseSpeedMHz -> OperatingSpeedMHz -> parse from Model |
| `build_processor_links`    | true    | Associate DIMMs to processors via Links                               |
| `build_memory_summary`     | true    | Aggregate MemorySummary per processor                                 |
| `enrich_ampere_model`      | true    | Rewrite Ampere Model to include PartNumber                            |
| `strip_memory_part_number` | true    | Strip HPE PartNumber whitespace padding                               |
| `use_vendor_oem_overrides` | true    | Use vendor OEM fields for standard field overrides                    |


## Prometheus Metrics

Redpool exposes metrics on `:9101/metrics` (configurable) with `vendor` and `model` labels:

```
redpool_requests_total{vendor="Dell", model="PowerEdge R630", method="GET", status_code="200", norm_status="normalized"}
redpool_request_duration_seconds_bucket{vendor="Dell", model="PowerEdge R630", method="GET", le="0.5"}
redpool_normalization_errors_total{vendor="HPE", model="ProLiant DL380 Gen10", path_pattern="/redfish/v1/..."}
redpool_cache_operations_total{cache="response", op="get", result="hit"}
redpool_active_bmc_connections
```

## Response Headers

Every proxied response includes:


| Header             | Values                               | Description                       |
| ------------------ | ------------------------------------ | --------------------------------- |
| `X-Redpool-Status` | `normalized`, `passthrough`, `error` | Whether normalization was applied |
| `X-Redpool-Vendor` | e.g., `Dell`, `HPE`                  | Detected BMC vendor               |
| `X-Redpool-Model`  | e.g., `PowerEdge R630`               | Detected server model             |


## Supported Vendors

Normalizers are validated against the following models. The last column says whether the capture is in the public `fixtures/` submodule, which holds lab servers only. Maintainers hold the other captures and regenerate their outputs and goldens; a clone without them cannot reproduce those models. New BMC firmware can change `@odata.type` or fields; add `version_overrides` as needed when new firmware appears.


| Vendor     | Model                         | BMC / Firmware (tested)                          | Public fixtures |
| ---------- | ----------------------------- | ------------------------------------------------ | ---------------- |
| Dell       | PowerEdge R630                | iDRAC 2.85.85.85 (Redfish 1.4.0)                 | no |
| Dell       | PowerEdge R630 (second host)  | iDRAC 2.86.86.86 (Redfish 1.4.0); fixture `PowerEdge_R630_2`, same model as R630 | no |
| Dell       | PowerEdge R6525               | iDRAC 7.20.80.50 (Redfish 1.20.1)                | no |
| Dell       | PowerEdge R740                | iDRAC 7.00.00.183 (Redfish 1.17.0)               | yes |
| Dell       | PowerEdge R7525               | iDRAC 7.10.30.00 (Redfish 1.18.0)                | yes |
| Dell       | PowerEdge R760                | iDRAC 7.20.30.50 (Redfish 1.20.1)                | no |
| Dell       | PowerEdge R7625               | iDRAC 7.30.30.51 (Redfish 1.20.1)                | no |
| HPE        | ProLiant DL360 Gen10          | iLO 5 v2.96 (Redfish 1.6.0)                      | no |
| HPE        | ProLiant DL380 Gen10          | iLO 5 v2.96 (Redfish 1.6.0)                      | yes |
| HPE        | ProLiant DL380 Gen10 (second) | iLO 5 v2.42 (Redfish 1.6.0); fixture `ProLiant_DL380_Gen10_2` | no |
| HPE        | ProLiant DL380a Gen11         | iLO 6 v1.59 (Redfish 1.13.0)                     | no |
| HPE        | ProLiant DL385 Gen10 Plus     | iLO 5 v3.07 (Redfish 1.20.0)                     | yes |
| Intel      | M50CYP2SBSTD                  | Intel BMC 2.93.a858f4d1 (Redfish 1.7.0)          | no |
| Lenovo     | ThinkSystem SR630 V2          | XCC AFBT30P 2.93 (2023-03-24) (Redfish 1.15.0)   | yes |
| Lenovo     | ThinkSystem SR650 V2          | XCC AFBT48B 4.70 (2024-02-20) (Redfish 1.15.0)   | no |
| Lenovo     | ThinkSystem SR675 V3          | XCC2 QGX394J 14.10 (2025-09-05) (Redfish 1.22.0) | no |
| Lenovo     | ThinkSystem SR680a V3         | XCC R3X308M 3.10 (2024-11-21) (Redfish 1.16.0)   | no |
| Lenovo     | ThinkSystem SR680a V3         | XCC R3X318M 6.10 (2025-06-10) (Redfish 1.20.0); fixture `ThinkSystem_SR680a_V3_610` | no |
| Lenovo     | ThinkSystem SR680a V3         | XCC R3X328A 9.10 (2025-09-08) (Redfish 1.22.0); fixture `ThinkSystem_SR680a_V3_910` | no |
| Supermicro | ARS-110M-NR (Ampere Altra)    | OpenBmc BMC 51.02.25.00 (Redfish 1.17.0)         | yes |
| Supermicro | SYS-220TP-HTTR                | ASPEED BMC 01.02.34 (Redfish 1.9.0)              | yes |


## Normalized Resources

Over 50 resource patterns and 40 collection patterns, covering:

- **Systems**: ComputerSystem, Processors, Memory, Storage, Drives, Volumes, Controllers, Bios, SecureBoot, BootOptions, EthernetInterfaces, NetworkInterfaces, LogServices
- **Chassis**: Power, Thermal, Sensors, Fans, PowerSupplies, Assembly, PCIeSlots, PCIeDevices, PCIeFunctions, NetworkAdapters, Drives, EnvironmentMetrics
- **Managers**: NetworkProtocol, EthernetInterfaces, HostInterfaces, VirtualMedia, SerialInterfaces, LogServices
- **UpdateService**: FirmwareInventory
- **Metrics**: ProcessorMetrics, MemoryMetrics, PowerSupplyMetrics, EnvironmentMetrics

## Project Structure

```
.
├── redpool/              # Proxy package: mitmproxy addon, proxy core, cache, config, metrics, shard supervisor
├── normalizers/          # One directory per resource type; registry.py is the lookup
│   ├── systems/          #   Systems, Processors, Memory, Storage, ...
│   ├── chassis/          #   Power, Thermal, Sensors, Fans, ...
│   ├── managers/         #   NetworkProtocol, VirtualMedia, ...
│   ├── firmware_inventory/
│   └── _shared/          #   Helpers shared across vendors
├── redpool.yaml          # Default configuration
├── schemas/json-schema/  # Published schema for Oem.Redpool
├── fixtures/             # Submodule (redpool-fixtures): captured BMC data per vendor and model,
│                         #   normalized outputs, and Prometheus goldens
├── tests/                # pytest tests (test_*.py) and scrape-versus-golden harnesses
├── scripts/              # Golden generators, validators, release checks, mock-server helpers
├── redfish-snapshot/     # Capture and sanitize Redfish responses from a BMC (workspace member)
├── third_party/          # Submodules: redfish-inventory-exporter, fishymetrics, pciids,
│                         #   DMTF Redfish-Mockup-Server and Redfish-Publications, SNIA Swordfish-Publications
├── deploy/systemd/       # Units for the single-process and sharded deployments
├── docs/
├── Dockerfile, docker-compose.yml, Makefile, install.sh
└── pyproject.toml, uv.lock   # uv workspace: redpool and redfish-snapshot
```

## Distribution

### Docker (one image per service, shared base layer)

Build both images (redpool, redfish-snapshot) or a single target:

```bash
make docker-build                      # redpool + redfish-snapshot
make docker-build-redpool              # redpool only
make docker-build-redfish-snapshot     # redfish-snapshot only

# Tag with a specific version
VERSION=v1.2.3 make docker-build
```

Images use a shared `deps` stage, so deploying both on the same host reuses the same base layers.

### Pip (sdist / wheel)

Build source distributions and wheels for the workspace (root, redfish-snapshot):

```bash
make pip-build       # sdist + wheel for all packages
make pip-sdist      # source distributions only
make pip-wheel      # wheels only
make pip-build-all  # build and list artifacts
make clean-dist     # remove dist/ and build artifacts
```

See `make help` for a full list of targets.

## Testing

Install the project and its dev dependencies:

```bash
uv sync --all-packages --all-extras
```

Then run the checks CI runs:

```bash
uv run pytest -q                                   # tests/ and redfish-snapshot/tests/
uv run ruff check .
uv run ruff format --check .
uv run mypy redpool
uv run python scripts/validate_redfish_schema.py --strict   # normalized fixtures against the DMTF schemas
uv run python scripts/check_doc_links.py                    # every relative link and repository path in the docs exists
```

Before a release, and before pushing fixtures, run the leak check by hand. It is not part of CI. `REDPOOL_SANITIZE_STATE` is optional; set it when you have the sanitizer state directory so saved identifiers are checked too.

```bash
uv run python scripts/check_fixture_leaks.py                # no identifier that should have been removed is left in a fixture
```

Tests that need the corpus skip when the `fixtures/` submodule is not checked out. `tests/helpers.py` holds unit tests for pure helpers. pytest does not collect it, so run it with `uv run python -m unittest tests.helpers`.

### Normalized outputs

The normalized files under `fixtures/<Vendor>/<Model>/normalized/` are generated from `original/`. After changing a normalizer, regenerate them and review the diff in `fixtures/`. It is the separate `redpool-fixtures` repository, so a corpus change is a pull request there plus a pointer bump here. `REDPOOL_FIXTURES` points the scripts at another checkout:

```bash
uv run python scripts/generate_normalized_outputs.py

# Limit to one vendor or model
uv run python scripts/generate_normalized_outputs.py --vendor Dell --model PowerEdge_R740

git -C fixtures diff --stat
```

### Mock server test (random resources)

To verify the mock server is serving fixtures correctly (no fishymetrics, no proxy):

```bash
# Start mock and request 10 random resources from fixtures (default)
uv run python scripts/mock_server_test.py --model Dell/PowerEdge_R740

# Request 8 resources
uv run python scripts/mock_server_test.py --model Dell/PowerEdge_R740 --count 8

# Mock already running on port 9000
uv run python scripts/mock_server_test.py --model Dell/PowerEdge_R740 --no-start --mock-port 9000
```

### Fishymetrics + mock test (no proxy)

To confirm fishymetrics works against the mock server before testing through the proxy:

```bash
# Build fishymetrics once
git submodule update --init third_party/fishymetrics
make -C third_party/fishymetrics build

# Test one model (scrape can take a few minutes for large fixtures)
uv run python scripts/fishymetrics_mock_test.py --model Dell/PowerEdge_R740

# Test all models
uv run python scripts/fishymetrics_mock_test.py

# Longer scrape timeout if needed (default 300s)
uv run python scripts/fishymetrics_mock_test.py --model Dell/PowerEdge_R740 --scrape-timeout 600
```

Uses default ports 18889 (mock) and 10024 (fishymetrics).

To see which responses the proxy passed through unnormalized, set `REDPOOL_RESPONSE_LOG` to a file path. The proxy then writes each response's path and `X-Redpool-Status` to it.

### Fishymetrics golden test

To assert that fishymetrics produces stable Prometheus metrics per model, generate golden files then run the test:

```bash
# Generate golden files through redpool proxy (fishymetrics_redpool.prom)
uv run python scripts/generate_fishymetrics_golden.py

# Generate golden files directly against mock (fishymetrics_direct.prom)
uv run python scripts/generate_fishymetrics_golden.py --no-proxy

# Run the test (compares live scrape output to each golden file)
uv run python -m unittest tests.fishymetrics
```

Goldens are stored in `fixtures/<Vendor>/<Model>/fishymetrics_redpool.prom` (through proxy) and `fishymetrics_direct.prom` (direct to mock). Regenerate after changing normalizers or fishymetrics scrape behavior. See [docs/GOLDEN_FILES.md](docs/GOLDEN_FILES.md).

### redfish-inventory-exporter golden test

The [redfish-inventory-exporter](https://github.com/asama-ai-labs/redfish-inventory-exporter) submodule collects Redfish inventory as Prometheus metrics. Generate golden files and run tests:

```bash
git submodule update --init third_party/redfish-inventory-exporter
cd third_party/redfish-inventory-exporter && mkdir -p build && go build -o build/redfish-inventory-exporter . && cd ../..

uv run python scripts/generate_redfish_inventory_exporter_golden.py
uv run python scripts/generate_redfish_inventory_exporter_golden.py --no-proxy

uv run python -m unittest tests.redfish_inventory_exporter
```

Goldens: `redfish_inventory_exporter_redpool.prom`, `redfish_inventory_exporter_direct.prom`. See [docs/GOLDEN_FILES.md](docs/GOLDEN_FILES.md). Rebuild the collector binary after changing its source, or the goldens will not reflect the change.

## Adding a New Vendor

Vendor behavior lives in `normalizers/<area>/<resource>/<vendor>.py`, one module per vendor and resource, registered in the package `__init__.py`. Vendor names are canonicalized, so `Dell Inc.` and `Dell` reach the same normalizers. The step-by-step walkthrough, with the five extension points and when to use each, is in [docs/ADDING_A_VENDOR.md](docs/ADDING_A_VENDOR.md).

## Exposing the proxy

Redpool listens on `127.0.0.1` by default and does not authenticate callers. To serve collectors on other hosts, change the bind on purpose (`redpool-proxy --listen-host 0.0.0.0`, `REDPOOL_SHARD_FRONT_HOST` for the sharded proxy, or the port mapping in `docker-compose.yml`) and restrict who can connect:

```bash
# Only these BMC networks and names can be fetched; anything else gets 403.
REDPOOL_ALLOWED_TARGETS="10.20.0.0/16,*.bmc.example.net" \
  uv run redpool-proxy --listen-host 0.0.0.0 -p 7000 --set proxyauth=collector:change-me
```

Only `/redfish` paths are served. See the threat model in [SECURITY.md](SECURITY.md).

## Relationship to DMTF tools

Redpool builds on the DMTF Redfish ecosystem and does not replace any of it.

| DMTF tool | What it does | How Redpool relates |
| --- | --- | --- |
| [Redfish-Mockup-Server](https://github.com/DMTF/Redfish-Mockup-Server) | Serves a captured mockup as a fake BMC. | Redpool's tests and goldens run against it (`third_party/Redfish-Mockup-Server`). |
| [Redfish-Mockup-Creator](https://github.com/DMTF/Redfish-Mockup-Creator) | Captures a live service into the mockup layout, with no redaction. | `redfish-snapshot` writes the same layout, and it also sanitizes identifiers and records capture metadata. `redfish-snapshot sanitize` works on Mockup-Creator output. |
| [Redfish-Service-Validator](https://github.com/DMTF/Redfish-Service-Validator) | Checks a live service against the DMTF schemas through its `$metadata`. | Redpool's normalized fixtures are validated against the pinned DMTF schemas (`scripts/validate_redfish_schema.py`). The proxy itself does not yet serve a `$metadata` that describes its `Oem.Redpool` types or raised `@odata.type` versions, so the Service Validator is not expected to pass against it yet. |
| [Redfish-Interop-Validator](https://github.com/DMTF/Redfish-Interop-Validator) | Checks a service against an interoperability profile. | Redpool has no profile of its own. The Interop Validator is not part of its tests. |

Redpool's own data lives under `Oem.Redpool`, described by [docs/REDPOOL_OEM_SCHEMA.md](docs/REDPOOL_OEM_SCHEMA.md). It is not defined by DMTF.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) first. Contributions need a `Signed-off-by` line (DCO) and follow the [Code of Conduct](CODE_OF_CONDUCT.md). [MAINTAINERS.md](MAINTAINERS.md) lists who reviews, [CHANGELOG.md](CHANGELOG.md) records changes, and [docs/RELEASING.md](docs/RELEASING.md) describes how a release is cut. Report vulnerabilities as described in [SECURITY.md](SECURITY.md).

## License

Redpool is licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE). Third-party components and their licenses are listed in [docs/THIRD_PARTY.md](docs/THIRD_PARTY.md).

## Trademarks

Redfish and DMTF are trademarks of DMTF. Redpool is an independent project. It is not affiliated with, endorsed by, or certified by DMTF. Dell, HPE, Lenovo, Supermicro, Intel and the other product names used here belong to their owners and appear only to say which hardware Redpool works with.
