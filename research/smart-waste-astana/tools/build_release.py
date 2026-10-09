"""Build a deterministic standalone ZIP from an allowlist; no third-party tools."""
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
NAME = "smart-waste-astana-1.0.0"
FILES = ("README.md", "LICENSE", "CONTRIBUTING.md", "main.py", "run_demo.bat",
         "pyproject.toml", "requirements.txt", ".gitignore")
DIRECTORIES = ("smart_waste", "tests", "data", "docs", "tools")


def build(destination: Path | None = None) -> Path:
    """Include only deliverable source/data/docs, never git credentials or caches."""
    destination = destination or ROOT / "dist" / f"{NAME}.zip"
    destination.parent.mkdir(parents=True, exist_ok=True)
    paths = [ROOT / f for f in FILES]
    for folder in DIRECTORIES:
        paths += [p for p in (ROOT / folder).rglob("*") if p.is_file()
                  and "__pycache__" not in p.parts and p.suffix != ".pyc"]
    with ZipFile(destination, "w", compression=ZIP_DEFLATED) as archive:
        for path in sorted(paths):
            entry = ZipInfo(f"{NAME}/{path.relative_to(ROOT).as_posix()}", date_time=(2026, 10, 9, 0, 0, 0))
            entry.compress_type = ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, path.read_bytes())
    return destination


if __name__ == "__main__":
    print(build())

