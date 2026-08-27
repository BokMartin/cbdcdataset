#!/usr/bin/env python3
"""Reproduce the released v10.2e blind human-audit metrics."""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "validation/human_audit"
OUTPUT = ROOT / "results/human_validation/human_validation_results.json"
Z_95 = 1.959963984540054


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def as_bool(series: pd.Series) -> pd.Series:
    return series.fillna(False).astype(str).str.strip().str.lower().isin({"1", "true", "yes"})


def weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    mask = values.notna() & weights.notna()
    return float(np.average(values[mask].astype(float), weights=weights[mask].astype(float)))


def stratified_estimate(frame: pd.DataFrame, value: str, manifest: dict) -> dict:
    specifications = {
        f"{row['language']}|{row['origin_type']}": row for row in manifest["strata"]
    }
    population = sum(int(row["population"]) for row in manifest["strata"])
    estimate = 0.0
    variance = 0.0
    details = []
    for stratum, specification in specifications.items():
        group = frame.loc[frame["sample_stratum"].eq(stratum)]
        n_h = len(group)
        if n_h == 0:
            continue
        n_population = int(specification["population"])
        values = group[value].astype(float)
        mean = float(values.mean())
        sample_variance = float(values.var(ddof=1)) if n_h > 1 else 0.25
        estimate += n_population * mean / population
        variance += (
            (n_population / population) ** 2
            * (1 - n_h / n_population)
            * sample_variance
            / n_h
        )
        details.append({
            "stratum": stratum,
            "population": n_population,
            "n_analyzed": n_h,
            "mean": mean,
        })
    standard_error = math.sqrt(max(variance, 0.0))
    return {
        "estimate": estimate,
        "standard_error": standard_error,
        "ci95": [
            max(0.0, estimate - Z_95 * standard_error),
            min(1.0, estimate + Z_95 * standard_error),
        ],
        "strata": details,
    }


def reliability(left: pd.Series, right: pd.Series, weights: pd.Series) -> dict:
    paired = pd.DataFrame({"left": left, "right": right, "weight": weights}).dropna(
        subset=["left", "right"]
    )
    paired["left"] = paired["left"].astype(str)
    paired["right"] = paired["right"].astype(str)
    n = len(paired)
    require(n > 0, "reliability denominator is empty")
    same = paired["left"].eq(paired["right"])
    observed = float(same.mean())
    categories = sorted(set(paired["left"]) | set(paired["right"]))
    counts = Counter(paired["left"])
    counts.update(paired["right"])
    total_ratings = 2 * n
    same_chance = sum(count * (count - 1) for count in counts.values()) / (
        total_ratings * (total_ratings - 1)
    )
    expected_disagreement = 1.0 - same_chance
    alpha = 1.0 - (1.0 - observed) / expected_disagreement
    if len(categories) <= 1:
        expected_ac1 = 0.0
    else:
        proportions = [counts[category] / total_ratings for category in categories]
        expected_ac1 = sum(p * (1 - p) for p in proportions) / (len(categories) - 1)
    ac1 = (observed - expected_ac1) / (1 - expected_ac1)
    return {
        "n": n,
        "agreements": int(same.sum()),
        "percent_agreement": observed,
        "ipw_percent_agreement": weighted_mean(same.astype(float), paired["weight"]),
        "krippendorff_alpha_nominal": alpha,
        "gwet_ac1_nominal": ac1,
    }


def wilson(successes: int, trials: int) -> list[float]:
    proportion = successes / trials
    denominator = 1 + Z_95 * Z_95 / trials
    centre = (proportion + Z_95 * Z_95 / (2 * trials)) / denominator
    half = Z_95 * math.sqrt(
        proportion * (1 - proportion) / trials + Z_95 * Z_95 / (4 * trials * trials)
    ) / denominator
    return [centre - half, centre + half]


