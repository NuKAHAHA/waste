"""Unit and integration tests: python -m unittest discover -s tests -v"""
import csv
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wastemas import tools as T  # noqa: E402
from wastemas.agents import AGENT_CLASSES, MAX_TOOLS  # noqa: E402
from wastemas.core import (Config, DataError, LimitExceeded, LLMSettings, Message,  # noqa: E402
                           TransientError)
from wastemas.datagen import TRUE_UPLIFT, generate  # noqa: E402
from wastemas.orchestrator import Orchestrator  # noqa: E402
from wastemas.runtime import Logbook, Runtime, StateStore  # noqa: E402
from wastemas.scenarios import run_scenarios  # noqa: E402

DATA = ROOT / "data" / "astana_bins.csv"
CAL = ROOT / "data" / "kz_calendar_2026.json"


def rows(series):
    """series: {bin: [fill,...]} daily from 2026-10-01 -> raw CSV dict rows."""
    out = []
    for i, (b, fills) in enumerate(series.items()):
        for k, f in enumerate(fills):
            out.append({"bin_id": b, "district": "Есиль", "latitude": str(51.1 + i / 100), "longitude": "71.4",
                        "capacity_m3": "1.1", "observed_on": (date(2026, 10, 1) + timedelta(days=k)).isoformat(),
                        "fill_pct": str(f)})
    return out


