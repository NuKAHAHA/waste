"""Test scenario runner: executes scenarios.json and compares with expectations."""
from __future__ import annotations

import csv
import json
import re
import shutil
import threading
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .core import Config, LLMSettings
from .datagen import generate
from .orchestrator import Orchestrator

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "astana_bins.csv"
CALENDAR = ROOT / "data" / "kz_calendar_2026.json"


class _MockLLM(BaseHTTPRequestHandler):
    """OpenAI-compatible stub: /ok answers from the facts, /bad hallucinates."""

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        facts = json.loads(body["messages"][1]["content"])
        if self.path.startswith("/bad"):
            text = f"Завтра нужно 1234 рейса и {facts['bins_selected']} контейнеров."
        else:
            text = (f"На {facts['target_date']} к вывозу {facts['bins_selected']} из {facts['bins_total']} "
                    f"контейнеров: {facts['trips']} рейс(а), около {facts['distance_km']} км и "
                    f"{facts['volume_m3']} м³. План проверен.")
        data = json.dumps({"choices": [{"message": {"role": "assistant", "content": text}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def _mutate(kind: str, work: Path) -> Path:
    path = work / "input.csv"
    if kind == "missing_file":
        return work / "no_such_file.csv"
    rows = list(csv.reader(DATA.open(encoding="utf-8")))
    if kind == "bad_fill":
        rows[5][6] = "150"
    elif kind == "duplicate":
        rows.insert(3, rows[2])
    elif kind == "bad_header":
        rows[0][6] = "fill"
    elif kind == "uneven_dates":
        rows = [r for r in rows if not (r[0] == "AST-001" and r[5] == "2026-10-24")]
    with path.open("w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(rows)
    return path


def check(expect: dict, result, bundle: dict | None) -> list[str]:
    fails = []
    ev = result.load
    events = _events(result.log_path)
    facts = bundle["facts"] if bundle else {}

    def need(cond, text):
        if not cond:
            fails.append(text)
    need(result.status == expect.get("status", result.status), f"status={result.status}")
    if "exit_code" in expect:
        need(result.exit_code == expect["exit_code"], f"exit={result.exit_code}")
    if "message_contains" in expect:
        need(expect["message_contains"].lower() in result.message.lower(), f"message='{result.message}'")
    if "replans" in expect:
        need(result.replans == expect["replans"], f"replans={result.replans}")
    if "replans_ge" in expect:
        need(result.replans >= expect["replans_ge"], f"replans={result.replans}")
    if "max_share_le" in expect:
        need(ev["max_share"] <= expect["max_share_le"], f"max_share={ev['max_share']}")
    if "min_selected" in expect:
        need(facts.get("bins_selected", 0) >= expect["min_selected"], f"selected={facts.get('bins_selected')}")
    if expect.get("all_critical_served"):
        served = {b for t in bundle["plan"]["trips"] for b in t["bin_ids"]}
        crit = {d["bin_id"] for d in bundle["decisions"] if d["category"] == "critical"}
        need(crit <= served, f"unserved critical={sorted(crit - served)}")
    if "off_days_include" in expect:
        need(any(expect["off_days_include"] in x for x in facts.get("off_days_in_horizon", [])), "off day missing")
    if expect.get("deferred_nonempty"):
        need(bool(facts.get("deferred")), "nothing deferred")
    if expect.get("mae_order"):
        m = facts["forecast_mae_pp"]
        need(m["calendar_model"] < m["linear"] < m["persistence"], f"mae={m}")
    if "mae_model_le" in expect:
        need(facts["forecast_mae_pp"]["calendar_model"] <= expect["mae_model_le"], "mae too high")
    if "summary_source" in expect:
        need(bundle and bundle["summary_source"] == expect["summary_source"],
             f"summary_source={bundle and bundle['summary_source']}")
    if "llm_calls" in expect:
        n = sum(1 for e in events if e["kind"] == "llm_call")
        need(n == expect["llm_calls"], f"llm_calls={n}")
    if "guard_events" in expect:
        n = sum(1 for e in events if e["kind"] == "guard")
        need(n == expect["guard_events"], f"guard={n}")
    if "retries_ge" in expect:
        n = sum(1 for e in events if e["kind"] == "retry")
        need(n >= expect["retries_ge"], f"retries={n}")
    return fails


def _events(path: str) -> list[dict]:
    p = Path(path)
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.is_file() else []


def run_one(sc: dict, out_root: Path, llm_port: int) -> dict:
    work = out_root / sc["id"]
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    inp = sc.get("input", {})
    if "mutate" in inp:
        source = _mutate(inp["mutate"], work)
    elif "generate_seed" in inp:
        source = work / "input.csv"
        generate(source, CALENDAR, seed=inp["generate_seed"])
    else:
        source = DATA
    cfg = Config(retry_backoff_s=0.05)
    cfg = replace(cfg, **sc.get("config", {}))
    mode = sc.get("llm")
    if mode:
        url = {"ok": f"http://127.0.0.1:{llm_port}/ok", "hallucinate": f"http://127.0.0.1:{llm_port}/bad",
               "down": "http://127.0.0.1:9"}[mode]
        cfg = replace(cfg, use_llm=True, llm=LLMSettings(url, "mock-model", "", 2.0))
    result = Orchestrator(cfg, work, run_id=sc["id"]).run(source, CALENDAR)
    report = work / "report.json"
    bundle = json.loads(report.read_text(encoding="utf-8")) if report.is_file() and result.status in ("approved", "rejected") else None
    fails = check(sc["expect"], result, bundle)
    return {"id": sc["id"], "name": sc["name"], "passed": not fails, "fails": fails, "status": result.status,
            "message": result.message, "steps": result.steps, "replans": result.replans,
            "calls": result.load["total_calls"], "max_share": result.load["max_share"],
            "expect": sc["expect"]}


def run_scenarios(file: Path, out_root: Path) -> int:
    scenarios = json.loads(Path(file).read_text(encoding="utf-8"))
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MockLLM)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        results = [run_one(sc, out_root, server.server_address[1]) for sc in scenarios]
    finally:
        server.shutdown()
        server.server_close()
    passed = sum(r["passed"] for r in results)
    lines = ["# Результаты тестовых сценариев", "",
             f"Пройдено **{passed} из {len(results)}** ({passed / len(results):.0%}).", "",
             "| ID | Сценарий | Ожидание | Факт | Шаги | Вызовы | Макс. доля | Итог |",
             "|---|---|---|---|---:|---:|---:|---|"]
    for r in results:
        exp = ", ".join(f"{k}={v}" for k, v in r["expect"].items())
        fact = f"{r['status']}: {r['message']}"
        lines.append(f"| {r['id']} | {r['name']} | {exp} | {re.sub(r'[|]', '/', fact)} | {r['steps']} | "
                     f"{r['calls']} | {r['max_share']:.0%} | {'✅' if r['passed'] else '❌ ' + '; '.join(r['fails'])} |")
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "scenarios_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out_root / "scenarios_report.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    for r in results:
        print(f"{'PASS' if r['passed'] else 'FAIL'} {r['id']} {r['name']}: {r['status']}"
              + ("" if r["passed"] else f"  ← {'; '.join(r['fails'])}"))
    print(f"Итого: {passed}/{len(results)}. Отчёт: {out_root / 'scenarios_report.md'}")
    return 0 if passed == len(results) else 1
