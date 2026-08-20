import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
POSITIVE = {"ANO", "ANO-částečně"}
SKIP = {"", "skip_language"}


def resolve(path):
    path = Path(path)
    return path if path.is_absolute() else ROOT / path


def sha256(path, canonical_text=False):
    content = path.read_bytes()
    if canonical_text:
        content = content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(content).hexdigest()


def normalize(value):
    value = unicodedata.normalize("NFKC", str(value).casefold())
    return re.sub(r"[^\w]+", " ", value, flags=re.UNICODE).strip()


def score_pair(quote, paragraph):
    quote = str(quote).strip()
    paragraph = str(paragraph).strip()
    if not quote or not paragraph:
        return 0.0, "none"
    if quote == paragraph:
        return 1.0, "raw_equal"
    if quote in paragraph:
        return 1.0, "raw_contains"

    q_norm, p_norm = normalize(quote), normalize(paragraph)
    if min(len(q_norm), len(p_norm)) < 12:
        return 0.0, "none"
    if q_norm == p_norm:
        return 1.0, "normalized_equal"
    if q_norm in p_norm:
        return 1.0, "normalized_contains"
    if p_norm in q_norm:
        return 1.0, "normalized_container"

    q_tokens, p_tokens = q_norm.split(), p_norm.split()
    best_score, method = 0.0, "none"
    if min(len(q_tokens), len(p_tokens)) >= 4:
        match = SequenceMatcher(None, q_tokens, p_tokens, autojunk=False).find_longest_match()
        minimum = 4 if min(len(q_tokens), len(p_tokens)) <= 6 else 6
        if match.size >= minimum:
            best_score = max(match.size / len(q_tokens), match.size / len(p_tokens))
            method = "fuzzy_token"

    q_chars, p_chars = q_norm.replace(" ", ""), p_norm.replace(" ", "")
    if min(len(q_chars), len(p_chars)) >= 20:
        match = SequenceMatcher(None, q_chars, p_chars, autojunk=False).find_longest_match()
        if match.size >= 20:
            char_score = max(match.size / len(q_chars), match.size / len(p_chars))
            if char_score > best_score:
                best_score, method = char_score, "fuzzy_character"
    return best_score, method


def best_match(candidate, paragraphs):
    variants = [("quote", candidate["quote"]), ("quote_en", candidate["quote_en"])]
    best = {"index": None, "score": 0.0, "method": "none", "field": ""}
    for index, paragraph in paragraphs:
        for field, quote in variants:
            score, method = score_pair(quote, paragraph)
            if score > best["score"]:
                best = {"index": index, "score": score, "method": method, "field": field}
    return best


def truth(label):
    if label in POSITIVE:
        return "positive"
    if label in SKIP:
        return "excluded"
    return "negative"


