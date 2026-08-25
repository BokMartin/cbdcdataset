import argparse
import csv
import hashlib
import io
import json
import math
import shutil
import unicodedata
import zipfile
from collections import Counter
from pathlib import Path

import pandas as pd
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_DIR = ROOT / "validation" / "extraction_v10_1"
CALIBRATION_DIR = ROOT / "validation" / "calibration_v10"
SAMPLE = ROOT / "validation" / "sample.csv"
GOLD = ROOT / "validation" / "human_gold" / "gold_extraction_martin_v10f.csv"
CODEBOOK = ROOT / "data" / "codebook.csv"
REFERENCE = CALIBRATION_DIR / "calibration_reference_v10_1.csv"
REFERENCE_SUMMARY = CALIBRATION_DIR / "calibration_reference_v10_1.json"
PACKAGE_FILES = [
    PROTOCOL_DIR / "PROMPT_CORE.md",
    PROTOCOL_DIR / "PROTOCOL.md",
    PROTOCOL_DIR / "TASK_CODEX.md",
    PROTOCOL_DIR / "TASK_CLAUDE.md",
    PROTOCOL_DIR / "output_schema.json",
    PROTOCOL_DIR / "run_config.json",
    PROTOCOL_DIR / "pricing.json",
    CODEBOOK,
]


def sha256(path, canonical=False):
    content = Path(path).read_bytes()
    if canonical:
        content = content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(content).hexdigest()


def sha256_bytes(content):
    return hashlib.sha256(content).hexdigest()


def read_jsonl(path):
    with Path(path).open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def original_truth(label):
    if label in {"ANO", "ANO-částečně"}:
        return "positive"
    if label in {"skip_language", "structural_blank"}:
        return "excluded"
    return "negative"


def model_quote(value):
    parts = str(value).split(" | ", 2)
    return parts[2].strip() if len(parts) == 3 else ""


def build_reference():
    gold = pd.read_csv(GOLD, keep_default_na=False)
    audit = pd.read_csv(CALIBRATION_DIR / "error_cases.csv", keep_default_na=False)
    if len(audit) != 66 or not audit["status"].eq("adjudicated").all():
        raise AssertionError("complete 66-case adjudication is required")
    keyed = {
        (row.case_type, row.gold_id, row.paragraph_id): row
        for row in audit.itertuples(index=False)
        if row.gold_id and row.paragraph_id and row.case_type in {"FN", "FP"}
    }
    records = []
    applied = set()
    for row in gold.itertuples(index=False):
        truth = original_truth(row.label)
        code = ""
        span = ""
        case_id = ""
        rule = "original_human_label"
        fn = keyed.get(("FN", row.gold_id, row.paragraph_id))
        fp = keyed.get(("FP", row.gold_id, row.paragraph_id))
        if fn is not None:
            applied.add(fn.case_id)
            case_id = fn.case_id
            if fn.source_verdict == "gold_valid":
                truth = "positive"
                code = fn.target_code
                span = fn.corrected_span
                rule = "adjudicated_gold_valid"
            elif fn.source_verdict == "gold_invalid":
                truth = "negative"
                rule = "adjudicated_scope_exclusion"
            else:
                raise AssertionError(f"unexpected FN verdict: {fn.case_id}:{fn.source_verdict}")
        if fp is not None and fp.source_verdict == "gold_false_negative":
            applied.add(fp.case_id)
            case_id = fp.case_id
            truth = "positive"
            code = fp.target_code or "PROG.generic"
            span = fp.corrected_span or model_quote(fp.model_outputs)
            rule = "adjudicated_false_negative"
        records.append({
            "gold_id": row.gold_id,
            "paragraph_id": row.paragraph_id,
            "doc_id": row.doc_id,
            "page": int(row.page),
            "stratum": row.stratum,
            "language": "ja" if row.doc_id == "JP_BoJ_Pilot_JP" else row.language,
            "text": row.text,
            "original_label": row.label,
            "original_truth": original_truth(row.label),
            "reference_truth": truth,
            "reference_code": code,
            "reference_span": span,
            "adjudication_case_id": case_id,
            "adjudication_rule": rule,
        })
    expected = set(audit.loc[
        (
            audit["case_type"].eq("FN")
            | audit["source_verdict"].eq("gold_false_negative")
        )
        & audit["gold_id"].ne("")
        & audit["paragraph_id"].ne(""), "case_id"
    ])
    missing = sorted(expected - applied)
    if missing:
        raise AssertionError("unapplied adjudications: " + ", ".join(missing))
    reference = pd.DataFrame(records)
    reference.to_csv(REFERENCE, index=False, lineterminator="\n")
    probability = reference[reference["stratum"].eq("probability")]
    summary = {
        "schema": "calibration_reference_v10_1",
        "source_gold_sha256": sha256(GOLD, canonical=True),
        "error_cases_sha256": sha256(CALIBRATION_DIR / "error_cases.csv", canonical=True),
        "reference_sha256": sha256(REFERENCE, canonical=True),
        "counts": {
            "rows": len(reference),
            "pages": int(reference[["doc_id", "page"]].drop_duplicates().shape[0]),
            "all_truth": dict(Counter(reference["reference_truth"])),
            "probability_truth": dict(Counter(probability["reference_truth"])),
            "scope_exclusions": int(reference["adjudication_rule"].eq("adjudicated_scope_exclusion").sum()),
            "false_negative_corrections": int(reference["adjudication_rule"].eq("adjudicated_false_negative").sum()),
        },
        "reserve_status": "sealed",
    }
    REFERENCE_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def zip_members_by_basename(archive):
    by_name = {}
    for member in archive.namelist():
        if member.endswith("/"):
            continue
        name = Path(member).name
        if name in by_name:
            raise AssertionError(f"duplicate archive basename: {name}")
        by_name[name] = member
    return by_name


