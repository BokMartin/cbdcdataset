import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const outputDir = process.argv[2];
if (!outputDir) throw new Error("usage: verify_ai_reviewer_workbooks_v10_2e.mjs output_dir");

const requiredSheets = ["Instructions", "Candidate Review", "Dual Empty Audit", "Empty Supplements", "Contexts", "Codebook", "QC Summary", "Lists", "Metadata"];
const specs = [
  { provider: "OPENAI", emitted: 296, absent: 69 },
  { provider: "CLAUDE", emitted: 295, absent: 70 },
];
const sha256 = (bytes) => crypto.createHash("sha256").update(bytes).digest("hex");
const lines = (value) => String(value ?? "").split(/\r?\n/).filter(Boolean);

const results = [];
for (const spec of specs) {
  const fileName = `VALIDATION_SAMPLE_v10_2e_${spec.provider}_PREFILLED_SEALED.xlsx`;
  const file = path.join(outputDir, fileName);
  const bytes = await fs.readFile(file);
  const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(file));
  const sheetInspect = await workbook.inspect({ kind: "sheet", include: "id,name", maxChars: 5000 });
  const sheetNames = lines(sheetInspect.ndjson).map((line) => JSON.parse(line).name).filter(Boolean);
  const missingSheets = requiredSheets.filter((name) => !sheetNames.includes(name));
  const candidates = workbook.worksheets.getItem("Candidate Review").getRange("A4:AB368").values;
  const dualEmpty = workbook.worksheets.getItem("Dual Empty Audit").getRange("A4:O39").values;
  const supplements = workbook.worksheets.getItem("Empty Supplements").getRange("A4:M183").values;
  const keep = candidates.filter((row) => row[15] === "keep");
  const exclude = candidates.filter((row) => row[15] === "exclude");
  const checks = {
    sheet_order_and_presence: JSON.stringify(sheetNames) === JSON.stringify(requiredSheets) && missingSheets.length === 0,
    candidate_ids: candidates.length === 365 && candidates[0][0] === "SV-0001" && candidates.at(-1)[0] === "SV-0365" && new Set(candidates.map((row) => row[0])).size === 365,
    emitted_count: keep.length === spec.emitted,
    absent_count: exclude.length === spec.absent,
    emitted_required_fields: keep.every((row) => [16, 17, 18, 19, 20, 22, 23, 26].every((index) => row[index] !== "" && row[index] !== null)),
    absent_semantics: exclude.every((row) => row[21] === "not_extracted_by_provider" && row[22] === "not_reported" && [16, 17, 18, 19, 20].every((index) => row[index] === "" || row[index] === null)),
    candidate_qc_complete: candidates.every((row) => row[27] === "COMPLETE"),
    dual_empty_semantics: dualEmpty.length === 36 && dualEmpty.every((row) => row[10] === "no" && row[11] === "not_reported" && row[14] === "COMPLETE"),
    supplements_unused: supplements.every((row) => row[12] === "UNUSED"),
    reviewer_initials: candidates.every((row) => row[26] === spec.provider) && dualEmpty.every((row) => row[13] === spec.provider),
  };
  const errors = await workbook.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    options: { useRegex: true, maxResults: 300 },
    summary: "AI reviewer workbook formula error scan",
  });
  const errorRows = lines(errors.ndjson).filter((line) => {
    const row = JSON.parse(line);
    return !(row.kind === "notice" && /matched 0 entries/i.test(row.message ?? ""));
  });
  const qc = await workbook.inspect({ kind: "region", sheetId: "QC Summary", range: "A1:D16", maxChars: 12000 });
  results.push({
    provider: spec.provider.toLowerCase(),
    file: fileName,
    bytes: bytes.length,
    sha256: sha256(bytes),
    counts: { candidates: candidates.length, emitted: keep.length, absent: exclude.length, dual_empty: dualEmpty.length },
    checks,
    formula_error_matches: errorRows.length,
    qc_summary: lines(qc.ndjson),
    passed: Object.values(checks).every(Boolean) && errorRows.length === 0,
  });
}

const report = {
  schema: "cbdc-v10.2e-ai-reviewer-workbook-independent-verification-v1",
  created_utc: new Date().toISOString(),
  passed: results.every((row) => row.passed),
  workbooks: results,
};
await fs.writeFile(path.join(outputDir, "AI_REVIEWER_WORKBOOK_INDEPENDENT_VERIFICATION.json"), JSON.stringify(report, null, 2) + "\n", "utf8");
console.log(JSON.stringify({ passed: report.passed, workbooks: results.map((row) => ({ provider: row.provider, sha256: row.sha256, counts: row.counts, checks: row.checks, formula_error_matches: row.formula_error_matches })) }));
