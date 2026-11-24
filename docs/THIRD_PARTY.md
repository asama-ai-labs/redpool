# Third-party components

Redpool depends on the components below. Each one keeps its own license, and the license terms apply to its source. The submodules live under `third_party/`, and their versions are pinned by this repository.

| Component | License | Used for | Shipped in the proxy image |
|---|---|---|---|
| `pciids` (`third_party/pciids`) | GPL-2.0-or-later **or** BSD-3-Clause, at your option (see its header) | PCI vendor and device names when a BMC omits them. Redpool uses the BSD-3-Clause option. | Yes: `pci.ids` only |
| `Redfish-Publications` (`third_party/Redfish-Publications`) | BSD-3-Clause (DMTF) | DMTF schema and registry files for schema validation | No |
| `Redfish-Mockup-Server` (`third_party/Redfish-Mockup-Server`) | BSD-3-Clause (DMTF) | Mock BMC that serves a fixture model for the golden tests and local runs | No |
| `Swordfish-Publications` (`third_party/Swordfish-Publications`) | BSD-3-Clause (SNIA) | SNIA schema files used when a Redfish document references Swordfish types | No |
| `fishymetrics` (`third_party/fishymetrics`) | Apache-2.0, with a NOTICE file | Golden test comparison against a Prometheus exporter | No |
| `redfish-inventory-exporter` (`third_party/redfish-inventory-exporter`) | Apache-2.0 | Golden test comparison against an inventory collector | No |
| `fixtures` (`fixtures/`) | CC0-1.0; see `fixtures/NOTICE.md` | Captured and sanitized BMC responses for tests | No |

## pciids

[pciids](https://github.com/pciutils/pciids) is the pciutils PCI ID database. The proxy image copies `third_party/pciids/pci.ids` so PCIe device names can be filled in when a BMC omits them. The file's own header says it may be distributed under the GNU GPL version 2 or later, or under the 3-clause BSD License. Redpool redistributes it under the BSD-3-Clause option. The database itself is not modified.

## Redfish-Publications

[Redfish-Publications](https://github.com/DMTF/Redfish-Publications) is published by DMTF under the BSD-3-Clause License. Redpool uses its schema files to validate normalized output in tests. Nothing from it is shipped in the image.

## Redfish-Mockup-Server

[Redfish-Mockup-Server](https://github.com/DMTF/Redfish-Mockup-Server) is published by DMTF under the BSD-3-Clause License and is pinned to release 1.3.0. The fixtures use its mockup layout (`redfish/v1/<path>/index.json`), and the golden scripts run it unmodified to serve `fixtures/<Vendor>/<Model>/original` as the BMC. Nothing from it is shipped in an image.

## Swordfish-Publications

[Swordfish-Publications](https://github.com/SNIA/Swordfish-Publications) is published by the Storage Networking Industry Association (SNIA) under the BSD-3-Clause License. The licence text is `third_party/Swordfish-Publications/LICENSE`. Schema validation uses its schema files when a Redfish document references a Swordfish type. Nothing from it is shipped in the image.

## fishymetrics

`fishymetrics` is the Apache-2.0 Redfish Prometheus exporter published as [comcast/fishymetrics](https://github.com/comcast/fishymetrics). Redpool pins that repository itself as the `third_party/fishymetrics` submodule and does not modify it. The golden suite scrapes the mock server directly and through the proxy, and records the difference in `fixtures/<Vendor>/<Model>/fishymetrics_*.prom`.

## redfish-inventory-exporter

`redfish-inventory-exporter` is an Apache-2.0 inventory exporter. Its Go module path is `github.com/asama-ai-labs/redfish-inventory-exporter`. The normalizers are written to suit this collector: prefetch and field maps let it read one shape across Dell, HPE, Lenovo, Supermicro, and Intel captures. It is used only by the golden tests.

## fixtures

The fixtures are Redfish responses captured from lab servers and sanitized for publication. They live in the separate [redpool-fixtures](https://github.com/asama-ai-labs/redpool-fixtures) repository, which is the `fixtures/` submodule. Some responses reproduce message registries and descriptive text that belongs to the vendors, and that text is included as factual interoperability test data. The repository is dedicated under [CC0 1.0 Universal](https://creativecommons.org/publicdomain/zero/1.0/). CC0 waives only the copyright Asama holds in the curation, layout, normalized forms, golden files and documentation. `fixtures/NOTICE.md` states that Asama does not claim copyright in the vendor-generated responses, that those rights stay with their owners, and that CC0 does not grant vendor trademarks or any right Asama does not hold. The fixtures are not part of the sdist or the image.