class ToolTests(unittest.TestCase):
    def test_validation_detects_collections(self):
        res = T.validate_readings(rows({"A": [10, 50, 90, 5, 20]}))
        self.assertEqual(res["summary"]["collections_detected"], 1)

    def test_validation_rejects_bad_values(self):
        for bad in ("150", "nan", "-1", ""):
            r = rows({"A": [10, 20, 30]})
            r[1]["fill_pct"] = bad
            with self.assertRaises(DataError):
                T.validate_readings(r)

    def test_validation_requires_three_points_and_common_last_date(self):
        with self.assertRaises(DataError):
            T.validate_readings(rows({"A": [10, 20]}))
        with self.assertRaises(DataError):
            T.validate_readings(rows({"A": [10, 20, 30], "B": [1, 2, 3, 4]}))

    def test_calendar_includes_transfer_and_weekends(self):
        cal = T.load_calendar(CAL, "2026-10-23", "2026-10-27")["off_days"]
        self.assertEqual(sorted(cal), ["2026-10-24", "2026-10-25", "2026-10-26"])

    def test_uplift_recovers_generator_truth(self):
        data = T.validate_readings(T.read_csv(DATA))
        cal = T.load_calendar(CAL, data["summary"]["first_date"], "2026-10-31")["off_days"]
        model = T.estimate_rates(data["readings"], cal)
        self.assertAlmostEqual(model["uplift"], TRUE_UPLIFT, delta=0.05)

    def test_projection_uses_calendar_and_caps(self):
        r = T.validate_readings(rows({"A": [10, 20, 30]}))["readings"]
        model = {"uplift": 0.5, "rates": {"A": 10.0}}
        work = T.project_fill(r, model, {}, 1)[0]
        off = T.project_fill(r, model, {"2026-10-04": "x"}, 1)[0]
        self.assertEqual(work["predicted_pct"], 40.0)
        self.assertEqual(off["predicted_pct"], 45.0)
        self.assertEqual(T.project_fill(r, {"uplift": 0, "rates": {"A": 90}}, {}, 1)[0]["predicted_pct"], 100.0)

    def test_priority_threshold_inclusive_and_critical(self):
        f = [{"bin_id": "A", "overflow": False, "fill_pct": 50, "predicted_pct": 80.0, "capacity_m3": 1},
             {"bin_id": "B", "overflow": True, "fill_pct": 90, "predicted_pct": 100.0, "capacity_m3": 1},
             {"bin_id": "C", "overflow": False, "fill_pct": 10, "predicted_pct": 20.0, "capacity_m3": 1}]
        d = {x["bin_id"]: x for x in T.score_bins(f, 80)}
        self.assertTrue(d["A"]["selected"])
        self.assertEqual(d["B"]["category"], "critical")
        self.assertFalse(d["C"]["selected"])

    def test_defer_never_drops_critical_and_always_progresses(self):
        dec = [{"bin_id": "A", "selected": True, "category": "critical", "predicted_pct": 100, "load_m3": 5},
               {"bin_id": "B", "selected": True, "category": "high", "predicted_pct": 85, "load_m3": 1}]
        res = T.defer_bins(dec, fleet_volume_m3=100)
        self.assertEqual(res["deferred"], ["B"])
        res2 = T.defer_bins(res["decisions"], fleet_volume_m3=1)
        self.assertFalse(res2["progress"])

    def test_trips_respect_capacity_and_serve_each_once(self):
        pts = [(51.128, 71.43)] + [(51.1 + i / 200, 71.4 + i / 300) for i in range(12)]
        m = T.distance_matrix(pts)
        loads = [1.1, 2.5, 0.66] * 4
        trips = T.build_trips(loads, m, 4.0)
        flat = [i for t in trips for i in t]
        self.assertEqual(sorted(flat), list(range(1, 13)))
        self.assertTrue(all(sum(loads[i - 1] for i in t) <= 4.0 + 1e-9 for t in trips))
        opt = T.improve_2opt(trips, m)
        self.assertLessEqual(opt["km_after"], opt["km_before"])
        with self.assertRaises(DataError):
            T.build_trips([5.0], T.distance_matrix(pts[:2]), 4.0)

    def test_check_plan_finds_violations(self):
        dec = [{"bin_id": "A", "selected": True, "category": "critical", "load_m3": 3},
               {"bin_id": "B", "selected": True, "category": "high", "load_m3": 3}]
        plan = {"trips": [{"trip_id": 1, "bin_ids": ["A", "A"], "load_m3": 6, "distance_km": 1}]}
        codes = {v["code"] for v in T.check_plan(dec, plan, 1, 4)["violations"]}
        self.assertTrue({"unserved", "duplicate", "overload"} <= codes)

    def test_hallucination_guard(self):
        facts = {"trips": 2, "distance_km": 49.89, "date": "2026-10-25"}
        self.assertEqual(T.numbers_grounded("2 рейса, 49.9 км, 25 октября 2026", facts), [])
        self.assertEqual(T.numbers_grounded("нужно 1234 рейса", facts), ["1234"])

    def test_csv_output_is_formula_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = {"plan": {"trips": []}, "forecasts": [{"bin_id": "=cmd()", "district": "+x"}],
                      "decisions": [{"bin_id": "=cmd()", "fill_pct": 1, "predicted_pct": 2, "category": "low",
                                     "selected": False, "deferred": False, "reason": "@evil"}]}
            T.write_outputs(tmp, bundle, "<html></html>")
            text = (Path(tmp) / "plan.csv").read_text(encoding="utf-8-sig")
            self.assertIn("'=cmd()", text)
            self.assertIn("'@evil", text)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.cfg = Config(tool_retries=2, retry_backoff_s=0)
        self.rt = Runtime(self.cfg, StateStore(), Logbook(None, "t"), "t", sleep=lambda s: None)

    def test_retry_then_success(self):
        calls = []

        def flaky():
            calls.append(1)
            if len(calls) < 3:
                raise TransientError("temporary")
            return "ok"
        self.assertEqual(self.rt.call_tool("a", "flaky", flaky), "ok")
        self.assertEqual(sum(e["kind"] == "retry" for e in self.rt.log.events), 2)

    def test_retry_exhausted_gives_clear_error(self):
        def down():
            raise ConnectionError("refused")
        with self.assertRaises(TransientError) as ctx:
            self.rt.call_tool("a", "down", down)
        self.assertIn("после 3 попыток", str(ctx.exception))

    def test_data_errors_are_not_retried(self):
        def bad():
            raise DataError("bad")
        with self.assertRaises(DataError):
            self.rt.call_tool("a", "bad", bad)
        self.assertFalse(any(e["kind"] == "retry" for e in self.rt.log.events))

    def test_deadline(self):
        self.rt.deadline = 0
        with self.assertRaises(LimitExceeded):
            self.rt.call_tool("a", "x", lambda: 1)

    def test_store_keeps_versions(self):
        s = self.rt.store
        s.put("t", "k", {"v": 1}, "a")
        self.assertEqual(s.put("t", "k", {"v": 2}, "b"), 2)
        self.assertEqual(s.get("t", "k"), {"v": 2})

    def test_message_roundtrip(self):
        m = Message("r", 1, "orchestrator", "data", "task", {"task": "ingest", "params": {"path": "x"}})
        self.assertEqual(Message.from_json(m.to_json()), m)


