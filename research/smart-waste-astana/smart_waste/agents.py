"""Five explainable agents and a small extensible orchestration protocol.

    Analysis -> Forecast -> Priority -> Route -> Evaluation

Two-agent mode uses Analysis -> Priority and current fill only. Agents implement
run(context); replacing an agent does not require changing input/output code.
"""
from collections import defaultdict
from math import asin, cos, radians, sin, sqrt
from typing import Protocol

from .models import BinState, Context, DataError, Trip


def group_readings(readings):
    groups = defaultdict(list)
    for row in readings:
        groups[row.bin_id].append(row)
    return {key: sorted(rows, key=lambda r: r.observed_on) for key, rows in sorted(groups.items())}


def fit_growth(rows) -> float:
    """OLS slope in percentage points/day using elapsed dates, not row indices.

    Positive slopes are capped only when projecting fill, not during fitting.
    Negative slopes are clamped to zero under the single-cycle assumption.
    """
    origin = rows[0].observed_on
    xs = [(r.observed_on - origin).days for r in rows]
    ys = [r.fill_pct for r in rows]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    denom = sum((x - mx) ** 2 for x in xs)
    if not denom:
        return 0.0
    return max(0.0, sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom)


def predict(rows, horizon: float) -> float:
    """Last observation plus OLS growth; a trend forecast anchored at latest fill."""
    return min(100.0, max(0.0, rows[-1].fill_pct + fit_growth(rows) * horizon))


def distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Haversine straight-line distance; not road distance or travel time."""
    lat1, lon1, lat2, lon2 = map(radians, (*a, *b))
    value = sin((lat2-lat1)/2)**2 + cos(lat1)*cos(lat2)*sin((lon2-lon1)/2)**2
    return 6371.0088 * 2 * asin(sqrt(min(1.0, max(0.0, value))))


class Agent(Protocol):
    """Minimal extension contract for research agents."""
    name: str

    def run(self, context: Context) -> None: ...


class AnalysisAgent:
    name = "analysis"

    def run(self, context: Context) -> None:
        context.states = []
        for bin_id, rows in group_readings(context.readings).items():
            row = rows[-1]
            context.states.append(BinState(bin_id, row.district, row.latitude, row.longitude,
                                           row.capacity_m3, row.fill_pct, fit_growth(rows),
                                           row.observed_on, predicted_pct=row.fill_pct))


class ForecastAgent:
    name = "forecast"

    def run(self, context: Context) -> None:
        for state in context.states:
            state.predicted_pct = min(100.0, state.fill_pct +
                                       state.daily_growth_pct * context.config.horizon_days)


class PriorityAgent:
    name = "priority"

    def run(self, context: Context) -> None:
        for state in context.states:
            state.selected = state.predicted_pct >= context.config.threshold_pct
            state.priority = ("critical" if state.predicted_pct >= 95 else
                              "high" if state.selected else
                              "medium" if state.predicted_pct >= 60 else "low")
        context.states.sort(key=lambda s: (-s.predicted_pct, -s.fill_pct, s.bin_id))


class RouteAgent:
    name = "route"

    def run(self, context: Context) -> None:
        """Greedy nearest-neighbour trips with unloading at the depot.

        All selected bins must be served exactly once. No splitting a container
        between trips: reject a container larger than the vehicle's estimated
        loading capacity. Number of trips is unlimited; there is no shift limit.
        """
        capacity = context.config.truck_capacity_m3
        remaining = [s for s in context.states if s.selected]
        if any(s.load_m3 > capacity + 1e-9 for s in remaining):
            raise DataError("A selected container exceeds truck capacity; increase --truck-capacity")
        context.trips = []
        depot = (context.config.depot_lat, context.config.depot_lon)
        while remaining:
            current, load, km, ids = depot, 0.0, 0.0, []
            while True:
                feasible = [s for s in remaining if load + s.load_m3 <= capacity + 1e-9]
                if not feasible:
                    break
                chosen = min(feasible, key=lambda s: (distance_km(current, (s.latitude, s.longitude)), s.bin_id))
                point = (chosen.latitude, chosen.longitude)
                km += distance_km(current, point)
                load += chosen.load_m3
                ids.append(chosen.bin_id)
                remaining.remove(chosen)
                current = point
            km += distance_km(current, depot)
            context.trips.append(Trip(len(context.trips) + 1, ids, load, km))


class EvaluationAgent:
    name = "evaluation"

    def run(self, context: Context) -> None:
        """Last-date holdout: fit on previous dates, score untouched final date.

        Baseline = previous observed fill (persistence). Units: percentage points.
        This evaluation supports no claim about real Astana performance.
        """
        errors, baseline, cases = [], [], []
        for bin_id, rows in group_readings(context.readings).items():
            train, target = rows[:-1], rows[-1]
            gap = (target.observed_on - train[-1].observed_on).days
            predicted = predict(train, gap)
            error = abs(predicted - target.fill_pct)
            errors.append(error)
            baseline.append(abs(train[-1].fill_pct - target.fill_pct))
            cases.append({"bin_id": bin_id, "actual_pct": target.fill_pct,
                          "forecast_pct": predicted, "absolute_error_pp": error})
        context.metrics.update({"holdout_n": len(errors),
                                "forecast_mae_pp": sum(errors) / len(errors),
                                "persistence_mae_pp": sum(baseline) / len(baseline),
                                "holdout_cases": cases,
                                "route_distance_km": sum(t.distance_km for t in context.trips),
                                "collection_volume_m3": sum(t.load_m3 for t in context.trips)})


def run_pipeline(context: Context, agent_count: int = 5,
                 agents: list[Agent] | None = None) -> Context:
    """Run two essential or five extended agents, or an explicit custom list."""
    if not context.readings:
        raise DataError("Pipeline requires observations")
    if agents is None:
        if agent_count not in (2, 5):
            raise DataError("Agent count must be 2 or 5")
        agents = ([AnalysisAgent(), PriorityAgent()] if agent_count == 2 else
                  [AnalysisAgent(), ForecastAgent(), PriorityAgent(), RouteAgent(), EvaluationAgent()])
    context.states, context.trips, context.metrics, context.trace = [], [], {}, []
    for agent in agents:
        agent.run(context)
        context.trace.append(agent.name)
    context.metrics.update({"bins_total": len(context.states),
                            "bins_selected": sum(s.selected for s in context.states),
                            "trips_total": len(context.trips)})
    return context

