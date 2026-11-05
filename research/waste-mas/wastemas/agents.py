"""Six specialised agents. Each has one role, at most 5 tools and a clear
completion criterion. Agents communicate only through Messages (via the
orchestrator) and the shared SQLite state store (blackboard).
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

from . import tools as T
from .core import DataError, LimitExceeded, MASError, Message
from .dashboard import render_dashboard
from .runtime import Runtime

MAX_TOOLS = 5


class Agent:
    """Base class: validates the task, exposes only the agent's own tools."""
    name = "agent"
    role = ""
    tasks: tuple[str, ...] = ()
    tools: dict[str, Callable] = {}
    done_when = ""

    def __init__(self, rt: Runtime):
        if len(self.tools) > MAX_TOOLS:
            raise ValueError(f"{self.name}: больше {MAX_TOOLS} инструментов")
        self.rt = rt

    def use(self, tool: str, *args, **kwargs):
        if tool not in self.tools:
            raise DataError(f"Агент {self.name} не имеет инструмента {tool}")
        return self.rt.call_tool(self.name, tool, self.tools[tool], *args, **kwargs)

    # blackboard helpers wrapped as tools
    def read(self, *keys: str) -> dict:
        return self.use("db_read", self.rt.run_id, keys)

    def write(self, author_data: dict) -> dict:
        return self.use("db_write", self.rt.run_id, self.name, author_data)

    def handle(self, msg: Message) -> Message:
        task = msg.payload.get("task")
        if task not in self.tasks:
            raise DataError(f"Агент {self.name} не выполняет задачу '{task}'")
        summary = getattr(self, task)(**msg.payload.get("params", {}))
        return Message(self.rt.run_id, msg.step, self.name, msg.sender, "result",
                       {"task": task, "status": "ok", "summary": summary})


def _make_db_tools(store):
    def db_read(run_id: str, keys) -> dict:
        return {k: (store.load_readings(run_id) if k == "readings" else store.get(run_id, k)) for k in keys}

    def db_write(run_id: str, author: str, data: dict) -> dict:
        versions = {}
        for k, v in data.items():
            if k == "readings":
                versions[k] = store.save_readings(run_id, v)
            else:
                versions[k] = store.put(run_id, k, v, author)
        return versions
    return db_read, db_write


class DataAgent(Agent):
    name = "data"
    role = "Загрузка и валидация телеметрии контейнеров, запись в хранилище"
    tasks = ("ingest",)
    done_when = "все строки проверены и сохранены в SQLite, либо выдана ошибка с номером строки"

    def __init__(self, rt):
        db_read, db_write = _make_db_tools(rt.store)
        self.tools = {"read_csv": T.read_csv, "validate_readings": T.validate_readings, "db_write": db_write}
        super().__init__(rt)

    def ingest(self, path: str) -> dict:
        rows = self.use("read_csv", path)
        checked = self.use("validate_readings", rows)
        self.write({"readings": checked["readings"], "dataset_summary": checked["summary"]})
        return checked["summary"]


class ForecastAgent(Agent):
    name = "forecast"
    role = "Прогноз заполненности на горизонт с учётом выходных и праздников"
    tasks = ("forecast",)
    done_when = "для каждого контейнера есть прогноз на целевую дату"

    def __init__(self, rt):
        db_read, db_write = _make_db_tools(rt.store)
        self.tools = {"db_read": db_read, "load_calendar": T.load_calendar,
                      "estimate_rates": T.estimate_rates, "project_fill": T.project_fill, "db_write": db_write}
        super().__init__(rt)

    def forecast(self, calendar: str) -> dict:
        data = self.read("readings", "dataset_summary")
        s = data["dataset_summary"]
        end = (date.fromisoformat(s["last_date"]) + timedelta(days=self.rt.config.horizon_days)).isoformat()
        cal = self.use("load_calendar", calendar, s["first_date"], end)
        model = self.use("estimate_rates", data["readings"], cal["off_days"])
        fc = self.use("project_fill", data["readings"], model, cal["off_days"], self.rt.config.horizon_days)
        horizon_off = {d: n for d, n in cal["off_days"].items() if d > s["last_date"]}
        self.write({"forecasts": fc, "calendar": cal,
                    "forecast_model": {"uplift": model["uplift"], "bins_used_for_uplift": model["bins_used_for_uplift"],
                                       "horizon_off_days": horizon_off}})
        return {"bins": len(fc), "uplift": model["uplift"], "target_date": fc[0]["target_date"] if fc else None,
                "overflow": sum(f["overflow"] for f in fc), "horizon_off_days": horizon_off}