class SystemTests(unittest.TestCase):
    def test_agent_contracts(self):
        rt = Runtime(Config(), StateStore(), Logbook(None, "t"), "t")
        agents = [cls(rt) for cls in AGENT_CLASSES]
        self.assertGreaterEqual(len(agents), 5)
        self.assertEqual(len({a.name for a in agents}), len(agents))
        tasks = [t for a in agents for t in a.tasks]
        self.assertEqual(len(tasks), len(set(tasks)), "роли/задачи не должны дублироваться")
        for a in agents:
            self.assertLessEqual(len(a.tools), MAX_TOOLS)
            self.assertTrue(a.role and a.done_when)

    def test_typical_run_balanced_and_logged(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = Orchestrator(Config(), Path(tmp), run_id="t1").run(DATA, CAL)
            self.assertEqual(res.status, "approved")
            self.assertLessEqual(res.load["max_share"], 0.40)
            self.assertNotIn("orchestrator", res.load["agents"])
            events = [json.loads(x) for x in Path(res.log_path).read_text(encoding="utf-8").splitlines()]
            kinds = {e["kind"] for e in events}
            self.assertTrue({"run_start", "plan", "message", "agent_call", "tool_call", "run_end"} <= kinds)
            for name in ("report.json", "plan.csv", "dashboard.html", "load_report.md", "state.db"):
                self.assertTrue((Path(tmp) / name).is_file(), name)

    def test_outputs_deterministic(self):
        outs = []
        for i in range(2):
            with tempfile.TemporaryDirectory() as tmp:
                Orchestrator(Config(), Path(tmp), run_id="same").run(DATA, CAL)
                b = json.loads((Path(tmp) / "report.json").read_text(encoding="utf-8"))
                outs.append((b["plan"], b["decisions"], b["summary"]))
        self.assertEqual(outs[0], outs[1])

    def test_api_key_never_logged(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = replace(Config(retry_backoff_s=0, tool_retries=0), use_llm=True,
                          llm=LLMSettings("http://127.0.0.1:9", "m", "sk-SECRET-123", 0.5))
            res = Orchestrator(cfg, Path(tmp), run_id="k").run(DATA, CAL)
            self.assertEqual(res.status, "approved")
            for p in Path(tmp).rglob("*"):
                if p.is_file() and p.suffix != ".db":
                    self.assertNotIn("sk-SECRET-123", p.read_text(encoding="utf-8", errors="ignore"), p)

    def test_generator_reproducible(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / "a.csv", Path(tmp) / "b.csv"
            generate(a, CAL, seed=42)
            generate(b, CAL, seed=42)
            self.assertEqual(a.read_bytes(), b.read_bytes())
            self.assertEqual(a.read_bytes(), DATA.read_bytes())

    def test_all_scenarios_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = run_scenarios(ROOT / "scenarios" / "scenarios.json", Path(tmp))
            report = json.loads((Path(tmp) / "scenarios_report.json").read_text(encoding="utf-8"))
            self.assertGreaterEqual(len(report), 10)
            self.assertEqual(code, 0, [r for r in report if not r["passed"]])


if __name__ == "__main__":
    unittest.main()
