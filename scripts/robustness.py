import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CONDITIONS = ["vdem", "cbi", "shadow", "basel"]
DIR_SIGN = {"increases": 1.0, "decreases": -1.0, "conditional": -0.25, "neutral": 0.0}
RELATION_WEIGHT = {"from_state": 1.0, "from_intermediary": 0.5}


def posture(group):
    privacy = group[group["is_priv"]]
    if privacy.empty:
        return 0.0
    total = (
        privacy["dw"] * privacy["privacy_direction"].map(DIR_SIGN).fillna(0)
        * privacy["privacy_relation"].map(RELATION_WEIGHT).fillna(0.5) * privacy["strength_num"]
    ).sum()
    return total / len(group)


def main():
    candidates = pd.read_csv(ROOT / "data/candidates.csv", keep_default_na=False)
    documents = pd.read_csv(ROOT / "data/documents.csv", keep_default_na=False)
    kept = candidates[candidates["v5_verdict"] == "keep"].copy()
    kept["jur"] = kept["doc_id"].str.split("_").str[0]
    kept["dw"] = np.where(kept["odr"] == "decision", 1, np.where(kept["odr"] == "proposal", 0.5, 0.25))
    kept["strength_num"] = pd.to_numeric(kept["strength"], errors="coerce").clip(1, 3).fillna(1)
    kept["is_priv"] = kept["privacy_direction"].isin(["increases", "decreases", "conditional"])

    scores = pd.read_csv(ROOT / "results/scores.csv", keep_default_na=False)
    macro = pd.read_excel(ROOT / "data/macro.xlsx", sheet_name="1_Master", header=1)
    macro = macro.dropna(subset=["ISO-3"]).rename(columns={
        "ISO-3": "iso3", "V-Dem LibDem": "vdem", "Romelli CBIE": "cbi",
        "Informal DGE %GDP": "shadow", "Basel score": "basel",
    })
    covariates = scores.merge(macro[["iso3", *CONDITIONS]], on="iso3", how="left").set_index("jur")[CONDITIONS]
    covariates = covariates.apply(pd.to_numeric, errors="coerce")

    def correlations(values):
        result = {}
        for condition in CONDITIONS:
            rows = pd.concat([values, covariates[condition]], axis=1).dropna()
            result[condition] = {"r": round(float(np.corrcoef(rows.iloc[:, 0], rows.iloc[:, 1])[0, 1]), 3), "n": len(rows)}
        return result

    result = {}
    baseline = kept.groupby("jur").apply(posture, include_groups=False)
    result["headline"] = correlations(baseline)
    decisions = kept[kept["odr"] == "decision"]
    result["decision_only"] = correlations(decisions.groupby("jur").apply(posture, include_groups=False))
    document_posture = kept.groupby(["jur", "doc_id"]).apply(posture, include_groups=False)
    result["document_balanced"] = correlations(document_posture.groupby("jur").mean())
    eligible = kept[kept["is_priv"]].groupby("jur").size().loc[lambda count: count >= 8].index
    result["min8_privacy_statements"] = correlations(baseline[baseline.index.isin(eligible)])
    wholesale = set(documents.loc[documents["scope"] == "wholesale", "doc_id"])
    subset = kept[~kept["doc_id"].isin(wholesale)]
    result["wholesale_excluded"] = correlations(subset.groupby("jur").apply(posture, include_groups=False))
    leave_one_out = {condition: [] for condition in CONDITIONS}
    for doc_id in kept["doc_id"].unique():
        values = kept[kept["doc_id"] != doc_id].groupby("jur").apply(posture, include_groups=False)
        current = correlations(values)
        for condition in CONDITIONS:
            leave_one_out[condition].append(current[condition]["r"])
    result["lodo_range"] = {
        condition: {"min": min(values), "max": max(values)}
        for condition, values in leave_one_out.items()
    }
    (ROOT / "results/robustness.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print("robustness: headline + four variants + leave-one-document-out")


if __name__ == "__main__":
    main()
