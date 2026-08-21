import argparse
import csv
import hashlib
import json
import shutil
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
CAL = ROOT / "validation" / "calibration_v10"
PARAGRAPHS = ROOT / "validation" / "model_b_pilot" / "paragraph_audit.csv"
STATEMENTS = ROOT / "validation" / "model_b_pilot" / "statement_assignments.csv"
CASES = CAL / "error_cases.csv"
SUMMARY = CAL / "audit_summary.json"
HUMAN_FIELDS = [
    "source_verdict", "primary_cause", "secondary_cause", "corrected_span",
    "target_code", "protocol_change_id", "adjudicator", "status", "notes",
]
FIELDS = [
    "case_id", "case_type", "doc_id", "page", "stratum", "language",
    "gold_id", "paragraph_id", "gold_label", "source_text",
    "model_statement_ids", "model_outputs", "match_score", "auto_signal",
] + HUMAN_FIELDS


def sha256(path):
    content = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(content).hexdigest()


def sha256_raw(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compact_outputs(rows):
    return "\n".join(
        f"{row.statement_id} | {row.code1} | {row.quote}"
        for row in rows.itertuples(index=False)
    )


def base_record(case_id, case_type, row):
    return {
        "case_id": case_id,
        "case_type": case_type,
        "doc_id": row.get("doc_id", ""),
        "page": row.get("page", ""),
        "stratum": row.get("stratum", ""),
        "language": row.get("language", ""),
        "gold_id": row.get("gold_id", ""),
        "paragraph_id": row.get("paragraph_id", ""),
        "gold_label": row.get("label", ""),
        "source_text": row.get("text", ""),
        "model_statement_ids": "",
        "model_outputs": "",
        "match_score": "",
        "auto_signal": "",
        **{field: "" for field in HUMAN_FIELDS},
    }


def build_cases():
    paragraphs = pd.read_csv(PARAGRAPHS, keep_default_na=False)
    statements = pd.read_csv(STATEMENTS, keep_default_na=False)
    by_page = {(doc, int(page)): group for (doc, page), group in statements.groupby(["doc_id", "page"])}
    by_id = statements.set_index("statement_id", drop=False)
    records = []

    fn = paragraphs[(paragraphs["stratum"] == "probability") & (paragraphs["model_b_outcome"] == "FN")]
    fn = fn.sort_values(["doc_id", "page", "gold_id", "paragraph_id"])
    for number, (_, row) in enumerate(fn.iterrows(), 1):
        record = base_record(f"FN-{number:03d}", "FN", row)
        page_rows = by_page.get((row["doc_id"], int(row["page"])), statements.iloc[0:0])
        record["model_statement_ids"] = ";".join(page_rows["statement_id"])
        record["model_outputs"] = compact_outputs(page_rows)
        record["auto_signal"] = "gold_partial" if row["label"] == "ANO-částečně" else "gold_full"
        records.append(record)

    fp = paragraphs[(paragraphs["stratum"] == "probability") & (paragraphs["model_b_outcome"] == "FP")]
    fp = fp.sort_values(["doc_id", "page", "gold_id", "paragraph_id"])
    for number, (_, row) in enumerate(fp.iterrows(), 1):
        record = base_record(f"FP-{number:03d}", "FP", row)
        ids = [item for item in row["model_b_statement_ids"].split(";") if item]
        matched = by_id.loc[ids] if ids else statements.iloc[0:0]
        if isinstance(matched, pd.Series):
            matched = matched.to_frame().T
        record["model_statement_ids"] = ";".join(ids)
        record["model_outputs"] = compact_outputs(matched)
        record["match_score"] = max((float(value) for value in matched["gold_best_score"]), default="")
        record["auto_signal"] = row["label"]
        records.append(record)

    span = statements[
        (statements["span_status"] == "fuzzy_fail")
        & (statements["gold_assignment_status"] == "unassigned")
    ].sort_values(["doc_id", "page", "statement_id"])
    language_by_page = {
        (row.doc_id, int(row.page)): row.language
        for row in paragraphs[["doc_id", "page", "language"]].drop_duplicates().itertuples(index=False)
    }
    for number, (_, row) in enumerate(span.iterrows(), 1):
        record = base_record(f"SPAN-{number:03d}", "SPAN", row)
        record["language"] = language_by_page.get((row["doc_id"], int(row["page"])), "")
        record["gold_label"] = row["gold_label"]
        record["model_statement_ids"] = row["statement_id"]
        record["model_outputs"] = f"{row['statement_id']} | {row['code1']} | {row['quote']}"
        record["match_score"] = float(row["gold_best_score"])
        record["auto_signal"] = (
            "strict_span_unresolved; language_metadata_zh_but_source_is_ja"
            if row["doc_id"] == "JP_BoJ_Pilot_JP"
            else "strict_span_unresolved"
        )
        records.append(record)

    counts = Counter(record["case_type"] for record in records)
    if counts != Counter({"FN": 41, "FP": 20, "SPAN": 5}):
        raise AssertionError(f"unexpected case counts: {dict(counts)}")
    return records


def read_existing():
    if not CASES.exists():
        return {}
    with CASES.open(encoding="utf-8-sig", newline="") as handle:
        return {row["case_id"]: row for row in csv.DictReader(handle)}


def write_cases(records, reset):
    existing = {} if reset else read_existing()
    for record in records:
        old = existing.get(record["case_id"], {})
        for field in HUMAN_FIELDS:
            record[field] = old.get(field, "")
    CAL.mkdir(parents=True, exist_ok=True)
    with CASES.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)


