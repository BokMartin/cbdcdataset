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
    result = json.loads((ROOT / "results/human_validation/human_validation_results.json").read_text(encoding="utf-8"))
    candidates = pd.read_csv(ROOT / "validation/human_audit/reviewed_candidates.csv")
    queue = pd.read_csv(ROOT / "validation/human_audit/adjudication_queue.csv")
    dual = pd.read_csv(ROOT / "validation/human_audit/dual_empty_joint_audit.csv")
    supplements = pd.read_csv(ROOT / "validation/human_audit/dual_empty_supplements.csv")
    require(freeze["status"] == "frozen before human coding", "human-audit freeze status")
    require((freeze["population_candidates"], freeze["sample_candidates"]) == (6949, 365), "human-audit sample")
    require((freeze["dual_empty_population"], freeze["dual_empty_sample"]) == (359, 36), "dual-empty sample")
    for reviewer in ("MARTIN", "DOMINIK"):
        path = ROOT / f"validation/human_audit/VALIDATION_SAMPLE_v10_2e_{reviewer}.xlsx"
        require(path.is_file() and path.stat().st_size > 500_000, f"human workbook: {reviewer}")
    combined = ROOT / "validation/human_audit/VALIDATION_v10_2e_HUMAN_AUDIT_PREADJUDICATION.xlsx"
    require(combined.is_file() and combined.stat().st_size > 200_000, "combined human-audit workbook")
    require((len(candidates), candidates["candidate_id"].nunique()) == (365, 365), "reviewed candidate rows")
    require(len(queue) == 319, "adjudication queue rows")
    require((len(dual), len(supplements)) == (36, 2), "dual-empty release rows")
    require(candidates["confidence_martin_assumed"].eq("high").all(), "Martin confidence assumption")
    require(candidates["confidence_dominik_assumed"].eq("high").all(), "Dominik confidence assumption")
    require(queue["confidence_martin_assumed"].eq("high").all(), "queue Martin confidence assumption")
    require(queue["confidence_dominik_assumed"].eq("high").all(), "queue Dominik confidence assumption")
    require(dual["confidence"].eq("high").all(), "dual-empty confidence assumption")
    require(supplements["confidence"].eq("high").all(), "supplement confidence assumption")
    require(result["blind_status"]["independence_confirmed_by_authors"], "blind author confirmation")
    require(result["sample"]["analyzable_candidates"] == 364, "analyzable human sample")
    require((result["sample"]["decision_agreements"], result["sample"]["decision_disagreements"]) == (228, 136), "human inclusion agreement")
    require(abs(result["candidate_validity"]["martin"]["stratified"]["estimate"] - 0.7855858699550238) < 1e-12, "Martin validity")
    require(abs(result["candidate_validity"]["dominik"]["stratified"]["estimate"] - 0.7606658603384752) < 1e-12, "Dominik validity")
    require(abs(result["intercoder_reliability"]["inclusion_decision"]["gwet_ac1_nominal"] - 0.4260272701975698) < 1e-12, "human Gwet AC1")
    require((result["dual_empty"]["analyzable_units"], result["dual_empty"]["missed_units"]) == (31, 1), "dual-empty missed-unit yield")


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
    print("repository: minimal bundle, hashes, calibration, ensemble and blind human audit verified")


if __name__ == "__main__":
    main()
