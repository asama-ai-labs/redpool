# Schema validation report

Redpool serves one DMTF schema version for each resource. A BMC that sends an older version of that resource is rewritten to the Redpool version. Properties that have no standard home stay under `Oem.Redpool`.

## What was tested

Every JSON file under `fixtures/<Vendor>/<Model>/normalized/` was validated against the DMTF schema named by its `@odata.type`. Schemas come from the pinned [Redfish-Publications](https://github.com/DMTF/Redfish-Publications) bundle in `third_party/Redfish-Publications/json-schema`. Properties that DMTF schemas take from SNIA Swordfish (Volume `VolumeType`, `RAIDType`, cache policies and others) are checked against the pinned [Swordfish-Publications](https://github.com/SNIA/Swordfish-Publications) bundle in `third_party/Swordfish-Publications/json-schema`. A `$ref` to any other location fails as unresolvable.

A file is skipped when it is not a JSON object, has no `@odata.type`, or names a type that bundle does not publish. A path with no file under `normalized/` was unchanged by the proxy and was not part of this check.

The corpus is 22 models:

| Vendor | Model | Documents | Valid | Invalid | Skipped |
| --- | --- | ---: | ---: | ---: | ---: |
| Dell | PowerEdge_R630 | 114 | 114 | 0 | 0 |
| Dell | PowerEdge_R630_2 | 104 | 104 | 0 | 0 |
| Dell | PowerEdge_R640 | 371 | 371 | 0 | 0 |
| Dell | PowerEdge_R6525 | 371 | 371 | 0 | 0 |
| Dell | PowerEdge_R740 | 282 | 282 | 0 | 0 |
| Dell | PowerEdge_R7525 | 436 | 436 | 0 | 0 |
| Dell | PowerEdge_R760 | 295 | 295 | 0 | 0 |
| Dell | PowerEdge_R7625 | 384 | 384 | 0 | 0 |
| HPE | ProLiant_DL360_Gen10 | 225 | 225 | 0 | 0 |
| HPE | ProLiant_DL380_Gen10 | 231 | 231 | 0 | 0 |
| HPE | ProLiant_DL380_Gen10_2 | 333 | 333 | 0 | 0 |
| HPE | ProLiant_DL380a_Gen11 | 444 | 444 | 0 | 0 |
| HPE | ProLiant_DL385_Gen10_Plus | 348 | 348 | 0 | 0 |
| Intel | M50CYP2SBSTD | 167 | 167 | 0 | 0 |
| Lenovo | ThinkSystem_SR630_V2 | 389 | 389 | 0 | 0 |
| Lenovo | ThinkSystem_SR650_V2 | 305 | 305 | 0 | 0 |
| Lenovo | ThinkSystem_SR675_V3 | 441 | 441 | 0 | 0 |
| Lenovo | ThinkSystem_SR680a_V3_310 | 563 | 563 | 0 | 0 |
| Lenovo | ThinkSystem_SR680a_V3_610 | 548 | 548 | 0 | 0 |
| Lenovo | ThinkSystem_SR680a_V3_910 | 543 | 543 | 0 | 0 |
| Supermicro | ARS-110M-NR | 340 | 340 | 0 | 0 |
| Supermicro | SYS-220TP-HTTR | 169 | 169 | 0 | 0 |
| **Total** | **22** | **7,403** | **7,403** | **0** | **0** |

Each document was checked against one of these 66 schemas:

| Schema | Documents |
| --- | ---: |
| `#Assembly.v1_5_1.Assembly` | 22 |
| `#Bios.v1_2_0.Bios` | 18 |
| `#BootOption.v1_0_4.BootOption` | 163 |
| `#BootOptionCollection.BootOptionCollection` | 20 |
| `#Chassis.v1_25_1.Chassis` | 45 |
| `#ChassisCollection.ChassisCollection` | 22 |
| `#ComputerSystem.v1_25_0.ComputerSystem` | 22 |
| `#ComputerSystemCollection.ComputerSystemCollection` | 22 |
| `#Drive.v1_19_0.Drive` | 22 |
| `#DriveCollection.DriveCollection` | 5 |
| `#EnvironmentMetrics.v1_3_0.EnvironmentMetrics` | 86 |
| `#EthernetInterface.v1_12_1.EthernetInterface` | 141 |
| `#EthernetInterfaceCollection.EthernetInterfaceCollection` | 44 |
| `#Fan.v1_5_2.Fan` | 202 |
| `#FanCollection.FanCollection` | 13 |
| `#HostInterface.v1_3_0.HostInterface` | 21 |
| `#HostInterfaceCollection.HostInterfaceCollection` | 21 |
| `#LogEntry.v1_16_1.LogEntry` | 2081 |
| `#LogEntryCollection.LogEntryCollection` | 82 |
| `#LogService.v1_4_0.LogService` | 92 |
| `#LogServiceCollection.LogServiceCollection` | 30 |
| `#Manager.v1_19_1.Manager` | 22 |
| `#ManagerCollection.ManagerCollection` | 22 |
| `#ManagerNetworkProtocol.v1_9_0.ManagerNetworkProtocol` | 22 |
| `#Memory.v1_20_0.Memory` | 444 |
| `#MemoryCollection.MemoryCollection` | 22 |
| `#MemoryMetrics.v1_7_0.MemoryMetrics` | 207 |
| `#NetworkAdapter.v1_11_0.NetworkAdapter` | 58 |
| `#NetworkAdapter.v1_8_1.NetworkAdapter` | 3 |
| `#NetworkAdapterCollection.NetworkAdapterCollection` | 17 |
| `#NetworkInterface.v1_2_0.NetworkInterface` | 55 |
| `#NetworkInterfaceCollection.NetworkInterfaceCollection` | 20 |
| `#NetworkPort.v1_4_3.NetworkPort` | 48 |
| `#NetworkPortCollection.NetworkPortCollection` | 26 |
| `#PCIeDevice.v1_14_0.PCIeDevice` | 364 |
| `#PCIeDeviceCollection.PCIeDeviceCollection` | 32 |
| `#PCIeFunction.v1_2_3.PCIeFunction` | 23 |
| `#PCIeFunction.v1_3_0.PCIeFunction` | 4 |
| `#PCIeFunction.v1_5_0.PCIeFunction` | 436 |
| `#PCIeFunctionCollection.PCIeFunctionCollection` | 382 |
| `#PCIeSlots.v1_5_0.PCIeSlots` | 19 |
| `#Port.v1_20_0.Port` | 127 |
| `#PortCollection.PortCollection` | 27 |
| `#Power.v1_7_3.Power` | 69 |
| `#PowerSupply.v1_5_0.PowerSupply` | 46 |
| `#PowerSupplyCollection.PowerSupplyCollection` | 13 |
| `#PowerSupplyMetrics.v1_1_0.PowerSupplyMetrics` | 18 |
| `#Processor.v1_20_0.Processor` | 81 |
| `#ProcessorCollection.ProcessorCollection` | 22 |
| `#ProcessorMetrics.v1_6_0.ProcessorMetrics` | 21 |
| `#SecureBoot.v1_1_0.SecureBoot` | 17 |
| `#Sensor.v1_9_0.Sensor` | 454 |
| `#SensorCollection.SensorCollection` | 14 |
| `#SerialInterface.v1_2_0.SerialInterface` | 17 |
| `#SerialInterfaceCollection.SerialInterfaceCollection` | 20 |
| `#SoftwareInventory.v1_10_2.SoftwareInventory` | 655 |
| `#SoftwareInventoryCollection.SoftwareInventoryCollection` | 33 |
| `#Storage.v1_16_0.Storage` | 46 |
| `#StorageCollection.StorageCollection` | 25 |
| `#StorageController.v1_7_0.StorageController` | 24 |
| `#StorageControllerCollection.StorageControllerCollection` | 24 |
| `#Thermal.v1_7_3.Thermal` | 43 |
| `#VirtualMedia.v1_6_0.VirtualMedia` | 90 |
| `#VirtualMediaCollection.VirtualMediaCollection` | 22 |
| `#Volume.v1_10_0.Volume` | 52 |
| `#VolumeCollection.VolumeCollection` | 43 |

## Result

**7,403 checked, 7,403 valid, 0 invalid, 0 skipped.**

Every normalized document matches the schema for its `@odata.type`.

## Keeping the targets current

CI runs `uv run python scripts/validate_redfish_schema.py --strict` after the tests. It fails when a normalized document is invalid, and also when a document names a DMTF type at a version that is not in the pinned bundle. A normalizer that targets a version newer than the pin, or a bundle that is out of date, fails the build. OEM types, which have no DMTF schema, are skipped.

The script also prints a report-only list of deprecated schemas and properties the output still uses, taken from the `deprecated` markers in the pinned schemas. It never fails the build. Today it lists:

- **`Power` and `Thermal` (v1_7_3).** DMTF deprecated both in favor of `PowerSubsystem` and `ThermalSubsystem`. Redpool keeps serving them because redfish-inventory-exporter and fishymetrics still read them. Moving to the subsystem schemas is a separate change to those collectors.
- **`NetworkPort`.** Served only where the BMC has it. Ports are served as `Port` at `Ports`.
- **Deprecated properties.** For example `Drive.Location`, `Chassis.IndicatorLED` and `Memory.DeviceID`. These are passed through when the BMC sends them. Redpool does not add them when the BMC omits them.

To move to a newer DMTF release, update the Redfish-Publications pin, raise the `@odata.type` literals in the field maps, regenerate the outputs, and run the validator.