def allowed_categories():
    taxonomy = pd.read_csv(CAL / "taxonomy.csv", keep_default_na=False)
    return {
        case_type: set(group["category_id"])
        for case_type, group in taxonomy.groupby("case_type")
    }


def summarize(require_complete=False):
    cases = pd.read_csv(CASES, keep_default_na=False)
    if len(cases) != 66 or not cases["case_id"].is_unique:
        raise AssertionError("error cases must contain 66 unique rows")
    expected = {"FN": 41, "FP": 20, "SPAN": 5}
    if cases["case_type"].value_counts().to_dict() != expected:
        raise AssertionError("error case type counts")
    allowed = allowed_categories()
    invalid = []
    for row in cases.itertuples(index=False):
        if row.primary_cause and row.primary_cause not in allowed[row.case_type]:
            invalid.append(f"{row.case_id}:{row.primary_cause}")
        if row.secondary_cause and row.secondary_cause not in allowed[row.case_type]:
            invalid.append(f"{row.case_id}:{row.secondary_cause}")
    if invalid:
        raise AssertionError("invalid taxonomy: " + ", ".join(invalid))
    completed = cases["status"].eq("adjudicated")
    if require_complete and not completed.all():
        raise AssertionError(f"pending adjudications: {int((~completed).sum())}")
    summary = {
        "schema": "calibration_error_audit_v1",
        "status": "complete" if completed.all() else "pending_human_adjudication",
        "inputs": {
            "paragraph_audit_sha256": sha256(PARAGRAPHS),
            "statement_assignments_sha256": sha256(STATEMENTS),
            "taxonomy_sha256": sha256(CAL / "taxonomy.csv"),
            "error_cases_sha256": sha256(CASES),
        },
        "counts": {
            "all": len(cases),
            "by_type": expected,
            "adjudicated": int(completed.sum()),
            "pending": int((~completed).sum()),
        },
        "primary_causes": {
            case_type: dict(Counter(group.loc[group["primary_cause"] != "", "primary_cause"]))
            for case_type, group in cases.groupby("case_type")
        },
        "rules": {
            "development_pages": 78,
            "reserve_pages": 40,
            "reserve_status": "sealed",
            "reserve_reuse_after_unblinding": False,
        },
    }
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"calibration audit: FN={expected['FN']} FP={expected['FP']} SPAN={expected['SPAN']} "
        f"adjudicated={summary['counts']['adjudicated']} pending={summary['counts']['pending']}"
    )