def estimated_tokens(text, language):
    ratio = 2.0 if language in {"zh", "ja", "ko"} else 4.0
    return max(1, math.ceil(len(text) / ratio))


def chunk_text(text, language, target_tokens, overlap_tokens):
    if not text:
        return [(0, 0, "")]
    ratio = 2 if language in {"zh", "ja", "ko"} else 4
    target = target_tokens * ratio
    overlap = overlap_tokens * ratio
    chunks = []
    start = 0
    while start < len(text):
        tentative = min(len(text), start + target)
        end = tentative
        if tentative < len(text):
            floor = start + int(target * 0.80)
            breaks = [text.rfind("\n", floor, tentative), text.rfind(" ", floor, tentative)]
            end = max(breaks)
            if end <= start:
                end = tentative
        chunks.append((start, end, text[start:end]))
        if end >= len(text):
            break
        next_start = max(start + 1, end - overlap)
        while next_start > start and next_start < len(text) and not text[next_start - 1].isspace():
            next_start -= 1
        start = next_start if next_start > start else end
    return chunks


def bool_value(value):
    return str(value).strip().lower() in {"true", "1", "yes"}


def reserve_allowed():
    freeze = pd.read_csv(CALIBRATION_DIR / "freeze_checklist.csv", keep_default_na=False)
    blocking = freeze[freeze["id"].isin([f"C{i:02d}" for i in range(1, 13)])]
    return len(blocking) == 12 and blocking["status"].eq("complete").all()