class PriorityAgent(Agent):
    name = "priority"
    role = "Отбор контейнеров к вывозу, категории срочности, перенос при нехватке рейсов"
    tasks = ("prioritize", "defer")
    done_when = "у каждого контейнера есть решение selected/deferred и объяснение"

    def __init__(self, rt):
        db_read, db_write = _make_db_tools(rt.store)
        self.tools = {"db_read": db_read, "score_bins": T.score_bins, "defer_bins": T.defer_bins,
                      "db_write": db_write}
        super().__init__(rt)

    def prioritize(self) -> dict:
        fc = self.read("forecasts")["forecasts"]
        decisions = self.use("score_bins", fc, self.rt.config.threshold_pct)
        self.write({"decisions": decisions})
        return {"selected": sum(d["selected"] for d in decisions),
                "critical": sum(d["category"] == "critical" for d in decisions),
                "volume_m3": round(sum(d["load_m3"] for d in decisions if d["selected"]), 3)}

    def defer(self, violations: list | None = None) -> dict:
        decisions = self.read("decisions")["decisions"]
        cfg = self.rt.config
        result = self.use("defer_bins", decisions, cfg.fleet_trips * cfg.truck_capacity_m3)
        self.write({"decisions": result["decisions"]})
        return {"deferred": result["deferred"], "volume_m3": result["volume_m3"],
                "progress": result["progress"],
                "selected": sum(d["selected"] for d in result["decisions"])}


class RouteAgent(Agent):
    name = "route"
    role = "Построение рейсов: вместимость машины, ближайший сосед + 2-opt, распределение по машинам"
    tasks = ("plan_routes",)
    done_when = "каждый выбранный контейнер ровно в одном рейсе, рейсы начинаются и заканчиваются в депо"

    def __init__(self, rt):
        db_read, db_write = _make_db_tools(rt.store)
        self.tools = {"db_read": db_read, "distance_matrix": T.distance_matrix,
                      "build_trips": T.build_trips, "improve_2opt": T.improve_2opt, "db_write": db_write}
        super().__init__(rt)

    def plan_routes(self) -> dict:
        data = self.read("decisions", "forecasts")
        cfg = self.rt.config
        fc = {f["bin_id"]: f for f in data["forecasts"]}
        chosen = sorted((d for d in data["decisions"] if d["selected"]), key=lambda d: d["bin_id"])
        points = [cfg.depot] + [(fc[d["bin_id"]]["latitude"], fc[d["bin_id"]]["longitude"]) for d in chosen]
        loads = [d["load_m3"] for d in chosen]
        matrix = self.use("distance_matrix", points)
        raw = self.use("build_trips", loads, matrix, cfg.truck_capacity_m3)
        opt = self.use("improve_2opt", raw, matrix)
        trips = []
        for i, trip in enumerate(opt["trips"]):
            trips.append({"trip_id": i + 1, "truck": i % cfg.trucks + 1,
                          "bin_ids": [chosen[k - 1]["bin_id"] for k in trip],
                          "load_m3": round(sum(loads[k - 1] for k in trip), 4),
                          "distance_km": round(T.route_length(trip, matrix), 3)})
        plan = {"trips": trips, "km_greedy": opt["km_before"], "km_2opt": opt["km_after"],
                "depot": list(cfg.depot)}
        self.write({"plan": plan})
        return {"trips": len(trips), "km": opt["km_after"], "km_greedy": opt["km_before"]}


