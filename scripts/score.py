import json
from pathlib import Path

import numpy as np
import pandas as pd

from signals import CODE_SIGNAL, ENDGOALS, KEYWORDS, code_root, keyword_hits

ROOT = Path(__file__).resolve().parents[1]
DIR_SIGN = {"increases": 1.0, "decreases": -1.0, "conditional": -0.25, "neutral": 0.0}
RELATION_WEIGHT = {"from_state": 1.0, "from_intermediary": 0.5}


def calibrate(values):
    values = np.asarray(values, dtype=float)
    low, middle, high = np.percentile(values, [5, 50, 95])
    high = high if high > middle else middle + 1e-6
    low = low if middle > low else middle - 1e-6
    out = np.empty_like(values)
    above = values >= middle
    out[above] = 0.5 + 0.45 * np.minimum(1, (values[above] - middle) / (high - middle))
    out[~above] = 0.05 + 0.45 * np.maximum(0, (values[~above] - low) / (middle - low))
    return np.clip(out, 0.01, 0.99)


def privacy_posture(group):
    privacy = group[group["is_priv"]]
    if privacy.empty:
        return 0.0
    total = (
        privacy["dw"]
        * privacy["privacy_direction"].map(DIR_SIGN).fillna(0)
        * privacy["privacy_relation"].map(RELATION_WEIGHT).fillna(0.5)
        * privacy["strength_num"]
    ).sum()
    return total / len(group)


def state_privacy(group):
    rows = group[(group["privacy_relation"] == "from_state") & group["is_priv"]]
    if rows.empty:
        return 0.0
    weight = rows["dw"] * rows["strength_num"]
    return float((rows["privacy_direction"].map(DIR_SIGN).fillna(0) * weight).sum() / weight.sum())


def score():
    candidates = pd.read_csv(ROOT / "data/candidates.csv", keep_default_na=False)
    candidates["jur"] = candidates["doc_id"].str.split("_").str[0]
    kept = candidates[
        (candidates["v5_verdict"] == "keep") & candidates["odr"].isin(["decision", "proposal"])
    ].copy()
    kept["dw"] = np.where(kept["odr"] == "decision", 1.0, 0.5)
    kept["strength_num"] = pd.to_numeric(kept["strength"], errors="coerce").clip(1, 3).fillna(1)
    kept["is_priv"] = kept["privacy_direction"] != "neutral"
    kept["text"] = np.where(kept["quote_en"].astype(str).str.len() > 0, kept["quote_en"], kept["quote"])
    kept["code"] = np.where(kept["code_v5r"].astype(str).str.len() > 0, kept["code_v5r"], kept["code1"])

    subcodes = pd.read_csv(ROOT / "data/subcodes.csv", keep_default_na=False).set_index("seg_id")["code_v6"]
    mapped = kept["seg_id"].map(subcodes)
    kept["code"] = np.where(mapped.notna() & (mapped != "") & (mapped != "OTHER.keep"), mapped.fillna(""), kept["code"])
    kept["family"] = kept["code"].str.split(".").str[0]

    metadata = pd.read_csv(ROOT / "data/jurisdictions.csv", converters={"jur": str})
    composites = set(metadata[metadata["jur"].isin(["BIS", "UN"])]["jur"]) | {"BIS", "UN"}

    family_counts = kept.pivot_table(index="jur", columns="family", values="seg_id", aggfunc="count").fillna(0)
    for family in ["PRIV", "AML", "KYC", "TECH"]:
        if family not in family_counts:
            family_counts[family] = 0
    denominator = family_counts[["PRIV", "AML", "KYC", "TECH"]].sum(axis=1)
    vocabulary = (family_counts["PRIV"] / denominator.replace(0, np.nan)).rename("vocab")
    posture = kept.groupby("jur").apply(privacy_posture, include_groups=False).rename("net_privacy_posture")

    for goal in ENDGOALS:
        kept[f"kw_{goal}"] = kept["text"].map(lambda text: keyword_hits(text, KEYWORDS[goal]))

    rows = []
    for jur, group in kept.groupby("jur"):
        denominator = (group["dw"] * group["strength_num"]).sum()
        if denominator <= 0:
            continue
        row = {"jur": jur, "n_segs": len(group), "n_docs": group["doc_id"].nunique()}
        for goal in ENDGOALS:
            keywords = (group[f"kw_{goal}"] * group["dw"] * group["strength_num"]).sum()
            structural = sum(
                CODE_SIGNAL.get(code_root(code), {}).get(goal, 0) * weight * strength
                for code, weight, strength in zip(group["code"], group["dw"], group["strength_num"])
            )
            row[f"raw_{goal}"] = (keywords + structural) / denominator
        rows.append(row)
    scores = pd.DataFrame(rows)

    for goal in ENDGOALS:
        scores[f"fz_{goal}"] = calibrate(scores[f"raw_{goal}"])
    state = kept.groupby("jur").apply(state_privacy, include_groups=False).rename("state_privacy_raw")
    scores = scores.merge(state, on="jur", how="left").fillna({"state_privacy_raw": 0})
    scores["state_privacy_fz"] = calibrate(scores["state_privacy_raw"])
    scores["fz_cash_substitution_ungated"] = scores["fz_cash_substitution"]
    scores["fz_cash_substitution"] *= 0.35 + 0.65 * scores["state_privacy_fz"]

    fuzzy = [f"fz_{goal}" for goal in ENDGOALS]
    scores["dominant_centre"] = scores[fuzzy].idxmax(axis=1).str.removeprefix("fz_")
    scores["dominant_score"] = scores[fuzzy].max(axis=1)
    scores["second_score"] = scores[fuzzy].apply(lambda row: sorted(row, reverse=True)[1], axis=1)
    scores["mixed_case"] = scores["dominant_score"] - scores["second_score"] < 0.10
    scores = scores.merge(metadata[["jur", "iso3", "country", "cluster"]], on="jur", how="left")
    scores["is_composite"] = scores["jur"].isin(composites)
    scores = scores.merge(vocabulary, on="jur", how="left").merge(posture, on="jur", how="left")
    scores.to_csv(ROOT / "results/scores.csv", index=False)
    return scores


