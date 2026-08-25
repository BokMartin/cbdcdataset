import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const dataDir = process.argv[2];
const outputDir = process.argv[3];
if (!dataDir || !outputDir) {
  throw new Error("usage: verify_ai_candidate_masters_v10_2e.mjs data_dir output_dir");
}

const specs = [
  { payload: "master_full.json", file: "AI_CANDIDATE_MASTER_v10_2e_FULL_SEALED.xlsx", count: 6949, statements: 11358, first: "PC-00001", last: "PC-06949" },
  { payload: "master_martin.json", file: "AI_CANDIDATE_MASTER_v10_2e_MARTIN_SAMPLE_SEALED.xlsx", count: 365, statements: 596, first: "SV-0001", last: "SV-0365" },
  { payload: "master_dominik.json", file: "AI_CANDIDATE_MASTER_v10_2e_DOMINIK_SAMPLE_SEALED.xlsx", count: 365, statements: 596, first: "SV-0001", last: "SV-0365" },
];
const requiredSheets = ["README", "Candidates", "Provider Statements", "Dual Empty Sample", "Codebook", "Data Dictionary", "Provenance"];

const sha256 = (bytes) => crypto.createHash("sha256").update(bytes).digest("hex");
const lines = (value) => String(value ?? "").split(/\r?\n/).filter(Boolean);
const parseLines = (value) => lines(value).map((line) => JSON.parse(line));
const payloads = {};
for (const spec of specs) payloads[spec.payload] = JSON.parse(await fs.readFile(path.join(dataDir, spec.payload), "utf8"));
const full = payloads["master_full.json"];
const martin = structuredClone(payloads["master_martin.json"]);
const dominik = structuredClone(payloads["master_dominik.json"]);
martin.reviewer = "REVIEWER";
dominik.reviewer = "REVIEWER";
const fullCandidateIds = new Set(full.candidates.map((row) => row.candidate_id));

const payloadChecks = {
  sample_payloads_equal_except_reviewer: JSON.stringify(martin) === JSON.stringify(dominik),
  full_candidate_ids_unique: new Set(full.candidates.map((row) => row.candidate_id)).size === full.candidates.length,
  full_statement_ids_unique: new Set(full.provider_statements.map((row) => row.statement_id)).size === full.provider_statements.length,
  every_statement_links_to_candidate: full.provider_statements.every((row) => fullCandidateIds.has(row.candidate_id)),
  sample_candidates_are_full_subset: payloads["master_martin.json"].candidates.every((row) => fullCandidateIds.has(row.candidate_id)),
  dual_empty_samples_equal: JSON.stringify(payloads["master_martin.json"].dual_empty_sample) === JSON.stringify(payloads["master_dominik.json"].dual_empty_sample),
};

const results = [];
for (const spec of specs) {
  const payload = payloads[spec.payload];
  const file = path.join(outputDir, spec.file);
  const bytes = await fs.readFile(file);
  const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(file));
  const sheetInspect = await workbook.inspect({ kind: "sheet", include: "id,name", maxChars: 5000 });
  const sheetNames = parseLines(sheetInspect.ndjson).map((row) => row.name ?? row.sheet).filter(Boolean);
  const first = await workbook.inspect({ kind: "region", sheetId: "Candidates", range: "A3:J5", maxChars: 10000 });
  const endRow = spec.count + 3;
  const last = await workbook.inspect({ kind: "region", sheetId: "Candidates", range: `A${endRow}:J${endRow}`, maxChars: 5000 });
  const readme = await workbook.inspect({ kind: "region", sheetId: "README", range: "A4:H6", maxChars: 10000 });
  const errors = await workbook.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    options: { useRegex: true, maxResults: 300 },
    summary: "AI master formula error scan",
  });
  const errorRows = parseLines(errors.ndjson).filter((row) => !(row.kind === "notice" && /matched 0 entries/i.test(row.message ?? "")));
  const missingSheets = requiredSheets.filter((name) => !sheetNames.includes(name));
  const firstText = JSON.stringify(parseLines(first.ndjson));
  const lastText = JSON.stringify(parseLines(last.ndjson));
  const readmeText = JSON.stringify(parseLines(readme.ndjson));
  const passed = payload.candidates.length === spec.count
    && payload.provider_statements.length === spec.statements
    && payload.dual_empty_sample.length === 36
    && missingSheets.length === 0
    && sheetNames[0] === "README"
    && errorRows.length === 0
    && firstText.includes(spec.first)
    && lastText.includes(spec.last)
    && readmeText.includes(String(spec.count))
    && readmeText.includes(String(spec.statements));
  results.push({
    file: spec.file,
    sha256: sha256(bytes),
    bytes: bytes.length,
    candidate_rows: payload.candidates.length,
    provider_statement_rows: payload.provider_statements.length,
    dual_empty_rows: payload.dual_empty_sample.length,
    observed_sheets: sheetNames,
    missing_sheets: missingSheets,
    formula_error_matches: errorRows.length,
    boundary_ids: { first: spec.first, last: spec.last },
    passed,
  });
}

const report = {
  schema: "cbdc-v10.2e-ai-master-independent-verification-v1",
  created_utc: new Date().toISOString(),
  passed: Object.values(payloadChecks).every(Boolean) && results.every((row) => row.passed),
  payload_checks: payloadChecks,
  workbooks: results,
};
await fs.writeFile(path.join(outputDir, "AI_MASTER_INDEPENDENT_VERIFICATION.json"), JSON.stringify(report, null, 2) + "\n", "utf8");
console.log(JSON.stringify(report));