def prepare(args):
    config = json.loads((PROTOCOL_DIR / "run_config.json").read_text(encoding="utf-8"))
    sample = pd.read_csv(SAMPLE, keep_default_na=False)
    if args.phase == "calibration":
        selected = sample[~sample["stratum"].eq("reserve_sealed")].copy()
        prefix = "CAL"
    elif args.phase == "reserve":
        if not reserve_allowed():
            raise AssertionError("reserve remains sealed: checklist C01-C12 is incomplete")
        selected = sample[sample["stratum"].eq("reserve_sealed")].copy()
        prefix = "RES"
    else:
        raise AssertionError("prepare currently supports calibration or reserve; full corpus follows a passed reserve")
    expected = config["development_pages"] if args.phase == "calibration" else config["reserve_pages"]
    if len(selected) != expected:
        raise AssertionError(f"unexpected {args.phase} page count: {len(selected)}")

    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    renders_out = output / "renders"
    renders_out.mkdir(exist_ok=True)
    gold = pd.read_csv(GOLD, keep_default_na=False)
    page_to_gold = {
        (doc, int(page)): group.iloc[0]["gold_id"]
        for (doc, page), group in gold.groupby(["doc_id", "page"], sort=False)
    }

    input_config = config["input"]
    units = []
    manifest = []
    with zipfile.ZipFile(args.corpus) as corpus:
        corpus_members = zip_members_by_basename(corpus)
        render_archive = zipfile.ZipFile(args.renders) if args.renders else None
        render_members = zip_members_by_basename(render_archive) if render_archive else {}
        try:
            for ordinal, row in enumerate(selected.itertuples(index=False), 1):
                input_id = f"{prefix}-{ordinal:03d}"
                if row.fname not in corpus_members:
                    raise FileNotFoundError(f"corpus PDF missing: {row.fname}")
                pdf_bytes = corpus.read(corpus_members[row.fname])
                pdf_hash = sha256_bytes(pdf_bytes)
                reader = PdfReader(io.BytesIO(pdf_bytes))
                if int(row.page) < 1 or int(row.page) > len(reader.pages):
                    raise IndexError(f"page out of range: {row.fname}:{row.page}")
                text = (reader.pages[int(row.page) - 1].extract_text() or "").strip()
                need_render = bool_value(row.ocr_needed) or len(text) < 250
                render_name = ""
                render_hash = ""
                if need_render:
                    gold_id = page_to_gold.get((row.doc_id, int(row.page)), "")
                    source_render = f"{gold_id}.png" if gold_id else ""
                    if not render_archive or source_render not in render_members:
                        raise FileNotFoundError(
                            f"frozen render required for {input_id} {row.doc_id}:{row.page}"
                        )
                    render_name = f"{input_id}.png"
                    render_bytes = render_archive.read(render_members[source_render])
                    (renders_out / render_name).write_bytes(render_bytes)
                    render_hash = sha256_bytes(render_bytes)
                source_mode = "text_and_render" if need_render and text else "render" if need_render else "text"
                chunks = chunk_text(
                    text, row.language,
                    input_config["target_text_tokens_per_unit"],
                    input_config["overlap_text_tokens"],
                )
                for chunk_number, (start, end, chunk) in enumerate(chunks, 1):
                    unit_id = f"{input_id}-U{chunk_number:02d}"
                    block_id = f"{input_id}-P{int(row.page):04d}-B{chunk_number:02d}"
                    record = {
                        "unit_id": unit_id,
                        "input_id": input_id,
                        "block_id": block_id,
                        "doc_id": row.doc_id,
                        "page": int(row.page),
                        "language": row.language,
                        "source_mode": source_mode,
                        "chunk_start": start,
                        "chunk_end": end,
                        "source_text": chunk,
                        "render_file": f"renders/{render_name}" if render_name else None,
                    }
                    units.append(record)
                    manifest.append({
                        "unit_id": unit_id,
                        "input_id": input_id,
                        "doc_id": row.doc_id,
                        "page": int(row.page),
                        "stratum": row.stratum,
                        "language": row.language,
                        "fname": row.fname,
                        "pdf_sha256": pdf_hash,
                        "block_id": block_id,
                        "chunk_start": start,
                        "chunk_end": end,
                        "text_sha256": sha256_bytes(chunk.encode("utf-8")),
                        "source_mode": source_mode,
                        "render_file": f"renders/{render_name}" if render_name else "",
                        "render_sha256": render_hash,
                        "estimated_source_tokens": estimated_tokens(chunk, row.language),
                    })
        finally:
            if render_archive:
                render_archive.close()

    requests = []
    current = []
    current_tokens = 0
    for unit in units:
        tokens = estimated_tokens(unit["source_text"], unit["language"])
        limit_count = len(current) >= input_config["max_units_per_request"]
        limit_tokens = current and current_tokens + tokens > input_config["max_source_tokens_per_request"]
        if limit_count or limit_tokens:
            requests.append(current)
            current = []
            current_tokens = 0
        current.append(unit)
        current_tokens += tokens
    if current:
        requests.append(current)

    input_path = output / "inputs.jsonl"
    with input_path.open("w", encoding="utf-8", newline="") as handle:
        for number, request_units in enumerate(requests, 1):
            handle.write(json.dumps({
                "request_id": f"{prefix}-R{number:04d}",
                "units": request_units,
            }, ensure_ascii=False, separators=(",", ":")) + "\n")
    manifest_path = output / "input_manifest.csv"
    pd.DataFrame(manifest).to_csv(manifest_path, index=False, lineterminator="\n")
    for source in PACKAGE_FILES:
        shutil.copy2(source, output / source.name)
    package = {
        "schema": "extraction_v10_1_input_package",
        "phase": args.phase,
        "reserve_status": "sealed" if args.phase == "calibration" else "authorized_once",
        "pages": len(selected),
        "units": len(units),
        "requests": len(requests),
        "render_pages": sum(bool(item["render_file"]) for item in manifest),
        "files": [
            {"file": path.name, "sha256": sha256(path), "bytes": path.stat().st_size}
            for path in [input_path, manifest_path]
        ] + [
            {"file": source.name, "sha256": sha256(output / source.name), "bytes": (output / source.name).stat().st_size}
            for source in PACKAGE_FILES
        ],
    }
    package_path = output / "package_manifest.json"
    package_path.write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(package, indent=2))