def diagnostics(scores):
    fuzzy = [f"fz_{goal}" for goal in ENDGOALS]
    gated = scores["dominant_centre"].value_counts().to_dict()
    ungated_values = scores[fuzzy].copy()
    ungated_values["fz_cash_substitution"] = scores["fz_cash_substitution_ungated"]
    ungated = ungated_values.idxmax(axis=1).str.removeprefix("fz_")
    sensitivity = {
        "gated": gated,
        "ungated": ungated.value_counts().to_dict(),
        "cash_dominants_ungated": scores.loc[ungated == "cash_substitution", "jur"].tolist(),
    }
    (ROOT / "results/cash_gate_sensitivity.json").write_text(
        json.dumps(sensitivity, indent=1) + "\n", encoding="utf-8"
    )

    labels = ["CASH", "INCL", "SOV", "PAY", "MON", "CTRL"]
    correlation = scores[fuzzy].corr(method="spearman")
    correlation.index = labels
    correlation.columns = labels
    correlation.round(3).to_csv(ROOT / "results/centre_correlations.csv")

    values = scores[fuzzy].to_numpy(float)
    standardized = (values - values.mean(axis=0)) / values.std(axis=0, ddof=0)
    eigenvalues, vectors = np.linalg.eigh(np.cov(standardized, rowvar=False, ddof=1))
    order = np.argsort(eigenvalues)[::-1]
    eigenvalues, vectors = eigenvalues[order], vectors[:, order].T
    desired = [-1, 1, -1, -1, -1, 1]
    anchors = [0, 2, 1, 3, 5, 0]
    for i, (anchor, sign) in enumerate(zip(anchors, desired)):
        if np.sign(vectors[i, anchor]) != sign:
            vectors[i] *= -1
    pca = pd.DataFrame(vectors, columns=labels)
    pca.insert(0, "explained", eigenvalues / eigenvalues.sum())
    pca.insert(0, "eigenvalue", eigenvalues)
    pca.insert(0, "PC", [f"PC{i}" for i in range(1, 7)])
    pca.round(3).to_csv(ROOT / "results/centre_pca.csv", index=False)


if __name__ == "__main__":
    result = score()
    diagnostics(result)
    print(f"scores: {len(result)} entities, {int(result['mixed_case'].sum())} mixed")
