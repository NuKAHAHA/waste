"""Orchestrator: builds the task plan, dispatches messages and replans.

It does no domain work: it never reads telemetry, forecasts or routes. It only
looks at the ``status`` / ``approved`` / ``fix`` fields of result messages to
decide which task to send next, and enforces step, time and replan limits.
"""
from __future__ import annotations

import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from .agents import AGENT_CLASSES
from .core import Config, LimitExceeded, MASError, Message
from .runtime import Logbook, Runtime, StateStore

BASE_PLAN = (("data", "ingest"), ("forecast", "forecast"), ("priority", "prioritize"),
             ("route", "plan_routes"), ("verifier", "verify"), ("report", "report"))
REPAIRS = {"defer": (("priority", "defer"), ("route", "plan_routes"), ("verifier", "verify"))}


@dataclass
class RunResult:
    run_id: str
    status: str               # approved | rejected | aborted | error
    message: str
    steps: int
    replans: int
    trace: list = field(default_factory=list)
    load: dict = field(default_factory=dict)
    output: str = ""
    log_path: str = ""
    summaries: dict = field(default_factory=dict)

    @property
    def exit_code(self) -> int:
        return {"approved": 0, "rejected": 1, "aborted": 1}.get(self.status, 2)


class Orchestrator:
    name = "orchestrator"

    def __init__(self, config: Config, output: Path, store_path: Path | str | None = None,
                 run_id: str | None = None, sleep=time.sleep):
        self.config, self.output = config, Path(output)
        self.run_id = run_id or time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        self.log_path = self.output / "logs" / f"run_{self.run_id}.jsonl"
        self.store = StateStore(store_path if store_path is not None else self.output / "state.db")
        self.log = Logbook(self.log_path, self.run_id)
        self.rt = Runtime(config, self.store, self.log, self.run_id, sleep)
        self.agents = {cls.name: cls(self.rt) for cls in AGENT_CLASSES}

    def _dispatch(self, agent: str, task: str, params: dict) -> Message:
        if self.rt.step >= self.config.max_steps:
            raise LimitExceeded(f"Превышен лимит шагов ({self.config.max_steps})")
        self.rt.step += 1
        self.rt.check_deadline()
        msg = Message(self.run_id, self.rt.step, self.name, agent, "task", {"task": task, "params": params})
        self.store.log_message(msg)
        self.log.event("message", step=msg.step, sender=msg.sender, recipient=agent, type="task",
                       payload=msg.payload)
        started = time.perf_counter()
        try:
            reply = self.agents[agent].handle(msg)
        except MASError as exc:
            self.log.event("agent_call", agent=agent, task=task, step=msg.step, status="error",
                           duration_ms=round((time.perf_counter() - started) * 1000, 2), error=str(exc))
            raise
        self.log.event("agent_call", agent=agent, task=task, step=msg.step, status="ok",
                       duration_ms=round((time.perf_counter() - started) * 1000, 2))
        self.store.log_message(reply)
        self.log.event("message", step=reply.step, sender=agent, recipient=self.name, type="result",
                       payload=reply.payload)
        return reply

    def run(self, input_csv: Path, calendar: Path) -> RunResult:
        cfg = self.config
        self.store.start_run(self.run_id, cfg.public_dict())
        self.log.event("run_start", config=cfg.public_dict(), input=str(input_csv))
        queue = deque(BASE_PLAN)
        self.log.event("plan", agent=self.name, tasks=[f"{a}.{t}" for a, t in queue])
        trace, summaries, replans, status, message = [], {}, 0, "error", ""
        approved = False
        params = {"ingest": {"path": str(input_csv)}, "forecast": {"calendar": str(calendar)}}
        try:
            while queue:
                agent, task = queue.popleft()
                p = dict(params.get(task, {}))
                if task == "report":
                    p = {"output": str(self.output), "status": "approved" if approved else "rejected",
                         "trace": trace + ["report.report"]}
                reply = self._dispatch(agent, task, p)
                trace.append(f"{agent}.{task}")
                summary = reply.payload["summary"]
                summaries[f"{self.rt.step}:{agent}.{task}"] = summary
                if task == "defer" and not summary["progress"]:
                    queue = deque(t for t in queue if t[0] == "report")
                    self.log.event("replan", agent=self.name, decision="no_progress_stop")
                if task == "verify":
                    approved = summary["approved"]
                    fixes = {v["fix"] for v in summary["violations"]}
                    if not approved and fixes == {"defer"} and replans < cfg.max_replans:
                        replans += 1
                        self.log.event("replan", agent=self.name, iteration=replans, fix="defer",
                                       violations=[v["code"] for v in summary["violations"]])
                        queue.extendleft(reversed(REPAIRS["defer"]))
                    elif not approved:
                        self.log.event("replan", agent=self.name, decision="stop",
                                       reason="нет исправления" if fixes != {"defer"} else "лимит перепланирований")
            status = "approved" if approved else "rejected"
            message = ("План утверждён проверяющим агентом" if approved else
                       "План не утверждён: " + "; ".join(v["code"] for v in summary_violations(summaries)))
        except LimitExceeded as exc:
            status, message = "aborted", str(exc)
        except MASError as exc:
            status, message = "error", str(exc)
        self.log.event("run_end", status=status, message=message, steps=self.rt.step, replans=replans)
        load = self.log.load_distribution()
        self.store.finish_run(self.run_id, status, None if status == "approved" else message)
        self.store.close()
        _write_load_report(self.output / "load_report.md", self.run_id, load, trace, status)
        return RunResult(self.run_id, status, message, self.rt.step, replans, trace, load,
                         str(self.output), str(self.log_path), summaries)


def summary_violations(summaries: dict) -> list:
    verifies = [v for k, v in summaries.items() if k.endswith("verifier.verify")]
    return verifies[-1]["violations"] if verifies else []


def _write_load_report(path: Path, run_id: str, load: dict, trace: list, status: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# Распределение нагрузки — прогон {run_id}", "",
             f"Статус: **{status}**. Всего вызовов инструментов и LLM: **{load['total_calls']}**. "
             f"Максимальная доля агента: **{load['max_share']:.1%}** (лимит 40%) — "
             + ("✅ соблюдён" if load["balanced"] else "❌ превышен"), "",
             "| Агент | Вызовов агента | Инструменты | LLM | Всего | Доля |", "|---|---:|---:|---:|---:|---:|"]
    for name, a in load["agents"].items():
        lines.append(f"| {name} | {a['agent_calls']} | {a['tool_calls']} | {a['llm_calls']} | "
                     f"{a['total_calls']} | {a['share']:.1%} |")
    lines += ["", "Оркестратор не вызывает инструментов: только планирует и рассылает задачи.", "",
              "Трасса: " + " → ".join(trace)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
