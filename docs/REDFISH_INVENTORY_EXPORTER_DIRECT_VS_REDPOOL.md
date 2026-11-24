# redfish-inventory-exporter: direct vs redpool golden comparison

Compared `redfish_inventory_exporter_direct.prom` with `redfish_inventory_exporter_redpool.prom` for each fixtures model. Direct is the collector against the mock. Redpool is the collector against the proxy in front of the same mock. Counts are data lines. The goldens contain `redfish_*` series only.

## Summary

| Model | Direct | Redpool | Delta |
|-------|-------:|--------:|------:|
| Dell/PowerEdge_R630 | 948 | 950 | +2 |
| Dell/PowerEdge_R630_2 | 820 | 822 | +2 |
| Dell/PowerEdge_R640 | 1,200 | 1,217 | +17 |
| Dell/PowerEdge_R6525 | 1,412 | 1,429 | +17 |
| Dell/PowerEdge_R740 | 1,148 | 1,164 | +16 |
| Dell/PowerEdge_R7525 | 1,452 | 1,484 | +32 |
| Dell/PowerEdge_R760 | 1,431 | 1,447 | +16 |
| Dell/PowerEdge_R7625 | 1,494 | 1,513 | +19 |
| HPE/ProLiant_DL360_Gen10 | 711 | 738 | +27 |
| HPE/ProLiant_DL380_Gen10 | 716 | 781 | +65 |
| HPE/ProLiant_DL380_Gen10_2 | 641 | 709 | +68 |
| HPE/ProLiant_DL380a_Gen11 | 877 | 894 | +17 |
| HPE/ProLiant_DL385_Gen10_Plus | 664 | 716 | +52 |
| Intel/M50CYP2SBSTD | 1,313 | 1,617 | +304 |
| Lenovo/ThinkSystem_SR630_V2 | 948 | 954 | +6 |
| Lenovo/ThinkSystem_SR650_V2 | 1,303 | 1,309 | +6 |
| Lenovo/ThinkSystem_SR675_V3 | 1,208 | 1,216 | +8 |
| Lenovo/ThinkSystem_SR680a_V3_310 | 1,466 | 1,466 | 0 |
| Lenovo/ThinkSystem_SR680a_V3_610 | 1,493 | 1,507 | +14 |
| Lenovo/ThinkSystem_SR680a_V3_910 | 1,430 | 1,444 | +14 |
| Supermicro/ARS-110M-NR | 967 | 943 | −24 |
| Supermicro/SYS-220TP-HTTR | 653 | 686 | +33 |

Series that exist on only one side are listed below. Every model also has label changes on series that exist on both sides.

## Series redpool adds

- **Power supply capacity.** `redfish_powersupply_power_capacity_watts` on R630 and R630_2 (750 W for PS1 and PS2). Other Dells already expose that gauge on both paths. HPE models split one `HpeServerPowerSupply` series into one series per bay, so capacity, input volts, output watts, health, and state go from 1 to 2 (DL360, DL380, DL380 Gen10_2, DL385) or 1 to 4 (DL380a Gen11).
- **System rollup health.** `redfish_system_rollup_health_info` on R640 (15), R6525 (14), R740 (14), R7525 (14), R760 (14), and R7625 (14).
- **Dell airflow and exhaust.** `redfish_system_estimated_airflow_cfm` and `redfish_system_estimated_exhaust_temperature_celsius` on R640, R6525, R740, R7525, R760, and R7625. The `SystemAirFlow` chassis sensor stays on both paths. On R640 that sensor and the system gauge are both 20 CFM.
- **Drive spare.** `redfish_storage_drive_available_spare_percent` on R6525 (1), R7525 (16), and R7625 (3).
- **HPE storage and network.** Drive temperature and uncorrected read/write errors on DL360, DL380, DL380 Gen10_2, and DL385. Storage battery metrics, controller, drive inventory, and volumes where the direct scrape does not see the Smart Array tree (DL380 Gen10_2, DL385). Network adapters and ports on DL380 (4 ports; adapter count 1 to 2), DL380 Gen10_2 (2 adapters, 6 ports), and DL385 (1 adapter, 4 ports). DL380 keeps the RAID1 volume and the six SR volumes (`65`, `69`, `81`, `85`, `89`, `93`).
- **HPE PCIe.** On DL380 Gen10, direct has one PCIe series, `RootService` / `HPE RESTful Root Service`. Redpool has the Smart Array, the I350, the FlexFabric adapter, and the embedded video controller.
- **Intel thermal and power.** M50CYP2SBSTD gains voltage, power-supply, fan, and thermal-sensor families (+304). Direct does not emit those series.
- **GPU power limit.** `redfish_processor_power_limit_watts` (8 series) on SR675 V3, SR680a V3 610, and SR680a V3 910.
- **Lenovo ports.** Network port health, info, and state go from 2 to 4 on SR630 V2 and SR650 V2, and gain two ports on SR680a V3 610 (10 to 12) and 910 (9 to 11).
- **Lenovo power-supply output.** On every Lenovo model, `redfish_powersupply_output_watts` on the direct path repeats the chassis total on each supply (for example 2285 W on all eight SR680a V3 310 supplies). Redpool reports the per-supply reading (about 230–320 W on those supplies).
- **Supermicro multinode.** SYS-220TP-HTTR gains `redfish_chassis_multinode_*` and `redfish_multinode_chassis_info` (+33).

