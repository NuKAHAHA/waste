"""Run the unittest suite and write a JUnit XML report for Jenkins (stdlib only).

Usage: python tools/junit_runner.py [--start tests] [--output reports/junit.xml]
Exit code is 0 when every test passes and 1 otherwise, so CI fails on a broken test.
"""
import argparse
import sys
import time
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


class RecordingResult(unittest.TextTestResult):
    """TextTestResult that also remembers duration and outcome of every test."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = []
        self._started = time.perf_counter()

    def startTest(self, test):
        self._started = time.perf_counter()
        super().startTest(test)

    def _record(self, test, kind=None, detail=""):
        self.records.append((test.id(), time.perf_counter() - self._started, kind, detail))

    def addSuccess(self, test):
        super().addSuccess(test)
        self._record(test)

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._record(test, "failure", self.failures[-1][1])

    def addError(self, test, err):
        super().addError(test, err)
        self._record(test, "error", self.errors[-1][1])

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._record(test, "skipped", reason)

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self._record(test)

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self._record(test, "failure", "Unexpected success")


def to_junit(records, elapsed: float) -> ET.ElementTree:
    count = lambda kind: sum(1 for r in records if r[2] == kind)  # noqa: E731
    suite = ET.Element("testsuite", name="smart-waste-astana", tests=str(len(records)),
                       failures=str(count("failure")), errors=str(count("error")),
                       skipped=str(count("skipped")), time=f"{elapsed:.3f}")
    for test_id, duration, kind, detail in records:
        classname, _, name = test_id.rpartition(".")
        case = ET.SubElement(suite, "testcase", classname=classname or "tests",
                             name=name, time=f"{duration:.3f}")
        if kind:
            tag = ET.SubElement(case, kind, message=detail.strip().splitlines()[-1][:200] if detail else kind)
            tag.text = detail
    return ET.ElementTree(suite)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--start", default="tests", help="directory to discover tests in")
    parser.add_argument("--output", type=Path, default=Path("reports/junit.xml"))
    args = parser.parse_args(argv)

    sys.path.insert(0, str(ROOT))
    suite = unittest.defaultTestLoader.discover(args.start, top_level_dir=str(ROOT))
    runner = unittest.TextTestRunner(verbosity=2, resultclass=RecordingResult)
    started = time.perf_counter()
    result = runner.run(suite)
    elapsed = time.perf_counter() - started

    args.output.parent.mkdir(parents=True, exist_ok=True)
    tree = to_junit(result.records, elapsed)
    ET.indent(tree)
    tree.write(args.output, encoding="utf-8", xml_declaration=True)
    print(f"JUnit report: {args.output} ({len(result.records)} tests)")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
