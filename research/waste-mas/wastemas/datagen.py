"""Reproducible synthetic telemetry for Astana (fictional containers).

Model of the generator (known ground truth, used to check the agents):
* each container has a base growth rate 4..10 pp per working day;
* on weekends and public holidays growth is 35 % higher (households at home);
* noise ±1.2 pp;
* status quo operator: a FIXED schedule — each container is emptied every 8..14
  days regardless of its fill, so some containers overflow (stay at 100 %)
  while others are collected half-empty. This is the problem the agents solve;
* after emptying the residual fill is 2..8 %.
"""
from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from pathlib import Path
from random import Random

from .core import DataError
from .tools import FIELDS

DISTRICTS = {  # rough bounding boxes, fictional points inside the city
    "Есиль": (51.090, 51.130, 71.400, 71.470),
    "Алматы": (51.140, 51.175, 71.450, 71.520),
    "Сарыарка": (51.170, 51.200, 71.380, 71.440),
    "Байконур": (51.145, 51.170, 71.400, 71.450),
    "Нура": (51.060, 51.095, 71.400, 71.500),
}
TRUE_UPLIFT = 0.35


def generate(path: Path, calendar: Path | None = None, seed: int = 42, bins: int = 60,
             days: int = 21, end: date = date(2026, 10, 24)) -> dict:
    if not 1 <= bins <= 5000 or not 5 <= days <= 120:
        raise DataError("Допустимо 1..5000 контейнеров и 5..120 дней")
    off = set()
    if calendar and calendar.is_file():
        off = {d["date"] for d in json.loads(calendar.read_text(encoding="utf-8"))["off_days"]}
    rng = Random(seed)
    start = end - timedelta(days=days - 1)
    names = list(DISTRICTS)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = 0
    with path.open("w", encoding="utf-8", newline="") as stream:
        w = csv.writer(stream)
        w.writerow(FIELDS)
        for i in range(bins):
            district = names[i % len(names)]
            la0, la1, lo0, lo1 = DISTRICTS[district]
            lat, lon = round(rng.uniform(la0, la1), 6), round(rng.uniform(lo0, lo1), 6)
            cap = rng.choices((0.66, 1.1, 2.5), weights=(15, 60, 25))[0]
            rate = rng.uniform(4.0, 10.0)
            period = rng.randint(8, 14)
            offset = rng.randrange(period)
            fill = rng.uniform(5, 60)
            for k in range(days):
                d = start + timedelta(days=k)
                if k:
                    if (k + offset) % period == 0:
                        fill = rng.uniform(2, 8)
                    else:
                        is_off = d.weekday() >= 5 or d.isoformat() in off
                        fill = min(100.0, fill + max(0.0, rate * (1 + TRUE_UPLIFT * is_off) + rng.uniform(-1.2, 1.2)))
                w.writerow((f"AST-{i+1:03d}", district, lat, lon, cap, d.isoformat(), round(fill, 2)))
                rows += 1
    return {"path": str(path), "rows": rows, "bins": bins, "start": start.isoformat(), "end": end.isoformat(),
            "seed": seed}
