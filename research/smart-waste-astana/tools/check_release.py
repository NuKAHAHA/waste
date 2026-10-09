"""Verify a built ZIP can run and test independently from the source tree."""
import subprocess
import sys
import tempfile
from pathlib import Path
from zipfile import ZipFile

from build_release import NAME, ROOT


def check():
    with tempfile.TemporaryDirectory() as folder:
        with ZipFile(ROOT / "dist" / f"{NAME}.zip") as archive:
            archive.extractall(folder)
        work = Path(folder) / NAME
        subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=work, check=True)
        subprocess.run([sys.executable, "main.py", "demo"], cwd=work, check=True)
        assert (work / "results" / "dashboard.html").is_file()
    print("Standalone ZIP verified")


if __name__ == "__main__":
    check()

