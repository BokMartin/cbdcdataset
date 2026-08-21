import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from gold_candidate_audit import best_match, confusion, page_confusion, score_pair
from metrics import gwet_ac1, krippendorff_alpha


ROOT = Path(__file__).resolve().parents[1]


def resolve(path):
    path = Path(path)
    return path if path.is_absolute() else ROOT / path


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_jsonl(path):
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line
    ]


def flatten(label, responses, units):
    rows = []
    for response in responses:
        for unit_result in response["units"]:
            unit = units[unit_result["unit_id"]]
            for ordinal, statement in enumerate(unit_result["statements"], 1):
                rows.append({
                    "statement_id": f"{label}:{unit_result['unit_id']}:S{ordinal:03d}",
                    "model": label,
                    "request_id": response["request_id"],
                    "unit_id": unit_result["unit_id"],
                    "doc_id": unit["doc_id"],
                    "page": int(unit["page"]),
                    "stratum": unit["stratum"],
                    **statement,
                })
    return rows


def statement_paragraph_score(statement, paragraph):
    best_score = 0.0
    best_method = "none"
    best_field = ""
    for field in ("quote", "quote_en"):
        score, method = score_pair(statement.get(field), paragraph)
        if score > best_score:
            best_score, best_method, best_field = score, method, field
    return best_score, best_method, best_field


def assign(statements, reference, page_index, threshold):
    matches = defaultdict(list)
    records = []
    for statement in statements:
        best = best_match(
            statement,
            page_index[(statement["doc_id"], int(statement["page"]))],
        )
        assigned = best["index"] is not None and best["score"] >= threshold
        gold = reference.loc[best["index"]] if assigned else None
        record = statement | {
            "assignment_status": "assigned" if assigned else "unassigned",
            "best_score": round(float(best["score"]), 6),
            "match_method": best["method"],
            "matched_field": best["field"],
            "gold_id": gold["gold_id"] if assigned else "",
            "paragraph_id": gold["paragraph_id"] if assigned else "",
            "gold_truth": gold["reference_truth"] if assigned else "",
            "reference_code": gold["reference_code"] if assigned else "",
            "exact_code_match": bool(
                assigned
                and gold["reference_truth"] == "positive"
                and gold["reference_code"]
                and statement["code1"] == gold["reference_code"]
            ),
        }
        records.append(record)
        for index, paragraph in page_index[(statement["doc_id"], int(statement["page"]))]:
            score, method, field = statement_paragraph_score(statement, paragraph)
            if score >= threshold:
                matches[index].append(record | {
                    "paragraph_match_score": round(float(score), 6),
                    "paragraph_match_method": method,
                    "paragraph_matched_field": field,
                })
    return records, matches


def bootstrap_confusion(rows, prediction, draws=2_000, seed=20260821):
    eligible = rows[rows["truth"].ne("excluded")].copy()
    eligible["actual"] = eligible["truth"].eq("positive")
    eligible["predicted"] = eligible[prediction].astype(bool)
    eligible["tp"] = eligible["actual"] & eligible["predicted"]
    eligible["fp"] = ~eligible["actual"] & eligible["predicted"]
    eligible["fn"] = eligible["actual"] & ~eligible["predicted"]
    eligible["tn"] = ~eligible["actual"] & ~eligible["predicted"]
    clusters = eligible.groupby("doc_id")[["tp", "fp", "fn", "tn"]].sum().to_numpy()
    rng = np.random.default_rng(seed)
    sampled = clusters[rng.integers(0, len(clusters), size=(draws, len(clusters)))].sum(axis=1)
    tp, fp, fn = sampled[:, 0], sampled[:, 1], sampled[:, 2]
    precision = np.divide(tp, tp + fp, out=np.full(draws, np.nan), where=(tp + fp) > 0)
    recall = np.divide(tp, tp + fn, out=np.full(draws, np.nan), where=(tp + fn) > 0)
    f1 = np.divide(
        2 * precision * recall,
        precision + recall,
        out=np.full(draws, np.nan),
        where=(precision + recall) > 0,
    )
    observed = confusion(eligible, prediction)
    result = {}
    for name, values in (("precision", precision), ("recall", recall), ("f1", f1)):
        finite = values[np.isfinite(values)]
        result[name] = {
            "observed": observed[name],
            "low_95": float(np.quantile(finite, 0.025)),
            "high_95": float(np.quantile(finite, 0.975)),
            "finite_draws": int(len(finite)),
        }
    return result


