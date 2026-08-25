import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const templatePath = process.argv[2];
const sampleMasterPath = process.argv[3];
const fullMasterPath = process.argv[4];
const outputDir = process.argv[5];
const previewDir = process.argv[6];
if (!templatePath || !sampleMasterPath || !fullMasterPath || !outputDir || !previewDir) {
  throw new Error("usage: build_ai_reviewer_workbooks_v10_2e.mjs template sample_master full_master output_dir preview_dir");
}
await fs.mkdir(outputDir, { recursive: true });
await fs.mkdir(previewDir, { recursive: true });

const sample = JSON.parse(await fs.readFile(sampleMasterPath, "utf8"));
const full = JSON.parse(await fs.readFile(fullMasterPath, "utf8"));
const candidateEnd = 3 + sample.candidates.length;
const dualEmptyEnd = 3 + sample.dual_empty_sample.length;
const requiredSheets = ["Instructions", "Candidate Review", "Dual Empty Audit", "Empty Supplements", "Contexts", "Codebook", "QC Summary", "Lists", "Metadata"];

function sha256(bytes) {
  return crypto.createHash("sha256").update(bytes).digest("hex");
}

function sanitize(value, audit) {
  if (typeof value !== "string") return value;
  const cleaned = value.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, "");
  audit.removed_illegal_xml_characters += value.length - cleaned.length;
  return cleaned;
}

function statementGroups(provider) {
  const groups = new Map();
  for (const row of sample.provider_statements.filter((item) => item.provider === provider)) {
    const key = row.sample_case_id;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(row);
  }
  for (const rows of groups.values()) rows.sort((a, b) => a.statement_id.localeCompare(b.statement_id));
  return groups;
}

function candidateFills(provider, audit) {
  const groups = statementGroups(provider);
  return sample.candidates.map((candidate) => {
    const statements = groups.get(candidate.sample_case_id) ?? [];
    if (!statements.length) {
      return [
        "exclude", "", "", "", "", "", "not_extracted_by_provider", "not_reported", "", "",
        `MACHINE OUTPUT ARCHIVE; provider=${provider}; presence=absent; this is not a human validity judgment.`,
      ];
    }
    const primary = statements[0];
    const distinct = (field) => [...new Set(statements.map((row) => String(row[field] ?? "")).filter(Boolean))].join(" || ");
    const note = [
      "MACHINE OUTPUT ARCHIVE",
      `provider=${provider}`,
      "presence=emitted",
      "primary_rule=lowest_statement_id",
      `statement_ids=${statements.map((row) => row.statement_id).join(" || ")}`,
      `all_codes=${distinct("code1")}`,
      `all_odr=${distinct("odr")}`,
      "not_a_human_validity_judgment",
    ].join("; ");
    return [
      "keep",
      primary.code1,
      primary.odr,
      primary.privacy_direction,
      primary.privacy_relation,
      Number(primary.strength),
      "",
      "not_reported",
      primary.quote,
      primary.quote_en,
      note,
    ].map((value) => sanitize(value, audit));
  });
}

function disagreementSummary(rows) {
  const both = rows.filter((row) => row.origin_type === "both");
  const family = new Map(sample.codebook.map((row) => [row.code, row.family]));
  const set = (value) => new Set(String(value).split(" || ").filter(Boolean));
  const families = (value) => new Set([...set(value)].map((code) => family.get(code)));
  const sameSet = (left, right) => left.size === right.size && [...left].every((value) => right.has(value));
  return {
    candidates: rows.length,
    both: both.length,
    openai_only: rows.filter((row) => row.origin_type === "openai_only").length,
    claude_only: rows.filter((row) => row.origin_type === "claude_only").length,
    exact_code_set: both.filter((row) => row.ai_code_set_exact_match).length,
    same_family_set: both.filter((row) => sameSet(families(row.openai_codes), families(row.claude_codes))).length,
    exact_odr_set: both.filter((row) => row.ai_odr_set_exact_match).length,
  };
}

