"""Tools used by agents. Pure functions where possible, so they are easy to test.

Groups: files (CSV, calendar JSON, output files), forecasting, decisions,
routing, verification and the optional LLM client.
"""
from __future__ import annotations

import csv
import json
import re
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date, timedelta
from math import asin, cos, isfinite, radians, sin, sqrt
from pathlib import Path
from statistics import median

from .core import DataError, LLMSettings, Reading, TransientError

FIELDS = ("bin_id", "district", "latitude", "longitude", "capacity_m3", "observed_on", "fill_pct")
RESET_DROP_PP = 15.0  # a fall larger than this is a collection (container emptied)


# ---------------------------------------------------------------- files / data

def read_csv(path: str | Path) -> list[dict]:
    """Read raw CSV rows (strings). Header must match FIELDS exactly."""
    path = Path(path)
    if not path.is_file():
        raise DataError(f"Файл не найден: {path}")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(FIELDS):
            raise DataError("Колонки CSV должны быть: " + ",".join(FIELDS))
        rows = list(reader)
    if not rows:
        raise DataError("CSV не содержит наблюдений")
    return rows


def validate_readings(rows: list[dict]) -> dict:
    """Convert and validate rows; detect collections (fill resets).

    Returns readings as dicts plus a summary. Raises DataError with line number.
    """
    readings, seen, meta, series = [], set(), {}, defaultdict(list)
    for line, row in enumerate(rows, 2):
        try:
            if None in row or any(v is None or not str(v).strip() for v in row.values()):
                raise ValueError("пустое или лишнее поле")
            item = Reading(row["bin_id"].strip(), row["district"].strip(), float(row["latitude"]),
                           float(row["longitude"]), float(row["capacity_m3"]),
                           date.fromisoformat(row["observed_on"].strip()), float(row["fill_pct"]))
            if not all(isfinite(v) for v in (item.latitude, item.longitude, item.capacity_m3, item.fill_pct)):
                raise ValueError("NaN или бесконечность")
            if not -90 <= item.latitude <= 90 or not -180 <= item.longitude <= 180:
                raise ValueError("неверные координаты")
            if item.capacity_m3 <= 0:
                raise ValueError("объём контейнера должен быть > 0")
            if not 0 <= item.fill_pct <= 100:
                raise ValueError("заполненность вне диапазона 0..100%")
            key = (item.bin_id, item.observed_on)
            if key in seen:
                raise ValueError("дубликат контейнер/дата")
            m = (item.district, item.latitude, item.longitude, item.capacity_m3)
            if meta.setdefault(item.bin_id, m) != m:
                raise ValueError("метаданные контейнера изменились")
            seen.add(key)
            series[item.bin_id].append(item)
            readings.append(item)
        except (ValueError, TypeError, KeyError) as exc:
            raise DataError(f"Строка {line}: {exc}") from exc
    for bin_id, items in series.items():
        if len(items) < 3:
            raise DataError(f"{bin_id}: нужно минимум 3 наблюдения")
    last_dates = {max(r.observed_on for r in items) for items in series.values()}
    if len(last_dates) != 1:
        raise DataError("У всех контейнеров должна быть общая последняя дата")
    readings.sort(key=lambda r: (r.bin_id, r.observed_on))
    resets = sum(1 for items in group(readings).values()
                 for a, b in zip(items, items[1:]) if a.fill_pct - b.fill_pct > RESET_DROP_PP)
    return {"readings": [r.to_dict() for r in readings],
            "summary": {"rows": len(readings), "bins": len(series), "last_date": last_dates.pop().isoformat(),
                        "first_date": min(r.observed_on for r in readings).isoformat(),
                        "collections_detected": resets}}


def group(readings: list[Reading]) -> dict[str, list[Reading]]:
    out = defaultdict(list)
    for r in readings:
        out[r.bin_id].append(r)
    return {k: sorted(v, key=lambda r: r.observed_on) for k, v in sorted(out.items())}


