#!/usr/bin/env python3
"""Reproduce the released calibration and v10.2e ensemble results."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable

STEPS = [
    (
        "calibration",
        [
            PYTHON,
            str(ROOT / "scripts/evaluate_extraction_v10_1.py"),
            "--package",
            str(ROOT / "data/calibration"),
            "--model-a",
            str(ROOT / "data/calibration/openai_extractions.jsonl"),
            "--model-b",
            str(ROOT / "data/calibration/claude_extractions.jsonl"),
            "--model-a-run-status",
            "protocol_exact",
            "--model-b-run-status",
            "protocol_exact",
            "--reference",
            str(ROOT / "data/calibration/reference.csv"),
            "--out-dir",
            str(ROOT / "results/calibration"),
            "--threshold",
            "0.80",
        ],
    ),
    (
        "ensemble analysis and figures",
        [PYTHON, str(ROOT / "scripts/ensemble_analysis_v10_2e.py")],
    ),
    (
        "ensemble verification",
        [PYTHON, str(ROOT / "scripts/verify_ensemble_analysis_v10_2e.py")],
    ),
    (
        "repository verification",
        [PYTHON, str(ROOT / "scripts/verify.py")],
    ),
]


def main() -> None:
    for label, command in STEPS:
        print(f"\n[{label}]", flush=True)
        subprocess.run(command, check=True, cwd=ROOT)
    print("\nReproduction complete.")


if __name__ == "__main__":
    main()
