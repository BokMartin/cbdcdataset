#!/usr/bin/env python3
"""Build v10.2e ensemble and provider-sensitivity results."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from signals import CODE_SIGNAL, ENDGOALS, KEYWORDS, code_root, keyword_hits


ROOT = Path(__file__).resolve().parents[1]
PROVIDERS = ("openai", "claude")
VARIANTS = ("ensemble", "openai", "claude", "consensus")
ODR_WEIGHT = {"decision": 1.0, "proposal": 0.5}
DIR_SIGN = {"increases": 1.0, "decreases": -1.0, "conditional": -0.25, "neutral": 0.0}
RELATION_WEIGHT = {"from_state": 1.0, "from_intermediary": 0.5, "not_applicable": 0.5}
CONDITIONS = ("vdem", "cbi", "shadow", "basel")


def sha256(path: Path) -> str:
    content = path.read_bytes()
    if path.suffix.lower() in {".csv", ".json", ".jsonl", ".md"}:
        content = content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(content).hexdigest()


def read_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def split_ids(value: str) -> list[str]:
    return [item for item in str(value or "").split(";") if item]


def flatten_provider(provider: str, responses: list[dict]) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for response in responses:
        for unit in response["units"]:
            for ordinal, statement in enumerate(unit["statements"], 1):
                statement_id = f"{provider}:{unit['unit_id']}:S{ordinal:03d}"
                if statement_id in rows:
                    raise ValueError(f"duplicate statement id: {statement_id}")
                rows[statement_id] = {
                    "provider": provider,
                    "statement_id": statement_id,
                    "unit_id": unit["unit_id"],
                    **statement,
                }
    return rows


def code_set(rows: list[dict]) -> set[str]:
    return {str(row.get("code1") or "") for row in rows}


def family_set(rows: list[dict]) -> set[str]:
    return {str(row.get("code1") or "").split(".", 1)[0] for row in rows}


def odr_set(rows: list[dict]) -> set[str]:
    return {str(row.get("odr") or "") for row in rows}


def annotation_key(row: dict) -> tuple[str, str, str, int]:
    strength = int(row.get("strength") or 1)
    return (
        str(row.get("odr") or ""),
        str(row.get("privacy_direction") or "neutral"),
        str(row.get("privacy_relation") or "not_applicable"),
        min(3, max(1, strength)),
    )


def representative(rows: list[dict]) -> dict:
    def rank(row: dict) -> tuple[int, str]:
        text = str(row.get("quote_en") or row.get("quote") or "")
        return (len(text), hashlib.sha256(text.encode("utf-8")).hexdigest())

    return max(rows, key=rank)


def provider_contributions(
    candidate: dict,
    provider: str,
    rows: list[dict],
    provider_share: float,
    variant: str,
) -> list[dict]:
    by_code: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_code[str(row.get("code1") or "")].append(row)
    if not by_code:
        return []
    code_share = provider_share / len(by_code)
    output = []
    for code in sorted(by_code):
        by_annotation: dict[tuple[str, str, str, int], list[dict]] = defaultdict(list)
        for row in by_code[code]:
            by_annotation[annotation_key(row)].append(row)
        annotation_share = code_share / len(by_annotation)
        for annotation in sorted(by_annotation):
            odr, privacy_direction, privacy_relation, strength = annotation
            source = representative(by_annotation[annotation])
            quote = str(source.get("quote_en") or source.get("quote") or "")
            output.append(
                {
                    "variant": variant,
                    "candidate_id": candidate["candidate_id"],
                    "origin_type": candidate["origin_type"],
                    "provider": provider,
                    "doc_id": candidate["doc_id"],
                    "jur": candidate["doc_id"].split("_", 1)[0],
                    "page": int(candidate["page"]),
                    "language": candidate["language"],
                    "code": code,
                    "family": code.split(".", 1)[0],
                    "odr": odr,
                    "privacy_direction": privacy_direction,
                    "privacy_relation": privacy_relation,
                    "strength": strength,
                    "allocation_weight": annotation_share,
                    "representative_quote": quote,
                    "representative_statement_id": source["statement_id"],
                }
            )
    return output


def candidate_rows(mapping: list[dict], statements: dict[str, dict]) -> tuple[pd.DataFrame, dict]:
    contributions: list[dict] = []
    agreement = Counter()
    origin = Counter()
    provider_population = Counter()
    used_statements = Counter()
    for candidate in mapping:
        attached = {
            provider: [statements[item] for item in split_ids(candidate[f"{provider}_statement_ids"])]
            for provider in PROVIDERS
        }
        for provider in PROVIDERS:
            for row in attached[provider]:
                if row["provider"] != provider:
                    raise ValueError(f"provider mismatch: {row['statement_id']}")
                used_statements[row["statement_id"]] += 1
            expected = {item for item in str(candidate[f"{provider}_codes"] or "").split(";") if item}
            if expected and expected != code_set(attached[provider]):
                raise ValueError(f"mapping code mismatch: {candidate['candidate_id']} {provider}")

        present = [provider for provider in PROVIDERS if attached[provider]]
        if not present:
            raise ValueError(f"candidate without provider evidence: {candidate['candidate_id']}")
        origin[candidate["origin_type"]] += 1
        for provider in present:
            provider_population[provider] += 1

        both = len(present) == 2
        exact_code = both and code_set(attached["openai"]) == code_set(attached["claude"])
        exact_family = both and family_set(attached["openai"]) == family_set(attached["claude"])
        exact_odr = both and odr_set(attached["openai"]) == odr_set(attached["claude"])
        if both:
            agreement["both"] += 1
            agreement["exact_code_set"] += int(exact_code)
            agreement["exact_family_set"] += int(exact_family)
            agreement["exact_odr_set"] += int(exact_odr)

        for provider in present:
            contributions.extend(provider_contributions(candidate, provider, attached[provider], 1 / len(present), "ensemble"))
            contributions.extend(provider_contributions(candidate, provider, attached[provider], 1.0, provider))
        if exact_code:
            for provider in present:
                contributions.extend(provider_contributions(candidate, provider, attached[provider], 0.5, "consensus"))

    duplicate_use = [statement_id for statement_id, count in used_statements.items() if count != 1]
    if duplicate_use:
        raise ValueError(f"statement-to-candidate mapping is not one-to-one: {duplicate_use[:5]}")
    frame = pd.DataFrame(contributions).sort_values(
        ["variant", "candidate_id", "provider", "code", "odr", "privacy_direction", "privacy_relation", "strength"]
    )
    mass = frame.groupby(["variant", "candidate_id"])["allocation_weight"].sum()
    if not np.allclose(mass.to_numpy(), 1.0, atol=1e-12):
        raise ValueError("candidate mass does not sum to one")
    summary = {
        "candidate_population": len(mapping),
        "origin_type": dict(sorted(origin.items())),
        "provider_candidate_population": dict(sorted(provider_population.items())),
        "agreement_among_both": {
            "both": agreement["both"],
            "exact_code_set": agreement["exact_code_set"],
            "exact_code_set_rate": agreement["exact_code_set"] / agreement["both"],
            "exact_family_set": agreement["exact_family_set"],
            "exact_family_set_rate": agreement["exact_family_set"] / agreement["both"],
            "exact_odr_set": agreement["exact_odr_set"],
            "exact_odr_set_rate": agreement["exact_odr_set"] / agreement["both"],
        },
        "variant_candidate_population": {variant: int((frame.loc[frame.variant == variant, "candidate_id"]).nunique()) for variant in VARIANTS},
    }
    return frame, summary


def write_deterministic_gzip(frame: pd.DataFrame, path: Path) -> None:
    csv_bytes = frame.to_csv(index=False, lineterminator="\n", float_format="%.12g").encode("utf-8")
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
            zipped.write(csv_bytes)


def calibration_threshold(values: pd.Series) -> tuple[float, float, float]:
    low, middle, high = np.percentile(values.to_numpy(float), [5, 50, 95])
    if high <= middle:
        high = middle + 1e-6
    if middle <= low:
        low = middle - 1e-6
    return float(low), float(middle), float(high)


def apply_calibration(values: pd.Series, threshold: tuple[float, float, float]) -> np.ndarray:
    low, middle, high = threshold
    source = values.to_numpy(float)
    output = np.empty_like(source)
    above = source >= middle
    output[above] = 0.5 + 0.45 * np.minimum(1, (source[above] - middle) / (high - middle))
    output[~above] = 0.05 + 0.45 * np.maximum(0, (source[~above] - low) / (middle - low))
    return np.clip(output, 0.01, 0.99)


def raw_entity_scores(frame: pd.DataFrame) -> pd.DataFrame:
    eligible = frame[
        frame["odr"].isin(ODR_WEIGHT) & ~frame["code"].str.startswith("NONE")
    ].copy()
    eligible["odr_weight"] = eligible["odr"].map(ODR_WEIGHT)
    eligible["analytic_weight"] = eligible["allocation_weight"] * eligible["odr_weight"] * eligible["strength"]
    eligible["is_privacy"] = eligible["privacy_direction"].ne("neutral")
    for goal in ENDGOALS:
        eligible[f"kw_{goal}"] = eligible["representative_quote"].map(lambda text: keyword_hits(text, KEYWORDS[goal]))

    rows = []
    for jur, group in eligible.groupby("jur"):
        denominator = group["analytic_weight"].sum()
        row = {
            "jur": jur,
            "analytic_candidate_mass": group["allocation_weight"].sum(),
            "analytic_contributions": len(group),
            "documents": group["doc_id"].nunique(),
        }
        family_mass = group.groupby("family")["allocation_weight"].sum()
        privacy_denominator = sum(float(family_mass.get(family, 0)) for family in ("PRIV", "AML", "KYC", "TECH"))
        row["privacy_family_share"] = float(family_mass.get("PRIV", 0)) / privacy_denominator if privacy_denominator else np.nan
        posture_numerator = (
            group["analytic_weight"]
            * group["privacy_direction"].map(DIR_SIGN).fillna(0)
            * group["privacy_relation"].map(RELATION_WEIGHT).fillna(0.5)
        ).sum()
        row["privacy_posture"] = posture_numerator / group["allocation_weight"].sum()
        state = group[group["is_privacy"] & group["privacy_relation"].eq("from_state")]
        state_weight = state["analytic_weight"].sum()
        row["state_privacy_raw"] = (
            (state["privacy_direction"].map(DIR_SIGN).fillna(0) * state["analytic_weight"]).sum() / state_weight
            if state_weight else 0.0
        )
        for goal in ENDGOALS:
            lexical = (group[f"kw_{goal}"] * group["analytic_weight"]).sum()
            structural = sum(
                CODE_SIGNAL.get(code_root(code), {}).get(goal, 0.0) * weight
                for code, weight in zip(group["code"], group["analytic_weight"])
            )
            row[f"raw_{goal}"] = (lexical + structural) / denominator if denominator else 0.0
        rows.append(row)
    return pd.DataFrame(rows)


def build_entity_scores(frame: pd.DataFrame, metadata: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    raw = {variant: raw_entity_scores(frame[frame["variant"].eq(variant)]) for variant in VARIANTS}
    ensemble = raw["ensemble"]
    thresholds = {goal: calibration_threshold(ensemble[f"raw_{goal}"]) for goal in ENDGOALS}
    state_threshold = calibration_threshold(ensemble["state_privacy_raw"])
    outputs = []
    for variant in VARIANTS:
        scores = raw[variant].copy()
        for goal in ENDGOALS:
            scores[f"score_{goal}"] = apply_calibration(scores[f"raw_{goal}"], thresholds[goal])
        scores["state_privacy_score"] = apply_calibration(scores["state_privacy_raw"], state_threshold)
        scores["score_cash_substitution_ungated"] = scores["score_cash_substitution"]
        scores["score_cash_substitution"] *= 0.35 + 0.65 * scores["state_privacy_score"]
        columns = [f"score_{goal}" for goal in ENDGOALS]
        scores["dominant_centre"] = scores[columns].idxmax(axis=1).str.removeprefix("score_")
        scores["dominant_score"] = scores[columns].max(axis=1)
        scores["second_score"] = scores[columns].apply(lambda row: sorted(row, reverse=True)[1], axis=1)
        scores["mixed_case"] = scores["dominant_score"] - scores["second_score"] < 0.10
        scores.insert(0, "variant", variant)
        outputs.append(scores)
    result = pd.concat(outputs, ignore_index=True).merge(
        metadata[["jur", "iso3", "country", "cluster"]], on="jur", how="left", validate="many_to_one"
    )
    if result["country"].isna().any():
        raise ValueError(f"missing jurisdiction metadata: {sorted(result.loc[result.country.isna(), 'jur'].unique())}")
    result["is_composite"] = result["jur"].isin({"BIS", "UN"})
    return result, {
        "purpose_calibration_thresholds": {goal: list(thresholds[goal]) for goal in ENDGOALS},
        "state_privacy_calibration_threshold": list(state_threshold),
    }


def correlation(x: np.ndarray, y: np.ndarray) -> float:
    return float(np.corrcoef(x, y)[0, 1])


def inference(rows: pd.DataFrame, x: str, y: str, seed: str, draws: int) -> dict:
    clean = rows[[x, y]].dropna()
    xv = clean[x].to_numpy(float)
    yv = clean[y].to_numpy(float)
    observed = correlation(xv, yv)
    rng = np.random.default_rng(int(hashlib.sha256(seed.encode()).hexdigest()[:16], 16))
    indices = rng.integers(0, len(clean), size=(draws, len(clean)))
    bootstrap = np.array([correlation(xv[index], yv[index]) for index in indices])
    permutation = np.array([correlation(xv, rng.permutation(yv)) for _ in range(draws)])
    return {
        "r": observed,
        "n": len(clean),
        "ci": [float(item) for item in np.nanpercentile(bootstrap, [2.5, 97.5])],
        "p_perm": float((np.sum(np.abs(permutation) >= abs(observed)) + 1) / (draws + 1)),
    }


def macro_results(scores: pd.DataFrame, macro_path: Path, draws: int) -> dict:
    macro = pd.read_excel(macro_path, sheet_name="1_Master", header=1)
    macro = macro.dropna(subset=["ISO-3"]).rename(
        columns={
            "ISO-3": "iso3",
            "V-Dem LibDem": "vdem",
            "Romelli CBIE": "cbi",
            "Informal DGE %GDP": "shadow",
            "Basel score": "basel",
        }
    )
    output = {"draws": draws, "variants": {}}
    for variant in VARIANTS:
        rows = scores[scores["variant"].eq(variant) & ~scores["is_composite"]].merge(
            macro[["iso3", *CONDITIONS]], on="iso3", how="left"
        )
        variant_result = {"vocabulary": {}, "posture": {}}
        for measure, column in (("vocabulary", "privacy_family_share"), ("posture", "privacy_posture")):
            for condition in CONDITIONS:
                variant_result[measure][condition] = inference(
                    rows, condition, column, f"v10.2e|{variant}|{measure}|{condition}", draws
                )
        variant_result["measurement_relation"] = inference(
            rows,
            "privacy_family_share",
            "privacy_posture",
            f"v10.2e|{variant}|measurement_relation",
            draws,
        )
        output["variants"][variant] = variant_result

    tests = sorted(
        [
            (
                (measure, condition),
                output["variants"]["ensemble"][measure][condition]["p_perm"],
            )
            for measure in ("vocabulary", "posture")
            for condition in CONDITIONS
        ],
        key=lambda item: item[1],
    )
    running = 0.0
    for index, ((measure, condition), p_value) in enumerate(tests):
        running = max(running, min(1.0, (len(tests) - index) * p_value))
        output["variants"]["ensemble"][measure][condition]["p_holm"] = running
    return output


def distribution_tables(frame: pd.DataFrame) -> pd.DataFrame:
    blocks = []
    for dimension in ("code", "family", "odr", "privacy_direction", "privacy_relation"):
        values = frame.groupby(["variant", dimension], as_index=False)["allocation_weight"].sum()
        values = values.rename(columns={dimension: "category", "allocation_weight": "mass"})
        values.insert(1, "dimension", dimension)
        totals = values.groupby("variant")["mass"].transform("sum")
        values["share"] = values["mass"] / totals
        blocks.append(values)
    return pd.concat(blocks, ignore_index=True).sort_values(["dimension", "variant", "mass"], ascending=[True, True, False])


def plot_composition(scores: pd.DataFrame, path: Path) -> None:
    counts = scores.groupby(["variant", "dominant_centre"])["jur"].nunique().unstack(fill_value=0)
    centres = ENDGOALS
    y = np.arange(len(centres))
    fig, ax = plt.subplots(figsize=(8.2, 4.4))
    ensemble = np.array([counts.loc["ensemble"].get(centre, 0) for centre in centres])
    openai = np.array([counts.loc["openai"].get(centre, 0) for centre in centres])
    claude = np.array([counts.loc["claude"].get(centre, 0) for centre in centres])
    ax.barh(y, ensemble, color="0.78", edgecolor="black", label="Ensemble")
    ax.scatter(openai, y - 0.13, marker="o", facecolors="white", edgecolors="black", label="OpenAI")
    ax.scatter(claude, y + 0.13, marker="x", color="black", label="Claude")
    ax.set_yticks(y, [centre.replace("_", " ").title() for centre in centres])
    ax.set_xlabel("Jurisdictions / institutional composites")
    ax.grid(axis="x", color="0.88", linewidth=0.7)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, ncol=3, loc="lower right")
    fig.tight_layout()
    fig.savefig(path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def plot_macro(macro: dict, path: Path) -> None:
    labels = []
    ensemble = []
    openai = []
    claude = []
    for measure in ("vocabulary", "posture"):
        for condition in CONDITIONS:
            labels.append(f"{measure}: {condition}")
            ensemble.append(macro["variants"]["ensemble"][measure][condition]["r"])
            openai.append(macro["variants"]["openai"][measure][condition]["r"])
            claude.append(macro["variants"]["claude"][measure][condition]["r"])
    y = np.arange(len(labels))
    fig, ax = plt.subplots(figsize=(8.2, 4.8))
    for index in range(len(labels)):
        ax.plot([openai[index], claude[index]], [y[index], y[index]], color="0.65", linewidth=2)
    ax.scatter(ensemble, y, marker="s", color="black", label="Ensemble")
    ax.scatter(openai, y - 0.10, marker="o", facecolors="white", edgecolors="black", label="OpenAI")
    ax.scatter(claude, y + 0.10, marker="x", color="black", label="Claude")
    ax.axvline(0, color="0.55", linewidth=0.8)
    ax.set_yticks(y, labels)
    ax.set_xlim(-1, 1)
    ax.set_xlabel("Pearson correlation")
    ax.grid(axis="x", color="0.9", linewidth=0.7)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, ncol=3, loc="lower right")
    fig.tight_layout()
    fig.savefig(path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def json_dump(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mapping",
        type=Path,
        default=ROOT / "validation/extraction_v10_2_exploratory/human_review/2026-08-25_final_adjudication/candidate_machine_mapping.csv",
    )
    parser.add_argument(
        "--openai",
        type=Path,
        default=ROOT / "validation/extraction_v10_2_exploratory/runs/2026-08-25_openai_production/final/openai_extractions_v10_2e_canonical.jsonl",
    )
    parser.add_argument(
        "--claude",
        type=Path,
        default=ROOT / "validation/extraction_v10_2_exploratory/runs/2026-08-25_claude_production/claude_extractions_v10_2e_canonical.jsonl",
    )
    parser.add_argument("--metadata", type=Path, default=ROOT / "data/jurisdictions.csv")
    parser.add_argument("--macro", type=Path, default=ROOT / "data/macro.xlsx")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "results/v10_2e_ensemble")
    parser.add_argument("--figure-dir", type=Path, default=ROOT / "figures")
    parser.add_argument("--draws", type=int, default=10_000)
    parser.add_argument("--skip-figures", action="store_true")
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    args.figure_dir.mkdir(parents=True, exist_ok=True)

    mapping = pd.read_csv(args.mapping, keep_default_na=False).to_dict("records")
    if len(mapping) != 6_949 or len({row["candidate_id"] for row in mapping}) != 6_949:
        raise ValueError("unexpected candidate mapping population")
    statements = {
        **flatten_provider("openai", read_jsonl(args.openai)),
        **flatten_provider("claude", read_jsonl(args.claude)),
    }
    frame, summary = candidate_rows(mapping, statements)
    metadata = pd.read_csv(args.metadata, keep_default_na=False)
    scores, calibration = build_entity_scores(frame, metadata)
    macro = macro_results(scores, args.macro, args.draws)
    distributions = distribution_tables(frame)

    allocations_path = args.out_dir / "candidate_allocations.csv.gz"
    scores_path = args.out_dir / "entity_scores.csv"
    distributions_path = args.out_dir / "distributions.csv"
    summary_path = args.out_dir / "analysis_summary.json"
    macro_path = args.out_dir / "macro_results.json"
    manifest_path = args.out_dir / "analysis_manifest.json"
    write_deterministic_gzip(frame, allocations_path)
    scores.to_csv(scores_path, index=False, lineterminator="\n", float_format="%.12g")
    distributions.to_csv(distributions_path, index=False, lineterminator="\n", float_format="%.12g")

    summary.update(calibration)
    summary["analytic_candidate_mass"] = {
        variant: float(scores.loc[scores.variant.eq(variant), "analytic_candidate_mass"].sum()) for variant in VARIANTS
    }
    summary["dominant_centres"] = {
        variant: {
            str(key): int(value)
            for key, value in scores.loc[scores.variant.eq(variant), "dominant_centre"].value_counts().sort_index().items()
        }
        for variant in VARIANTS
    }
    summary["human_validation"] = {
        "status": "pending_blind_double_review",
        "candidate_sample": 365,
        "candidate_population": 6949,
        "dual_empty_sample": 36,
        "dual_empty_population": 359,
    }
    json_dump(summary_path, summary)
    json_dump(macro_path, macro)

    composition_figure = args.figure_dir / "v10_2e_ensemble_composition.png"
    macro_figure = args.figure_dir / "v10_2e_model_sensitivity.png"
    if not args.skip_figures:
        plot_composition(scores, composition_figure)
        plot_macro(macro, macro_figure)

    outputs = [allocations_path, scores_path, distributions_path, summary_path, macro_path]
    manifest = {
        "schema": "cbdc-v10.2e-ensemble-analysis-v1",
        "protocol": "validation/extraction_v10_2_exploratory/ENSEMBLE_ANALYSIS_PROTOCOL.md",
        "inputs": {
            "mapping": {"path": str(args.mapping.relative_to(ROOT)), "sha256": sha256(args.mapping)},
            "openai": {"path": str(args.openai.relative_to(ROOT)), "sha256": sha256(args.openai)},
            "claude": {"path": str(args.claude.relative_to(ROOT)), "sha256": sha256(args.claude)},
            "metadata": {"path": str(args.metadata.relative_to(ROOT)), "sha256": sha256(args.metadata)},
            "macro": {"path": str(args.macro.relative_to(ROOT)), "sha256": sha256(args.macro)},
        },
        "parameters": {"draws": args.draws, "variants": list(VARIANTS)},
        "outputs": {str(path.relative_to(ROOT)): sha256(path) for path in outputs},
        "figures": [str(composition_figure.relative_to(ROOT)), str(macro_figure.relative_to(ROOT))],
    }
    json_dump(manifest_path, manifest)
    print(json.dumps({"summary": summary, "manifest": str(manifest_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