def make_package(workbook_path, output_dir):
    workbook_path = Path(workbook_path)
    output_dir = Path(output_dir)
    if not workbook_path.is_file():
        raise FileNotFoundError(workbook_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    sources = [
        CAL / "PROTOCOL.md", CAL / "taxonomy.csv", CAL / "change_log.csv",
        CAL / "freeze_checklist.csv", CASES, SUMMARY, Path(__file__), workbook_path,
    ]
    copied = []
    for source in sources:
        target = output_dir / source.name
        shutil.copy2(source, target)
        copied.append(target)
    manifest = {
        "schema": "calibration_package_v1",
        "files": [
            {"file": path.name, "sha256": sha256_raw(path), "bytes": path.stat().st_size}
            for path in copied
        ],
        "reserve_status": "sealed",
    }
    manifest_path = output_dir / "package_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    archive = output_dir.with_suffix(".zip")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as handle:
        for path in copied + [manifest_path]:
            handle.write(path, arcname=path.name)
    print(f"package: {archive}")


def import_workbook(workbook_path):
    expected = read_existing()
    if len(expected) != 66:
        raise AssertionError("prepare error_cases.csv before importing a workbook")
    frames = []
    for sheet_name, case_type in [("FN audit", "FN"), ("FP audit", "FP"), ("Span audit", "SPAN")]:
        frame = pd.read_excel(workbook_path, sheet_name=sheet_name, dtype=str).fillna("")
        required = {"case_id", *HUMAN_FIELDS}
        if not required.issubset(frame.columns):
            raise AssertionError(f"missing workbook columns on {sheet_name}: {sorted(required - set(frame.columns))}")
        frame = frame[["case_id", *HUMAN_FIELDS]].copy()
        frame["case_type"] = case_type
        frames.append(frame)
    audit = pd.concat(frames, ignore_index=True)
    if len(audit) != 66 or not audit["case_id"].is_unique or set(audit["case_id"]) != set(expected):
        raise AssertionError("workbook case IDs do not match the frozen 66-case package")
    for row in audit.itertuples(index=False):
        if not row.case_id.startswith(row.case_type + "-"):
            raise AssertionError(f"case type mismatch: {row.case_id}")
        if row.status not in {"", "pending", "adjudicated"}:
            raise AssertionError(f"invalid status: {row.case_id}:{row.status}")
        if row.status == "adjudicated" and (not row.source_verdict or not row.primary_cause or not row.adjudicator):
            raise AssertionError(f"incomplete adjudication: {row.case_id}")
        for field in HUMAN_FIELDS:
            expected[row.case_id][field] = getattr(row, field)
    with CASES.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(expected[case_id] for case_id in sorted(expected))
    print(f"imported audit workbook: {workbook_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["prepare", "check", "package", "import-workbook"])
    parser.add_argument("--reset", action="store_true", help="discard existing human audit fields")
    parser.add_argument("--require-complete", action="store_true")
    parser.add_argument("--payload", help="write workbook input JSON")
    parser.add_argument("--workbook")
    parser.add_argument("--output-dir")
    args = parser.parse_args()
    if args.command == "prepare":
        write_cases(build_cases(), args.reset)
    if args.command == "import-workbook":
        if not args.workbook:
            parser.error("import-workbook requires --workbook")
        import_workbook(args.workbook)
    summarize(args.require_complete)
    if args.payload:
        model_b = json.loads((ROOT / "results" / "model_b_pilot.json").read_text(encoding="utf-8"))
        payload = {
            "cases": pd.read_csv(CASES, keep_default_na=False).to_dict("records"),
            "taxonomy": pd.read_csv(CAL / "taxonomy.csv", keep_default_na=False).to_dict("records"),
            "changes": pd.read_csv(CAL / "change_log.csv", keep_default_na=False).to_dict("records"),
            "freeze": pd.read_csv(CAL / "freeze_checklist.csv", keep_default_na=False).to_dict("records"),
            "codebook": pd.read_csv(ROOT / "data" / "codebook.csv", keep_default_na=False).to_dict("records"),
            "model_b": model_b,
        }
        output = Path(args.payload)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.command == "package":
        if not args.workbook or not args.output_dir:
            parser.error("package requires --workbook and --output-dir")
        make_package(args.workbook, args.output_dir)


if __name__ == "__main__":
    main()
