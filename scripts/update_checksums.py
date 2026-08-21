import argparse
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECKSUMS = ROOT / "checksums.sha256"
EXTRA = [
    "scripts/evaluate_extraction_v10_1.py",
    "scripts/extraction_v10_1.py",
    "scripts/finalize_provider_output.py",
    "scripts/prepare_scope_readjudication.py",
    "scripts/update_checksums.py",
    "validation/calibration_v10/calibration_reference_v10_1.csv",
    "validation/calibration_v10/calibration_reference_v10_1.json",
    "validation/calibration_v10/source/CALIBRATION_AUDIT_v10_FINALIZED.xlsx",
    "validation/extraction_v10_1/PROMPT_CORE.md",
    "validation/extraction_v10_1/PROTOCOL.md",
    "validation/extraction_v10_1/TASK_CODEX.md",
    "validation/extraction_v10_1/TASK_CLAUDE.md",
    "validation/extraction_v10_1/output_schema.json",
    "validation/extraction_v10_1/pricing.json",
    "validation/extraction_v10_1/run_config.json",
]
EXTRA_DIRS = [
    "validation/extraction_v10_1/runs",
]


def digest(path):
    content = path.read_bytes()
    if path.suffix.lower() in {".csv", ".json", ".sha256"}:
        content = content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(content).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    names = [line.split(maxsplit=1)[1].strip() for line in CHECKSUMS.read_text(encoding="utf-8").splitlines()]
    names += [name for name in EXTRA if name not in names]
    for directory in EXTRA_DIRS:
        names += [
            path.relative_to(ROOT).as_posix()
            for path in sorted((ROOT / directory).rglob("*"))
            if path.is_file() and path.relative_to(ROOT).as_posix() not in names
        ]
    missing = [name for name in names if not (ROOT / name).is_file()]
    if missing:
        raise FileNotFoundError(", ".join(missing))
    text = "".join(f"{digest(ROOT / name)}  {name}\n" for name in names)
    if args.write:
        CHECKSUMS.write_text(text, encoding="utf-8", newline="\n")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