def estimate_cost(args):
    package = Path(args.package)
    config = json.loads((PROTOCOL_DIR / "run_config.json").read_text(encoding="utf-8"))
    prices = json.loads((PROTOCOL_DIR / "pricing.json").read_text(encoding="utf-8"))["models"]
    prompt = (PROTOCOL_DIR / "PROMPT_CORE.md").read_text(encoding="utf-8")
    codebook = CODEBOOK.read_text(encoding="utf-8")
    schema = (PROTOCOL_DIR / "output_schema.json").read_text(encoding="utf-8")
    static_tokens = math.ceil((len(prompt) + len(codebook) + len(schema)) / 4)
    requests = read_jsonl(package / "inputs.jsonl")
    source_tokens = sum(
        estimated_tokens(unit["source_text"], unit["language"])
        for request in requests for unit in request["units"]
    )
    units = sum(len(request["units"]) for request in requests)
    input_tokens = source_tokens + static_tokens * len(requests)
    output_tokens = args.output_tokens_per_unit * units
    estimates = {}
    for model, price in prices.items():
        cost = (
            input_tokens * price["estimated_batch_input"]
            + output_tokens * price["estimated_batch_output"]
        ) / 1_000_000
        estimates[model] = round(cost, 4)
    result = {
        "requests": len(requests),
        "units": units,
        "source_tokens_estimated": source_tokens,
        "static_tokens_per_request_estimated": static_tokens,
        "input_tokens_estimated": input_tokens,
        "output_tokens_assumed": output_tokens,
        "batch_cost_usd_estimated": estimates,
        "two_model_total_usd_estimated": round(sum(estimates.values()), 4),
        "excludes": ["image-token charges", "failed-request retries", "taxes"],
        "instruction": "replace estimates with actual provider usage and invoice amounts after the run",
    }
    print(json.dumps(result, indent=2))


def normalized_span(text):
    text = unicodedata.normalize("NFKC", str(text)).replace("\u00ad", "")
    text = text.replace("-\n", "")
    return "".join(text.split())