def main() -> None:
    manifest = json.loads(
        (AUDIT / "SAMPLED_VALIDATION_FREEZE_MANIFEST.json").read_text(encoding="utf-8")
    )
    candidates = pd.read_csv(AUDIT / "reviewed_candidates.csv", keep_default_na=True)
    dual = pd.read_csv(AUDIT / "dual_empty_joint_audit.csv", keep_default_na=True)
    supplements = pd.read_csv(AUDIT / "dual_empty_supplements.csv", keep_default_na=True)

    require(len(candidates) == 365, "candidate sample must contain 365 rows")
    require(candidates["candidate_id"].nunique() == 365, "candidate IDs must be unique")
    require(len(dual) == 36, "dual-empty sample must contain 36 rows")
    require((supplements["empty_case_id"] == "DE-0009").all(), "unexpected supplement case")
    require(candidates["confidence_martin_assumed"].eq("high").all(), "Martin confidence assumption")
    require(candidates["confidence_dominik_assumed"].eq("high").all(), "Dominik confidence assumption")
    require(dual["confidence"].eq("high").all(), "dual-empty confidence assumption")
    require(supplements["confidence"].eq("high").all(), "supplement confidence assumption")

    candidates["exclude_untranslated"] = as_bool(candidates["exclude_untranslated"])
    analysis = candidates.loc[~candidates["exclude_untranslated"]].copy()
    require(len(analysis) == 364, "available-case candidate denominator must be 364")
    analysis["keep_martin"] = analysis["inclusion_decision_martin"].eq("keep").astype(int)
    analysis["keep_dominik"] = analysis["inclusion_decision_dominik"].eq("keep").astype(int)
    analysis["keep_midpoint"] = (analysis["keep_martin"] + analysis["keep_dominik"]) / 2
    analysis["keep_lower_bound"] = analysis[["keep_martin", "keep_dominik"]].min(axis=1)
    analysis["keep_upper_bound"] = analysis[["keep_martin", "keep_dominik"]].max(axis=1)
    analysis["decision_agreement"] = analysis["inclusion_decision_martin"].eq(
        analysis["inclusion_decision_dominik"]
    )

    validity = {}
    for label, column in [
        ("martin", "keep_martin"),
        ("dominik", "keep_dominik"),
        ("pre_adjudication_midpoint", "keep_midpoint"),
        ("unresolved_lower_bound", "keep_lower_bound"),
        ("unresolved_upper_bound", "keep_upper_bound"),
    ]:
        validity[label] = {
            "n": len(analysis),
            "unweighted": float(analysis[column].mean()),
            "ipw_hajek": weighted_mean(analysis[column], analysis["survey_weight"]),
            "stratified": stratified_estimate(analysis, column, manifest),
        }

    both_keep = analysis.loc[
        analysis["keep_martin"].eq(1) & analysis["keep_dominik"].eq(1)
    ].copy()
    require(len(both_keep) == 214, "both-keep denominator must be 214")
    intercoder = {
        "inclusion_decision": reliability(
            analysis["inclusion_decision_martin"],
            analysis["inclusion_decision_dominik"],
            analysis["survey_weight"],
        ),
        "exact_code_conditional_both_keep": reliability(
            both_keep["final_code1_martin"],
            both_keep["final_code1_dominik"],
            both_keep["survey_weight"],
        ),
        "family_conditional_both_keep": reliability(
            both_keep["family_martin"],
            both_keep["family_dominik"],
            both_keep["survey_weight"],
        ),
        "odr_conditional_both_keep": reliability(
            both_keep["final_odr_martin"],
            both_keep["final_odr_dominik"],
            both_keep["survey_weight"],
        ),
        "privacy_direction_conditional_both_keep": reliability(
            both_keep["privacy_direction_martin"],
            both_keep["privacy_direction_dominik"],
            both_keep["survey_weight"],
        ),
        "privacy_relation_conditional_both_keep": reliability(
            both_keep["privacy_relation_martin"],
            both_keep["privacy_relation_dominik"],
            both_keep["survey_weight"],
        ),
        "strength_conditional_both_keep": reliability(
            both_keep["strength_martin"],
            both_keep["strength_dominik"],
            both_keep["survey_weight"],
        ),
    }

    dual["exclude_untranslated"] = as_bool(dual["exclude_untranslated"])
    dual_analysis = dual.loc[~dual["exclude_untranslated"]].copy()
    missed = dual_analysis["missed_claims"].fillna("").str.lower().eq("yes")
    require((len(dual_analysis), int(missed.sum())) == (31, 1), "dual-empty release counts")

    result = {
        "schema": "cbdc-v10.2e-human-validation-results-v2",
        "status": "independent blind coding complete; consensus adjudication remains work in progress",
        "blind_status": {
            "provider_identity_hidden_during_review": True,
            "independence_confirmed_by_authors": True,
            "confirmation_date": "2026-08-27",
        },
        "confidence_assumption": "high for every candidate and dual-empty judgment, per author instruction",
        "exclusion_reason_policy": "not analyzed; retained only as future-version feedback",
        "sample": {
            "population_candidates": manifest["population_candidates"],
            "sampled_candidates": len(candidates),
            "analyzable_candidates": len(analysis),
            "excluded_untranslated_candidates": candidates.loc[
                candidates["exclude_untranslated"], "candidate_id"
            ].tolist(),
            "decision_agreements": int(analysis["decision_agreement"].sum()),
            "decision_disagreements": int((~analysis["decision_agreement"]).sum()),
            "both_keep": len(both_keep),
            "both_exclude": int(
                (analysis["inclusion_decision_martin"].eq("exclude")
                 & analysis["inclusion_decision_dominik"].eq("exclude")).sum()
            ),
        },
        "candidate_validity": validity,
        "intercoder_reliability": intercoder,
        "dual_empty": {
            "coding_mode": "joint author audit; not an independent inter-rater sample",
            "population_units": manifest["dual_empty_population"],
            "sample_units": len(dual),
            "excluded_untranslated_units": dual.loc[
                dual["exclude_untranslated"], "empty_case_id"
            ].tolist(),
            "analyzable_units": len(dual_analysis),
            "missed_units": int(missed.sum()),
            "missed_unit_rate": float(missed.mean()),
            "wilson_95": wilson(int(missed.sum()), len(dual_analysis)),
            "supplement_claims": len(supplements),
            "supplement_case_ids": sorted(supplements["empty_case_id"].unique().tolist()),
        },
        "interpretation_boundary": {
            "candidate_consensus_available": False,
            "reportable_now": "reviewer-specific validity, pre-adjudication midpoint, uncertainty bounds and intercoder metrics",
            "not_reportable_until_human_adjudication": "a single final consensus validity estimate and provider-to-consensus agreement",
        },
    }

    require(result["sample"]["decision_agreements"] == 228, "inclusion agreements")
    require(result["sample"]["decision_disagreements"] == 136, "inclusion disagreements")
    require(abs(validity["martin"]["stratified"]["estimate"] - 0.7855858699550238) < 1e-12, "Martin estimate")
    require(abs(validity["dominik"]["stratified"]["estimate"] - 0.7606658603384752) < 1e-12, "Dominik estimate")
    require(abs(intercoder["inclusion_decision"]["gwet_ac1_nominal"] - 0.4260272701975698) < 1e-12, "Gwet AC1")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(
        "human validation: 365 sampled, 364 analyzable, "
        "228 inclusion agreements, 136 disagreements, 1/31 dual-empty miss"
    )


if __name__ == "__main__":
    main()