class VerifierAgent(Agent):
    name = "verifier"
    role = "Независимая проверка плана (ограничения) и качества прогноза (бэктест)"
    tasks = ("verify",)
    done_when = "вынесен вердикт approved/rejected со списком нарушений"

    def __init__(self, rt):
        db_read, db_write = _make_db_tools(rt.store)
        self.tools = {"db_read": db_read, "check_plan": T.check_plan, "backtest": T.backtest,
                      "db_write": db_write}
        super().__init__(rt)

    def verify(self) -> dict:
        cfg = self.rt.config
        data = self.read("decisions", "plan", "readings", "calendar")
        verdict = self.use("check_plan", data["decisions"], data["plan"], cfg.fleet_trips, cfg.truck_capacity_m3)
        quality = self.use("backtest", data["readings"], data["calendar"]["off_days"])
        mae = quality["mae_pp"]
        verdict["warnings"] = []
        if mae["calendar_model"] is not None and mae["persistence"] is not None \
                and mae["calendar_model"] > mae["persistence"]:
            verdict["warnings"].append("модель прогноза хуже наивного метода на контрольной дате")
        verdict["backtest"] = quality
        self.write({"verdict": verdict})
        return {"approved": verdict["approved"], "violations": verdict["violations"],
                "mae_pp": mae, "warnings": verdict["warnings"]}


class ReportAgent(Agent):
    name = "report"
    role = "Сводка для диспетчера (LLM или шаблон) и выходные файлы"
    tasks = ("report",)
    done_when = "созданы report.json, plan.csv, dashboard.html"

    SYSTEM = ("Ты помощник диспетчера службы вывоза мусора в Астане. Напиши короткую сводку "
              "(4-6 предложений, по-русски, без нумерованных списков) по плану. Используй ТОЛЬКО "
              "числа из переданного JSON, ничего не придумывай и не округляй по-новому.")

    def __init__(self, rt):
        db_read, _ = _make_db_tools(rt.store)
        self.tools = {"db_read": db_read, "llm_complete": T.llm_complete,
                      "template_summary": T.template_summary, "write_outputs": T.write_outputs}
        super().__init__(rt)

    def report(self, output: str, status: str = "ok", trace: list | None = None) -> dict:
        data = self.read("dataset_summary", "forecasts", "forecast_model", "decisions", "plan", "verdict")
        facts = self._facts(data)
        summary, source, note = None, "template", None
        cfg = self.rt.config
        if cfg.use_llm:
            try:
                text = self.use("llm_complete", cfg.llm, self.SYSTEM, json.dumps(facts, ensure_ascii=False))
                bad = T.numbers_grounded(text, facts)
                if bad:
                    note = f"LLM-ответ отклонён: числа без источника {bad[:5]}"
                    self.rt.log.event("guard", agent=self.name, rejected_numbers=bad[:10])
                else:
                    summary, source = text, "llm"
            except LimitExceeded:
                raise
            except MASError as exc:  # LLM is optional: failure -> deterministic template
                note = f"LLM недоступна: {exc}"
                self.rt.log.event("fallback", agent=self.name, tool="template_summary", reason=str(exc))
        if summary is None:
            summary = self.use("template_summary", facts)
        bundle = {"status": status, "summary": summary, "summary_source": source, "summary_note": note,
                  "facts": facts, "dataset": data["dataset_summary"], "forecast_model": data["forecast_model"],
                  "forecasts": data["forecasts"], "decisions": data["decisions"], "plan": data["plan"],
                  "verdict": data["verdict"], "config": cfg.public_dict(), "run_id": self.rt.run_id,
                  "trace": trace or []}
        html = render_dashboard(bundle, self.rt.log.load_distribution())
        files = self.use("write_outputs", output, bundle, html)
        return {"files": files, "summary_source": source, "note": note}

    @staticmethod
    def _facts(d: dict) -> dict:
        plan, dec = d["plan"], d["decisions"]
        v = d["verdict"]
        return {"target_date": d["forecasts"][0]["target_date"] if d["forecasts"] else "",
                "bins_total": len(dec), "bins_selected": sum(x["selected"] for x in dec),
                "trips": len(plan["trips"]), "distance_km": round(sum(t["distance_km"] for t in plan["trips"]), 2),
                "volume_m3": round(sum(t["load_m3"] for t in plan["trips"]), 2),
                "critical": [x["bin_id"] for x in dec if x["category"] == "critical" and x["selected"]],
                "deferred": [x["bin_id"] for x in dec if x["deferred"]],
                "off_days_in_horizon": [f"{k} ({n})" for k, n in d["forecast_model"]["horizon_off_days"].items()],
                "approved": v["approved"],
                "violations": "; ".join(x["code"] for x in v["violations"]) or "нет",
                "forecast_mae_pp": v["backtest"]["mae_pp"]}


AGENT_CLASSES = (DataAgent, ForecastAgent, PriorityAgent, RouteAgent, VerifierAgent, ReportAgent)