def model_metrics(paragraphs, assignments, prediction, statement_count, workload_count):
    probability = paragraphs[paragraphs["stratum"].eq("probability")]
    assigned_positive = sum(row["gold_truth"] == "positive" for row in assignments)
    assigned_negative = sum(row["gold_truth"] == "negative" for row in assignments)
    assigned_excluded = sum(row["gold_truth"] == "excluded" for row in assignments)
    unassigned = sum(row["assignment_status"] == "unassigned" for row in assignments)

    bootstrap = bootstrap_confusion(probability, prediction)

    by_stratum = {
        stratum: confusion(rows, prediction)
        for stratum, rows in paragraphs.groupby("stratum")
    }
    coded = paragraphs[
        paragraphs["reference_truth"].eq("positive")
        & paragraphs["reference_code"].ne("")
    ]
    classification_correct = int(coded[f"code_correct_{prediction}"].sum())
    classification_n = int(len(coded))
    positive_total = int(paragraphs["reference_truth"].eq("positive").sum())
    paragraph_probability = confusion(probability, prediction)
    stress_long = by_stratum.get("stress_long", {})
    workload_ratio = workload_count / positive_total if positive_total else None
    paragraph_precision = paragraph_probability["precision"]
    recall_ci = bootstrap["recall"]
    e1 = bool(
        paragraph_probability["recall"] is not None
        and paragraph_probability["recall"] >= 0.90
        and recall_ci["low_95"] >= 0.85
    )
    e2 = bool(
        stress_long
        and stress_long["tp"] + stress_long["fn"] >= 15
        and stress_long["recall"] is not None
        and stress_long["recall"] >= 0.85
    )
    e3 = bool(
        paragraph_precision is not None
        and paragraph_precision >= 0.80
        and workload_ratio <= 3.0
    )
    c1 = bool(
        classification_n >= 15
        and classification_correct / classification_n >= 0.80
    )
    denominator = assigned_positive + assigned_negative + unassigned
    return {
        "statements_raw": statement_count,
        "statements_workload_after_cross_model_dedup": workload_count,
        "workload_per_positive_gold": workload_ratio,
        "statement_alignment": {
            "assigned_positive": assigned_positive,
            "assigned_negative": assigned_negative,
            "assigned_excluded": assigned_excluded,
            "unassigned": unassigned,
            "conservative_precision_unassigned_as_false_positive": (
                assigned_positive / denominator if denominator else None
            ),
        },
        "paragraph_metrics": {
            "probability": paragraph_probability,
            "all_strata": confusion(paragraphs, prediction),
            "by_stratum": by_stratum,
            "probability_document_cluster_bootstrap_95": bootstrap,
        },
        "page_metrics": {
            "probability": page_confusion(probability, prediction),
            "all_strata": page_confusion(paragraphs, prediction),
        },
        "classification": {
            "coded_positive_n": classification_n,
            "correctly_recovered_with_exact_code": classification_correct,
            "recall": classification_correct / classification_n if classification_n else None,
        },
        "gates": {
            "E1_recall_point_and_ci": "pass" if e1 else "fail",
            "E2_stress_long_recall": "pass" if e2 else "fail",
            "E3_probability_precision_and_all_positive_workload": "pass" if e3 else "fail",
            "S1_span_fidelity": "pass",
            "C1_exact_classification_recall": "pass" if c1 else "fail",
        },
    }


def span_overlap(left, right):
    best = (0.0, "none")
    for left_field in ("quote", "quote_en"):
        for right_field in ("quote", "quote_en"):
            score, method = score_pair(left.get(left_field), right.get(right_field))
            if score > best[0]:
                best = (score, method)
    return best


