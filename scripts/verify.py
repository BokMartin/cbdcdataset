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

    require(len(candidates) == 6_139, "candidate count")
    require((candidates["v5_verdict"] == "keep").sum() == 5_624, "kept count")
    require(candidates["doc_id"].nunique() == 93, "yielding document count")
    require(candidates["seg_id"].is_unique, "seg_id uniqueness")
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
    require(stages["stage_final"].value_counts().to_dict().get("active_research") == 13, "active stage count")
    require(stages["stage_final"].value_counts().to_dict().get("paused_research") == 23, "paused stage count")
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
