"""Strict CSV loading and reproducible synthetic telemetry generation."""
import csv
from datetime import date, timedelta
from math import isfinite
from pathlib import Path
from random import Random

from .models import DataError, Reading

FIELDS = ("bin_id", "district", "latitude", "longitude", "capacity_m3",
          "observed_on", "fill_pct")


def load_csv(path: Path) -> list[Reading]:
    """Read UTF-8 CSV, rejecting duplicates, inconsistent metadata and resets.

    All bins must share their last observation date. A decreasing fill level
    represents a collection/reset; split such data into separate cycles first.
    """
    readings, seen, metadata, series = [], set(), {}, {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(FIELDS):
            raise DataError("CSV columns must be: " + ",".join(FIELDS))
        for line, row in enumerate(reader, 2):
            try:
                if None in row or any(v is None or not v.strip() for v in row.values()):
                    raise ValueError("missing or extra fields")
                item = Reading(row["bin_id"].strip(), row["district"].strip(),
                               float(row["latitude"]), float(row["longitude"]),
                               float(row["capacity_m3"]),
                               date.fromisoformat(row["observed_on"]), float(row["fill_pct"]))
                nums = (item.latitude, item.longitude, item.capacity_m3, item.fill_pct)
                if not all(isfinite(n) for n in nums):
                    raise ValueError("non-finite number")
                if not -90 <= item.latitude <= 90 or not -180 <= item.longitude <= 180:
                    raise ValueError("invalid coordinates")
                if item.capacity_m3 <= 0 or not 0 <= item.fill_pct <= 100:
                    raise ValueError("invalid capacity or fill percentage")
                key = (item.bin_id, item.observed_on)
                if key in seen:
                    raise ValueError("duplicate bin/date")
                meta = (item.district, item.latitude, item.longitude, item.capacity_m3)
                if item.bin_id in metadata and metadata[item.bin_id] != meta:
                    raise ValueError("container metadata changed")
                seen.add(key)
                metadata[item.bin_id] = meta
                series.setdefault(item.bin_id, []).append(item)
                readings.append(item)
            except (ValueError, TypeError) as exc:
                raise DataError(f"Line {line}: {exc}") from exc
    if not readings:
        raise DataError("CSV contains no observations")
    for bin_id, rows in series.items():
        rows.sort(key=lambda r: r.observed_on)
        if len(rows) < 3:
            raise DataError(f"{bin_id}: at least 3 observations required")
        if any(b.fill_pct < a.fill_pct for a, b in zip(rows, rows[1:])):
            raise DataError(f"{bin_id}: fill reset detected; split into collection cycles")
    if len({rows[-1].observed_on for rows in series.values()}) != 1:
        raise DataError("Containers must share the final observation date")
    return sorted(readings, key=lambda r: (r.bin_id, r.observed_on))


def generate_demo(path: Path, seed: int = 42, bins: int = 24, days: int = 7) -> None:
    """Generate fictional points within Astana, not municipal measurements.

    A fixed start date and seeded random generator make runs reproducible.
    Each series is one collection cycle with no fill reset.
    """
    if not 1 <= bins <= 10000 or not 3 <= days <= 30:
        raise DataError("Use 1..10000 bins and 3..30 days")
    rng = Random(seed)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(FIELDS)
        for i in range(bins):
            district = ("Есиль", "Сарыарка", "Алматы", "Байконур")[i % 4]
            lat, lon = round(rng.uniform(51.10, 51.18), 6), round(rng.uniform(71.37, 71.49), 6)
            capacity = rng.choice((1.1, 2.5, 4.0))
            fill, growth = rng.uniform(10, 40), rng.uniform(3, 10)
            for day in range(days):
                if day:
                    fill = min(100, fill + max(0, growth + rng.uniform(-1.5, 1.5)))
                writer.writerow((f"AST-{i+1:03d}", district, lat, lon, capacity,
                                 (date(2026, 10, 1) + timedelta(days=day)).isoformat(),
                                 round(fill, 2)))

