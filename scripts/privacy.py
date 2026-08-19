import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
import numpy as np
import pandas as pd
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DECISION_WEIGHT = {"decision": 1.0, "proposal": 0.5}
RELATION_WEIGHT = {
    "from_state": 1.0, "from_intermediary": 0.5,
    "from_counterparty": 0.5, "not_applicable": 0.5,
}
DIRECTION_SIGN = {"increases": 1.0, "decreases": -1.0, "conditional": -0.25}


def compute(candidates, scores):
    kept = candidates[
        (candidates["v5_verdict"] == "keep") & candidates["odr"].isin(DECISION_WEIGHT)
    ].copy()
    kept["jur"] = kept["doc_id"].str.split("_").str[0]
    kept["dw"] = kept["odr"].map(DECISION_WEIGHT)
    kept["strength_num"] = pd.to_numeric(kept["strength"], errors="coerce").clip(1, 3).fillna(1)
    privacy = kept[kept["privacy_direction"] != "neutral"].copy()
    unknown_direction = sorted(set(privacy["privacy_direction"]) - set(DIRECTION_SIGN))
    unknown_relation = sorted(set(privacy["privacy_relation"]) - set(RELATION_WEIGHT))
    if unknown_direction or unknown_relation:
        raise ValueError(f"unknown values: direction={unknown_direction}, relation={unknown_relation}")
    privacy["q"] = (
        privacy["dw"] * privacy["strength_num"] * privacy["privacy_relation"].map(RELATION_WEIGHT)
    )

    rows = []
    for jur, all_rows in kept.groupby("jur", sort=True):
        p = privacy[privacy["jur"] == jur]
        inc = p[p["privacy_direction"] == "increases"]
        dec = p[p["privacy_direction"] == "decreases"]
        con = p[p["privacy_direction"] == "conditional"]
        n_all, n_privacy = len(all_rows), len(p)
        positive, negative, conditional = inc["q"].sum(), dec["q"].sum(), con["q"].sum()
        directional = positive + negative
        rows.append({
            "jur": jur, "n_own_design": n_all, "n_privacy": n_privacy,
            "n_directional": len(inc) + len(dec), "n_conditional": len(con),
            "privacy_salience": n_privacy / n_all if n_all else np.nan,
            "directional_valence": (positive - negative) / directional if directional else np.nan,
            "conditionality": len(con) / n_privacy if n_privacy else np.nan,
            "positive_density": positive / n_all if n_all else np.nan,
            "negative_density": negative / n_all if n_all else np.nan,
            "conditional_density": conditional / n_all if n_all else np.nan,
            "directional_weight": directional,
            "current_signed_density": (positive - negative - 0.25 * conditional) / n_all if n_all else np.nan,
            "component_status": "no_privacy_evidence" if not n_privacy else (
                "no_directional_evidence" if not directional else "estimated"
            ),
        })
    result = pd.DataFrame(rows).merge(
        scores[["jur", "iso3", "country", "is_composite", "net_privacy_posture"]],
        on="jur", how="left", validate="one_to_one",
    )
    delta = (result["current_signed_density"] - result["net_privacy_posture"]).abs().max()
    if not np.isfinite(delta) or delta > 1e-12:
        raise AssertionError(f"privacy identity failed: {delta}")
    columns = [
        "jur", "iso3", "country", "is_composite", "n_own_design", "n_privacy",
        "n_directional", "n_conditional", "privacy_salience", "directional_valence",
        "conditionality", "positive_density", "negative_density", "conditional_density",
        "directional_weight", "component_status", "current_signed_density", "net_privacy_posture",
    ]
    return result[columns].sort_values("jur").reset_index(drop=True)