def load_calendar(path: str | Path, start: str, end: str) -> dict:
    """Non-working days (weekends + official holidays/transfers) in [start, end]."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    holidays = {item["date"]: item["name"] for item in data["off_days"]}
    d, last, off = date.fromisoformat(start), date.fromisoformat(end), {}
    while d <= last:
        if d.isoformat() in holidays:
            off[d.isoformat()] = holidays[d.isoformat()]
        elif d.weekday() >= 5:
            off[d.isoformat()] = "выходной"
        d += timedelta(days=1)
    return {"off_days": off, "source": data.get("source", "")}


# ---------------------------------------------------------------- forecasting

def _increments(rows: list[Reading]):
    """Yield (prev, cur) pairs inside one collection cycle."""
    for a, b in zip(rows, rows[1:]):
        if b.fill_pct >= a.fill_pct - 1.0 and b.observed_on > a.observed_on:
            yield a, b


def _days(a: date, b: date) -> list[date]:
    return [a + timedelta(days=i) for i in range(1, (b - a).days + 1)]


def estimate_rates(readings: list[dict], off_days: dict) -> dict:
    """Per-bin base growth (pp/working day) and pooled non-working-day uplift.

    Uplift u: median over bins of mean(off-day increment) / mean(work-day
    increment) - 1, using one-day gaps only. Base rate r: sum(increments) /
    sum(day weights), weight = 1 for a working day and 1+u for a day off.
    Increments that include a collection are skipped.
    """
    series = group([Reading.from_dict(r) for r in readings])
    ratios = []
    for rows in series.values():
        work, off = [], []
        for a, b in _increments(rows):
            if (b.observed_on - a.observed_on).days == 1 and b.fill_pct < 100:
                (off if b.observed_on.isoformat() in off_days else work).append(b.fill_pct - a.fill_pct)
        if len(work) >= 2 and off and sum(work) > 0:
            ratios.append((sum(off) / len(off)) / (sum(work) / len(work)))
    uplift = max(0.0, median(ratios) - 1) if ratios else 0.0
    rates = {}
    for bin_id, rows in series.items():
        inc, weight = 0.0, 0.0
        for a, b in _increments(rows):
            if b.fill_pct >= 100:
                continue  # saturated: true growth unknown
            inc += b.fill_pct - a.fill_pct
            weight += sum(1 + uplift if d.isoformat() in off_days else 1 for d in _days(a.observed_on, b.observed_on))
        rates[bin_id] = max(0.0, inc / weight) if weight else 0.0
    return {"uplift": round(uplift, 4), "rates": rates, "bins_used_for_uplift": len(ratios)}


def project_fill(readings: list[dict], model: dict, off_days: dict, horizon_days: int) -> list[dict]:
    """Forecast fill for the target day = last date + horizon (capped at 100%)."""
    out = []
    for bin_id, rows in group([Reading.from_dict(r) for r in readings]).items():
        last = rows[-1]
        target = last.observed_on + timedelta(days=horizon_days)
        weights = sum(1 + model["uplift"] if d.isoformat() in off_days else 1
                      for d in _days(last.observed_on, target))
        rate = model["rates"].get(bin_id, 0.0)
        raw = last.fill_pct + rate * weights
        days_to_full = None
        if rate > 0:
            days_to_full = round(max(0.0, (100 - last.fill_pct) / rate), 2)
        out.append({"bin_id": bin_id, "district": last.district, "latitude": last.latitude,
                    "longitude": last.longitude, "capacity_m3": last.capacity_m3,
                    "as_of": last.observed_on.isoformat(), "target_date": target.isoformat(),
                    "fill_pct": last.fill_pct, "rate_pp_per_day": round(rate, 4),
                    "predicted_pct": round(min(100.0, raw), 2), "overflow": raw >= 100,
                    "days_to_full": days_to_full})
    return out


def _ols_forecast(rows: list[Reading], target: date) -> float:
    """Linear trend on the current cycle (baseline for the backtest)."""
    cycle = [rows[-1]]
    for a, b in zip(reversed(rows[:-1]), reversed(rows[1:])):
        if b.fill_pct < a.fill_pct - RESET_DROP_PP:
            break
        cycle.insert(0, a)
    if len(cycle) < 2:
        return rows[-1].fill_pct
    x0 = cycle[0].observed_on
    xs = [(r.observed_on - x0).days for r in cycle]
    ys = [r.fill_pct for r in cycle]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    den = sum((x - mx) ** 2 for x in xs)
    slope = max(0.0, sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den) if den else 0.0
    return min(100.0, rows[-1].fill_pct + slope * (target - rows[-1].observed_on).days)


def backtest(readings: list[dict], off_days: dict) -> dict:
    """Hold out the last date; compare persistence, linear trend and the agent model.

    Bins emptied between the last two dates or already saturated are excluded:
    the collection itself is not predictable from fill data.
    """
    series = group([Reading.from_dict(r) for r in readings])
    train = [r.to_dict() for rows in series.values() for r in rows[:-1]]
    model = estimate_rates(train, off_days)
    errors = {"persistence": [], "linear": [], "calendar_model": []}
    excluded = 0
    for bin_id, rows in series.items():
        prev, actual = rows[-2], rows[-1]
        if actual.fill_pct < prev.fill_pct - 1.0 or prev.fill_pct >= 100 or actual.fill_pct >= 100:
            excluded += 1
            continue
        weights = sum(1 + model["uplift"] if d.isoformat() in off_days else 1
                      for d in _days(prev.observed_on, actual.observed_on))
        pred = min(100.0, prev.fill_pct + model["rates"][bin_id] * weights)
        errors["persistence"].append(abs(prev.fill_pct - actual.fill_pct))
        errors["linear"].append(abs(_ols_forecast(rows[:-1], actual.observed_on) - actual.fill_pct))
        errors["calendar_model"].append(abs(pred - actual.fill_pct))
    mae = {k: round(sum(v) / len(v), 3) if v else None for k, v in errors.items()}
    return {"holdout_date": max(r.observed_on for rows in series.values() for r in rows).isoformat(),
            "n": len(errors["persistence"]), "excluded": excluded, "mae_pp": mae}


# ---------------------------------------------------------------- decisions

def score_bins(forecasts: list[dict], threshold_pct: float) -> list[dict]:
    """Select containers for collection and assign an explainable category."""
    decisions = []
    for f in forecasts:
        critical = f["overflow"] or f["fill_pct"] >= 95
        selected = critical or f["predicted_pct"] >= threshold_pct or f["fill_pct"] >= threshold_pct
        category = ("critical" if critical else "high" if selected else
                    "medium" if f["predicted_pct"] >= 60 else "low")
        reason = ("ожидается переполнение" if f["overflow"] else
                  "почти полный сейчас" if f["fill_pct"] >= 95 else
                  f"прогноз {f['predicted_pct']}% ≥ порога {threshold_pct}%" if selected else
                  f"прогноз {f['predicted_pct']}% < порога")
        load = round(f["capacity_m3"] * f["predicted_pct"] / 100, 4)
        decisions.append({"bin_id": f["bin_id"], "selected": selected, "category": category,
                          "predicted_pct": f["predicted_pct"], "fill_pct": f["fill_pct"],
                          "load_m3": load, "reason": reason, "deferred": False})
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    decisions.sort(key=lambda d: (order[d["category"]], -d["predicted_pct"], d["bin_id"]))
    return decisions


def defer_bins(decisions: list[dict], fleet_volume_m3: float, packing: float = 0.9) -> dict:
    """Postpone the least urgent non-critical bins until volume fits the fleet.

    Always defers at least one bin if any is deferrable, which guarantees
    progress of the replanning loop. Critical bins are never deferred.
    """
    selected = [d for d in decisions if d["selected"]]
    volume = sum(d["load_m3"] for d in selected)
    target = fleet_volume_m3 * packing
    candidates = sorted((d for d in selected if d["category"] != "critical"),
                        key=lambda d: (d["predicted_pct"], d["bin_id"]))
    deferred = []
    for d in candidates:
        if deferred and volume <= target:
            break
        d["selected"], d["deferred"] = False, True
        d["reason"] = "перенесён на следующий день: не хватает рейсов"
        volume -= d["load_m3"]
        deferred.append(d["bin_id"])
    return {"decisions": decisions, "deferred": deferred, "volume_m3": round(volume, 4),
            "progress": bool(deferred)}


# ---------------------------------------------------------------- routing

def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(radians, (*a, *b))
    h = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 6371.0088 * 2 * asin(sqrt(min(1.0, max(0.0, h))))


def distance_matrix(points: list[tuple[float, float]]) -> list[list[float]]:
    """Straight-line distances; index 0 is the depot."""
    return [[round(haversine_km(a, b), 5) for b in points] for a in points]


def route_length(route: list[int], matrix: list[list[float]]) -> float:
    path = [0, *route, 0]
    return sum(matrix[a][b] for a, b in zip(path, path[1:]))


def build_trips(loads: list[float], matrix: list[list[float]], capacity: float) -> list[list[int]]:
    """Greedy nearest neighbour with capacity: returns lists of point indices (1..n)."""
    if any(load > capacity + 1e-9 for load in loads):
        raise DataError("Объём контейнера больше вместимости машины; увеличьте --truck-capacity")
    remaining, trips = set(range(1, len(loads) + 1)), []
    while remaining:
        current, load, trip = 0, 0.0, []
        while True:
            feasible = [i for i in remaining if load + loads[i - 1] <= capacity + 1e-9]
            if not feasible:
                break
            nxt = min(feasible, key=lambda i: (matrix[current][i], i))
            trip.append(nxt)
            load += loads[nxt - 1]
            remaining.discard(nxt)
            current = nxt
        trips.append(trip)
    return trips


def improve_2opt(trips: list[list[int]], matrix: list[list[float]], max_iter: int = 1000) -> dict:
    """Reverse route segments while it shortens the trip (bounded iterations)."""
    before = sum(route_length(t, matrix) for t in trips)
    improved = []
    for trip in trips:
        best, changed, it = list(trip), True, 0
        while changed and it < max_iter:
            changed, it = False, it + 1
            for i in range(len(best) - 1):
                for j in range(i + 1, len(best)):
                    cand = best[:i] + best[i:j + 1][::-1] + best[j + 1:]
                    if route_length(cand, matrix) < route_length(best, matrix) - 1e-9:
                        best, changed = cand, True
        improved.append(best)
    after = sum(route_length(t, matrix) for t in improved)
    return {"trips": improved, "km_before": round(before, 3), "km_after": round(after, 3)}


# ---------------------------------------------------------------- verification

def check_plan(decisions: list[dict], plan: dict, fleet_trips: int, capacity: float) -> dict:
    """Independent check of hard constraints. Returns verdict and violations."""
    violations = []
    selected = {d["bin_id"] for d in decisions if d["selected"]}
    critical = {d["bin_id"] for d in decisions if d["category"] == "critical"}
    loads = {d["bin_id"]: d["load_m3"] for d in decisions}
    served = [b for t in plan["trips"] for b in t["bin_ids"]]
    if missing := sorted(selected - set(served)):
        violations.append({"code": "unserved", "bins": missing, "fix": None})
    if dupes := sorted({b for b in served if served.count(b) > 1}):
        violations.append({"code": "duplicate", "bins": dupes, "fix": None})
    if extra := sorted(set(served) - selected):
        violations.append({"code": "not_selected", "bins": extra, "fix": None})
    if lost := sorted(critical - set(served)):
        violations.append({"code": "critical_unserved", "bins": lost, "fix": None})
    for t in plan["trips"]:
        load = sum(loads.get(b, 0) for b in t["bin_ids"])
        if load > capacity + 1e-6 or abs(load - t["load_m3"]) > 1e-3:
            violations.append({"code": "overload", "trip": t["trip_id"], "load_m3": round(load, 3), "fix": None})
        if not isfinite(t["distance_km"]) or t["distance_km"] < 0:
            violations.append({"code": "bad_distance", "trip": t["trip_id"], "fix": None})
    if len(plan["trips"]) > fleet_trips:
        deferrable = any(d["selected"] and d["category"] != "critical" for d in decisions)
        violations.append({"code": "fleet_limit", "trips": len(plan["trips"]), "available": fleet_trips,
                           "fix": "defer" if deferrable else None})
    return {"approved": not violations, "violations": violations,
            "checked": {"selected": len(selected), "served": len(served), "trips": len(plan["trips"])}}


# ---------------------------------------------------------------- LLM

NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?")


def llm_complete(settings: LLMSettings, system: str, user: str) -> str:
    """Call an OpenAI-compatible /chat/completions endpoint (e.g. Ollama, OpenAI)."""
    if not settings.configured:
        raise DataError("LLM не настроена: задайте LLM_BASE_URL и LLM_MODEL")
    body = json.dumps({"model": settings.model, "temperature": 0.2,
                       "messages": [{"role": "system", "content": system},
                                    {"role": "user", "content": user}]}).encode()
    headers = {"Content-Type": "application/json"}
    if settings.api_key:
        headers["Authorization"] = f"Bearer {settings.api_key}"
    req = urllib.request.Request(settings.base_url + "/chat/completions", body, headers)
    try:
        with urllib.request.urlopen(req, timeout=settings.timeout_s) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in (429, 500, 502, 503, 504):
            raise TransientError(f"HTTP {exc.code}") from exc
        raise DataError(f"LLM вернула HTTP {exc.code}") from exc
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise DataError("Неожиданный формат ответа LLM") from exc


def numbers_grounded(text: str, facts: dict) -> list[str]:
    """Return numbers in text that are absent from the facts (hallucination guard)."""
    allowed = set()

    def walk(v):
        if isinstance(v, bool):
            return
        if isinstance(v, (int, float)):
            allowed.add(round(float(v), 1))
            allowed.add(float(round(v)))
        elif isinstance(v, str):
            for m in NUMBER.findall(v):
                allowed.add(round(float(m.replace(",", ".")), 1))
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(facts)
    bad = []
    for m in NUMBER.findall(text):
        value = float(m.replace(",", "."))
        if value <= 5 and value == int(value):
            continue
        if not any(abs(value - a) <= 0.1 for a in allowed):
            bad.append(m)
    return bad


def template_summary(facts: dict) -> str:
    """Deterministic dispatcher brief used without LLM or when LLM fails."""
    p = facts
    lines = [f"План вывоза на {p['target_date']}: {p['bins_selected']} из {p['bins_total']} контейнеров, "
             f"{p['trips']} рейс(ов), {p['distance_km']} км по прямой, {p['volume_m3']} м³."]
    if p["critical"]:
        lines.append(f"Критические контейнеры ({len(p['critical'])}): {', '.join(p['critical'][:10])}.")
    if p["deferred"]:
        lines.append(f"Перенесены из-за нехватки рейсов: {', '.join(p['deferred'])}.")
    if p["off_days_in_horizon"]:
        lines.append("В горизонте прогноза нерабочие дни: " + ", ".join(p["off_days_in_horizon"]) +
                     "; учтён повышенный темп накопления.")
    lines.append("Проверка плана: " + ("утверждён." if p["approved"] else "НЕ утверждён: " + p["violations"]))
    return "\n".join(lines)


def write_outputs(out_dir: str | Path, bundle: dict, html_text: str) -> list[str]:
    """Write report.json, plan.csv and dashboard.html. CSV cells are formula-safe."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")

    def safe(v):
        s = str(v)
        return "'" + s if s[:1] in ("=", "+", "-", "@") and not NUMBER.fullmatch(s.lstrip("-")) else s
    trip_of = {b: t["trip_id"] for t in bundle["plan"]["trips"] for b in t["bin_ids"]}
    truck_of = {b: t["truck"] for t in bundle["plan"]["trips"] for b in t["bin_ids"]}
    with (out / "plan.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        w = csv.writer(stream)
        w.writerow(["bin_id", "district", "fill_pct", "predicted_pct", "category", "selected",
                    "deferred", "trip", "truck", "reason"])
        fc = {f["bin_id"]: f for f in bundle["forecasts"]}
        for d in bundle["decisions"]:
            w.writerow([safe(d["bin_id"]), safe(fc[d["bin_id"]]["district"]), d["fill_pct"], d["predicted_pct"],
                        d["category"], int(d["selected"]), int(d["deferred"]), trip_of.get(d["bin_id"], ""),
                        truck_of.get(d["bin_id"], ""), safe(d["reason"])])
    (out / "dashboard.html").write_text(html_text, encoding="utf-8")
    return ["report.json", "plan.csv", "dashboard.html"]
