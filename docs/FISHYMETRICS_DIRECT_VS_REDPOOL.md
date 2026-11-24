# fishymetrics: direct vs redpool golden comparison

Compared `fishymetrics_direct.prom` with `fishymetrics_redpool.prom` for each fixtures model. Direct is fishymetrics against the mock. Redpool is fishymetrics against the proxy in front of the same mock. Counts are data lines. The goldens were generated with fishymetrics v0.20.0.

## Summary

| Model | Direct | Redpool | Delta |
|-------|-------:|--------:|------:|
| Dell/PowerEdge_R630 | 143 | 143 | 0 |
| Dell/PowerEdge_R630_2 | 127 | 127 | 0 |
| Dell/PowerEdge_R640 | 81 | 81 | 0 |
| Dell/PowerEdge_R6525 | 87 | 87 | 0 |
| Dell/PowerEdge_R740 | 71 | 71 | 0 |
| Dell/PowerEdge_R7525 | 82 | 82 | 0 |
| Dell/PowerEdge_R760 | 88 | 88 | 0 |
| Dell/PowerEdge_R7625 | 91 | 91 | 0 |
| HPE/ProLiant_DL360_Gen10 | 168 | 168 | 0 |
| HPE/ProLiant_DL380_Gen10 | 153 | 159 | +6 |
| HPE/ProLiant_DL380_Gen10_2 | 159 | 159 | 0 |
| HPE/ProLiant_DL380a_Gen11 | 145 | 145 | 0 |
| HPE/ProLiant_DL385_Gen10_Plus | 139 | 139 | 0 |
| Intel/M50CYP2SBSTD | 30 | 152 | +122 |
| Lenovo/ThinkSystem_SR630_V2 | 84 | 84 | 0 |
| Lenovo/ThinkSystem_SR650_V2 | 121 | 121 | 0 |
| Lenovo/ThinkSystem_SR675_V3 | 110 | 110 | 0 |
| Lenovo/ThinkSystem_SR680a_V3_310 | 175 | 175 | 0 |
| Lenovo/ThinkSystem_SR680a_V3_610 | 175 | 175 | 0 |
| Lenovo/ThinkSystem_SR680a_V3_910 | 175 | 175 | 0 |
| Supermicro/ARS-110M-NR | 80 | 68 | −12 |
| Supermicro/SYS-220TP-HTTR | 122 | 122 | 0 |

Series that exist on only one side are listed below. Every model also has label changes on series that exist on both sides. Fishymetrics status gauges use `1` for OK and `0` otherwise.

## Series redpool adds

- **Intel thermal and power.** M50CYP2SBSTD direct emits CPU, memory, one disk, and device info (30 lines). Redpool also emits fans (6), thermal sensors (36 temperatures, 36 status, 31 critical thresholds), two voltage readings and their status, two power-supply status series, and `redfish_power_supply_total_consumed` (+122).
- **HPE SR volumes.** DL380 Gen10 `redfish_logical_drive_status` goes from 1 to 7. The six added series are `SR Volume 65`, `69`, `81`, `85`, `89`, and `93`.

## Series redpool drops

- **Supermicro PWM fans.** ARS-110M-NR direct emits `redfish_thermal_fan_speed` and `redfish_thermal_fan_status` for FAN1–FAN6 (RPM, about 8800) and for Pwm 1–Pwm 6 (duty cycle 37). Redpool keeps FAN1–FAN6 only. The speed gauge on those fans is 37, the PWM duty cycle, and the six Pwm speed series and six Pwm status series are absent (−12). Thermal sensor series stay on both paths.

## Value changes on shared series

- **Lenovo power-supply output.** `redfish_power_supply_output` on SR630 V2, SR650 V2, SR675 V3, and SR680a V3 310/610/910. Direct repeats one chassis total on every supply (158, 399, 1105, or 2285). Redpool reports that supply’s own output (for example SR630 PSU1 158 → 86, PSU2 158 → 75).
- **Lenovo thermal summary.** `redfish_thermal_summary_status` is 0 on direct and 1 on redpool for all six Lenovo models. Same labels.
- **Lenovo GPU health.** `redfish_cpu_status` for the eight GPUs on SR675 V3 and on each SR680a V3 is 0 on direct and 1 on redpool. The `model` label is filled at the same time (`NVIDIA H100 NVL` on SR675, `NVIDIA H200` on the SR680a models).

## Label changes on shared series

| Metric | Label | Direct | Redpool |
|--------|-------|--------|---------|
| `redfish_cpu_status` | `model` | BMC string, often with `CPU @ …GHz`, or empty on GPUs | Canonical name, for example `Intel(R) Xeon(R) Gold 6338`, `Ampere(R) Altra(R) Q32-17`, `NVIDIA H200` |
| `redfish_memory_dimm_status` | `manufacturer` | `Samsung`, `Micron`, `HPE`, or empty (183 DIMMs) | `Samsung Electronics Co., Ltd.`, `Micron Technology` |
| `redfish_power_supply_*` | `name` | `PS1 Status` / `PS2 Status`, or one `HpeServerPowerSupply` | `PS1` / `PS2`, or `PSU Bay 1` and so on |
| `redfish_power_supply_*` | `manufacturer` | vendor code such as `DELL`, `DELTA`, `GREA`, `ACBE`, `LTEON` | vendor name, for example `Delta Electronics, Inc.`, `Great Wall Power Technology Company Limited` |
| `redfish_thermal_fan_speed`, `redfish_thermal_fan_status` | `name` | `Fan 1A Tach` on Lenovo | `Fan 1A` |
| `redfish_logical_drive_status` | `name`, `raid` | `HpeSmartStorageLogicalDrive`, raid `1` or `10` | volume name, raid `RAID1` or `RAID10` |
| `redfish_storage_controller_status` | `name` | `Hpe Smart Storage Array Controller` | `HPE Smart Array P408i-a SR Gen10` or `HPE Smart Array E208i-a SR Gen10` |

`chassisSerialNumber` is `DUMMY-SerialNumber` on both paths.

## Regenerating goldens

From the repository root:

```bash
uv run python scripts/generate_fishymetrics_golden.py --no-proxy
uv run python scripts/generate_fishymetrics_golden.py
```

## Recommendation

Use redpool in front of fishymetrics. It fills processor model strings (including Lenovo GPUs and the Ampere and Intel CPU names), expands memory and power-supply manufacturers, names HPE supplies per bay, drops the Dell `Status` suffix on PSU names, and strips the Lenovo `Tach` suffix from fan names. It reports each Lenovo supply’s own output watts, sets Lenovo thermal summary and GPU health to OK, and exposes the Intel fan, thermal, voltage, and power-supply series that the direct scrape misses. It also exposes the six DL380 Gen10 SR volumes. On Supermicro ARS-110M-NR the PWM entries share the physical fan name, so the speed gauge is the duty cycle and the separate Pwm series are absent.
