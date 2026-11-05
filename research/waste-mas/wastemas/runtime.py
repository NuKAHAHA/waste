"""Shared runtime: JSONL log, SQLite state store and guarded tool calls.

Every agent call, tool call, LLM call, retry, message and error is written to
the log. ``Runtime.call_tool`` is the only way an agent may use a tool, so the
log is a complete record that supports the load-distribution check.
"""
from __future__ import annotations

import json
import sqlite3
import time
import urllib.error
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from .core import Config, DataError, LimitExceeded, MASError, Message, TransientError, now_iso

RETRYABLE = (TransientError, TimeoutError, ConnectionError, urllib.error.URLError,
             sqlite3.OperationalError)
LLM_TOOLS = {"llm_complete"}


class Logbook:
    """Append-only JSON Lines log of one run."""

    def __init__(self, path: Path | None, run_id: str):
        self.run_id, self.path, self.events = run_id, path, []
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")

    def event(self, kind: str, **fields) -> dict:
        record = {"ts": now_iso(), "run_id": self.run_id, "seq": len(self.events) + 1,
                  "kind": kind, **fields}
        self.events.append(record)
        if self.path:
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        return record

    def load_distribution(self) -> dict:
        """Share of tool and LLM calls per agent (one entry per logical call)."""
        calls = [e for e in self.events if e["kind"] in ("tool_call", "llm_call")]
        per_agent = Counter(e["agent"] for e in calls)
        llm = Counter(e["agent"] for e in calls if e["kind"] == "llm_call")
        dispatches = Counter(e["agent"] for e in self.events if e["kind"] == "agent_call")
        total = sum(per_agent.values())
        agents = {}
        for name in sorted(set(per_agent) | set(dispatches)):
            agents[name] = {"agent_calls": dispatches[name], "tool_calls": per_agent[name] - llm[name],
                            "llm_calls": llm[name], "total_calls": per_agent[name],
                            "share": round(per_agent[name] / total, 4) if total else 0.0}
        top = max(agents.values(), key=lambda a: a["share"], default={"share": 0.0})
        return {"total_calls": total, "agents": agents, "max_share": top["share"],
                "limit": 0.40, "balanced": top["share"] <= 0.40}


class StateStore:
    """Explicit task state in SQLite: runs, readings, artifacts and messages."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS runs(run_id TEXT PRIMARY KEY, started TEXT, finished TEXT,
        status TEXT, config TEXT, error TEXT);
    CREATE TABLE IF NOT EXISTS readings(run_id TEXT, bin_id TEXT, district TEXT, latitude REAL,
        longitude REAL, capacity_m3 REAL, observed_on TEXT, fill_pct REAL,
        PRIMARY KEY(run_id, bin_id, observed_on));
    CREATE TABLE IF NOT EXISTS artifacts(run_id TEXT, key TEXT, version INTEGER, author TEXT,
        value TEXT, ts TEXT, PRIMARY KEY(run_id, key, version));
    CREATE TABLE IF NOT EXISTS messages(run_id TEXT, step INTEGER, sender TEXT, recipient TEXT,
        type TEXT, payload TEXT, ts TEXT);
    """

    def __init__(self, path: Path | str = ":memory:"):
        if isinstance(path, Path):
            path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), timeout=5)
        self.db.executescript(self.SCHEMA)

    def close(self) -> None:
        self.db.close()

    def start_run(self, run_id: str, config: dict) -> None:
        with self.db:
            self.db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?)",
                            (run_id, now_iso(), None, "running", json.dumps(config), None))

    def finish_run(self, run_id: str, status: str, error: str | None) -> None:
        with self.db:
            self.db.execute("UPDATE runs SET finished=?, status=?, error=? WHERE run_id=?",
                            (now_iso(), status, error, run_id))

    def save_readings(self, run_id: str, rows: list[dict]) -> int:
        with self.db:
            self.db.executemany("INSERT INTO readings VALUES(?,?,?,?,?,?,?,?)",
                                [(run_id, r["bin_id"], r["district"], r["latitude"], r["longitude"],
                                  r["capacity_m3"], r["observed_on"], r["fill_pct"]) for r in rows])
        return len(rows)

    def load_readings(self, run_id: str) -> list[dict]:
        cur = self.db.execute("SELECT bin_id, district, latitude, longitude, capacity_m3, "
                              "observed_on, fill_pct FROM readings WHERE run_id=? "
                              "ORDER BY bin_id, observed_on", (run_id,))
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def put(self, run_id: str, key: str, value: Any, author: str) -> int:
        """Store a new version of an artifact; earlier versions are kept."""
        with self.db:
            (last,) = self.db.execute("SELECT COALESCE(MAX(version),0) FROM artifacts "
                                      "WHERE run_id=? AND key=?", (run_id, key)).fetchone()
            self.db.execute("INSERT INTO artifacts VALUES(?,?,?,?,?,?)",
                            (run_id, key, last + 1, author,
                             json.dumps(value, ensure_ascii=False), now_iso()))
        return last + 1

    def get(self, run_id: str, key: str) -> Any:
        row = self.db.execute("SELECT value FROM artifacts WHERE run_id=? AND key=? "
                              "ORDER BY version DESC LIMIT 1", (run_id, key)).fetchone()
        if row is None:
            raise DataError(f"В хранилище нет артефакта '{key}'")
        return json.loads(row[0])

    def has(self, run_id: str, key: str) -> bool:
        return self.db.execute("SELECT 1 FROM artifacts WHERE run_id=? AND key=? LIMIT 1",
                               (run_id, key)).fetchone() is not None

    def log_message(self, msg: Message) -> None:
        with self.db:
            self.db.execute("INSERT INTO messages VALUES(?,?,?,?,?,?,?)",
                            (msg.run_id, msg.step, msg.sender, msg.recipient, msg.type,
                             json.dumps(msg.payload, ensure_ascii=False), msg.ts))