def confusion(rows, prediction):
    eligible = rows[rows["truth"].ne("excluded")]
    actual = eligible["truth"].eq("positive")
    predicted = eligible[prediction].astype(bool)
    tp = int((actual & predicted).sum())
    fp = int((~actual & predicted).sum())
    fn = int((actual & ~predicted).sum())
    tn = int((~actual & ~predicted).sum())
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * precision * recall / (precision + recall) if precision and recall else 0.0
    return {
        "n": int(len(eligible)),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def page_confusion(rows, prediction):
    eligible = rows[rows["truth"].ne("excluded")].copy()
    pages = eligible.groupby(["doc_id", "page"], as_index=False).agg(
        actual_positive=("truth", lambda values: (values == "positive").any()),
        predicted_positive=(prediction, "any"),
    )
    actual, predicted = pages["actual_positive"], pages["predicted_positive"]
    tp = int((actual & predicted).sum())
    fp = int((~actual & predicted).sum())
    fn = int((actual & ~predicted).sum())
    tn = int((~actual & ~predicted).sum())
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * precision * recall / (precision + recall) if precision and recall else 0.0
    return {
        "n": int(len(pages)),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def candidate_summary(rows, kept_only=False):
    subset = rows[rows["v5_verdict"].eq("keep")] if kept_only else rows
    assigned = subset[subset["assignment_status"].eq("assigned")]
    methods = Counter(assigned["match_method"])
    return {
        "rows_on_gold_pages": int(len(subset)),
        "assigned_to_gold_paragraph": int(len(assigned)),
        "unassigned": int(len(subset) - len(assigned)),
        "assigned_positive": int(assigned["gold_truth"].eq("positive").sum()),
        "assigned_negative": int(assigned["gold_truth"].eq("negative").sum()),
        "assigned_excluded": int(assigned["gold_truth"].eq("excluded").sum()),
        "whole_paragraph_equal": int(methods["raw_equal"] + methods["normalized_equal"]),
        "span_containment_matches": int(sum(methods[name] for name in [
            "raw_equal", "normalized_equal", "raw_contains", "normalized_contains", "normalized_container",
        ])),
        "fuzzy_matches": int(methods["fuzzy_token"] + methods["fuzzy_character"]),
        "match_methods": dict(methods),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", default="data/candidates.csv")
    parser.add_argument("--gold", default="validation/human_gold/gold_extraction_martin_v10f.csv")
    parser.add_argument("--out-json", default="results/gold_candidate_audit.json")
    parser.add_argument("--out-gold", default="validation/human_gold/gold_candidate_paragraph_audit.csv")
    parser.add_argument("--out-candidates", default="validation/human_gold/candidate_assignment_audit.csv")
    parser.add_argument("--threshold", type=float, default=0.80)
    args = parser.parse_args()

    candidate_path, gold_path = resolve(args.candidates), resolve(args.gold)
    candidates = pd.read_csv(candidate_path, keep_default_na=False)
    gold = pd.read_csv(gold_path, keep_default_na=False)
    gold["page"] = pd.to_numeric(gold["page"]).astype(int)
    candidates["page"] = pd.to_numeric(candidates["page"]).astype(int)
    if gold[["gold_id", "paragraph_id"]].duplicated().any():
        raise AssertionError("duplicate gold paragraph id")
    if candidates["seg_id"].duplicated().any():
        raise AssertionError("duplicate candidate seg_id")

    page_index = defaultdict(list)
    for index, row in gold.iterrows():
        page_index[(row["doc_id"], row["page"])].append((index, row["text"]))
    sampled = candidates[
        candidates.apply(lambda row: (row["doc_id"], row["page"]) in page_index, axis=1)
    ].copy()

    assignments = []
    assigned_all, assigned_kept = defaultdict(list), defaultdict(list)
    for _, candidate in sampled.iterrows():
        best = best_match(candidate, page_index[(candidate["doc_id"], candidate["page"])])
        assigned = best["index"] is not None and best["score"] >= args.threshold
        gold_row = gold.loc[best["index"]] if assigned else None
        record = {
            "seg_id": candidate["seg_id"],
            "doc_id": candidate["doc_id"],
            "page": int(candidate["page"]),
            "jur": candidate["jur"],
            "v5_verdict": candidate["v5_verdict"],
            "code_v5r": candidate["code_v5r"],
            "quote": candidate["quote"],
            "quote_en": candidate["quote_en"],
            "assignment_status": "assigned" if assigned else "unassigned",
            "best_score": round(float(best["score"]), 6),
            "match_method": best["method"],
            "matched_field": best["field"],
            "gold_id": gold_row["gold_id"] if assigned else "",
            "paragraph_id": gold_row["paragraph_id"] if assigned else "",
            "gold_label": gold_row["label"] if assigned else "",
            "gold_truth": truth(gold_row["label"]) if assigned else "",
            "stratum": gold_row["stratum"] if assigned else "",
        }
        assignments.append(record)
        if assigned:
            assigned_all[best["index"]].append(record)
            if candidate["v5_verdict"] == "keep":
                assigned_kept[best["index"]].append(record)

    candidate_audit = pd.DataFrame(assignments)
    paragraph_audit = gold.copy()
    paragraph_audit["truth"] = paragraph_audit["label"].map(truth)
    paragraph_audit["partial_note_missing"] = (
        paragraph_audit["label"].eq("ANO-částečně") & paragraph_audit["note"].eq("")
    )
    paragraph_audit["matched_all"] = paragraph_audit.index.map(lambda index: bool(assigned_all[index]))
    paragraph_audit["matched_kept"] = paragraph_audit.index.map(lambda index: bool(assigned_kept[index]))
    paragraph_audit["matching_all_count"] = paragraph_audit.index.map(lambda index: len(assigned_all[index]))
    paragraph_audit["matching_kept_count"] = paragraph_audit.index.map(lambda index: len(assigned_kept[index]))
    paragraph_audit["matching_all_seg_ids"] = paragraph_audit.index.map(
        lambda index: ";".join(record["seg_id"] for record in assigned_all[index])
    )
    paragraph_audit["matching_kept_seg_ids"] = paragraph_audit.index.map(
        lambda index: ";".join(record["seg_id"] for record in assigned_kept[index])
    )
    paragraph_audit["best_kept_score"] = paragraph_audit.index.map(
        lambda index: max((record["best_score"] for record in assigned_kept[index]), default=0.0)
    )
    paragraph_audit["best_kept_seg_id"] = paragraph_audit.index.map(
        lambda index: max(assigned_kept[index], key=lambda record: record["best_score"])["seg_id"]
        if assigned_kept[index] else ""
    )
    paragraph_audit["outcome_all"] = paragraph_audit.apply(
        lambda row: "excluded" if row["truth"] == "excluded" else
        ("TP" if row["truth"] == "positive" and row["matched_all"] else
         "FN" if row["truth"] == "positive" else
         "FP" if row["matched_all"] else "TN"), axis=1
    )
    paragraph_audit["outcome_kept"] = paragraph_audit.apply(
        lambda row: "excluded" if row["truth"] == "excluded" else
        ("TP" if row["truth"] == "positive" and row["matched_kept"] else
         "FN" if row["truth"] == "positive" else
         "FP" if row["matched_kept"] else "TN"), axis=1
    )

    probability = paragraph_audit[paragraph_audit["stratum"].eq("probability")]
    unmarked_count = int(gold["label"].eq("").sum())
    partial_without_note = int((gold["label"].eq("ANO-částečně") & gold["note"].eq("")).sum())
    limitations = []
    if unmarked_count:
        limitations.append(f"Gold has {unmarked_count} unresolved labels.")
    else:
        limitations.append("All 351 gold paragraphs are labelled; the artifact is not yet frozen.")
    if partial_without_note:
        limitations.append(
            f"{partial_without_note} partial-positive rows still lack the phrase note required for phrase-level verification."
        )
    limitations.extend([
        "Metrics cover only sampled pages present in the human-gold workbook, not the full corpus.",
        "Three stress_ocr_zerotext pages in the workbook differ from validation/sample.csv and are excluded as skip_language.",
        "Second independent LLM extraction and the human second-coder decision remain pending.",
    ])
    summary = {
        "schema": "gold_candidate_audit_v1",
        "status": "diagnostic_gold_unfrozen",
        "inputs": {
            "candidates": str(candidate_path.relative_to(ROOT)) if candidate_path.is_relative_to(ROOT) else str(candidate_path),
            "candidates_sha256": sha256(candidate_path),
            "candidates_canonical_lf_sha256": sha256(candidate_path, canonical_text=True),
            "gold": str(gold_path.relative_to(ROOT)) if gold_path.is_relative_to(ROOT) else str(gold_path),
            "gold_sha256": sha256(gold_path, canonical_text=True),
        },
        "matching": {
            "unit": "candidate quote to one human paragraph on the same doc_id and page",
            "threshold": args.threshold,
            "methods": [
                "raw_equal", "normalized_equal", "raw_contains", "normalized_contains",
                "normalized_container", "fuzzy_token", "fuzzy_character",
            ],
            "fuzzy_rule": "longest contiguous span covers >=80% of candidate or paragraph; minimum 4-6 tokens or 20 characters",
        },
        "paragraph_metrics": {
            "probability_all_candidates": confusion(probability, "matched_all"),
            "probability_kept_candidates": confusion(probability, "matched_kept"),
            "all_strata_all_candidates": confusion(paragraph_audit, "matched_all"),
            "all_strata_kept_candidates": confusion(paragraph_audit, "matched_kept"),
        },
        "page_metrics": {
            "probability_all_candidates": page_confusion(probability, "matched_all"),
            "probability_kept_candidates": page_confusion(probability, "matched_kept"),
            "all_strata_all_candidates": page_confusion(paragraph_audit, "matched_all"),
            "all_strata_kept_candidates": page_confusion(paragraph_audit, "matched_kept"),
        },
        "candidate_alignment": {
            "all_candidates": candidate_summary(candidate_audit),
            "kept_candidates": candidate_summary(candidate_audit, kept_only=True),
        },
        "positive_coverage": {
            "probability_ANO_kept": {
                "matched": int((probability["label"].eq("ANO") & probability["matched_kept"]).sum()),
                "total": int(probability["label"].eq("ANO").sum()),
            },
            "probability_partial_kept": {
                "matched": int((probability["label"].eq("ANO-částečně") & probability["matched_kept"]).sum()),
                "total": int(probability["label"].eq("ANO-částečně").sum()),
                "missing_phrase_notes": int((probability["label"].eq("ANO-částečně") & probability["note"].eq("")).sum()),
            },
        },
        "limitations": limitations,
    }

    out_json, out_gold, out_candidates = map(resolve, [args.out_json, args.out_gold, args.out_candidates])
    for path in [out_json, out_gold, out_candidates]:
        path.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    paragraph_audit.to_csv(out_gold, index=False, lineterminator="\n")
    candidate_audit.to_csv(out_candidates, index=False, lineterminator="\n")
    primary = summary["paragraph_metrics"]["probability_kept_candidates"]
    print(
        "gold candidate audit: diagnostic; "
        f"probability kept TP={primary['tp']} FP={primary['fp']} "
        f"FN={primary['fn']} TN={primary['tn']} "
        f"precision={primary['precision']:.3f} recall={primary['recall']:.3f}"
    )


if __name__ == "__main__":
    main()
