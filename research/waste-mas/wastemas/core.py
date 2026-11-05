"""Typed data contracts, configuration and messages shared by all agents.

Agents never call each other directly: the orchestrator sends a ``Message`` of
type ``task`` and receives a ``Message`` of type ``result``. Both are plain
JSON-serialisable dataclasses that are logged and stored in SQLite.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from math import isfinite
from pathlib import Path


class MASError(Exception):
    """Base error with a message that is safe to show to the user."""


class DataError(MASError):
    """Invalid input data or configuration (not retried)."""


class TransientError(MASError):
    """Temporary failure of an external resource (retried)."""


class LimitExceeded(MASError):
    """Step or time limit of the orchestrator was reached."""


@dataclass(frozen=True)
class Reading:
    """One fill-level measurement of a container. Volume in m3, fill in %."""
    bin_id: str
    district: str
    latitude: float
    longitude: float
    capacity_m3: float
    observed_on: date
    fill_pct: float

    def to_dict(self) -> dict:
        data = asdict(self)
        data["observed_on"] = self.observed_on.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Reading":
        return cls(data["bin_id"], data["district"], float(data["latitude"]),
                   float(data["longitude"]), float(data["capacity_m3"]),
                   date.fromisoformat(data["observed_on"]), float(data["fill_pct"]))


@dataclass(frozen=True)
class LLMSettings:
    """OpenAI-compatible endpoint. The key is read from the environment only."""
    base_url: str = ""
    model: str = ""
    api_key: str = field(default="", repr=False)
    timeout_s: float = 20.0

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.model)

    @classmethod
    def from_env(cls) -> "LLMSettings":
        return cls(os.environ.get("LLM_BASE_URL", "").rstrip("/"),
                   os.environ.get("LLM_MODEL", ""),
                   os.environ.get("LLM_API_KEY", ""),
                   float(os.environ.get("LLM_TIMEOUT_S", "20")))


@dataclass(frozen=True)
class Config:
    """Scenario parameters and reliability limits."""
    threshold_pct: float = 80.0
    horizon_days: int = 1
    truck_capacity_m3: float = 8.0
    trucks: int = 2
    trips_per_truck: int = 2
    depot_lat: float = 51.128
    depot_lon: float = 71.430
    max_steps: int = 20
    timeout_s: float = 60.0
    max_replans: int = 3
    tool_retries: int = 2
    retry_backoff_s: float = 0.2
    use_llm: bool = False
    llm: LLMSettings = field(default_factory=LLMSettings)

    def __post_init__(self):
        numbers = (self.threshold_pct, self.truck_capacity_m3, self.depot_lat,
                   self.depot_lon, self.timeout_s, self.retry_backoff_s)
        if not all(isfinite(v) for v in numbers):
            raise DataError("Параметры должны быть конечными числами")
        if not 0 < self.threshold_pct <= 100:
            raise DataError("Порог должен быть в диапазоне (0, 100]")
        if not 1 <= self.horizon_days <= 7:
            raise DataError("Горизонт прогноза: 1..7 дней")
        if self.truck_capacity_m3 <= 0:
            raise DataError("Вместимость машины должна быть положительной")
        if self.trucks < 1 or self.trips_per_truck < 1:
            raise DataError("Нужна минимум 1 машина и 1 рейс")
        if not -90 <= self.depot_lat <= 90 or not -180 <= self.depot_lon <= 180:
            raise DataError("Неверные координаты депо")
        if self.max_steps < 1 or self.timeout_s <= 0 or self.max_replans < 0:
            raise DataError("Неверные лимиты оркестратора")
        if self.tool_retries < 0 or self.retry_backoff_s < 0:
            raise DataError("Неверные параметры повторных попыток")

    @property
    def fleet_trips(self) -> int:
        return self.trucks * self.trips_per_truck

    @property
    def depot(self) -> tuple[float, float]:
        return (self.depot_lat, self.depot_lon)

    def public_dict(self) -> dict:
        """Configuration for logs and reports, without the API key."""
        data = asdict(self)
        data["llm"] = {"base_url": self.llm.base_url, "model": self.llm.model,
                       "api_key_set": bool(self.llm.api_key)}
        return data


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass
class Message:
    """Structured message between the orchestrator and an agent."""
    run_id: str
    step: int
    sender: str
    recipient: str
    type: str            # "task" or "result"
    payload: dict
    ts: str = field(default_factory=now_iso)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> "Message":
        return cls(**json.loads(text))


def load_dotenv(path: Path) -> None:
    """Minimal .env reader: sets variables that are not already defined."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
