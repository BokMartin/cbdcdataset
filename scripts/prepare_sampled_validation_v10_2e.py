#!/usr/bin/env python3
"""Freeze a blinded probability sample for v10.2e human validation."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path


SEED = "cbdc-v10.2e-sampled-validation-20260825-v1"
CONFIDENCE_Z = 1.96
WORST_CASE_P = 0.5
TARGET_MARGIN = 0.05


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_hash(*values: object) -> str:
    return hashlib.sha256("|".join(map(str, values)).encode("utf-8")).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def required_sample_size(population: int) -> int:
    numerator = population * CONFIDENCE_Z**2 * WORST_CASE_P * (1 - WORST_CASE_P)
    denominator = TARGET_MARGIN**2 * (population - 1) + CONFIDENCE_Z**2 * WORST_CASE_P * (1 - WORST_CASE_P)
    return math.ceil(numerator / denominator)


def achieved_margin(population: int, sample: int) -> float:
    finite_population = (population - sample) / (population - 1)
    return CONFIDENCE_Z * math.sqrt(WORST_CASE_P * (1 - WORST_CASE_P) / sample * finite_population)


def hamilton_with_minimum_one(strata: dict[str, list[dict]], target: int) -> dict[str, int]:
    population = sum(len(rows) for rows in strata.values())
    quotas = {key: target * len(rows) / population for key, rows in strata.items()}
    allocation = {key: min(len(rows), max(1, math.floor(quotas[key]))) for key, rows in strata.items()}
    while sum(allocation.values()) < target:
        eligible = [key for key, rows in strata.items() if allocation[key] < len(rows)]
        key = max(eligible, key=lambda value: (quotas[value] - allocation[value], len(strata[value]), value))
        allocation[key] += 1
    while sum(allocation.values()) > target:
        eligible = [key for key in strata if allocation[key] > 1]
        key = min(eligible, key=lambda value: (quotas[value] - allocation[value], -len(strata[value]), value))
        allocation[key] -= 1
    return allocation


def merge_blind_candidates(payloads: list[dict]) -> tuple[dict[str, dict], dict[str, dict]]:
    candidates: dict[str, dict] = {}
    contexts: dict[str, dict] = {}
    for payload in payloads:
        for row in payload["candidates"]:
            candidate_id = row["candidate_id"]
            if candidate_id in candidates and candidates[candidate_id] != row:
                raise ValueError(f"candidate payload mismatch: {candidate_id}")
            candidates[candidate_id] = row
        for row in payload["contexts"]:
            unit_id = row["context_unit_id"]
            if unit_id in contexts and contexts[unit_id] != row:
                raise ValueError(f"context payload mismatch: {unit_id}")
            contexts[unit_id] = row
    return candidates, contexts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mapping", required=True, type=Path)
    parser.add_argument("--payload-martin", required=True, type=Path)
    parser.add_argument("--payload-dominik", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()

    mapping = read_csv(args.mapping)
    martin = read_json(args.payload_martin)
    dominik = read_json(args.payload_dominik)
    candidates, contexts = merge_blind_candidates([martin, dominik])
    mapping_by_id = {row["candidate_id"]: row for row in mapping}
    if set(mapping_by_id) != set(candidates):
        raise ValueError("machine mapping and blind candidate union differ")

    population = len(mapping)
    target = required_sample_size(population)
    strata: dict[str, list[dict]] = defaultdict(list)
    for row in mapping:
        stratum = f'{row["language"]}|{row["origin_type"]}'
        strata[stratum].append(row)
    allocation = hamilton_with_minimum_one(strata, target)

    selected_mapping: list[dict] = []
    for stratum, rows in sorted(strata.items()):
        ranked = sorted(rows, key=lambda row: (stable_hash(SEED, "select", row["candidate_id"]), row["candidate_id"]))
        n_h = allocation[stratum]
        N_h = len(rows)
        for rank, row in enumerate(ranked[:n_h], 1):
            selected_mapping.append({
                "sample_case_id": "",
                "sample_stratum": stratum,
                "stratum_population": N_h,
                "stratum_sample": n_h,
                "inclusion_probability": n_h / N_h,
                "survey_weight": N_h / n_h,
                "selection_rank_within_stratum": rank,
                "selection_hash": stable_hash(SEED, "select", row["candidate_id"]),
                **row,
            })

    selected_mapping.sort(key=lambda row: (stable_hash(SEED, "display", row["candidate_id"]), row["candidate_id"]))
    for index, row in enumerate(selected_mapping, 1):
        row["sample_case_id"] = f"SV-{index:04d}"
    if len(selected_mapping) != target:
        raise AssertionError((len(selected_mapping), target))

    selected_candidates = []
    for machine in selected_mapping:
        blind = dict(candidates[machine["candidate_id"]])
        blind["candidate_id"] = machine["sample_case_id"]
        # Alternate-provider fields disclose overlap membership and can anchor reviewers.
        blind["alternate_span"] = ""
        blind["alternate_translation"] = ""
        blind["alternate_context_unit_id"] = ""
        selected_candidates.append(blind)

    martin_empty = martin["dual_empty_units"]
    dominik_empty = dominik["dual_empty_units"]
    if [row["unit_id"] for row in martin_empty] != [row["unit_id"] for row in dominik_empty]:
        raise ValueError("reviewer dual-empty samples differ")
    dual_empty = martin_empty

    context_ids = {
        value
        for row in selected_candidates
        for value in (row.get("context_unit_id", ""), row.get("alternate_context_unit_id", ""))
        if value
    } | {row["unit_id"] for row in dual_empty}
    selected_contexts = [contexts[unit_id] for unit_id in sorted(context_ids)]

    render_files = sorted({
        str(row.get("render_file", "")).replace("\\", "/")
        for row in [*selected_candidates, *dual_empty, *selected_contexts]
        if str(row.get("render_file", "")).strip()
    })

    sample_fraction = target / population
    margin = achieved_margin(population, target)
    common = {
        "schema": "cbdc-v10.2e-blind-sampled-validation-workbook-v1",
        "blinding": "provider identity, provider code, origin type, and sampling stratum absent",
        "sampling": {
            "population_candidates": population,
            "sample_candidates": target,
            "sample_fraction": sample_fraction,
            "confidence_level": 0.95,
            "worst_case_margin": margin,
            "stratification": "language x provider-origin type; proportional Hamilton allocation with minimum one per nonempty stratum",
            "selection": "SHA-256 rank without replacement within stratum",
            "seed": SEED,
            "dual_empty_scope": "pre-frozen 10% sample of units where both providers returned zero candidates; estimates only dual-empty missed-claim yield, not production recall",
        },
        "candidates": selected_candidates,
        "dual_empty_units": dual_empty,
        "supplement_slots_per_unit": martin["supplement_slots_per_unit"],
        "contexts": selected_contexts,
        "codebook": martin["codebook"],
        "lists": martin["lists"],
    }
    for reviewer in ("Martin", "Dominik"):
        write_json(args.out_dir / f"payload_{reviewer.casefold()}.json", {"reviewer": reviewer, **common})

    write_csv(args.out_dir / "sample_machine_mapping.csv", selected_mapping)
    write_json(args.out_dir / "render_files.json", render_files)
    stratum_counts = []
    sample_by_stratum = Counter(row["sample_stratum"] for row in selected_mapping)
    for stratum in sorted(strata):
        language, origin_type = stratum.split("|", 1)
        stratum_counts.append({
            "language": language,
            "origin_type": origin_type,
            "population": len(strata[stratum]),
            "sample": sample_by_stratum[stratum],
            "inclusion_probability": sample_by_stratum[stratum] / len(strata[stratum]),
        })
    manifest = {
        "schema": "cbdc-v10.2e-sampled-human-validation-freeze-v1",
        "status": "frozen before human coding",
        "rationale": "sample size calculated for a two-sided 95% normal-approximation interval with worst-case proportion 0.5, 5 percentage-point target margin, and finite-population correction",
        "seed": SEED,
        "population_candidates": population,
        "sample_candidates": target,
        "sample_fraction": sample_fraction,
        "confidence_level": 0.95,
        "target_margin": TARGET_MARGIN,
        "achieved_worst_case_margin": margin,
        "sampled_documents": len({row["doc_id"] for row in selected_mapping}),
        "sampled_languages": dict(sorted(Counter(row["language"] for row in selected_mapping).items())),
        "dual_empty_population": 359,
        "dual_empty_sample": len(dual_empty),
        "dual_empty_fraction": len(dual_empty) / 359,
        "strata": stratum_counts,
        "estimands": {
            "candidate_acceptance": "inverse-probability weighted human keep rate in the 6,949-candidate union",
            "provider_candidate_validity": "inverse-probability weighted keep rate among sampled candidates attributable to each provider after unblinding",
            "code_agreement": "exact provider-to-consensus code agreement conditional on human keep",
            "intercoder": "pre-consensus percent agreement, Krippendorff alpha, and Gwet AC1 on the common sample",
            "dual_empty": "proportion of sampled both-empty units containing at least one missed eligible claim",
            "production_recall": "not estimable from this claim sample; report frozen calibration recall separately",
        },
        "hashes": {
            "candidate_mapping_input": sha256(args.mapping),
            "payload_martin_input": sha256(args.payload_martin),
            "payload_dominik_input": sha256(args.payload_dominik),
            "sample_machine_mapping": sha256(args.out_dir / "sample_machine_mapping.csv"),
            "payload_martin": sha256(args.out_dir / "payload_martin.json"),
            "payload_dominik": sha256(args.out_dir / "payload_dominik.json"),
            "render_files": sha256(args.out_dir / "render_files.json"),
        },
    }
    write_json(args.out_dir / "SAMPLED_VALIDATION_FREEZE_MANIFEST.json", manifest)
    print(json.dumps({
        "population": population,
        "sample": target,
        "fraction": sample_fraction,
        "worst_case_margin": margin,
        "documents": manifest["sampled_documents"],
        "languages": manifest["sampled_languages"],
        "dual_empty": len(dual_empty),
        "renders": len(render_files),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
