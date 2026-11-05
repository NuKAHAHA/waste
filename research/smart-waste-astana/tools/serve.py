"""Run the agent pipeline once and serve the results over HTTP (staging / Kubernetes).

Usage:
  python tools/serve.py                      # synthetic demo, port 8080
  python tools/serve.py --input data/x.csv   # analyze a real CSV instead
Endpoints: / (dashboard), /report.json, /priorities.csv, /healthz
"""
import argparse
import functools
import http.server
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from smart_waste.cli import main as run_cli  # noqa: E402


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/healthz":
            body = b"ok\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run agents, then serve results")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--output", type=Path, default=Path("/tmp/results"))
    parser.add_argument("--input", type=Path, help="CSV to analyze; default is the synthetic demo")
    args = parser.parse_args(argv)

    command = ["analyze", "--input", str(args.input)] if args.input else ["demo"]
    code = run_cli(command + ["--output", str(args.output)])
    if code:
        return code
    shutil.copyfile(args.output / "dashboard.html", args.output / "index.html")

    handler = functools.partial(Handler, directory=str(args.output))
    with http.server.ThreadingHTTPServer(("0.0.0.0", args.port), handler) as server:
        print(f"Serving {args.output} on port {args.port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
