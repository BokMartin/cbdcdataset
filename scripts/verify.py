#!/usr/bin/env python3
"""Verify the compact paper-reproduction bundle and its frozen claims."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from PIL import Image

from update_checksums import CHECKSUMS, ROOT, digest, discover_files


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def verify_checksums() -> None:
    recorded: dict[str, str] = {}
    for line in CHECKSUMS.read_text(encoding="utf-8").splitlines():
        expected, name = line.split(maxsplit=1)
        name = name.strip()
        require(name not in recorded, f"duplicate checksum entry: {name}")
        recorded[name] = expected
    require(sorted(recorded) == discover_files(), "checksum inventory differs from bundle")
    for name, expected in recorded.items():
        require(digest(ROOT / name) == expected, f"checksum mismatch: {name}")


def verify_minimal_boundary() -> None:
    banned = {".docx", ".pdf", ".zip"}
    offenders = [
        path.relative_to(ROOT).as_posix()
        for path in ROOT.rglob("*")
        if path.is_file() and ".git" not in path.parts and path.suffix.lower() in banned
    ]
    require(not offenders, f"non-minimal binary artifacts present: {offenders}")
    oversized = [
        path.relative_to(ROOT).as_posix()
        for path in ROOT.rglob("*")
        if path.is_file() and ".git" not in path.parts and path.stat().st_size > 10 * 1024 * 1024
    ]
    require(not oversized, f"unexpected files over 10 MiB: {oversized}")


def verify_calibration() -> None:
    reference = pd.read_csv(ROOT / "data/calibration/reference.csv", keep_default_na=False)
    result = json.loads((ROOT / "results/calibration/calibration_results.json").read_text(encoding="utf-8"))
    union = result["models"]["verified_union"]
    probability = union["paragraph_metrics"]["probability"]
    require(len(reference) == 351 and reference["gold_id"].nunique() == 78, "calibration reference shape")
    require(result["comparison_status"] == "complete", "calibration comparison status")
    require(result["reserve_status"] == "sealed", "calibration reserve boundary")
    require(
        (probability["tp"], probability["fp"], probability["fn"], probability["tn"])
        == (49, 1, 15, 185),
        "calibration probability confusion matrix",
    )
    require(probability["precision"] == 0.98, "calibration precision")
    require(probability["recall"] == 0.765625, "calibration recall")
    require(union["span_fidelity"]["fidelity_excluding_pending_render"] == 1.0, "span fidelity")
    require(
        union["gates"] == {
            "E1_recall_point_and_ci": "fail",
            "E2_stress_long_recall": "fail",
            "E3_probability_precision_and_all_positive_workload": "pass",
            "S1_span_fidelity": "pass",
            "C1_exact_classification_recall": "fail",
        },
        "frozen gates",
    )


def verify_human_boundary() -> None:
    freeze = json.loads((ROOT / "validation/human_audit/SAMPLED_VALIDATION_FREEZE_MANIFEST.json").read_text(encoding="utf-8"))
    require(freeze["status"] == "frozen before human coding", "human-audit freeze status")
    require((freeze["population_candidates"], freeze["sample_candidates"]) == (6949, 365), "human-audit sample")
    require((freeze["dual_empty_population"], freeze["dual_empty_sample"]) == (359, 36), "dual-empty sample")
    for reviewer in ("MARTIN", "DOMINIK"):
        path = ROOT / f"validation/human_audit/VALIDATION_SAMPLE_v10_2e_{reviewer}.xlsx"
        require(path.is_file() and path.stat().st_size > 500_000, f"human workbook: {reviewer}")


def verify_figures() -> None:
    for name in ("v10_2e_ensemble_composition.png", "v10_2e_model_sensitivity.png"):
        with Image.open(ROOT / "figures" / name) as image:
            require(image.mode in {"RGB", "RGBA"}, f"figure mode: {name}")
            require(image.width >= 1200 and image.height >= 800, f"figure dimensions: {name}")


def main() -> None:
    verify_checksums()
    verify_minimal_boundary()
    verify_calibration()
    verify_human_boundary()
    verify_figures()
    print("repository: minimal bundle, hashes, calibration and human boundary verified")


if __name__ == "__main__":
    main()
