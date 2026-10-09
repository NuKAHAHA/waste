"""Typed data contracts shared by agents and exporters."""
from dataclasses import dataclass, field
from datetime import date
from math import isfinite


class DataError(ValueError):
    """An invalid input dataset or simulation configuration."""


@dataclass(frozen=True)
class Reading:
    """One observation; capacities are cubic metres, fill is percent."""
    bin_id: str
    district: str
    latitude: float
    longitude: float
    capacity_m3: float
    observed_on: date
    fill_pct: float


@dataclass(frozen=True)
class Config:
    """Scenario assumptions; the depot is a fictional Astana location."""
    threshold_pct: float = 80.0
    horizon_days: float = 1.0
    truck_capacity_m3: float = 12.0
    depot_lat: float = 51.128
    depot_lon: float = 71.430

    def __post_init__(self):
        values = (self.threshold_pct, self.horizon_days, self.truck_capacity_m3,
                  self.depot_lat, self.depot_lon)
        if not all(isfinite(v) for v in values):
            raise DataError("Configuration values must be finite")
        if not 0 < self.threshold_pct <= 100:
            raise DataError("Threshold must be in (0, 100]")
        if not 0 < self.horizon_days <= 30:
            raise DataError("Horizon must be in (0, 30] days")
        if self.truck_capacity_m3 <= 0:
            raise DataError("Truck capacity must be positive")
        if not -90 <= self.depot_lat <= 90 or not -180 <= self.depot_lon <= 180:
            raise DataError("Invalid depot coordinates")


@dataclass
class BinState:
    """Analysis and forecast for a single container."""
    bin_id: str
    district: str
    latitude: float
    longitude: float
    capacity_m3: float
    fill_pct: float
    daily_growth_pct: float
    as_of: date
    predicted_pct: float = 0.0
    priority: str = "low"
    selected: bool = False

    @property
    def load_m3(self) -> float:
        """Estimate future collection volume, capped at physical capacity."""
        return self.capacity_m3 * min(100.0, self.predicted_pct) / 100.0


@dataclass
class Trip:
    """One depot-to-depot trip with bounded vehicle loading."""
    trip_id: int
    bin_ids: list[str]
    load_m3: float
    distance_km: float


@dataclass
class Context:
    """Pipeline message shared by independent agent implementations."""
    readings: list[Reading]
    config: Config
    states: list[BinState] = field(default_factory=list)
    trips: list[Trip] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    trace: list[str] = field(default_factory=list)

