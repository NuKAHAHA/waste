"""Behavioral tests: data quality, holdout integrity, routing, CLI and exports."""
import contextlib
import csv
import io
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from smart_waste.agents import (AnalysisAgent, EvaluationAgent, PriorityAgent,
                               distance_km, fit_growth, predict, run_pipeline)
from smart_waste.cli import main
from smart_waste.data import FIELDS, generate_demo, load_csv
from smart_waste.export import export_results
from smart_waste.models import Config, Context, DataError, Reading


def readings(values=(50, 60, 70), bin_id="A", capacity=4.0, lat=51.13, lon=71.43):
    return [Reading(bin_id, "Есиль", lat, lon, capacity,
                    date(2026, 10, 1) + timedelta(days=i), value)
            for i, value in enumerate(values)]


class AgentTests(unittest.TestCase):
    def test_known_linear_growth(self):
        self.assertAlmostEqual(fit_growth(readings()), 10)
        self.assertAlmostEqual(predict(readings(), 2), 90)

    def test_irregular_dates_use_elapsed_days(self):
        rows = [Reading("A", "X", 0, 0, 1, date(2026, 1, d), fill)
                for d, fill in ((1, 10), (3, 20), (7, 40))]
        self.assertAlmostEqual(fit_growth(rows), 5)

    def test_forecast_capped_at_capacity(self):
        self.assertEqual(predict(readings((70, 80, 90)), 5), 100)

    def test_constant_fill_zero_growth(self):
        self.assertEqual(fit_growth(readings((40, 40, 40))), 0)

    def test_threshold_is_inclusive(self):
        c = run_pipeline(Context(readings((60, 70, 80)), Config()), 2)
        self.assertTrue(c.states[0].selected)

    def test_forecast_changes_collection_decision(self):
        data = readings((55, 65, 75))
        current = run_pipeline(Context(data, Config()), 2)
        forecast = run_pipeline(Context(data, Config()), 5)
        self.assertFalse(current.states[0].selected)
        self.assertTrue(forecast.states[0].selected)

    def test_holdout_does_not_train_on_last_value(self):
        c = Context(readings((10, 20, 90)), Config())
        EvaluationAgent().run(c)
        self.assertAlmostEqual(c.metrics["holdout_cases"][0]["forecast_pct"], 30)
        self.assertAlmostEqual(c.metrics["forecast_mae_pp"], 60)

    def test_perfect_linear_holdout(self):
        c = run_pipeline(Context(readings(), Config()), 5)
        self.assertEqual(c.metrics["forecast_mae_pp"], 0)
        self.assertEqual(c.metrics["persistence_mae_pp"], 10)

    def test_capacity_and_exactly_once_service(self):
        data = readings((70, 80, 90), "A") + readings((70, 80, 90), "B", lon=71.44)
        c = run_pipeline(Context(data, Config(truck_capacity_m3=4)), 5)
        ids = [bid for trip in c.trips for bid in trip.bin_ids]
        self.assertEqual(sorted(ids), ["A", "B"])
        self.assertEqual(len(c.trips), 2)
        self.assertTrue(all(t.load_m3 <= 4 for t in c.trips))

    def test_depot_return_is_counted(self):
        c = run_pipeline(Context(readings((70, 80, 90), lat=51.15), Config()), 5)
        expected = 2 * distance_km((51.128, 71.430), (51.15, 71.43))
        self.assertAlmostEqual(c.trips[0].distance_km, expected)

    def test_container_larger_than_truck_rejected(self):
        with self.assertRaises(DataError):
            run_pipeline(Context(readings((70, 80, 90)), Config(truck_capacity_m3=1)), 5)

    def test_empty_selection_has_no_trips(self):
        c = run_pipeline(Context(readings((10, 11, 12)), Config()), 5)
        self.assertEqual(c.trips, [])
        self.assertEqual(c.metrics["collection_volume_m3"], 0)

    def test_haversine_known_equatorial_degree(self):
        self.assertAlmostEqual(distance_km((0, 0), (0, 1)), 111.195, places=3)
        self.assertEqual(distance_km((51, 71), (51, 71)), 0)

    def test_custom_agent_extension(self):
        class Extension:
            name = "custom"
            def run(self, context):
                context.metrics["custom_flag"] = True
        c = run_pipeline(Context(readings(), Config()),
                         agents=[AnalysisAgent(), PriorityAgent(), Extension()])
        self.assertEqual(c.trace, ["analysis", "priority", "custom"])
        self.assertTrue(c.metrics["custom_flag"])

    def test_pipeline_can_run_again_without_stale_metrics(self):
        c = Context(readings(), Config())
        run_pipeline(c, 5)
        run_pipeline(c, 2)
        self.assertNotIn("forecast_mae_pp", c.metrics)
        self.assertEqual(c.trips, [])

    def test_invalid_configuration(self):
        for config in ({"threshold_pct": 0}, {"horizon_days": -1},
                       {"truck_capacity_m3": 0}, {"depot_lat": 91},
                       {"threshold_pct": float("nan")}, {"depot_lon": float("inf")}):
            with self.subTest(config=config), self.assertRaises(DataError):
                Config(**config)

    def test_empty_pipeline_and_bad_count(self):
        with self.assertRaises(DataError):
            run_pipeline(Context([], Config()))
        with self.assertRaises(DataError):
            run_pipeline(Context(readings(), Config()), 3)


class IOTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / "input.csv"

    def tearDown(self):
        self.temp.cleanup()

    def write(self, rows):
        with self.path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(FIELDS)
            writer.writerows(rows)

    def rows(self):
        return [["A", "Есиль", 51.13, 71.43, 4, f"2026-10-0{i+1}", fill]
                for i, fill in enumerate((50, 60, 70))]

    def test_seed_is_reproducible(self):
        generate_demo(self.path)
        first = self.path.read_bytes()
        generate_demo(self.path)
        self.assertEqual(first, self.path.read_bytes())
        self.assertEqual(len(load_csv(self.path)), 168)

    def test_invalid_csv_values(self):
        for index, value in ((2, 91), (3, 181), (4, 0), (6, 101), (6, -1),
                             (6, "NaN"), (6, "inf"), (5, "bad-date"), (0, "")):
            rows = self.rows()
            rows[0][index] = value
            self.write(rows)
            with self.subTest(value=value), self.assertRaises(DataError):
                load_csv(self.path)

    def test_duplicate_rejected(self):
        rows = self.rows()
        self.write(rows + [rows[0]])
        with self.assertRaisesRegex(DataError, "duplicate"):
            load_csv(self.path)

    def test_metadata_change_rejected(self):
        rows = self.rows()
        rows[1][4] = 5
        self.write(rows)
        with self.assertRaisesRegex(DataError, "metadata"):
            load_csv(self.path)

    def test_fill_reset_rejected(self):
        rows = self.rows()
        rows[2][6] = 10
        self.write(rows)
        with self.assertRaisesRegex(DataError, "reset"):
            load_csv(self.path)

    def test_missing_data_and_bad_header(self):
        self.write([])
        with self.assertRaises(DataError):
            load_csv(self.path)
        self.write(self.rows()[:2])
        with self.assertRaisesRegex(DataError, "at least 3"):
            load_csv(self.path)
        self.path.write_text("wrong,header\n", encoding="utf-8")
        with self.assertRaisesRegex(DataError, "columns"):
            load_csv(self.path)

    def test_misaligned_last_dates_rejected(self):
        rows = self.rows()
        other = [["B", *r[1:]] for r in rows]
        other[-1][5] = "2026-10-04"
        self.write(rows + other)
        with self.assertRaisesRegex(DataError, "final observation"):
            load_csv(self.path)

    def test_unsorted_csv_is_sorted(self):
        self.write(list(reversed(self.rows())))
        self.assertEqual([r.fill_pct for r in load_csv(self.path)], [50, 60, 70])

    def test_demo_cli_outputs_and_two_agent_mode(self):
        out = self.root / "results"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["demo", "--output", str(out)]), 0)
        report = json.loads((out / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(len(report["agents"]), 5)
        self.assertEqual(report["metrics"]["holdout_n"], 24)
        self.assertTrue((out / "dashboard.html").exists())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["analyze", "--input", str(out / "synthetic_input.csv"),
                                   "--agents", "2", "--output", str(out)]), 0)
        report = json.loads((out / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["agents"], ["analysis", "priority"])

    def test_exports_repeat_byte_for_byte(self):
        generate_demo(self.path)
        c = run_pipeline(Context(load_csv(self.path), Config()))
        one, two = self.root / "one", self.root / "two"
        export_results(c, one, self.path)
        export_results(c, two, self.path)
        for name in ("report.json", "priorities.csv", "dashboard.html"):
            self.assertEqual((one / name).read_bytes(), (two / name).read_bytes())

    def test_html_escapes_labels_and_csv_formulas(self):
        rows = self.rows()
        for row in rows:
            row[0], row[1] = "=1+1", "<script>alert(1)</script>"
        self.write(rows)
        out = self.root / "results"
        export_results(run_pipeline(Context(load_csv(self.path), Config())), out, self.path)
        html = (out / "dashboard.html").read_text(encoding="utf-8")
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)
        with (out / "priorities.csv").open(encoding="utf-8-sig") as stream:
            self.assertEqual(next(csv.DictReader(stream))["bin_id"], "'=1+1")

    def test_cli_reports_errors_without_traceback(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(main(["analyze", "--input", str(self.path)]), 2)
            self.assertEqual(main(["demo", "--horizon", "nan"]), 2)
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_invalid_generator_dimensions(self):
        for bins, days in ((0, 7), (24, 2), (24, 31)):
            with self.assertRaises(DataError):
                generate_demo(self.path, bins=bins, days=days)


if __name__ == "__main__":
    unittest.main()

