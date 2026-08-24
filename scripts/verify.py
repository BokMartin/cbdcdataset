import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    for line in (ROOT / "checksums.sha256").read_text(encoding="utf-8").splitlines():
        expected, name = line.split(maxsplit=1)
        path = ROOT / name.strip()
        content = path.read_bytes()
        if path.suffix.lower() in {".csv", ".json", ".sha256"}:
            content = content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        require(hashlib.sha256(content).hexdigest() == expected, f"checksum: {name}")
    schema = json.loads((ROOT / "validation/provenance_schema.json").read_text(encoding="utf-8"))
    require(schema.get("type") == "object" and len(schema.get("required", [])) >= 40, "provenance schema")
    candidates = pd.read_csv(ROOT / "data/candidates.csv", keep_default_na=False)
    codebook = pd.read_csv(ROOT / "data/codebook.csv", keep_default_na=False)
    documents = pd.read_csv(ROOT / "data/documents.csv", keep_default_na=False)
    stages = pd.read_csv(ROOT / "data/stages.csv", keep_default_na=False)
    scores = pd.read_csv(ROOT / "results/scores.csv", keep_default_na=False)
    components = pd.read_csv(ROOT / "results/privacy_components.csv", keep_default_na=False)
    manifest = pd.read_csv(ROOT / "validation/page_manifest.csv", keep_default_na=False)
    split = pd.read_csv(ROOT / "validation/split.csv", keep_default_na=False)
    sample = pd.read_csv(ROOT / "validation/sample.csv", keep_default_na=False)
    model_b_input = pd.read_csv(
        ROOT / "validation/model_b_pilot/input_manifest.csv", keep_default_na=False
    )
    model_b_audit = pd.read_csv(
        ROOT / "validation/model_b_pilot/audit_manifest.csv", keep_default_na=False
    )
    open_items = pd.read_csv(ROOT / "validation/open_items.csv", keep_default_na=False)
    gates = pd.read_csv(ROOT / "validation/gates.csv", keep_default_na=False)
    gold_audit = json.loads((ROOT / "results/gold_candidate_audit.json").read_text(encoding="utf-8"))
    model_b = json.loads((ROOT / "results/model_b_pilot.json").read_text(encoding="utf-8"))
    model_b_freeze = json.loads(
        (ROOT / "validation/model_b_pilot/run_freeze.json").read_text(encoding="utf-8")
    )
    calibration = pd.read_csv(
        ROOT / "validation/calibration_v10/error_cases.csv", keep_default_na=False
    )
    calibration_summary = json.loads(
        (ROOT / "validation/calibration_v10/audit_summary.json").read_text(encoding="utf-8")
    )
    calibration_taxonomy = pd.read_csv(
        ROOT / "validation/calibration_v10/taxonomy.csv", keep_default_na=False
    )
    calibration_reference = pd.read_csv(
        ROOT / "validation/calibration_v10/calibration_reference_v10_1.csv",
        keep_default_na=False,
    )
    calibration_reference_summary = json.loads(
        (ROOT / "validation/calibration_v10/calibration_reference_v10_1.json")
        .read_text(encoding="utf-8")
    )
    extraction_config = json.loads(
        (ROOT / "validation/extraction_v10_1/run_config.json").read_text(encoding="utf-8")
    )
    extraction_schema = json.loads(
        (ROOT / "validation/extraction_v10_1/output_schema.json").read_text(encoding="utf-8")
    )
    calibration_freeze = pd.read_csv(
        ROOT / "validation/calibration_v10/freeze_checklist.csv", keep_default_na=False
    )
    calibration_archive = json.loads(
        (ROOT / "validation/extraction_v10_1/runs/2026-08-21_calibration/ARCHIVE_MANIFEST.json")
        .read_text(encoding="utf-8")
    )
    calibration_evaluation = json.loads(
        (ROOT / "validation/extraction_v10_1/runs/2026-08-21_calibration/evaluation/calibration_results.json")
        .read_text(encoding="utf-8")
    )

    require(len(candidates) == 6_139, "candidate count")
    require((candidates["v5_verdict"] == "keep").sum() == 5_624, "kept count")
    require(candidates["doc_id"].nunique() == 93, "yielding document count")
    require(candidates["seg_id"].is_unique, "seg_id uniqueness")
    require(gold_audit["schema"] == "gold_candidate_audit_v1", "gold audit schema")
    require(gold_audit["matching"]["threshold"] == 0.8, "gold audit threshold")
    primary = gold_audit["paragraph_metrics"]["probability_kept_candidates"]
    require(
        {key: primary[key] for key in ["n", "tp", "fp", "fn", "tn"]}
        == {"n": 285, "tp": 34, "fp": 8, "fn": 58, "tn": 185},
        "gold audit primary counts",
    )
    blocking_statuses = {
        "open",
        "required_pending",
        "deferred_open",
        "author_confirmation_pending",
        "ready_for_blind_runs",
    }
    require(
        set(open_items.loc[open_items["status"].isin(blocking_statuses), "item_id"])
        == {"HUMAN-002", "CALIB-002", "CALIB-004"},
        "open validation items",
    )
    require(
        len(calibration) == 66
        and calibration["case_id"].is_unique
        and calibration["case_type"].value_counts().to_dict()
        == {"FN": 41, "FP": 20, "SPAN": 5},
        "calibration error package",
    )
    require(
        calibration_summary["schema"] == "calibration_error_audit_v1"
        and calibration_summary["status"] == "complete"
        and calibration_summary["rules"]["reserve_status"] == "sealed"
        and calibration_summary["counts"]["all"] == 66
        and calibration_summary["counts"]["pending"] == 0
        and calibration_summary["counts"]["adjudicated"] == 66
        and calibration["status"].eq("adjudicated").all(),
        "calibration audit status",
    )
    require(
        calibration_taxonomy["category_id"].is_unique
        and set(calibration_taxonomy["case_type"]) == {"FN", "FP", "SPAN"},
        "calibration taxonomy",
    )
    require(
        calibration_reference_summary["schema"] == "calibration_reference_v10_1"
        and calibration_reference_summary["reserve_status"] == "sealed"
        and calibration_reference_summary["counts"] == {
            "rows": 351,
            "pages": 78,
            "all_truth": {"negative": 240, "excluded": 15, "positive": 96},
            "probability_truth": {"negative": 209, "excluded": 5, "positive": 76},
            "scope_exclusions": 17,
            "false_negative_corrections": 1,
        }
        and len(calibration_reference) == 351,
        "corrected calibration reference",
    )
    schema_codes = set(
        extraction_schema["properties"]["units"]["items"]["properties"]
        ["statements"]["items"]["properties"]["code1"]["enum"]
    )
    require(
        extraction_config["status"] == "calibration_candidate_not_reserve_frozen"
        and extraction_config["development_pages"] == 78
        and extraction_config["reserve_pages"] == 40
        and extraction_config["reserve_status"] == "sealed"
        and extraction_config["input"]["semantic_prefilter"] is False
        and schema_codes == set(codebook["code"]),
        "v10.1 shared extraction protocol",
    )
    require(
        calibration_freeze.set_index("id").loc[["C01", "C02", "C05", "C07"], "status"]
        .eq("complete").all()
        and calibration_freeze.set_index("id").loc[["C04", "C06", "C09"], "status"]
        .eq("pending").all()
        and calibration_freeze.set_index("id").loc["C08", "status"] == "fail_blocks_reserve"
        and calibration_freeze.set_index("id").loc["C10", "status"] == "partial",
        "calibration freeze progression",
    )
    union = calibration_evaluation["models"]["verified_union"]
    require(
        calibration_archive["reserve_status"] == "sealed and not accessed"
        and calibration_evaluation["status"] == "development_calibration_not_confirmatory"
        and calibration_evaluation["reserve_status"] == "sealed"
        and calibration_archive["provider_runs"]["codex"]["authoritative_statement_count"] == 96
        and calibration_archive["provider_runs"]["claude"]["authoritative_statement_count"] == 127
        and union["paragraph_metrics"]["probability"]["tp"] == 45
        and union["paragraph_metrics"]["probability"]["fn"] == 31
        and union["paragraph_metrics"]["probability"]["recall"] < 0.90
        and union["paragraph_metrics"]["probability"]["precision"] < 0.80
        and union["classification"]["recall"] < 0.80,
        "v10.1 calibration archive and failed gates",
    )
    require(
        documents.loc[documents["doc_id"].eq("JP_BoJ_Pilot_JP"), "language"].eq("ja").all()
        and split.loc[split["doc_id"].eq("JP_BoJ_Pilot_JP"), "stratum"].eq("ja|retail_or_general").all()
        and sample.loc[sample["doc_id"].eq("JP_BoJ_Pilot_JP"), "language"].eq("ja").all()
        and model_b_audit.loc[model_b_audit["doc_id"].eq("JP_BoJ_Pilot_JP"), "language"].eq("zh").all(),
        "prospective Japanese metadata with archived v9 evidence preserved",
    )
    require(
        model_b["schema"] == "model_b_v9_pilot_v1"
        and model_b["extraction"] == {
            "sample_pages": 78,
            "model_calls": 70,
            "protocol_skips": 8,
            "statements": 202,
            "pages_with_statements": 35,
        },
        "Model B extraction counts",
    )
    require(
        model_b["paragraph_metrics"]["probability"]["recall"] < 0.90
        and model_b["paragraph_metrics"]["probability"]["precision"] < 0.80
        and model_b["span_fidelity"]["verified_rate"] < 0.95,
        "Model B failed gates",
    )
    require(
        gates.set_index("id").loc[["E1", "E2", "E3", "C1"], "status"].eq("fail").all()
        and gates.set_index("id").loc["S1", "status"] == "pass",
        "current v10.1 calibration gate status",
    )
    response_path = ROOT / "validation/model_b_pilot/responses.jsonl"
    require(
        hashlib.sha256(response_path.read_bytes()).hexdigest()
        == model_b_freeze["responses_sha256"],
        "Model B response freeze",
    )
    raw = b"".join(
        (ROOT / f"validation/model_b_pilot/raw/part{part}.jsonl").read_bytes()
        for part in (1, 2, 3)
    )
    require(raw == response_path.read_bytes(), "Model B raw concatenation")
    require(codebook["code"].nunique() == 35 and codebook["family"].nunique() == 16, "codebook shape")
    require(not codebook.astype(str).apply(lambda col: col.str.contains("&amp;", regex=False)).any().any(), "encoded HTML in codebook")
    require(len(scores) == 48 and scores["jur"].is_unique, "score entities")
    require((~scores["is_composite"].astype(str).str.lower().isin(["true", "1"])).sum() == 47, "empirical entities")
    require(int(scores["mixed_case"].astype(str).str.lower().isin(["true", "1"]).sum()) == 19, "mixed count")
    require(scores["dominant_centre"].value_counts().to_dict() == {
        "sovereignty_competition": 12, "state_control": 11, "payment_modernization": 9,
        "financial_inclusion": 9, "monetary_transmission": 7,
    }, "dominant centres")
    require(len(components) == len(scores) and components["jur"].is_unique, "privacy component entities")
    delta = pd.to_numeric(components["current_signed_density"]) - pd.to_numeric(components["net_privacy_posture"])
    require(np.isfinite(delta).all() and delta.abs().max() <= 1e-12, "privacy identity")
    require(pd.to_numeric(components["privacy_salience"]).between(0, 1).all(), "privacy salience range")
    require(pd.to_numeric(components["directional_valence"], errors="coerce").dropna().between(-1, 1).all(), "valence range")

    queued = documents[documents["extraction_status"] == "queued_series3"]
    outside = set(manifest["doc_id"]) - set(split["doc_id"])
    require(outside == set(queued["doc_id"]), "Series 3 boundary")
    outside_pages = manifest[manifest["doc_id"].isin(outside)]
    require(len(queued) == 13 and len(outside_pages) == 394, "Series 3 size")
    require(split["doc_id"].nunique() == 100 and split["doc_id"].is_unique, "split size")
    require((sample["stratum"] == "probability").sum() == 60, "probability sample")
    require((sample["stratum"] == "reserve_sealed").sum() == 40, "sealed reserve")
    require(not sample[["fname", "page"]].astype(str).agg("|".join, axis=1).duplicated().any(), "sample uniqueness")
    require(
        list(model_b_input.columns) == ["input_id", "status", "prompt_file", "prompt_sha256"],
        "Model B blind manifest fields",
    )
    require(
        len(model_b_input) == 78
        and model_b_input["status"].value_counts().to_dict()
        == {"ready": 70, "skipped_lt250": 8},
        "Model B pilot size",
    )
    require(
        len(model_b_audit) == 78
        and model_b_audit["doc_id"].nunique() == 42
        and model_b_audit["input_id"].tolist() == model_b_input["input_id"].tolist(),
        "Model B audit manifest",
    )
    stage_counts = stages["stage_final"].value_counts().to_dict()
    require(stage_counts.get("active_research") == 13, "active stage count")
    require(stage_counts.get("paused_research") == 22, "paused stage count")
    require(stage_counts.get("cancelled") == 1, "cancelled stage count")
    dcash = stages.loc[stages["jur"] == "ECCU"].squeeze()
    require(
        dcash["stage"] == dcash["stage_final"] == "cancelled"
        and dcash["doc_id"] == "ECCU_ECCB_MonetaryCouncil_112_2026"
        and "suspension of DCash 2.0 development" in dcash["evidence"],
        "DCash cancellation evidence",
    )
    sensitivity = json.loads((ROOT / "results/cash_gate_sensitivity.json").read_text(encoding="utf-8"))
    require(sensitivity["ungated"].get("cash_substitution") == 9, "cash-gate sensitivity")
    for path in [
        "results/audit.json", "results/robustness.json", "results/centre_correlations.csv",
        "results/centre_pca.csv", "figures/correlations.png", "figures/composition.png",
        "figures/centres.png", "figures/privacy_components.png", "paper/current.docx", "paper/current.pdf",
    ]:
        require((ROOT / path).is_file() and (ROOT / path).stat().st_size > 0, path)
    expected_figures = {
        "correlations.png": (1839, 1120),
        "composition.png": (1824, 2400),
        "centres.png": (2100, 2200),
        "privacy_components.png": (1967, 2976),
    }
    for name, size in expected_figures.items():
        with Image.open(ROOT / "figures" / name) as image:
            require(image.mode == "RGB" and image.size == size, f"figure format: {name}")
    print("verify: checks passed")


if __name__ == "__main__":
    main()