def draw(data, path):
    data = data[~data["is_composite"].astype(bool)].sort_values(
        ["privacy_salience", "country"], ascending=[True, True]
    )
    y = np.arange(len(data))
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 7.5})
    fig, axes = plt.subplots(1, 3, figsize=(8.2, 12.4), sharey=True,
                             gridspec_kw={"width_ratios": [1, 1.25, 1.15]})
    salience, valence, density = axes
    salience.scatter(data["privacy_salience"], y, s=19, color="#264653", zorder=3)
    salience.set(xlabel="Privacy salience (S)", xlim=(-0.01, None))
    valid = data["directional_valence"].notna()
    points = valence.scatter(
        data.loc[valid, "directional_valence"], y[valid.to_numpy()],
        c=data.loc[valid, "conditionality"], cmap="viridis", norm=Normalize(0, 1),
        s=25, edgecolor="white", linewidth=0.35, zorder=3,
    )
    if (~valid).any():
        valence.scatter(np.zeros((~valid).sum()), y[(~valid).to_numpy()], marker="x",
                        color="#999999", s=22, linewidth=0.8, zorder=3)
    valence.axvline(0, color="#777777", lw=0.8)
    valence.set(xlabel="Directional valence (V)\ncolour = conditionality (C)", xlim=(-1.05, 1.05))
    colorbar = fig.colorbar(points, ax=valence, orientation="horizontal", fraction=0.035, pad=0.07)
    colorbar.set_label("Conditionality (C)")
    density.scatter(data["positive_density"], y, marker=">", s=22, color="#2a9d8f", label="D+", zorder=3)
    density.scatter(data["negative_density"], y, marker="<", s=22, color="#e76f51", label="D−", zorder=3)
    density.set(xlabel="Weighted density (D+ / D−)", xlim=(-0.01, None))
    density.legend(frameon=False, loc="lower right")
    for axis in axes:
        axis.grid(axis="x", color="#dddddd", lw=0.5)
        axis.spines[["top", "right"]].set_visible(False)
        axis.set_ylim(-0.8, len(data) - 0.2)
    salience.set_yticks(y, data["country"])
    valence.tick_params(labelleft=False)
    density.tick_params(labelleft=False)
    fig.suptitle("Privacy language as components, not a commitment ranking",
                 x=0.08, ha="left", fontsize=12, fontweight="bold")
    fig.text(0.08, 0.965,
             "Frozen observed corpus; 47 empirical jurisdictions. An x marks missing directional valence.",
             ha="left", va="top", fontsize=8)
    fig.subplots_adjust(left=0.29, right=0.98, top=0.94, bottom=0.055, wspace=0.17)
    fig.savefig(path, dpi=240, facecolor="white")
    plt.close(fig)
    with Image.open(path) as image:
        image.convert("RGB").save(path)


def main():
    data = compute(
        pd.read_csv(ROOT / "data/candidates.csv", keep_default_na=False),
        pd.read_csv(ROOT / "results/scores.csv", keep_default_na=False),
    )
    data.to_csv(ROOT / "results/privacy_components.csv", index=False)
    delta = float((data["current_signed_density"] - data["net_privacy_posture"]).abs().max())
    metadata = {
        "name": "privacy component decomposition", "version": "1.0",
        "estimand": "descriptive distribution within the frozen observed CBDC document corpus",
        "recommended_outputs": ["privacy_salience", "directional_valence", "conditionality", "positive_density", "negative_density"],
        "legacy_bridge_only": ["current_signed_density", "net_privacy_posture"],
        "decision_weight": DECISION_WEIGHT, "relation_weight": RELATION_WEIGHT,
        "conditional_sign_in_legacy_bridge": -0.25,
        "missing_rule": "directional_valence is missing when directional weight is zero",
        "n_jurisdictions": len(data),
        "n_empirical_non_composite": int((~data["is_composite"].astype(bool)).sum()),
        "n_without_privacy_evidence": int((data["n_privacy"] == 0).sum()),
        "n_without_directional_evidence": int(data["directional_valence"].isna().sum()),
        "legacy_identity_max_abs_delta": delta,
    }
    (ROOT / "results/privacy_method.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    draw(data, ROOT / "figures/privacy_components.png")
    print(f"privacy: {len(data)} entities, identity delta {delta:.3g}")


if __name__ == "__main__":
    main()
