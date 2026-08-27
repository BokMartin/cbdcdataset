#!/usr/bin/env python3
"""Write or verify SHA-256 checksums for the deployed website tree."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEBSITE = ROOT / "website"
CHECKSUMS = WEBSITE / "data/checksums.sha256"
TEXT_SUFFIXES = {".css", ".html", ".js", ".json", ".php", ".txt", ".xml"}


def digest(path: Path) -> str:
    content = path.read_bytes()
    if path.suffix.lower() in TEXT_SUFFIXES:
        content = content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(content).hexdigest()


def files() -> list[Path]:
    return sorted(
        path for path in WEBSITE.rglob("*")
        if path.is_file() and path != CHECKSUMS
    )


def rendered() -> str:
    return "".join(
        f"{digest(path)}  {path.relative_to(WEBSITE).as_posix()}\n" for path in files()
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    arguments = parser.parse_args()
    expected = rendered()
    if arguments.write:
        CHECKSUMS.write_text(expected, encoding="utf-8", newline="\n")
        print(f"wrote {len(files())} website checksums")
    elif CHECKSUMS.read_text(encoding="utf-8") != expected:
        raise SystemExit("website/data/checksums.sha256 is stale")
    else:
        print(f"website checksums: {len(files())} files verified")


if __name__ == "__main__":
    main()
