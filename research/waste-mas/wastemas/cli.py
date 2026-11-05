"""Command line interface: run, demo, scenarios, generate."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .core import Config, DataError, LLMSettings, load_dotenv
from .datagen import generate
from .orchestrator import Orchestrator

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "astana_bins.csv"
CALENDAR = ROOT / "data" / "kz_calendar_2026.json"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="waste-mas", description="Многоагентная система планирования вывоза ТБО")
    sub = p.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Запустить агентов на CSV")
    run.add_argument("--input", type=Path, default=DATA)
    demo = sub.add_parser("demo", help="Типовой сценарий на демонстрационных данных")
    for c in (run, demo):
        c.add_argument("--calendar", type=Path, default=CALENDAR)
        c.add_argument("--output", type=Path, default=Path("results"))
        c.add_argument("--threshold", type=float, default=80.0)
        c.add_argument("--horizon", type=int, default=1)
        c.add_argument("--truck-capacity", type=float, default=8.0)
        c.add_argument("--trucks", type=int, default=2)
        c.add_argument("--trips-per-truck", type=int, default=2)
        c.add_argument("--max-steps", type=int, default=20)
        c.add_argument("--timeout", type=float, default=60.0)
        c.add_argument("--max-replans", type=int, default=3)
        c.add_argument("--retries", type=int, default=2)
        c.add_argument("--llm", action="store_true", help="Сводка через LLM (LLM_BASE_URL, LLM_MODEL, LLM_API_KEY)")
    sc = sub.add_parser("scenarios", help="Прогнать тестовые сценарии с ожидаемыми результатами")
    sc.add_argument("--file", type=Path, default=ROOT / "scenarios" / "scenarios.json")
    sc.add_argument("--output", type=Path, default=Path("results") / "scenarios")
    gen = sub.add_parser("generate", help="Сгенерировать синтетический датасет")
    gen.add_argument("--output", type=Path, default=DATA)
    gen.add_argument("--seed", type=int, default=42)
    gen.add_argument("--bins", type=int, default=60)
    gen.add_argument("--days", type=int, default=21)
    return p


def config_from_args(a) -> Config:
    return Config(threshold_pct=a.threshold, horizon_days=a.horizon, truck_capacity_m3=a.truck_capacity,
                  trucks=a.trucks, trips_per_truck=a.trips_per_truck, max_steps=a.max_steps,
                  timeout_s=a.timeout, max_replans=a.max_replans, tool_retries=a.retries,
                  use_llm=a.llm, llm=LLMSettings.from_env())


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # Windows consoles with cp866/cp1251
        except (AttributeError, ValueError):
            pass
    load_dotenv(ROOT / ".env")
    args = build_parser().parse_args(argv)
    try:
        if args.command == "generate":
            info = generate(args.output, CALENDAR, args.seed, args.bins, args.days)
            print(f"OK: {info['rows']} строк, {info['bins']} контейнеров → {info['path']}")
            return 0
        if args.command == "scenarios":
            from .scenarios import run_scenarios
            return run_scenarios(args.file, args.output)
        cfg = config_from_args(args)
        if args.llm and not cfg.llm.configured:
            print("Внимание: LLM не настроена (LLM_BASE_URL/LLM_MODEL) — сводка будет по шаблону", file=sys.stderr)
        source = DATA if args.command == "demo" else args.input
        result = Orchestrator(cfg, args.output).run(source, args.calendar)
    except DataError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2
    print(f"[{result.status}] {result.message}")
    print(f"Шагов: {result.steps}, перепланирований: {result.replans}, "
          f"вызовов инструментов/LLM: {result.load['total_calls']}, "
          f"макс. доля агента: {result.load['max_share']:.1%}")
    for name, a in result.load["agents"].items():
        print(f"  {name:<10} {a['total_calls']:>3} вызовов  {a['share']:>6.1%}")
    print(f"Трасса: {' → '.join(result.trace)}")
    print(f"Результаты: {Path(result.output).resolve()}  Лог: {result.log_path}")
    return result.exit_code
