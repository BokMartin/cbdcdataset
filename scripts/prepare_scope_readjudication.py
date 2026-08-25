import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_jsonl(path):
    with Path(path).open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--paragraph-audit", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--codebook", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    audit = pd.read_csv(args.paragraph_audit, keep_default_na=False)
    audit["page"] = pd.to_numeric(audit["page"]).astype(int)
    disagreement = audit[
        (
            audit["reference_truth"].eq("positive")
            & ~audit["matched_union"].astype(str).str.casefold().eq("true")
        )
        | (
            audit["reference_truth"].eq("negative")
            & audit["matched_union"].astype(str).str.casefold().eq("true")
        )
    ].copy()
    disagreement["shuffle_key"] = disagreement.apply(
        lambda row: hashlib.sha256(
            f"v10.1-scope-readjudication|{row['gold_id']}|{row['paragraph_id']}".encode()
        ).hexdigest(),
        axis=1,
    )
    disagreement = disagreement.sort_values("shuffle_key").reset_index(drop=True)

    package_rows = read_jsonl(args.package / "inputs.jsonl")
    units = {
        (unit["doc_id"], int(unit["page"])): unit
        for request in package_rows
        for unit in request["units"]
    }
    cases = []
    context_ids = set()
    for index, row in disagreement.iterrows():
        unit = units[(row["doc_id"], int(row["page"]))]
        context_ids.add(unit["unit_id"])
        cases.append({
            "review_case_id": f"RA-{index + 1:03d}",
            "gold_id": row["gold_id"],
            "paragraph_id": row["paragraph_id"],
            "doc_id": row["doc_id"],
            "page": int(row["page"]),
            "stratum": row["stratum"],
            "language": row["language"],
            "paragraph_text": row["text"],
            "context_unit_id": unit["unit_id"],
        })

    contexts = []
    for request in package_rows:
        for unit in request["units"]:
            if unit["unit_id"] not in context_ids:
                continue
            contexts.append({
                "context_unit_id": unit["unit_id"],
                "doc_id": unit["doc_id"],
                "page": int(unit["page"]),
                "language": unit["language"],
                "source_mode": unit["source_mode"],
                "source_text": unit["source_text"],
                "render_file": unit.get("render_file") or "",
            })
    contexts.sort(key=lambda row: row["context_unit_id"])
    codebook = pd.read_csv(args.codebook, keep_default_na=False)
    codes = codebook.to_dict("records")
    payload = {
        "schema": "cbdc_v10_1_blind_scope_readjudication",
        "selection": "all reference/model-union paragraph disagreements; direction and model identity hidden",
        "cases": cases,
        "contexts": contexts,
        "codes": codes,
        "decision_lists": {
            "ternary": ["yes", "no", "unclear"],
            "eligible_claim_type": [
                "decision_or_commitment",
                "explicit_proposal_or_preference",
                "concrete_own_system_feature",
                "executed_own_pilot_finding",
                "supported_risk_tradeoff_requirement",
                "none",
                "unclear",
            ],
            "exclusion_trigger": [
                "none",
                "foreign_or_cited_research",
                "generic_context",
                "future_research_or_open_question",
                "stakeholder_or_consultant_not_adopted",
                "glossary_heading_or_list",
                "incomplete_fragment_or_ocr",
                "non_cbdc_or_off_scope",
                "other",
            ],
            "final_decision": ["keep", "exclude", "needs_context"],
            "confidence": ["high", "medium", "low"],
        },
        "hashes": {
            "paragraph_audit_sha256": sha256(args.paragraph_audit),
            "package_inputs_sha256": sha256(args.package / "inputs.jsonl"),
            "codebook_sha256": sha256(args.codebook),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "cases": len(cases),
        "contexts": len(contexts),
        "output": str(args.output),
        "sha256": sha256(args.output),
    }, indent=2))


if __name__ == "__main__":
    main()
