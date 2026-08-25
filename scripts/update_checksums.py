import argparse
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECKSUMS = ROOT / "checksums.sha256"
EXTRA = [
    "scripts/evaluate_extraction_v10_1.py",
    "scripts/extraction_v10_1.py",
    "scripts/extraction_v10_2.py",
    "scripts/finalize_provider_output.py",
    "scripts/freeze_reference_v10_2.py",
    "scripts/openai_batch_v10_2.py",
    "scripts/prepare_scope_readjudication.py",
    "scripts/update_checksums.py",
    "scripts/verify_extraction_v10_2.py",
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
    "validation/extraction_v10_2/PROMPT_CORE.md",
    "validation/extraction_v10_2/PROTOCOL.md",
    "validation/extraction_v10_2/CLAUDE_AUDIT_HANDOVER_v10_2.md",
    "validation/extraction_v10_2/REFERENCE_REVIEW.md",
    "validation/extraction_v10_2/TASK_CLAUDE.md",
    "validation/extraction_v10_2/TASK_CODEX.md",
    "validation/extraction_v10_2/authority_overrides.json",
    "validation/extraction_v10_2/BATCH_INPUT_FREEZE_v10_2.json",
    "validation/extraction_v10_2/codebook_overrides.json",
    "validation/extraction_v10_2/output_schema.json",
    "validation/extraction_v10_2/matching_erratum_v10_2.json",
    "validation/extraction_v10_2/reference/SCOPE_READJUDICATION_v10_2_FROZEN.xlsx",
    "validation/extraction_v10_2/reference/author_decisions_v10_2.json",
    "validation/extraction_v10_2/reference/calibration_reference_v10_2.csv",
    "validation/extraction_v10_2/reference/calibration_reference_v10_2.json",
    "validation/extraction_v10_2/reference/reference_changes_v10_2.csv",
    "validation/extraction_v10_2/run_config.json",
]
EXTRA_DIRS = [
    "validation/extraction_v10_1/runs",
    "validation/extraction_v10_2/audits",
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
            if path.is_file()
            and not path.name.startswith("~$")
            and path.relative_to(ROOT).as_posix() not in names
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