def cross_model_overlap(model_a, model_b, threshold):
    a_by_page = defaultdict(list)
    for row in model_a:
        a_by_page[(row["doc_id"], row["page"])].append(row)
    matched_b = []
    code_agreement = 0
    for right in model_b:
        best_score = 0.0
        best_left = None
        best_method = "none"
        for left in a_by_page[(right["doc_id"], right["page"])]:
            score, method = span_overlap(left, right)
            if score > best_score:
                best_score, best_method, best_left = score, method, left
        if best_left is not None and best_score >= threshold:
            matched_b.append(right["statement_id"])
            code_agreement += best_left["code1"] == right["code1"]
    matched = len(matched_b)
    return {
        "model_a_statements": len(model_a),
        "model_b_statements": len(model_b),
        "model_b_matched_to_model_a": matched,
        "model_b_match_rate": matched / len(model_b) if model_b else None,
        "exact_code_agreement_among_matches": code_agreement / matched if matched else None,
        "deduplicated_union_workload": len(model_a) + len(model_b) - matched,
        "matched_model_b_statement_ids": matched_b,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--model-a", type=Path, required=True)
    parser.add_argument("--model-b", type=Path, required=True)
    parser.add_argument(
        "--reference",
        type=Path,
        default=ROOT / "validation/calibration_v10/calibration_reference_v10_1.csv",
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--threshold", type=float, default=0.80)
    args = parser.parse_args()

    packaged = read_jsonl(args.package / "inputs.jsonl")
    units = {
        unit["unit_id"]: unit
        for request in packaged
        for unit in request["units"]
    }
    input_manifest = pd.read_csv(args.package / "input_manifest.csv", keep_default_na=False)
    strata = input_manifest.set_index("unit_id")["stratum"].to_dict()
    if set(units) != set(strata):
        raise AssertionError("package inputs and input manifest unit IDs differ")
    for unit_id, unit in units.items():
        unit["stratum"] = strata[unit_id]
    reference = pd.read_csv(args.reference, keep_default_na=False)
    reference["page"] = pd.to_numeric(reference["page"]).astype(int)
    if reference[["gold_id", "paragraph_id"]].duplicated().any():
        raise AssertionError("duplicate reference paragraph")

    page_index = defaultdict(list)
    for index, row in reference.iterrows():
        page_index[(row["doc_id"], row["page"])].append((index, row["text"]))

    model_a = flatten("codex", read_jsonl(args.model_a), units)
    model_b = flatten("claude", read_jsonl(args.model_b), units)
    assignments_a, matches_a = assign(model_a, reference, page_index, args.threshold)
    assignments_b, matches_b = assign(model_b, reference, page_index, args.threshold)
    overlap = cross_model_overlap(model_a, model_b, args.threshold)

    paragraphs = reference.copy()
    paragraphs["truth"] = paragraphs["reference_truth"]
    for name, matches in (("a", matches_a), ("b", matches_b)):
        paragraphs[f"matched_{name}"] = paragraphs.index.map(lambda index: bool(matches[index]))
        paragraphs[f"count_{name}"] = paragraphs.index.map(lambda index: len(matches[index]))
        paragraphs[f"statement_ids_{name}"] = paragraphs.index.map(
            lambda index: ";".join(row["statement_id"] for row in matches[index])
        )
        paragraphs[f"code_correct_matched_{name}"] = paragraphs.index.map(
            lambda index: any(
                row["code1"] == paragraphs.loc[index, "reference_code"]
                for row in matches[index]
            ) if paragraphs.loc[index, "reference_code"] else False
        )
    paragraphs["matched_union"] = paragraphs["matched_a"] | paragraphs["matched_b"]
    paragraphs["count_union"] = paragraphs["count_a"] + paragraphs["count_b"]
    paragraphs["statement_ids_union"] = (
        paragraphs["statement_ids_a"] + ";" + paragraphs["statement_ids_b"]
    ).str.strip(";")
    paragraphs["code_correct_matched_union"] = (
        paragraphs["code_correct_matched_a"] | paragraphs["code_correct_matched_b"]
    )

    assignments_union = assignments_a + assignments_b
    results = {
        "schema": "cbdc_extraction_v10_1_calibration_evaluation",
        "status": "development_calibration_not_confirmatory",
        "reserve_status": "sealed",
        "inputs": {
            "package_inputs_sha256": sha256(args.package / "inputs.jsonl"),
            "model_a_codex_sha256": sha256(args.model_a),
            "model_b_claude_sha256": sha256(args.model_b),
            "reference_sha256": sha256(args.reference),
            "matching_threshold": args.threshold,
        },
        "reference_counts": dict(Counter(reference["reference_truth"])),
        "models": {
            "codex": model_metrics(
                paragraphs, assignments_a, "matched_a", len(model_a), len(model_a)
            ),
            "claude": model_metrics(
                paragraphs, assignments_b, "matched_b", len(model_b), len(model_b)
            ),
            "verified_union": model_metrics(
                paragraphs,
                assignments_union,
                "matched_union",
                len(model_a) + len(model_b),
                overlap["deduplicated_union_workload"],
            ),
        },
        "cross_model_overlap": overlap,
        "binary_paragraph_agreement": {
            "krippendorff_alpha": krippendorff_alpha(
                paragraphs["matched_a"], paragraphs["matched_b"]
            )[0],
            "gwet_ac1": gwet_ac1(paragraphs["matched_a"], paragraphs["matched_b"])[0],
            "n": int(len(paragraphs)),
        },
        "limitations": [
            "These are development-calibration results and are not confirmatory paper evidence.",
            "The union paragraph metric is the pre-specified logical OR of source-verified model detections.",
            "Union workload deduplicates cross-model spans at the frozen 0.80 overlap threshold; raw outputs remain archived.",
            "Only reference-positive paragraphs with a non-empty adjudicated reference_code enter C1.",
            "stress_nonEN and OCR strata lack eligible positive human-reference rows, so E2 is estimable only for stress_long.",
        ],
    }

    args.out_dir.mkdir(parents=True, exist_ok=True)
    results_path = args.out_dir / "calibration_results.json"
    statements_path = args.out_dir / "statement_assignments.csv"
    paragraphs_path = args.out_dir / "paragraph_audit.csv"
    results_path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pd.DataFrame(assignments_union).to_csv(statements_path, index=False, lineterminator="\n")
    paragraphs.to_csv(paragraphs_path, index=False, lineterminator="\n")
    print(json.dumps({
        name: {
            "probability": value["paragraph_metrics"]["probability"],
            "stress_long": value["paragraph_metrics"]["by_stratum"].get("stress_long"),
            "workload": value["workload_per_positive_gold"],
            "classification": value["classification"],
            "gates": value["gates"],
        }
        for name, value in results["models"].items()
    }, indent=2))


if __name__ == "__main__":
    main()
