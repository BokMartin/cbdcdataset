import json
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

ROOT = Path(__file__).resolve().parents[1]
CONDITIONS = ["vdem", "cbi", "shadow", "basel"]
RNG = np.random.default_rng(42)


def correlation(x, y):
    return float(np.corrcoef(x, y)[0, 1])


def inference(x, y, draws=10_000):
    x, y = np.asarray(x, float), np.asarray(y, float)
    observed = correlation(x, y)
    index = RNG.integers(0, len(x), size=(draws, len(x)))
    boot = np.array([correlation(x[i], y[i]) for i in index])
    low, high = np.nanpercentile(boot, [2.5, 97.5])
    permuted = np.array([correlation(x, RNG.permutation(y)) for _ in range(draws)])
    p_raw = float((np.sum(np.abs(permuted) >= abs(observed)) + 1) / (draws + 1))
    return {
        "r": round(observed, 3), "n": len(x),
        "ci": [round(float(low), 3), round(float(high), 3)],
        "p_perm": round(p_raw, 4), "_p_raw": p_raw,
    }


def main():
    scores = pd.read_csv(ROOT / "results/scores.csv")
    scores = scores[~scores["is_composite"]].copy()
    macro = pd.read_excel(ROOT / "data/macro.xlsx", sheet_name="1_Master", header=1)
    macro = macro.dropna(subset=["ISO-3"]).rename(columns={
        "ISO-3": "iso3", "V-Dem LibDem": "vdem", "Romelli CBIE": "cbi",
        "Informal DGE %GDP": "shadow", "Basel score": "basel",
    })
    data = scores.merge(macro[["iso3", *CONDITIONS]], on="iso3", how="left")
    result = {
        "dataset": "v5r 2026-07-28 (5,624 kept statements, 47 empirical jurisdictions)",
        "pairwise": {"vocabulary": {}, "commitment": {}},
    }
    for condition in CONDITIONS:
        rows = data[["vocab", condition]].dropna()
        result["pairwise"]["vocabulary"][condition] = inference(rows[condition], rows["vocab"])
        rows = data[["net_privacy_posture", condition]].dropna()
        result["pairwise"]["commitment"][condition] = inference(rows[condition], rows["net_privacy_posture"])

    tests = sorted([
        (f"{measure}-{condition}", result["pairwise"][measure][condition]["_p_raw"])
        for measure in ["vocabulary", "commitment"] for condition in CONDITIONS
    ], key=lambda item: item[1])
    running, holm = 0.0, {}
    for i, (name, p_value) in enumerate(tests):
        running = max(running, min(1.0, (len(tests) - i) * p_value))
        holm[name] = round(running, 4)
    for measure in ["vocabulary", "commitment"]:
        for condition in CONDITIONS:
            item = result["pairwise"][measure][condition]
            item["p_holm"] = holm[f"{measure}-{condition}"]
            del item["_p_raw"]

    rows = data[["vocab", "net_privacy_posture"]].dropna()
    result["vocab_vs_commitment"] = inference(rows["vocab"], rows["net_privacy_posture"])
    del result["vocab_vs_commitment"]["_p_raw"]

    complete = data.dropna(subset=["net_privacy_posture", *CONDITIONS])
    design = sm.add_constant(complete[CONDITIONS].apply(lambda col: (col - col.mean()) / col.std()))
    ols = sm.OLS(complete["net_privacy_posture"], design).fit()
    threshold = complete["net_privacy_posture"].quantile(0.70)
    probit = sm.Probit((complete["net_privacy_posture"] > threshold).astype(int), design).fit(disp=0)
    result["regression"] = {
        "n": int(ols.nobs),
        "ols_beta": {name: round(float(ols.params[name]), 4) for name in CONDITIONS},
        "ols_p": {name: round(float(ols.pvalues[name]), 3) for name in CONDITIONS},
        "probit_p": {name: round(float(probit.pvalues[name]), 3) for name in CONDITIONS},
    }
    (ROOT / "results/audit.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(f"statistics: {len(complete)} complete cases")


if __name__ == "__main__":
    main()