def validate_output(args):
    package = Path(args.package)
    input_requests = {
        item["request_id"]: item for item in read_jsonl(package / "inputs.jsonl")
    }
    responses = read_jsonl(args.responses)
    if len(responses) != len(input_requests):
        raise AssertionError("response count differs from request count")
    if len({item.get("request_id") for item in responses}) != len(responses):
        raise AssertionError("duplicate response request_id")
    codebook = set(pd.read_csv(CODEBOOK, keep_default_na=False)["code"])
    allowed_status = {"ok", "structural_blank", "source_unavailable", "skip_language"}
    allowed_odr = {"decision", "proposal", "finding"}
    allowed_direction = {"increases", "decreases", "conditional", "neutral"}
    allowed_relation = {"from_state", "from_intermediary", "from_counterparty", "not_applicable"}
    rows = []
    statement_count = 0
    for response in responses:
        request_id = response.get("request_id")
        if request_id not in input_requests:
            raise AssertionError(f"unknown request_id: {request_id}")
        expected_units = {unit["unit_id"]: unit for unit in input_requests[request_id]["units"]}
        returned_units = response.get("units")
        if not isinstance(returned_units, list):
            raise AssertionError(f"units must be an array: {request_id}")
        if {unit.get("unit_id") for unit in returned_units} != set(expected_units):
            raise AssertionError(f"unit coverage differs: {request_id}")
        for returned in returned_units:
            unit = expected_units[returned["unit_id"]]
            status = returned.get("status")
            statements = returned.get("statements")
            if status not in allowed_status or not isinstance(statements, list):
                raise AssertionError(f"invalid unit result: {returned['unit_id']}")
            if status != "ok" and statements:
                raise AssertionError(f"non-ok unit has statements: {returned['unit_id']}")
            for ordinal, statement in enumerate(statements, 1):
                required = {
                    "block_id", "quote", "quote_en", "code1", "odr", "privacy_direction",
                    "privacy_relation", "strength", "source_mode",
                }
                if set(statement) != required:
                    raise AssertionError(f"statement fields differ: {returned['unit_id']}:{ordinal}")
                if statement["block_id"] != unit["block_id"]:
                    raise AssertionError(f"block mismatch: {returned['unit_id']}:{ordinal}")
                if not statement["quote"] or statement["code1"] not in codebook:
                    raise AssertionError(f"invalid quote/code: {returned['unit_id']}:{ordinal}")
                if statement["odr"] not in allowed_odr:
                    raise AssertionError(f"invalid odr: {returned['unit_id']}:{ordinal}")
                if statement["privacy_direction"] not in allowed_direction:
                    raise AssertionError(f"invalid privacy_direction: {returned['unit_id']}:{ordinal}")
                if statement["privacy_relation"] not in allowed_relation:
                    raise AssertionError(f"invalid privacy_relation: {returned['unit_id']}:{ordinal}")
                if type(statement["strength"]) is not int or statement["strength"] not in {1, 2, 3}:
                    raise AssertionError(f"invalid strength: {returned['unit_id']}:{ordinal}")
                if unit["language"] == "en" and statement["quote_en"] is not None:
                    raise AssertionError(f"English quote_en must be null: {returned['unit_id']}:{ordinal}")
                if not statement["code1"].startswith("PRIV.") and (
                    statement["privacy_direction"] != "neutral"
                    or statement["privacy_relation"] != "not_applicable"
                ):
                    raise AssertionError(f"non-privacy defaults differ: {returned['unit_id']}:{ordinal}")
                quote_normalized = normalized_span(statement["quote"])
                text_normalized = normalized_span(unit["source_text"])
                if quote_normalized and quote_normalized in text_normalized:
                    span_status = "text_verified"
                elif unit["render_file"]:
                    span_status = "render_review_required"
                else:
                    span_status = "unsupported"
                rows.append({
                    "request_id": request_id,
                    "unit_id": returned["unit_id"],
                    "doc_id": unit["doc_id"],
                    "page": unit["page"],
                    "statement_ordinal": ordinal,
                    "code1": statement["code1"],
                    "quote": statement["quote"],
                    "span_status": span_status,
                })
                statement_count += 1
    unsupported = sum(row["span_status"] == "unsupported" for row in rows)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=[
        "request_id", "unit_id", "doc_id", "page", "statement_ordinal",
        "code1", "quote", "span_status",
    ]).to_csv(out, index=False, lineterminator="\n")
    summary = {
        "requests": len(responses),
        "units": sum(len(item["units"]) for item in responses),
        "statements": statement_count,
        "span_status": dict(Counter(row["span_status"] for row in rows)),
        "valid": unsupported == 0,
        "responses_sha256": sha256(args.responses),
        "span_audit_sha256": sha256(out, canonical=True),
    }
    print(json.dumps(summary, indent=2))
    if unsupported:
        raise AssertionError(f"unsupported spans: {unsupported}")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build-reference")
    prep = sub.add_parser("prepare")
    prep.add_argument("--phase", choices=["calibration", "reserve"], required=True)
    prep.add_argument("--corpus", type=Path, required=True)
    prep.add_argument("--renders", type=Path)
    prep.add_argument("--output", type=Path, required=True)
    cost = sub.add_parser("estimate-cost")
    cost.add_argument("--package", type=Path, required=True)
    cost.add_argument("--output-tokens-per-unit", type=int, default=220)
    validate = sub.add_parser("validate-output")
    validate.add_argument("--package", type=Path, required=True)
    validate.add_argument("--responses", type=Path, required=True)
    validate.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build-reference":
        build_reference()
    elif args.command == "prepare":
        prepare(args)
    elif args.command == "estimate-cost":
        estimate_cost(args)
    else:
        validate_output(args)


if __name__ == "__main__":
    main()
