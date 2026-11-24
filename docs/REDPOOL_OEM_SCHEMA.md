# Redpool OEM extension

Redpool adds its own data to normalized Redfish resources under `Oem.Redpool`. That data is not defined by DMTF. This page and the schema below define it.

## Name and casing

The name is capitalized: `Oem.Redpool`. Redpool never writes a lowercase `Oem.redpool`. Vendor blocks keep their own names, such as `Oem.Dell` or `Oem.Hpe`, and Redpool leaves them as the BMC sent them.

## Schema

The published schema is [`schemas/json-schema/Redpool.v1_0_0.json`](../schemas/json-schema/Redpool.v1_0_0.json). It is JSON Schema draft-07, in the same dialect as the DMTF bundle.

Each `Oem.Redpool` object names the definition for its owning resource in its own `@odata.type`, for example `#Redpool.v1_0_0.RedpoolChassis`. Redpool stamps this type on every normalized response. An object with no type in the namespace fails validation.

Each definition sets `additionalProperties: false`. A new key fails validation until the schema is updated, so the schema lists everything Redpool emits.

## Generated from the fixtures

`scripts/generate_redpool_oem_schema.py` builds the schema from the normalized fixtures, so it describes what Redpool actually emits. A test checks that the generator still reproduces the committed file. `scripts/validate_redfish_schema.py` checks every fixture block against the schema, and reports the result next to the DMTF result.

## Definitions

| Definition | Properties | Names |
|---|---|---|
| `RedpoolBios` | 1 | `BypassBIOSPwFlag` |
| `RedpoolChassis` | 16 | `EngineeringChangeLevel`, `FruPartNumber`, `ManufactureDate`, `ManufactureWeek`, `ManufactureYear`, `MultiNodeBackplaneModelName`, `MultiNodeBackplaneSerialNo`, `MultiNodeChassisPartNo`, `MultiNodeChassisSerialNo`, `MultiNodeConfigurationID`, `MultiNodeNodes`, `MultiNodeNodesUri`, `MultiNodeSelfID`, `MultiNodeSystemPartNo`, `MultiNodeSystemSerialNo`, `MultiNodeTwinType` |
| `RedpoolComputerSystem` | 25 | `AggregateServerHealth`, `BatteryRollupStatus`, `CPURollupStatus`, `ChassisServiceTag`, `CoolingRollupStatus`, `CurrentRollupStatus`, `EstimatedExhaustTemperatureCelsius`, `EstimatedSystemAirflowCFM`, `ExpressServiceCode`, `FanRedundancy`, `FanRollupStatus`, `IntrusionRollupStatus`, `LicensingRollupStatus`, `NodeID`, `PCAPartNumber`, `PSRollupStatus`, `PlatformGUID`, `PostState`, `SDCardRollupStatus`, `SELRollupStatus`, `StorageRollupStatus`, `SystemHealthRollupStatus`, `TempRollupStatus`, `TempStatisticsRollupStatus`, `VoltRollupStatus` |
| `RedpoolDrive` | 1 | `HpeSmartStorage` |
| `RedpoolEnvironmentMetrics` | 1 | `AverageFanPWM` |
| `RedpoolFan` | 1 | `FanPWM` |
| `RedpoolLogEntry` | 36 | `AffectedIndicatorLEDs`, `AuxiliaryData`, `Categories`, `Category`, `Class`, `ClassDescription`, `Code`, `Comment`, `CommonEventID`, `Count`, `EventFlag`, `EventNumber`, `EventSequenceNumber`, `EventType`, `FQDD`, `FailingFRU`, `Hidden`, `Interface`, `IsLocalEvent`, `LastUpdatedByUser`, `LearnMoreLink`, `LenovoMessageID`, `MarkAsAcknowledged`, `RawDebugLogURL`, `RawEventData`, `RecommendedAction`, `RelatedEventID`, `Repaired`, `ReportingChain`, `Serviceable`, `Source`, `SubSystem`, `TSLVersion`, `TotalSequenceNumber`, `User`, `UserAction` |
| `RedpoolMemory` | 5 | `EccBits`, `FruPartNumber`, `ManufactureDate`, `ManufactureWeek`, `ManufactureYear` |
| `RedpoolNetworkAdapter` | 12 | `EngineeringChangeLevel`, `FcPorts`, `Firmware`, `FruPartNumber`, `Location`, `ManufactureDate`, `ManufactureWeek`, `ManufactureYear`, `PhysicalPorts`, `StructuredName`, `UEFIDevicePath`, `UUID` |
| `RedpoolPort` | 1 | `PhysicalPortNumber` |
| `RedpoolPower` | 6 | `EngineeringChangeLevel`, `FruPartNumber`, `ManufactureDate`, `ManufactureWeek`, `ManufactureYear`, `SensorNumber` |
| `RedpoolPowerSupply` | 1 | `FruPartNumber` |
| `RedpoolSoftwareInventory` | 1 | `FirmwareInventory` |
| `RedpoolStorage` | 2 | `ControllerBattery`, `HpeSmartStorage` |
| `RedpoolStorageController` | 6 | `EngineeringChangeLevel`, `FruPartNumber`, `HpeSmartStorage`, `ManufactureDate`, `ManufactureWeek`, `ManufactureYear` |
| `RedpoolVolume` | 1 | `HpeSmartStorage` |

`HpeSmartStorage` is shared. It appears under the storage and drive resources and is defined once. Its properties are: `Kind` (one of `ArrayController`, `DiskDrive`, `LogicalDrive`, `SmartStorageBattery`) and `ChargeLevelPercent`, `MaximumCapWatts`, `RemainingChargeTimeSeconds`, `TemperatureCelsius`, `UncorrectedReadErrors`, `UncorrectedWriteErrors`.

## Descriptions

Each property currently carries a generic description. Replace it with a real one when you propose or change a property.

## Versioning

- A new optional property is additive: bump the minor version (`v1_1_0`).
- Removing, renaming, or changing the type of a property is breaking: bump the major version (`v2_0_0`).
- Consumers must ignore unknown properties only within the version they were built for, because the schema is closed.

## Proposing a property

1. Add the value in the normalizer, under `Oem.Redpool`, with a name that matches its meaning.
2. Run `uv run python scripts/generate_redpool_oem_schema.py` from the repository root, and give the property a real description in the schema.
3. Regenerate the fixtures and run `uv run --extra dev python scripts/validate_redfish_schema.py`.
4. Update this page.
