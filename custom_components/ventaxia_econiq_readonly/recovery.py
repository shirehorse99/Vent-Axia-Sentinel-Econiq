"""Pure local temperature-recovery calculations and minute-sample statistics.

No network, Home Assistant imports, thermal-power estimate, or clipping. Coverage
is valid minute samples divided by the whole window's expected sample count.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
import statistics

DAY = timedelta(hours=24)
MAX_SAMPLES = 1440


def _number(value):
    if type(value) not in (int, float):
        return None
    try:
        return float(value) if math.isfinite(value) else None
    except (OverflowError, ValueError):
        return None


def _utc(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("An aware datetime is required")
    return value.astimezone(timezone.utc)


def _percentile(sorted_values, fraction):
    position = (len(sorted_values) - 1) * fraction
    low = math.floor(position)
    high = math.ceil(position)
    fraction = position - low
    return sorted_values[low] * (1 - fraction) + sorted_values[high] * fraction


def _mean(values):
    scale = max(abs(value) for value in values)
    return statistics.fmean(value / scale for value in values) * scale if scale else 0.0


def _sd(values):
    scale = max(abs(value) for value in values)
    result = statistics.stdev(value / scale for value in values) * scale if scale else 0.0
    return result if math.isfinite(result) else None


class RecoveryStatistics:
    """One device's independent rolling sample buffer; call sample each minute."""

    def __init__(self):
        self._samples = []

    @staticmethod
    def current(values: dict, connected: bool) -> dict:
        result = {"recovery_ratio": None, "temperature_lift": None,
                  "available_temperature_difference": None,
                  "remaining_temperature_difference": None,
                  "recovery_status": "Disconnected"}
        if not connected:
            return result
        readings = {key: _number(values.get(key)) for key in (
            "outdoor_temperature", "supply_temperature", "indoor_temperature",
            "supply_rpm", "extract_rpm")}
        if any(value is None for value in readings.values()):
            result["recovery_status"] = "Missing or invalid temperatures or fan readings"
            return result
        if readings["supply_rpm"] <= 0 or readings["extract_rpm"] <= 0:
            result["recovery_status"] = "Fans not running"
            return result
        outdoor, supply, indoor = (readings[key] for key in (
            "outdoor_temperature", "supply_temperature", "indoor_temperature"))
        lift, available, remaining = supply - outdoor, indoor - outdoor, indoor - supply
        if not all(math.isfinite(value) for value in (lift, available, remaining)):
            result["recovery_status"] = "Invalid temperature differences"
            return result
        result.update(temperature_lift=lift, available_temperature_difference=available,
                      remaining_temperature_difference=remaining)
        if abs(available) < 3:
            result["recovery_status"] = "Temperature difference below 3 K"
            return result
        ratio = 100 * (lift / available)
        if not math.isfinite(ratio):
            result["recovery_status"] = "Invalid recovery ratio"
            return result
        result["recovery_ratio"] = ratio
        result["recovery_status"] = ("Outside 0–100%; inspect readings and operating conditions"
                                     if not 0 <= ratio <= 100 else "Apparent temperature recovery")
        return result

    def _trim(self, now):
        start = now - DAY
        # Exclusive left edge, inclusive right edge; no fabricated gap samples.
        self._samples = [row for row in self._samples if start < row[0] <= now][-MAX_SAMPLES:]

    def sample(self, now: datetime, values: dict, connected: bool) -> None:
        now = _utc(now)
        minute = now.replace(second=0, microsecond=0)
        self._trim(now)
        # A sample belongs to a fixed UTC minute bucket. Timer jitter within a
        # minute cannot increase its weight or insert a second point.
        if self._samples and minute <= self._samples[-1][0]:
            return
        value = self.current(values, connected)
        self._samples.append((minute, value["recovery_ratio"], value["temperature_lift"]))
        self._trim(now)

    def stats(self, now: datetime) -> dict:
        now = _utc(now)
        self._trim(now)
        ratio_rows = [row for row in self._samples if row[1] is not None]
        ratios = [row[1] for row in ratio_rows]
        hour_ratios = [row[1] for row in ratio_rows if now - timedelta(hours=1) < row[0]]
        lifts = [row[2] for row in self._samples if row[2] is not None]
        ordered = sorted(ratios)
        return {
            "recovery_mean_1h": _mean(hour_ratios) if hour_ratios else None,
            "recovery_mean_24h": _mean(ratios) if ratios else None,
            "recovery_median_24h": _percentile(ordered, .5) if ratios else None,
            "recovery_minimum_24h": min(ratios) if ratios else None,
            "recovery_maximum_24h": max(ratios) if ratios else None,
            "recovery_sd_24h": _sd(ratios) if len(ratios) >= 2 else None,
            "recovery_p10_24h": _percentile(ordered, .1) if len(ordered) >= 20 else None,
            "recovery_p90_24h": _percentile(ordered, .9) if len(ordered) >= 20 else None,
            "recovery_samples_24h": len(ratios),
            "recovery_coverage_1h": min(100.0, len(hour_ratios) / 60 * 100),
            "recovery_coverage_24h": min(100.0, len(ratios) / 1440 * 100),
            "recovery_oldest_sample": ratio_rows[0][0] if ratio_rows else None,
            "recovery_newest_sample": ratio_rows[-1][0] if ratio_rows else None,
            "lift_mean_24h": _mean(lifts) if lifts else None,
            "lift_minimum_24h": min(lifts) if lifts else None,
            "lift_maximum_24h": max(lifts) if lifts else None,
        }

    def snapshot(self) -> dict:
        return {"samples": [{"at": at.isoformat(), "ratio": ratio, "lift": lift}
                            for at, ratio, lift in self._samples]}

    def restore(self, data, now: datetime) -> None:
        now = _utc(now)
        self._samples = []
        if not isinstance(data, dict) or not isinstance(data.get("samples"), list):
            return
        rows = data["samples"]
        # Refuse oversized snapshots before sorting/copying; bounded persistence
        # never needs more than 1440 points, including invalid minute markers.
        if len(rows) > MAX_SAMPLES:
            return
        points = {}
        for row in rows:
            if not isinstance(row, dict) or len(row) != 3 or set(row) != {"at", "ratio", "lift"}:
                continue
            text = row["at"]
            if not isinstance(text, str) or len(text) > 64:
                continue
            try:
                at = _utc(datetime.fromisoformat(text))
            except (ValueError, OverflowError):
                continue
            if at.second or at.microsecond or not now - DAY < at <= now:
                continue
            ratio = _number(row["ratio"])
            lift = _number(row["lift"])
            if (row["ratio"] is not None and ratio is None) or (row["lift"] is not None and lift is None):
                continue
            # A valid ratio requires a valid temperature lift from the same sample.
            if ratio is not None and lift is None:
                continue
            if at in points:
                continue
            points[at] = (at, ratio, lift)
        self._samples = sorted(points.values(), key=lambda point: point[0])
