# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Mask when and where a capture was taken: time zones, timestamps and uptime counters.

Event timestamps share a capture-specific shift to preserve ordering and durations.
Certificate validity bypasses the shift. Power-monitor epochs use synthetic instants.
Zones become UTC, manufacture and licence dates are rounded, and uptime counters are scaled.

Each capture's offset comes from a secret key and the capture's name.
The pass is applied once per capture. ``metadata.json`` records the version as ``time_policy``.
"""

from __future__ import annotations

import hmac
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from .sanitize import _CERT_DATES, certificate_document

_ISO_RE = re.compile(
    r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})T(\d{2}):(\d{2}):(\d{2})(\.\d+)?"
    r"(Z|[+-]\d{2}:\d{2})?(?!\d)"
)
_MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
CTIME_RE = re.compile(
    r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) ("
    + "|".join(_MONTHS)
    + r") +(\d{1,2}) (\d{2}:\d{2}:\d{2}) (UTC |GMT )?(\d{4})\b( UTC\b| GMT\b)?"
)
# Values already damaged by an earlier sanitizer pass (hh:mm:ss became ::1) cannot be
# shifted, so their month and day are dropped and the year kept.
_MANGLED_MONTH_DAY_RE = re.compile(
    r"(?:[A-Z][a-z]{2} )?[A-Z][a-z]{2} +\d{1,2} (::\d)((?: [A-Z]{3})?) (\d{4})((?: [A-Z]{3})?)"
)
_MANGLED_DAY_FIRST_RE = re.compile(r"\d{1,2} [A-Z][a-z]{2} (\d{4}), (::\d\.\d+ [AP]M)")
_DAY_MONTH_YEAR_RE = re.compile(r"\d{1,2} [A-Z][a-z]{2} (\d{4})")

_ZONE_NAME_LEAVES = frozenset({"TimeZoneName", "Timezone"})
_MONTH_LEAVES = frozenset(
    {"ManufactureDate", "ProductionDate", "DIMMManufacturingDate"}
)
_YEAR_LEAVES = frozenset({"LicenseSoldDate", "LicenseInstallDate"})
_COUNTER_LEAVES = frozenset(
    {
        "PowerOnMinutes",
        "PowerOnHours",
        "TotalPowerOnHours",
        "NumberOfReboots",
        "ServerPoweredOnTime",
    }
)
_UTC_HPE_ZONE = {"Index": 0, "Name": "UTC", "UtcOffset": "+00:00", "Value": "UTC0"}
# Years outside this range are sentinels (0000-00-00, 1970, 1996-01-01, 9999-12-31).
_YEAR_MIN, _YEAR_MAX = 2000, 2100
# Supermicro log entry ids are epoch microseconds (16 digits) or milliseconds (13 digits).
_EPOCH_ID_RE = re.compile(r"(?<!\d)(\d{16}|\d{13})(?!\d)")
_EPOCH_ID_LEAVES = frozenset({"Id", "@odata.id"})
_EPOCH_RANGE = (1_420_070_400, 2_051_222_400)  # 2015-01-01 to 2035-01-01, in seconds
TIME_POLICY_VERSION = 3
_POWER_EPOCH_KEYS = {
    "ServerPwrMon.1." + field
    for field in (
        "CumulativePowerStartTime",
        "MinPowerTime",
        "PeakCurrentTime",
        "PeakPowerStartTime",
        "PeakPowerTime",
    )
}
_LENOVO_CLOCK = re.compile(
    r"\d{1,2} [A-Z][a-z]{2} \d{4}, \d{1,2}:\d{2}:\d{2}\.\d+ [AP]M"
)


def _mask_power_epochs(doc):
    # These times have been published. Use synthetic instants independent of the secret shift.
    fields = {
        key: value
        for key, value in doc.items()
        if key in _POWER_EPOCH_KEYS and re.fullmatch(r"[1-9]\d{8,9}", str(value))
    }
    ordered = sorted({int(value) for value in fields.values()})
    for key, value in fields.items():
        synthetic = 946684800 + ordered.index(int(value))
        doc[key] = str(synthetic) if isinstance(value, str) else synthetic


def _display_time(instant: datetime) -> str:
    return (
        instant.strftime("%d %b %Y, %I:%M:%S.")
        + f"{instant.microsecond // 1000:03d} "
        + instant.strftime("%p")
    )


def paired_display_time(row: dict) -> Optional[str]:
    """Render the companion UTC timestamp in Lenovo's OEM display format."""
    twin = row.get("TimestampWithTZ")
    if not isinstance(twin, str) or not _ISO_RE.fullmatch(twin):
        return None
    try:
        instant = datetime.fromisoformat(twin.replace("Z", "+00:00"))
    except ValueError:
        return None
    if instant.tzinfo:
        instant = instant.astimezone(timezone.utc)
    return _display_time(instant)


