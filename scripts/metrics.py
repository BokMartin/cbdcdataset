import numpy as np
import pandas as pd


def paired(a, b):
    a, b = pd.Series(a), pd.Series(b)
    valid = a.notna() & b.notna() & (a.astype(str) != "") & (b.astype(str) != "")
    return a[valid].astype(str), b[valid].astype(str), int(valid.sum()), int((~valid).sum())


def krippendorff_alpha(a, b):
    a, b, n, missing = paired(a, b)
    if not n:
        return np.nan, 0, missing
    observed = float((a != b).mean())
    proportions = pd.concat([a, b]).value_counts(normalize=True)
    expected = 1 - float((proportions ** 2).sum())
    expected *= 2 * n / (2 * n - 1)
    return (1.0 if expected == 0 else 1 - observed / expected), n, missing


def gwet_ac1(a, b):
    a, b, n, missing = paired(a, b)
    if not n:
        return np.nan, 0, missing
    observed = float((a == b).mean())
    proportions = pd.concat([a, b]).value_counts(normalize=True)
    categories = len(proportions)
    expected = float((proportions * (1 - proportions)).sum()) / max(1, categories - 1) if categories > 1 else 0
    return (1.0 if expected == 1 else (observed - expected) / (1 - expected)), n, missing


def per_code_prf(truth, prediction, zero_division=0.0):
    truth, prediction, n, missing = paired(truth, prediction)
    rows = []
    for code in sorted(set(truth) | set(prediction)):
        tp = int(((truth == code) & (prediction == code)).sum())
        fp = int(((truth != code) & (prediction == code)).sum())
        fn = int(((truth == code) & (prediction != code)).sum())
        precision = tp / (tp + fp) if tp + fp else zero_division
        recall = tp / (tp + fn) if tp + fn else zero_division
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else zero_division
        rows.append({
            "code": code, "n_true": int((truth == code).sum()), "tp": tp, "fp": fp, "fn": fn,
            "precision": precision, "recall": recall, "f1": f1,
            "degenerate": (tp + fp == 0) or (tp + fn == 0),
        })
    table = pd.DataFrame(rows, columns=[
        "code", "n_true", "tp", "fp", "fn", "precision", "recall", "f1", "degenerate",
    ])
    if table.empty:
        aggregate = {name: np.nan for name in ["macro_precision", "macro_recall", "macro_f1", "accuracy"]}
        aggregate["n_degenerate_codes"] = 0
    else:
        aggregate = {
            "macro_precision": float(table["precision"].mean()),
            "macro_recall": float(table["recall"].mean()),
            "macro_f1": float(table["f1"].mean()),
            "accuracy": float((truth == prediction).mean()),
            "n_degenerate_codes": int(table["degenerate"].sum()),
        }
    aggregate.update(n_valid=n, n_missing=missing)
    return table, aggregate


def cluster_bootstrap_ci(data, cluster, statistic, draws=2_000, seed=42, alpha=0.05):
    if cluster not in data:
        raise KeyError(cluster)
    if data.empty:
        raise ValueError("empty data")
    if data[cluster].isna().any() or (data[cluster].astype(str) == "").any():
        raise ValueError("missing cluster ID")
    if not isinstance(draws, (int, np.integer)) or draws < 1:
        raise ValueError("draws must be a positive integer")
    if not 0 < alpha < 1:
        raise ValueError("alpha must be in (0, 1)")
    observed = float(statistic(data))
    rng = np.random.default_rng(seed)
    clusters = data[cluster].unique()
    groups = {value: data[data[cluster] == value] for value in clusters}
    estimates = []
    for _ in range(draws):
        sampled = rng.choice(clusters, size=len(clusters), replace=True)
        parts = []
        for replicate, value in enumerate(sampled):
            part = groups[value].copy()
            part[cluster] = f"rep{replicate:04d}"
            parts.append(part)
        estimate = statistic(pd.concat(parts, ignore_index=True))
        if np.isfinite(estimate):
            estimates.append(float(estimate))
    if not estimates:
        return observed, np.nan, np.nan, 0
    low, high = np.quantile(estimates, [alpha / 2, 1 - alpha / 2])
    return observed, float(low), float(high), len(estimates)


def selftest():
    a, b = ["A", "A", "A", "B"], ["A", "A", "B", "B"]
    assert abs(krippendorff_alpha(a, b)[0] - 0.533333) < 1e-5
    assert abs(gwet_ac1(a, b)[0] - 0.529412) < 1e-5
    assert krippendorff_alpha(["A", None, "B"], ["A", "B", None])[1:] == (1, 2)
    table, aggregate = per_code_prf(["A", None, "B"], ["A", "B", None])
    assert table["code"].tolist() == ["A"] and aggregate["n_missing"] == 2
    data = pd.DataFrame({"doc": ["d1"] * 99 + ["d2"], "ok": [1] * 98 + [0] + [1]})
    observed, low, high, finite = cluster_bootstrap_ci(data, "doc", lambda rows: rows["ok"].mean(), draws=400)
    assert observed == data["ok"].mean() and finite == 400 and low <= high
    equal = pd.DataFrame({"doc": ["a"] * 3 + ["b"] * 3, "v": [1] * 3 + [0] * 3})
    observed, low, high, _ = cluster_bootstrap_ci(
        equal, "doc", lambda rows: rows.groupby("doc")["v"].mean().mean(), draws=400
    )
    assert observed == 0.5 and low != high
    print("metrics: self-test passed")


if __name__ == "__main__":
    selftest()
