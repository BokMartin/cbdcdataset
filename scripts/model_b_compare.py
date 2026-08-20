import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import pandas as pd

from gold_candidate_audit import best_match, confusion, page_confusion, score_pair, truth
from metrics import cluster_bootstrap_ci
from spans import verify_span


ROOT = Path(__file__).resolve().parents[1]


def resolve(path):
    path = Path(path)
    return path if path.is_absolute() else ROOT / path


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_jsonl(path):
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def pair_score(left, right):
    best = (0.0, "none", "", "")
    for left_field in ("quote", "quote_en"):
        for right_field in ("quote", "quote_en"):
            score, method = score_pair(left[left_field], right[right_field])
            if score > best[0]:
                best = (score, method, left_field, right_field)
    return best


def closest(statement, rows):
    best = {"index": None, "score": 0.0, "method": "none", "left_field": "", "right_field": ""}
    for index, row in rows:
        score, method, left_field, right_field = pair_score(statement, row)
        if score > best["score"]:
            best = {
                "index": index,
                "score": score,
                "method": method,
                "left_field": left_field,
                "right_field": right_field,
            }
    return best


def metrics_by_stratum(paragraphs, prediction):
    result = {"all": confusion(paragraphs, prediction)}
    for stratum, rows in paragraphs.groupby("stratum"):
        result[stratum] = confusion(rows, prediction)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--responses", default="validation/model_b_pilot/responses.jsonl")
    parser.add_argument("--metadata", default="validation/model_b_pilot/run_metadata.json")
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--threshold", type=float, default=0.80)
    parser.add_argument("--out-json", default="results/model_b_pilot.json")
    parser.add_argument(
        "--out-statements", default="validation/model_b_pilot/statement_assignments.csv"
    )
    parser.add_argument(
        "--out-paragraphs", default="validation/model_b_pilot/paragraph_audit.csv"
    )
    args = parser.parse_args()

    responses_path = resolve(args.responses)
    metadata_path = resolve(args.metadata)
    package = args.package.resolve()
    audit = pd.read_csv(ROOT / "validation/model_b_pilot/audit_manifest.csv", keep_default_na=False)
    gold = pd.read_csv(
        ROOT / "validation/human_gold/gold_extraction_martin_v10f.csv", keep_default_na=False
    )
    candidates = pd.read_csv(ROOT / "data/candidates.csv", keep_default_na=False)
    gold["page"] = pd.to_numeric(gold["page"]).astype(int)
    candidates["page"] = pd.to_numeric(candidates["page"]).astype(int)
    audit["page"] = pd.to_numeric(audit["page"]).astype(int)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    response_rows = read_jsonl(responses_path)
    if [r["input_id"] for r in response_rows] != audit["input_id"].tolist():
        raise AssertionError("responses do not match the frozen audit manifest")

    audit_by_id = audit.set_index("input_id").to_dict("index")
    prompt_template = (ROOT / "validation/model_b_pilot/prompt_v9.txt").read_text(encoding="utf-8")
    source_text = {}
    for input_id, source in audit_by_id.items():
        if source["status"] != "ready":
            continue
        prompt = (package / source["prompt_file"]).read_text(encoding="utf-8")
        prefix = (
            prompt_template.replace("<<DOC_ID>>", source["doc_id"])
            .replace("<<PAGE>>", str(source["page"]))
        )
        if not prompt.startswith(prefix):
            raise AssertionError(f"prompt prefix mismatch: {input_id}")
        source_text[input_id] = prompt[len(prefix):]
    statements = []
    for record in response_rows:
        source = audit_by_id[record["input_id"]]
        expected_status = "ok" if source["status"] == "ready" else source["status"]
        if record["status"] != expected_status:
            raise AssertionError(f"status mismatch: {record['input_id']}")
        for number, item in enumerate(record["response"] or [], 1):
            span = verify_span(item["quote"], source_text[record["input_id"]])
            statements.append(
                {
                    "statement_id": f"{record['input_id']}-S{number:03d}",
                    "input_id": record["input_id"],
                    "doc_id": source["doc_id"],
                    "page": source["page"],
                    "stratum": source["stratum"],
                    **item,
                    "span_status": span["status"],
                    "span_start": span["start"],
                    "span_end": span["end"],
                    "span_ambiguous": span["ambiguous"],
                }
            )
    model_b = pd.DataFrame(statements)
    if model_b.empty:
        model_b = pd.DataFrame(columns=[
            "statement_id", "input_id", "doc_id", "page", "stratum",
            "quote", "quote_en", "code1", "odr", "privacy_direction",
            "privacy_relation", "strength",
        ])

    page_index = defaultdict(list)
    for index, row in gold.iterrows():
        page_index[(row["doc_id"], row["page"])].append((index, row["text"]))
    gold_matches = defaultdict(list)
    statement_records = []
    for _, statement in model_b.iterrows():
        best = best_match(statement, page_index[(statement["doc_id"], statement["page"])])
        assigned = best["index"] is not None and best["score"] >= args.threshold
        gold_row = gold.loc[best["index"]] if assigned else None
        record = statement.to_dict() | {
            "gold_assignment_status": "assigned" if assigned else "unassigned",
            "gold_best_score": round(float(best["score"]), 6),
            "gold_match_method": best["method"],
            "gold_matched_field": best["field"],
            "gold_id": gold_row["gold_id"] if assigned else "",
            "paragraph_id": gold_row["paragraph_id"] if assigned else "",
            "gold_label": gold_row["label"] if assigned else "",
            "gold_truth": truth(gold_row["label"]) if assigned else "",
        }
        statement_records.append(record)
        if assigned:
            gold_matches[best["index"]].append(record)

    paragraph_audit = gold.copy()
    paragraph_audit["truth"] = paragraph_audit["label"].map(truth)
    paragraph_audit["matched_model_b"] = paragraph_audit.index.map(
        lambda index: bool(gold_matches[index])
    )
    paragraph_audit["model_b_count"] = paragraph_audit.index.map(
        lambda index: len(gold_matches[index])
    )
    paragraph_audit["model_b_statement_ids"] = paragraph_audit.index.map(
        lambda index: ";".join(row["statement_id"] for row in gold_matches[index])
    )
    paragraph_audit["model_b_outcome"] = paragraph_audit.apply(
        lambda row: "excluded" if row["truth"] == "excluded" else
        ("TP" if row["truth"] == "positive" and row["matched_model_b"] else
         "FN" if row["truth"] == "positive" else
         "FP" if row["matched_model_b"] else "TN"),
        axis=1,
    )
    gold_by_statement = {row["statement_id"]: row for row in statement_records}

    sample_pages = set(zip(audit["doc_id"], audit["page"]))
    model_a = candidates[
        candidates.apply(lambda row: (row["doc_id"], row["page"]) in sample_pages, axis=1)
    ].copy()
    model_a_by_page = defaultdict(list)
    for index, row in model_a.iterrows():
        model_a_by_page[(row["doc_id"], row["page"])].append((index, row))
    model_b_by_page = defaultdict(list)
    for index, row in model_b.iterrows():
        model_b_by_page[(row["doc_id"], row["page"])].append((index, row))

    b_to_a = []
    exact_code_agreement = 0
    for _, statement in model_b.iterrows():
        best = closest(statement, model_a_by_page[(statement["doc_id"], statement["page"])])
        assigned = best["index"] is not None and best["score"] >= args.threshold
        matched = model_a.loc[best["index"]] if assigned else None
        if assigned:
            exact_code_agreement += statement["code1"] == matched["code1"]
        b_to_a.append(
            {
                **gold_by_statement[statement["statement_id"]],
                "model_a_assignment_status": "assigned" if assigned else "unassigned",
                "model_a_best_score": round(float(best["score"]), 6),
                "model_a_match_method": best["method"],
                "model_a_seg_id": matched["seg_id"] if assigned else "",
                "model_a_v5_verdict": matched["v5_verdict"] if assigned else "",
                "model_a_code1": matched["code1"] if assigned else "",
                "exact_code_agreement": bool(assigned and statement["code1"] == matched["code1"]),
            }
        )

    b_matched = sum(row["model_a_assignment_status"] == "assigned" for row in b_to_a)
    kept_a = model_a[model_a["v5_verdict"].eq("keep")]
    recovered_a = set()
    for index, statement in model_a.iterrows():
        best = closest(statement, model_b_by_page[(statement["doc_id"], statement["page"])])
        if best["index"] is not None and best["score"] >= args.threshold:
            recovered_a.add(index)
    recovered_a_kept = recovered_a & set(kept_a.index)
    probability = paragraph_audit[paragraph_audit["stratum"].eq("probability")]
    skipped_ids = set(audit.loc[audit["status"].eq("skipped_lt250"), "input_id"])
    skipped_pages = set(
        zip(
            audit.loc[audit["input_id"].isin(skipped_ids), "doc_id"],
            audit.loc[audit["input_id"].isin(skipped_ids), "page"],
        )
    )
    skipped_gold = paragraph_audit[
        paragraph_audit.apply(lambda row: (row["doc_id"], row["page"]) in skipped_pages, axis=1)
    ]
    assigned_positive = sum(row["gold_truth"] == "positive" for row in statement_records)
    assigned_negative = sum(row["gold_truth"] == "negative" for row in statement_records)
    assigned_excluded = sum(row["gold_truth"] == "excluded" for row in statement_records)
    unassigned = sum(row["gold_assignment_status"] == "unassigned" for row in statement_records)
    failed_spans = [
        row for row in statement_records if row["span_status"] in {"fuzzy_fail", "invalid_quote"}
    ]
    failed_spans_supported_by_gold = sum(
        row["gold_assignment_status"] == "assigned" for row in failed_spans
    )
    def gold_metric(rows, name):
        value = confusion(rows, "matched_model_b")[name]
        return float("nan") if value is None else value

    bootstrap = {}
    for metric in ("precision", "recall", "f1"):
        observed, low, high, finite = cluster_bootstrap_ci(
            probability,
            "doc_id",
            lambda rows, name=metric: gold_metric(rows, name),
            draws=2_000,
            seed=20260820,
        )
        bootstrap[metric] = {
            "observed": observed,
            "low_95": low,
            "high_95": high,
            "finite_draws": finite,
        }
    summary = {
        "schema": "model_b_v9_pilot_v1",
        "status": "diagnostic_gold_unfrozen",
        "inputs": {
            "responses_sha256": sha256(responses_path),
            "run_metadata_sha256": sha256(metadata_path),
            "audit_manifest_sha256": sha256(ROOT / "validation/model_b_pilot/audit_manifest.csv"),
            "input_package_sha256": metadata["input_package_sha256"],
            "matching_threshold": args.threshold,
        },
        "run": metadata,
        "extraction": {
            "sample_pages": int(len(audit)),
            "model_calls": int(audit["status"].eq("ready").sum()),
            "protocol_skips": int(audit["status"].eq("skipped_lt250").sum()),
            "statements": int(len(model_b)),
            "pages_with_statements": int(model_b[["doc_id", "page"]].drop_duplicates().shape[0]),
        },
        "span_fidelity": {
            "exact": int(model_b["span_status"].eq("exact").sum()),
            "normalized": int(model_b["span_status"].eq("normalized").sum()),
            "failed": int(model_b["span_status"].isin(["fuzzy_fail", "invalid_quote"]).sum()),
            "verified_rate": (
                float(model_b["span_status"].isin(["exact", "normalized"]).mean())
                if len(model_b) else None
            ),
            "strict_failures_supported_by_same_page_gold_text": failed_spans_supported_by_gold,
            "strict_failures_unresolved": len(failed_spans) - failed_spans_supported_by_gold,
            "source_or_same_page_gold_support_rate": (
                (len(model_b) - len(failed_spans) + failed_spans_supported_by_gold) / len(model_b)
                if len(model_b) else None
            ),
        },
        "statement_alignment": {
            "assigned_positive": assigned_positive,
            "assigned_negative": assigned_negative,
            "assigned_excluded": assigned_excluded,
            "unassigned": unassigned,
            "precision_among_assigned_nonexcluded": (
                assigned_positive / (assigned_positive + assigned_negative)
                if assigned_positive + assigned_negative else None
            ),
            "conservative_precision_unassigned_as_false_positive": (
                assigned_positive / (assigned_positive + assigned_negative + unassigned)
                if assigned_positive + assigned_negative + unassigned else None
            ),
        },
        "paragraph_metrics": {
            "probability": confusion(probability, "matched_model_b"),
            "probability_cluster_bootstrap_95": bootstrap,
            "all_strata": confusion(paragraph_audit, "matched_model_b"),
            "by_stratum": metrics_by_stratum(paragraph_audit, "matched_model_b"),
        },
        "page_metrics": {
            "probability": page_confusion(probability, "matched_model_b"),
            "all_strata": page_confusion(paragraph_audit, "matched_model_b"),
        },
        "protocol_skip_effect": {
            "pages": len(skipped_pages),
            "eligible_gold_paragraphs": int(skipped_gold["truth"].ne("excluded").sum()),
            "positive_gold_paragraphs": int(skipped_gold["truth"].eq("positive").sum()),
        },
        "cross_model_overlap": {
            "model_b_statements": int(len(model_b)),
            "model_b_matched_to_any_model_a": int(b_matched),
            "model_b_match_rate": b_matched / len(model_b) if len(model_b) else None,
            "model_a_statements_on_sample_pages": int(len(model_a)),
            "model_a_recovered_by_model_b": int(len(recovered_a)),
            "model_a_recovery_rate": len(recovered_a) / len(model_a) if len(model_a) else None,
            "kept_model_a_statements_on_sample_pages": int(len(kept_a)),
            "kept_model_a_recovered_by_model_b": int(len(recovered_a_kept)),
            "kept_model_a_recovery_rate": len(recovered_a_kept) / len(kept_a) if len(kept_a) else None,
            "exact_code_agreement_among_matches": (
                exact_code_agreement / b_matched if b_matched else None
            ),
        },
        "limitations": [
            "Human labels are complete but not frozen.",
            "The exact backend model identifier was not exposed if run_metadata says so.",
            "Cross-model overlap is span-based and is not a substitute for human adjudication.",
            "Same-page gold support for strict span failures is diagnostic only; it does not replace strict source-text fidelity.",
        ],
    }

    out_json = resolve(args.out_json)
    out_statements = resolve(args.out_statements)
    out_paragraphs = resolve(args.out_paragraphs)
    for path in (out_json, out_statements, out_paragraphs):
        path.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pd.DataFrame(b_to_a).to_csv(out_statements, index=False, lineterminator="\n")
    paragraph_audit.to_csv(out_paragraphs, index=False, lineterminator="\n")
    primary = summary["paragraph_metrics"]["probability"]
    print(
        f"Model B: statements={len(model_b)}; probability TP={primary['tp']} "
        f"FP={primary['fp']} FN={primary['fn']} TN={primary['tn']} "
        f"precision={primary['precision']} recall={primary['recall']}"
    )


if __name__ == "__main__":
    main()
