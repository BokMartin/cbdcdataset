import fs from "node:fs/promises";
import path from "node:path";
import crypto from "node:crypto";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const outputDir = process.argv[2];
if (!outputDir) throw new Error("usage: verify_workbooks.mjs output_dir");

const specs = [
  { reviewer: "MARTIN", candidates: 4171, candidateEnd: 4174, emptyEnd: 39, supplementEnd: 183 },
  { reviewer: "DOMINIK", candidates: 4168, candidateEnd: 4171, emptyEnd: 39, supplementEnd: 183 },
];

function lines(text) {
  return String(text ?? "").split(/\r?\n/).filter(Boolean);
}

const results = [];
for (const spec of specs) {
  const file = path.join(outputDir, `FINAL_ADJUDICATION_v10_2e_${spec.reviewer}.xlsx`);
  const bytes = await fs.readFile(file);
  const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(file));
  const sheetInspect = await workbook.inspect({ kind: "sheet", include: "id,name", maxChars: 5000 });
  const sheetNames = lines(sheetInspect.ndjson).map((line) => JSON.parse(line).name ?? JSON.parse(line).sheet).filter(Boolean);
  const candidateTop = await workbook.inspect({ kind: "region", sheetId: "Candidate Review", range: "A1:AB5", maxChars: 18000 });
  const candidateBottom = await workbook.inspect({ kind: "region", sheetId: "Candidate Review", range: `A${spec.candidateEnd}:AB${spec.candidateEnd}`, maxChars: 14000 });
  const candidateQc = await workbook.inspect({ kind: "region", sheetId: "Candidate Review", range: `AA4:AB6`, maxChars: 6000 });
  const dualEmptyBottom = await workbook.inspect({ kind: "region", sheetId: "Dual Empty Audit", range: `A${spec.emptyEnd}:O${spec.emptyEnd}`, maxChars: 12000 });
  const supplementBottom = await workbook.inspect({ kind: "region", sheetId: "Empty Supplements", range: `A${spec.supplementEnd}:M${spec.supplementEnd}`, maxChars: 8000 });
  const qc = await workbook.inspect({ kind: "region", sheetId: "QC Summary", range: "A1:D16", maxChars: 12000 });
  const errors = await workbook.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    options: { useRegex: true, maxResults: 300 },
    summary: "final formula error scan",
  });
  const errorLines = lines(errors.ndjson).filter((line) => {
    const record = JSON.parse(line);
    return !(record.kind === "notice" && /matched 0 entries/i.test(record.message ?? ""));
  });
  const requiredSheets = ["Instructions", "Candidate Review", "Dual Empty Audit", "Empty Supplements", "Contexts", "Codebook", "QC Summary", "Lists", "Metadata"];
  const missingSheets = requiredSheets.filter((name) => !sheetNames.includes(name));
  results.push({
    reviewer: spec.reviewer,
    file,
    bytes: bytes.length,
    sha256: crypto.createHash("sha256").update(bytes).digest("hex"),
    expected_candidate_rows: spec.candidates,
    required_sheets: requiredSheets,
    observed_sheets: sheetNames,
    missing_sheets: missingSheets,
    formula_error_matches: errorLines,
    passed: missingSheets.length === 0 && errorLines.length === 0,
    inspections: {
      candidate_top: lines(candidateTop.ndjson),
      candidate_bottom: lines(candidateBottom.ndjson),
      candidate_qc: lines(candidateQc.ndjson),
      dual_empty_bottom: lines(dualEmptyBottom.ndjson),
      supplement_bottom: lines(supplementBottom.ndjson),
      qc_summary: lines(qc.ndjson),
    },
  });
}

const report = {
  schema: "cbdc-v10.2e-adjudication-workbook-verification-v1",
  created_utc: new Date().toISOString(),
  passed: results.every((x) => x.passed),
  workbooks: results,
};
await fs.writeFile(path.join(outputDir, "FINAL_ADJUDICATION_WORKBOOK_VERIFICATION.json"), JSON.stringify(report, null, 2) + "\n", "utf8");
console.log(JSON.stringify({ passed: report.passed, workbooks: results.map((x) => ({ reviewer: x.reviewer, sha256: x.sha256, bytes: x.bytes, missing_sheets: x.missing_sheets, formula_error_count: x.formula_error_matches.length })) }));
