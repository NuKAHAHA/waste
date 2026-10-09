"""Command line interface, safe errors and reproducible execution."""
import argparse
import sys
from pathlib import Path

from .agents import run_pipeline
from .data import generate_demo, load_csv
from .export import export_results
from .models import Config, Context, DataError


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description="Smart Waste Astana: offline research module")
    sub = cli.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="Generate synthetic data and run all agents")
    demo.add_argument("--seed", type=int, default=42)
    demo.add_argument("--bins", type=int, default=24)
    demo.add_argument("--days", type=int, default=7)
    analyze = sub.add_parser("analyze", help="Analyze an existing CSV")
    analyze.add_argument("--input", type=Path, required=True)
    for command in (demo, analyze):
        command.add_argument("--output", type=Path, default=Path("results"))
        command.add_argument("--agents", type=int, choices=(2, 5), default=5)
        command.add_argument("--threshold", type=float, default=80)
        command.add_argument("--horizon", type=float, default=1)
        command.add_argument("--truck-capacity", type=float, default=12)
        command.add_argument("--depot-lat", type=float, default=51.128)
        command.add_argument("--depot-lon", type=float, default=71.430)
    return cli


def main(argv: list[str] | None = None) -> int:
    """Return 0 on success, 2 on invalid input; don't expose stack traces."""
    args = parser().parse_args(argv)
    try:
        config = Config(args.threshold, args.horizon, args.truck_capacity,
                        args.depot_lat, args.depot_lon)
        source = args.output / "synthetic_input.csv" if args.command == "demo" else args.input
        if args.command == "demo":
            generate_demo(source, args.seed, args.bins, args.days)
        else:
            # Avoid accidentally overwriting an input named like an output.
            if any(source.resolve() == (args.output / name).resolve()
                   for name in ("report.json", "priorities.csv", "dashboard.html")):
                raise DataError("Input path conflicts with an output filename")
        context = run_pipeline(Context(load_csv(source), config), args.agents)
        export_results(context, args.output, source)
        print(f"OK: {len(context.states)} bins, {context.metrics['bins_selected']} selected, "
              f"{len(context.trips)} trips. Results: {args.output.resolve()}")
        return 0
    except (DataError, OSError, UnicodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