class Runtime:
    """Everything an agent may touch: config, store, log, deadline, tools."""

    def __init__(self, config: Config, store: StateStore, log: Logbook, run_id: str,
                 sleep: Callable[[float], None] = time.sleep):
        self.config, self.store, self.log, self.run_id = config, store, log, run_id
        self.deadline = time.monotonic() + config.timeout_s
        self.sleep = sleep
        self.step = 0

    def check_deadline(self) -> None:
        if time.monotonic() > self.deadline:
            raise LimitExceeded(f"Превышен лимит времени {self.config.timeout_s} с")

    def call_tool(self, agent: str, tool: str, fn: Callable, *args, **kwargs):
        """Run one tool with logging, deadline check and retries on transient errors."""
        kind = "llm_call" if tool in LLM_TOOLS else "tool_call"
        attempts = self.config.tool_retries + 1
        for attempt in range(1, attempts + 1):
            self.check_deadline()
            started = time.perf_counter()
            try:
                result = fn(*args, **kwargs)
            except RETRYABLE as exc:
                ms = round((time.perf_counter() - started) * 1000, 2)
                if attempt < attempts:
                    self.log.event("retry", agent=agent, tool=tool, attempt=attempt,
                                   error=f"{type(exc).__name__}: {exc}", duration_ms=ms)
                    self.sleep(self.config.retry_backoff_s * 2 ** (attempt - 1))
                    continue
                self.log.event(kind, agent=agent, tool=tool, step=self.step, status="error",
                               attempts=attempt, duration_ms=ms, error=f"{type(exc).__name__}: {exc}")
                raise TransientError(f"Инструмент {tool} недоступен после {attempt} попыток: {exc}") from exc
            except MASError as exc:
                ms = round((time.perf_counter() - started) * 1000, 2)
                self.log.event(kind, agent=agent, tool=tool, step=self.step, status="error",
                               attempts=attempt, duration_ms=ms, error=str(exc))
                raise
            except (OSError, ValueError, KeyError, TypeError) as exc:
                ms = round((time.perf_counter() - started) * 1000, 2)
                self.log.event(kind, agent=agent, tool=tool, step=self.step, status="error",
                               attempts=attempt, duration_ms=ms, error=f"{type(exc).__name__}: {exc}")
                raise DataError(f"Инструмент {tool}: {exc}") from exc
            ms = round((time.perf_counter() - started) * 1000, 2)
            self.log.event(kind, agent=agent, tool=tool, step=self.step, status="ok",
                           attempts=attempt, duration_ms=ms)
            return result
        raise AssertionError("unreachable")