## Series redpool drops

- **HPE collection members that are not volumes or ports.** DL360 volumes go from 3 to 2 and DL380 volumes go from 8 to 7 because the `Capabilities` member is omitted. DL380a Gen11 network ports go from 11 to 10 because the `DA000000` / `RootService` port is omitted, while `redfish_network` goes from 9 to 10 (`DE07A000` and `DE081000` replace `RootService`).
- **Supermicro thermal fans.** ARS-110M-NR direct emits thermal-fan series for FAN1–FAN6 and Pwm 1–Pwm 6. FAN speed percent on that path is the RPM ratio (about 22). Redpool keeps FAN1–FAN6 and reports the PWM duty cycle (37) on `redfish_thermal_fan_speed_percent`. That removes 6 series from fan info, health, speed percent, and state (−24). The `Pwm 1`–`Pwm 6` chassis sensors stay on both paths.

## Label changes on shared series

| Metric | Label | Direct | Redpool |
|--------|-------|--------|---------|
| `redfish_processor_info` | `base_speed_mhz` | `0` when the BMC omits it (43 processors) | Filled, for example 2100, 2300, 2200 |
| `redfish_processor_info` | `part_number` | empty (40 processors) | CPU name, for example Xeon Gold 6430, Xeon E5-2650 v4 |
| `redfish_processor_info` | `processor_id_vendor_id` | `GenuineIntel`, `AuthenticAMD`, `0x10de` (71 processors) | `Intel(R) Corporation`, `Advanced Micro Devices, Inc.`, `Nvidia Corporation` |
| `redfish_powersupply_info` | `name` | `PS1 Status` / `PS2 Status`, or one `HpeServerPowerSupply` (28 supplies) | `PS1` / `PS2`, or `PSU Bay 1` and so on |
| `redfish_powersupply_info` | `manufacturer` | vendor code such as `GREA` (60 supplies) | expanded name, for example Great Wall Power Technology Company Limited |
| `redfish_memory` | `part_number` | trailing spaces, including `NOT AVAILABLE   ` | trimmed |
| `redfish_memory` | `manufacture_date`, `manufacture_week`, `manufacture_year` | empty on 256 DIMMs | filled. Lenovo ISO week `year 2023 week 28` becomes `manufacture_date` `2023-07-10` |
| `redfish_memory` | `ecc_bits` | empty (375 DIMMs) | `8` |
| `redfish_firmware_inventory_info` | `inventory_slot`, `related_kind`, `related_ref`, `device_context` | empty | filled, for example `installed` / `current` / `previous`, `network_adapter`, `drive`, `bios` |
| `redfish_pcie_device_info` | `manufacturer` | vendor string from the BMC, often with an `[AMD]` suffix or `NVIDIA` | canonical vendor name |
| `serial_number` | — | `DUMMY-SerialNumber` | `DUMMY-SerialNumber` |

`link_status` on `redfish_network_port_state_info` is `LinkUp`, `LinkDown`, or `NoLink` on both paths. A port with no status leaves the label empty.

## Regenerating goldens

From the repository root:

```bash
uv run python scripts/generate_redfish_inventory_exporter_golden.py --no-proxy
uv run python scripts/generate_redfish_inventory_exporter_golden.py
```

## Recommendation

Use redpool in front of redfish-inventory-exporter. It fills processor speed, part number, and vendor id, memory manufacture dates and ECC width, firmware-inventory relation labels, and per-bay power-supply names. Lenovo power-supply output is the per-supply wattage instead of the repeated chassis total. It also exposes chassis PCIe devices, HPE storage and network ports, Intel thermal and power, Lenovo GPU power limits, Dell airflow and exhaust, and Supermicro multinode metrics that the direct scrape misses. It omits the HPE service-root PCIe series, the volume `Capabilities` member, and the Supermicro PWM entries under the thermal-fan metrics. Chassis sensors are kept on both paths, including `SystemAirFlow` and readings that also appear on a power-supply or processor gauge.