async function build(provider) {
  const display = provider === "openai" ? "OpenAI" : "Claude";
  const upper = provider.toUpperCase();
  const audit = { removed_illegal_xml_characters: 0 };
  const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(templatePath));
  const sheetInspect = await workbook.inspect({ kind: "sheet", include: "id,name", maxChars: 5000 });
  const sheets = String(sheetInspect.ndjson).split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line).name).filter(Boolean);
  if (JSON.stringify(sheets) !== JSON.stringify(requiredSheets)) throw new Error(`template sheet mismatch: ${sheets.join(", ")}`);

  const instructions = workbook.worksheets.getItem("Instructions");
  instructions.getRange("A1").values = [[`CBDC v10.2e — sealed machine-output workbook — ${display}`]];
  instructions.getRange("A2").values = [["Předvyplněný archiv výstupu modelu ve stejném schématu jako lidské sešity. keep = model emitoval kandidáta; exclude + not_extracted_by_provider = model jej neemitoval. Nejde o lidský verdikt validity."]];
  instructions.getRange("B3").values = [[upper]];

  const candidates = workbook.worksheets.getItem("Candidate Review");
  candidates.getRange("A1").values = [[`Candidate Validation Sample — ${display} — SEALED`]];
  candidates.getRange("A2").values = [["Machine-output answer key. Do not open before both human workbooks are returned and hash-locked. Provider absence is encoded as exclude/not_extracted_by_provider; model confidence was not reported."]];
  candidates.getRange(`P4:Z${candidateEnd}`).values = candidateFills(provider, audit);
  candidates.getRange(`V4:V${candidateEnd}`).dataValidation = { rule: { type: "list", values: ["foreign_or_cited_research", "generic_context", "future_research_or_open_question", "stakeholder_or_consultant_not_adopted", "glossary_heading_or_list", "incomplete_fragment_or_ocr", "non_cbdc_or_off_scope", "duplicate_candidate", "other", "not_extracted_by_provider"] } };
  candidates.getRange(`W4:W${candidateEnd}`).dataValidation = { rule: { type: "list", values: ["high", "medium", "low", "not_reported"] } };

  const dualEmpty = workbook.worksheets.getItem("Dual Empty Audit");
  dualEmpty.getRange("A1").values = [[`Dual Empty Audit — ${display} — SEALED`]];
  dualEmpty.getRange("A2").values = [["Both providers emitted zero candidates for these units. missed_claims=no encodes observed machine output only; the independent human audit determines whether a claim was actually missed."]];
  dualEmpty.getRange(`K4:M${dualEmptyEnd}`).values = sample.dual_empty_sample.map(() => [
    "no", "not_reported", "MACHINE OUTPUT ARCHIVE; no candidate emitted by either provider; not a human assessment of source content.",
  ]);
  dualEmpty.getRange(`L4:L${dualEmptyEnd}`).dataValidation = { rule: { type: "list", values: ["high", "medium", "low", "not_reported"] } };

  workbook.worksheets.getItem("Empty Supplements").getRange("A1").values = [[`Empty Supplements — ${display} — SEALED`]];
  workbook.worksheets.getItem("Contexts").getRange("A1").values = [[`Full source contexts — ${display} — SEALED`]];
  workbook.worksheets.getItem("QC Summary").getRange("A1").values = [[`QC Summary — ${display}`]];
  workbook.worksheets.getItem("QC Summary").getRange("A2").values = [["Machine-output completeness check. COMPLETE means the provider archive was mapped successfully; it is not a human-validity result."]];
  const lists = workbook.worksheets.getItem("Lists");
  lists.getRange("B11").values = [["not_extracted_by_provider"]];
  lists.getRange("G5").values = [["not_reported"]];
  const metadata = workbook.worksheets.getItem("Metadata");
  metadata.getRange("B5").values = [[`${display} (machine output)`]];
  metadata.getRange("B8").values = [["unblinded machine-output answer key; sealed until both human workbooks are hash-locked"]];

  const previews = {
    Instructions: "A1:F17",
    "Candidate Review": "A1:AB16",
    "Dual Empty Audit": "A1:O14",
    "Empty Supplements": "A1:M18",
    Contexts: "A1:G12",
    Codebook: "A1:F12",
    "QC Summary": "A1:D16",
    Lists: "A1:H12",
    Metadata: "A1:C18",
  };
  for (const [sheetName, range] of Object.entries(previews)) {
    const preview = await workbook.render({ sheetName, range, scale: 0.85, format: "png" });
    await fs.writeFile(path.join(previewDir, `${upper}_${sheetName.replaceAll(" ", "_")}.png`), new Uint8Array(await preview.arrayBuffer()));
  }
  const errors = await workbook.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    options: { useRegex: true, maxResults: 300 },
    summary: "AI reviewer workbook formula error scan",
  });
  const outputName = `VALIDATION_SAMPLE_v10_2e_${upper}_PREFILLED_SEALED.xlsx`;
  const outputPath = path.join(outputDir, outputName);
  const xlsx = await SpreadsheetFile.exportXlsx(workbook);
  await xlsx.save(outputPath);
  const bytes = await fs.readFile(outputPath);
  return {
    provider,
    file: outputName,
    bytes: bytes.length,
    sha256: sha256(bytes),
    candidate_rows: sample.candidates.length,
    emitted_candidates: sample.candidates.filter((row) => Number(row[`${provider}_statement_count`]) > 0).length,
    absent_candidates: sample.candidates.filter((row) => Number(row[`${provider}_statement_count`]) === 0).length,
    dual_empty_rows: sample.dual_empty_sample.length,
    primary_statement_rule: "lowest statement_id; all provider values retained in notes and the separate AI candidate master",
    confidence: "not_reported",
    formula_error_scan: errors.ndjson,
    sanitation: audit,
  };
}

const results = [await build("openai"), await build("claude")];
const manifest = {
  schema: "cbdc-v10.2e-prefilled-ai-reviewer-workbooks-v1",
  status: "sealed until both independent human workbooks are returned and hash-locked",
  semantics: {
    keep: "provider emitted the candidate; not a human validity judgment",
    exclude: "provider did not emit the candidate; exclusion_reason=not_extracted_by_provider",
    confidence: "not reported by either provider",
    dual_empty_no: "no candidate emitted; not a source-content judgment",
  },
  source_hashes: {
    template: sha256(await fs.readFile(templatePath)),
    sample_master: sha256(await fs.readFile(sampleMasterPath)),
    full_master: sha256(await fs.readFile(fullMasterPath)),
  },
  disagreement: {
    sample: disagreementSummary(sample.candidates),
    full: disagreementSummary(full.candidates),
  },
  workbooks: results,
};
await fs.writeFile(path.join(outputDir, "AI_REVIEWER_WORKBOOK_MANIFEST.json"), JSON.stringify(manifest, null, 2) + "\n", "utf8");
console.log(JSON.stringify(manifest));