def _leaf(key: Optional[str]) -> str:
    return key.rsplit(".", 1)[-1] if key else ""


class TemporalMasker:
    """One capture's time masking, keyed by a secret and the capture's name."""

    def __init__(self, secret: bytes, capture: str) -> None:
        digest = hmac.new(secret, capture.encode(), "sha256").hexdigest()
        # 40 to 399 days into the past, plus up to a day of seconds.
        days = 40 + int(digest[:4], 16) % 360
        seconds = int(digest[4:8], 16) % 86400
        self.shift = timedelta(seconds=-(days * 86400 + seconds))
        # Cumulative counters scale by 0.85 to 1.14, the same for every counter of a capture.
        self._counter_factor = 0.85 + (int(digest[8:12], 16) % 30) / 100

    @staticmethod
    def _as_utc_label(m: re.Match) -> str:
        """A value that is not shifted still must not carry the site's UTC offset."""
        zone = m.group(8)
        if zone and zone != "Z" and zone != "+00:00":
            return m.group(0)[: -len(zone)] + "+00:00"
        return m.group(0)

    def _shift_match(self, m: re.Match) -> str:
        year, month, day, hour, minute, second = (int(g) for g in m.groups()[:6])
        frac, zone = m.group(7) or "", m.group(8)
        if not _YEAR_MIN <= year <= _YEAR_MAX:
            return self._as_utc_label(m)
        try:
            dt = datetime(year, month, day, hour, minute, second)
        except ValueError:
            return self._as_utc_label(m)
        if zone and zone != "Z":
            sign = 1 if zone[0] == "+" else -1
            dt -= sign * timedelta(hours=int(zone[1:3]), minutes=int(zone[4:6]))
        dt += self.shift
        suffix = "" if zone is None else ("Z" if zone == "Z" else "+00:00")
        return f"{dt:%Y-%m-%dT%H:%M:%S}{frac}{suffix}"

    def shift_text(self, text: str) -> str:
        """Shift every ISO timestamp inside *text*; offsets become UTC."""
        return _ISO_RE.sub(self._shift_match, text)

    @staticmethod
    def _ctime_to_iso(match: re.Match) -> str:
        month, day, clock, leading_zone, year, trailing_zone = match.groups()
        zone = "Z" if leading_zone or trailing_zone else ""
        return f"{year}-{_MONTHS.index(month) + 1:02d}-{int(day):02d}T{clock}{zone}"

    @staticmethod
    def _round(text: str, leaf: str) -> str:
        """Month (manufacture) or year (licence) precision; the rest of the value is kept."""
        month = leaf in _MONTH_LEAVES

        def repl(m: re.Match) -> str:
            year, mon = int(m.group(1)), int(m.group(2)) if month else 1
            return (
                f"{year:04d}-{mon:02d}-01T00:00:00{m.group(7) or ''}{m.group(8) or ''}"
            )

        out = _ISO_RE.sub(repl, text)
        if out == text and not month:
            out = _DAY_MONTH_YEAR_RE.sub(r"1 Jan \1", text)
        return out

    @staticmethod
    def _coarsen_mangled(text: str) -> str:
        """Keep only the year of dates an earlier pass damaged (their time became ::1)."""
        text = _MANGLED_MONTH_DAY_RE.sub(r"Jan 1 \1\2 \3\4", text)
        return _MANGLED_DAY_FIRST_RE.sub(r"1 Jan \1, \2", text)

    def _scale(self, value: int) -> int:
        return max(1, round(value * self._counter_factor))

    def _shift_epoch_ids(self, text: str) -> str:
        """Shift 13- and 16-digit epoch ids, keeping their width."""
        delta = int(self.shift.total_seconds())

        def repl(m: re.Match) -> str:
            digits = m.group(1)
            unit = 1_000_000 if len(digits) == 16 else 1_000
            if not _EPOCH_RANGE[0] <= int(digits) // unit <= _EPOCH_RANGE[1]:
                return digits
            return str(int(digits) + delta * unit)

        return _EPOCH_ID_RE.sub(repl, text)

    @staticmethod
    def legacy_path_timestamps(path: str, resource_id: str) -> dict[str, str]:
        """Recover the shifted timestamps from a v1 mockup's already-masked @odata.id."""
        if _ISO_RE.sub("", path) != _ISO_RE.sub("", resource_id):
            return {}
        before = list(_ISO_RE.finditer(path))
        after = list(_ISO_RE.finditer(resource_id))
        if len(before) != len(after):
            return {}
        return {
            old.group(0): new.group(0)
            for old, new in zip(before, after)
            if new.group(8) in {None, "Z", "+00:00"}
        }

    def shift_path(
        self, text: str, *, legacy_timestamps: Optional[dict[str, str]] = None
    ) -> str:
        """Shift resource IDs consistently in paths and metadata URLs."""
        if legacy_timestamps is None:
            return self.shift_text(self._shift_epoch_ids(text))

        def repair(m: re.Match) -> str:
            if m.group(0) in legacy_timestamps:
                return legacy_timestamps[m.group(0)]
            if m.group(8) not in {None, "Z", "+00:00"}:
                return self._shift_match(m)
            return m.group(0)

        return _ISO_RE.sub(repair, text)

    def _string(self, key: Optional[str], value: str, legacy: bool) -> str:
        leaf = _leaf(key)
        round_date = leaf in _MONTH_LEAVES or leaf in _YEAR_LEAVES
        if legacy:

            def mask_ctime(match: re.Match) -> str:
                timestamp = self.shift_text(self._ctime_to_iso(match))
                return self._round(timestamp, leaf) if round_date else timestamp

            return CTIME_RE.sub(mask_ctime, value)
        if leaf in _ZONE_NAME_LEAVES:
            return "UTC"
        if leaf == "DateTimeLocalOffset":
            return "+00:00"
        if leaf == "TimeZone" and re.fullmatch(r"Utc[PM]\d+", value):
            return "Utc0"
        text = self._coarsen_mangled(
            self.shift_text(CTIME_RE.sub(self._ctime_to_iso, value))
        )
        if leaf in _EPOCH_ID_LEAVES:
            text = self._shift_epoch_ids(text)
        if round_date:
            text = self._round(text, leaf)
        return text

    def mask(
        self, data: Any, key: Optional[str] = None, *, legacy: bool = False
    ) -> Any:
        """Return *data* with its times and counters masked."""
        if isinstance(data, dict):
            if not legacy and _leaf(key) == "TimeZone" and "UtcOffset" in data:
                return dict(_UTC_HPE_ZONE)
            certificate = certificate_document(data)
            out = {}
            for k, v in data.items():
                if _leaf(k) in _CERT_DATES and (
                    certificate or k.startswith("SecurityCertificate.")
                ):
                    out[k] = v
                else:
                    out[k] = self.mask(v, k, legacy=legacy)
            _mask_power_epochs(out)
            stamp = data.get("Timestamp")
            if isinstance(stamp, str) and (
                _LENOVO_CLOCK.fullmatch(stamp) or _MANGLED_DAY_FIRST_RE.fullmatch(stamp)
            ):
                twin = paired_display_time(out)
                if twin:
                    out["Timestamp"] = twin
                elif _LENOVO_CLOCK.fullmatch(stamp):
                    try:
                        instant = (
                            datetime.strptime(stamp, "%d %b %Y, %I:%M:%S.%f %p")
                            + self.shift
                        )
                    except ValueError:
                        instant = datetime(2000, 1, 1)
                    out["Timestamp"] = _display_time(instant)
            return out
        if isinstance(data, list):
            return [self.mask(v, key, legacy=legacy) for v in data]
        if isinstance(data, str):
            return self._string(key, data, legacy)
        if (
            not legacy
            and isinstance(data, int)
            and not isinstance(data, bool)
            and data > 0
            and _leaf(key) in _COUNTER_LEAVES
        ):
            return self._scale(data)
        return data

    def collection_date(self, timestamp: str) -> str:
        """``collection_timestamp`` as a shifted UTC date with no time of day."""
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", timestamp):
            timestamp += "T00:00:00"
        return self.shift_text(timestamp).split("T", 1)[0]
