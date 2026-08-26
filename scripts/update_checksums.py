#!/usr/bin/env python3
"""Write or verify hashes for the complete reproducibility bundle."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECKSUMS = ROOT / "checksums.sha256"
ROOT_FILES = ("run.py", "requirements.txt")
INCLUDED_DIRS = ("data", "validation", "results", "figures", "scripts")
TEXT_SUFFIXES = {
    ".csv", ".css", ".html", ".js", ".json", ".jsonl", ".md", ".py",
    ".sha256", ".txt", ".yaml", ".yml",
}


def digest(path: Path) -> str:
    content = path.read_bytes()
    if path.suffix.lower() in TEXT_SUFFIXES:
        content = content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(content).hexdigest()


def discover_files() -> list[str]:
    paths = [ROOT / name for name in ROOT_FILES]
    for directory in INCLUDED_DIRS:
        paths.extend((ROOT / directory).rglob("*"))
    return sorted(
        path.relative_to(ROOT).as_posix()
        for path in paths
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix.lower() != ".pyc"
        and not path.name.startswith("~$")
    )


def rendered_checksums() -> str:
    return "".join(f"{digest(ROOT / name)}  {name}\n" for name in discover_files())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="replace checksums.sha256")
    args = parser.parse_args()
    rendered = rendered_checksums()
    if args.write:
        CHECKSUMS.write_text(rendered, encoding="utf-8", newline="\n")
        print(f"wrote {len(discover_files())} checksums")
        return
    current = CHECKSUMS.read_text(encoding="utf-8")
    if current != rendered:
        raise SystemExit("checksums.sha256 is stale; run with --write after reviewing changes")
    print(f"checksums: {len(discover_files())} files verified")


if __name__ == "__main__":
    main()
