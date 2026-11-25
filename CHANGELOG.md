# Changelog

All notable changes to Redpool are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to follow [Semantic Versioning](https://semver.org/). [docs/RELEASING.md](docs/RELEASING.md) says what counts as a breaking change.

## [Unreleased]

## [1.0.0] - 2026-11-25

First public release of Redpool.

### Added
- CI validates every normalized fixture against the pinned DMTF schemas with `validate_redfish_schema.py --strict`. It fails on an invalid document or a DMTF type newer than the bundle, and prints a report of deprecated schemas and properties still in use.

- Apache-2.0 `LICENSE`, `NOTICE`, SPDX headers, and a third-party license table.
- A CI workflow that runs ruff, mypy and the tests, a DCO workflow that requires `Signed-off-by` on every pull request commit, and a Docker workflow that publishes the image to GHCR on a `v*` tag.
- A published schema for `Oem.Redpool`, with one typed `Oem.Redpool` per resource. See `docs/REDPOOL_OEM_SCHEMA.md`.
- Manufacturer inference from a model's product line, from Dell `BP_` and Supermicro `BPN-` backplane names, and from Supermicro `PWS` power-supply model names.
- Ethernet link technology inferred from a 48-bit port MAC address.
- `redfish-snapshot sanitize`, which sanitizes any DMTF-layout mockup in place. `redfish-snapshot fix-collections` also works on any DMTF mockup.
- `register_collection_override`, so a vendor can replace a collection's mapping the same way it replaces a resource's.
- `docs/ADDING_A_VENDOR.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `MAINTAINERS.md`, `docs/RELEASING.md`, and issue and pull request templates.

### Security

- `redpool-proxy`, the shard front and the Prometheus service-discovery endpoint listen on `127.0.0.1` by default, and the shipped systemd files and `docker-compose.yml` do the same. To serve other hosts, set `--listen-host`, `REDPOOL_SHARD_FRONT_HOST`, or the compose port mapping.
- A wrong password or a malformed `Authorization` header now gets 401. It used to get 500, which a collector reported as a BMC outage. A rejected password is tried once, not twice, so it adds one failed login toward BMC lockout.
- `/metrics` binds `127.0.0.1` by default. It used to bind every interface. Set `proxy.metrics_host` or `REDPOOL_METRICS_HOST` (for example `0.0.0.0`) to let another host scrape it, and Redpool warns when the address is not loopback. The container image sets `0.0.0.0`.
- `proxy.log_level: DEBUG` now sets mitmproxy's `flow_detail` to 1 instead of 2, so `Authorization` and `X-Auth-Token` are no longer printed to the log.
- only `/redfish` paths are served. Other paths get 403. Set `proxy.require_redfish_path: false` to restore the old behavior.
- Added `proxy.allowed_targets` and `REDPOOL_ALLOWED_TARGETS`, an optional allowlist of hostnames, globs and CIDRs a caller may target. Refused requests get 403.
- Added `proxy.max_targets`: per-BMC locks and clients are dropped least-recently-used past the cap.
- mitmproxy's `proxyauth` now works with the addon. The addon used to overwrite its 407 response, so `--set proxyauth=...` let every request through.
- `SECURITY.md` describes the threat model.
- **redfish-snapshot:** `--password` is removed. Set `REDFISH_SNAPSHOT_PASSWORD`, or run from a terminal to be prompted. The password is no longer a command-line argument.
- redfish-snapshot hides urllib3's unverified-certificate warnings by default. `--tls-warnings` shows them. The vendored `redfish` library still hides them process-wide when it is imported, so this change does not stop that.
- Added `proxy.tls_verify` and `proxy.ca_file`, to verify each BMC's TLS certificate. Off by default, so existing deployments behave as before. A startup warning is logged while it is off.

### Changed
- **OEM key:** Redpool writes its OEM data under `Oem.Redpool`, not `Oem.redpool`. Clients and the redfish-inventory-exporter must read the capitalized key. The published schema and the normalized fixtures use it.
- **ports:** chassis ports are served at `NetworkAdapters/{id}/Ports` as DMTF `#Port.v1_20_0.Port` on every BMC. `NetworkPorts` (deprecated `#NetworkPort`) is returned only where the BMC has it, and is no longer rewritten into `Ports` or synthesized from `BaseNetworkAdapters`. Clients that walked only `NetworkPorts` see no ports on HPE Gen10+ and Lenovo; they should read `Ports`.
- **redfish-inventory-exporter:** the collector reads `Ports` only. Direct scrapes of a BMC that exposes only `NetworkPorts` (Dell R630 family) report no ports, because the BMC has no `Ports` link to follow. Through Redpool those BMCs still report their ports.
- Dell iDRACs with only `NetworkPorts` (R630 family): Redpool adds a `Ports` link to the adapter, restamped `#NetworkAdapter.v1_8_1` because `Ports` first appears in v1_8, and serves `Ports` from `NetworkPorts`, converted to `#Port`.
- Fixed a case where HPE chassis ports were served as a blank member and an empty placeholder: blank `Members` links are dropped from the `Ports` collection too.
- The normalizer no longer writes documents for URLs whose captured response is a BMC error. Such documents had been invented from error bodies (for example, `EthernetInterface` entries built from `ResourceMissingAtURI`).


- Fixtures use the DMTF mockup layout (`redfish/v1/<path>/index.json`). The golden scripts and smoke tests serve them with DMTF Redfish-Mockup-Server 1.3.0, pinned under `third_party/`.
- Vendor names are canonicalized wherever Redpool matches a vendor. `Dell Inc.` reaches the `Dell` normalizers, `Hpe` reaches `HPE`, and `Intel Corporation` reaches `Intel`. Normalizers register under the canonical name, and registering a different class for a vendor that already has one now raises.
- Vendor-specific code moved out of shared `base.py` files into vendor modules: Dell drives, Dell power supplies, HPE power supply hot-plug, Dell, HPE and Lenovo memory, HPE system PCIe devices, and the Dell and HPE collection member handling. Output is unchanged.
- BMC clients and cached responses are scoped by credential, so one caller never receives another caller's session or cached reads.
- BMC errors, raw bodies and query strings are passed through to clients. Request bodies are forwarded for `PATCH`, and unknown upstream methods are refused.
- SmartStorage presence is keyed by BMC and expires. Failures are never cached.
- Normalizers no longer invent values the BMC never sent. A BMC placeholder date maps to null.
- The README no longer describes a publishing workflow that this repository does not contain.

### Fixed
- Corrected DIMM location mappings for Dell PowerEdge, HPE ProLiant, and Lenovo ThinkSystem models, and regenerated the normalized fixtures and Prometheus golden files.
- The Docker publish workflow retries signing when GHCR temporarily fails to serve the pushed image digest.
- PCI `DeviceClass` is mapped from the PCI base class using DMTF names. 0x10 is `EncryptionController` (it was the non-DMTF `CoprocessorController`). Added 0x0E to 0x13 and 0x40 `Coprocessor`, and 0xFF is `UnassignedClass`.
- `Status.State` is no longer set to `Unknown`, which is not a valid value. When processors report different states, `ProcessorSummary.Status.State` is omitted. An HPE DIMM whose `DIMMStatus` is `Unknown` is left unmapped, where it was mapped to `OK`/`Enabled` with an invalid `HealthRollup`.
- Drives no longer get an empty `Location: []` when the BMC does not send one. `Location` is deprecated in favor of `PhysicalLocation` and is passed through only when sent.
- Intel BMCs reach their Intel normalizers. They sent `Intel Corporation`, the normalizers registered as `Intel`, so Intel resources came back through the proxy with empty ids and missing drives.
- The sanitizer no longer masks DMTF schema names (`redfish-schema-v1`, `odata.v4_0_1`) as hostnames, and it masks the account name in HPE iLO session ids instead of replacing the whole id.
- Dell and Supermicro normalizers no longer skip a BMC that reports `Dell Inc.`.

### Removed

- `redfish-mock`, replaced by DMTF Redfish-Mockup-Server. The `redfish-mock` image and Makefile targets are gone with it.

### Security

- Credential scoping of BMC clients and cached responses (see Changed).
- The former mock server stopped path traversal and bound to loopback by default before it was removed.
