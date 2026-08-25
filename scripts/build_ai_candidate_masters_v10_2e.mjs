import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const dataDir = process.argv[2];
const outputDir = process.argv[3];
const previewDir = process.argv[4];
if (!dataDir || !outputDir || !previewDir) {
  throw new Error("usage: build_ai_candidate_masters_v10_2e.mjs data_dir output_dir preview_dir");
}
await fs.mkdir(outputDir, { recursive: true });
await fs.mkdir(previewDir, { recursive: true });

const freeze = JSON.parse(await fs.readFile(path.join(dataDir, "AI_MASTER_FREEZE_MANIFEST.json"), "utf8"));
const COLORS = {
  navy: "#17324D",
  teal: "#137C8B",
  paleBlue: "#DCEAF4",
  paleGray: "#F4F7FA",
  paleRed: "#FCE4D6",
  paleGreen: "#DDEFE2",
  white: "#FFFFFF",
  ink: "#263238",
  grid: "#CCD5DF",
  red: "#9C0006",
};
const thin = { preset: "all", style: "thin", color: COLORS.grid };

function sha256(bytes) {
  return crypto.createHash("sha256").update(bytes).digest("hex");
}

function colName(index) {
  let value = index + 1;
  let result = "";
  while (value > 0) {
    const remainder = (value - 1) % 26;
    result = String.fromCharCode(65 + remainder) + result;
    value = Math.floor((value - 1) / 26);
  }
  return result;
}

function sanitize(value, audit) {
  if (typeof value === "string") {
    const cleaned = value.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\uFFFE\uFFFF]/g, "");
    audit.removed_illegal_xml_characters += value.length - cleaned.length;
    return cleaned;
  }
  if (Array.isArray(value)) return value.map((item) => sanitize(item, audit));
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, sanitize(item, audit)]));
  }
  return value;
}

function title(sheet, endColumn, text) {
  sheet.mergeCells(`A1:${endColumn}1`);
  sheet.getRange("A1").values = [[text]];
  sheet.getRange(`A1:${endColumn}1`).format = {
    fill: COLORS.navy,
    font: { bold: true, color: COLORS.white, size: 17 },
    verticalAlignment: "center",
  };
  sheet.getRange(`A1:${endColumn}1`).format.rowHeight = 30;
}

function subtitle(sheet, endColumn, text, warning = false) {
  sheet.mergeCells(`A2:${endColumn}2`);
  sheet.getRange("A2").values = [[text]];
  sheet.getRange(`A2:${endColumn}2`).format = {
    fill: warning ? COLORS.paleRed : COLORS.paleBlue,
    font: { bold: warning, italic: !warning, color: warning ? COLORS.red : COLORS.ink },
    wrapText: true,
    verticalAlignment: "center",
  };
  sheet.getRange(`A2:${endColumn}2`).format.rowHeight = 34;
}

function writeRows(sheet, startRow, rows, headers) {
  const chunkSize = 750;
  for (let offset = 0; offset < rows.length; offset += chunkSize) {
    const chunk = rows.slice(offset, offset + chunkSize).map((row) => headers.map((header) => row[header] ?? null));
    sheet.getRangeByIndexes(startRow - 1 + offset, 0, chunk.length, headers.length).values = chunk;
  }
}

function applyWidths(sheet, headers) {
  const wide = new Set([
    "authority_note", "candidate_span", "candidate_translation", "alternate_span", "alternate_translation", "source_excerpt",
    "openai_quotes", "openai_translations", "claude_quotes", "claude_translations", "quote", "quote_en", "source_text",
    "definition", "code_when", "dont_code_when", "meaning", "value",
  ]);
  const medium = new Set([
    "project_owner", "render_file", "selection_hash", "candidate_span_sha256", "openai_statement_ids", "claude_statement_ids",
    "statement_id", "context_unit_id", "alternate_context_unit_id", "unit_id", "block_id",
  ]);
  headers.forEach((header, index) => {
    const width = wide.has(header) ? 46 : medium.has(header) ? 30 : header.includes("probability") ? 18 : 16;
    sheet.getRange(`${colName(index)}:${colName(index)}`).format.columnWidth = width;
  });
}

function tableSheet(workbook, name, sheetTitle, rows, tableName, description) {
  const sheet = workbook.worksheets.add(name);
  sheet.showGridLines = false;
  const headers = rows.length ? Object.keys(rows[0]) : ["no_rows"];
  const lastColumn = colName(headers.length - 1);
  title(sheet, lastColumn, sheetTitle);
  subtitle(sheet, lastColumn, description);
  sheet.getRange(`A3:${lastColumn}3`).values = [headers];
  sheet.getRange(`A3:${lastColumn}3`).format = {
    fill: COLORS.teal,
    font: { bold: true, color: COLORS.white },
    wrapText: true,
    verticalAlignment: "center",
    horizontalAlignment: "center",
    borders: thin,
  };
  sheet.getRange(`A3:${lastColumn}3`).format.rowHeight = 42;
  if (rows.length) {
    writeRows(sheet, 4, rows, headers);
    const endRow = rows.length + 3;
    sheet.getRange(`A4:${lastColumn}${endRow}`).format = {
      font: { color: COLORS.ink, size: 10 },
      verticalAlignment: "top",
    };
    const table = sheet.tables.add(`A3:${lastColumn}${endRow}`, true, tableName);
    table.style = "TableStyleMedium2";
    // Keep large evidence tables scannable. Full text remains available in the
    // formula bar and exported cell value; row height carries no analytic meaning.
    sheet.getRange(`A4:${lastColumn}${endRow}`).format.wrapText = false;
    sheet.getRange(`A4:${lastColumn}${endRow}`).format.rowHeight = 18;
    for (const header of ["inclusion_probability", "survey_weight", "match_score"]) {
      const index = headers.indexOf(header);
      if (index >= 0) sheet.getRange(`${colName(index)}4:${colName(index)}${endRow}`).format.numberFormat = header === "inclusion_probability" ? "0.0000%" : "0.0000";
    }
    for (const header of ["ai_code_set_exact_match", "ai_odr_set_exact_match"]) {
      const index = headers.indexOf(header);
      if (index >= 0) {
        const range = sheet.getRange(`${colName(index)}4:${colName(index)}${endRow}`);
        range.conditionalFormats.add("containsText", { text: "TRUE", format: { fill: COLORS.paleGreen, font: { color: "#17663A" } } });
        range.conditionalFormats.add("containsText", { text: "FALSE", format: { fill: COLORS.paleRed, font: { color: COLORS.red } } });
      }
    }
  }
  applyWidths(sheet, headers);
  sheet.freezePanes.freezeRows(3);
  sheet.freezePanes.freezeColumns(Math.min(2, headers.length));
  return { sheet, headers, endRow: rows.length + 3, lastColumn };
}

const DEFINITIONS = {
  sample_case_id: "Blind SV identifier used in both reviewer workbooks.",
  sample_stratum: "Frozen language × provider-origin sampling stratum.",
  stratum_population: "Number of union candidates in the stratum.",
  stratum_sample: "Number selected from the stratum.",
  inclusion_probability: "Stratum-specific probability of selection.",
  survey_weight: "Inverse inclusion probability used for population estimates.",
  selection_rank_within_stratum: "Deterministic SHA-256 selection rank.",
  selection_hash: "Frozen selection hash; not an analytic variable.",
  candidate_id: "Stable identifier in the 6,949-candidate union.",
  origin_type: "Provider provenance: both, openai_only, or claude_only.",
  candidate_span: "Representative verbatim source span shown to the reviewer.",
  alternate_span: "Matched alternate-provider span when text differs.",
  source_excerpt: "Source context supplied for human assessment.",
  openai_codes: "Distinct OpenAI code1 values after within-provider same-span deduplication.",
  claude_codes: "Distinct Claude code1 values after within-provider same-span deduplication.",
  openai_odr: "Distinct OpenAI observation/decision/recommendation values.",
  claude_odr: "Distinct Claude observation/decision/recommendation values.",
  ai_code_set_exact_match: "TRUE when both providers are present and their code1 sets are identical.",
  ai_odr_set_exact_match: "TRUE when both providers are present and their ODR sets are identical.",
  match_score: "Frozen cross-provider span-overlap score; blank for single-provider candidates.",
  match_method: "Frozen cross-provider matching rule that produced the pair.",
  candidate_span_sha256: "SHA-256 of the representative candidate span.",
  provider: "Provider that emitted the underlying statement.",
  statement_id: "Stable provider/unit/ordinal identifier.",
  code1: "Provider-assigned primary code.",
  odr: "Provider-assigned observation/decision/recommendation type.",
  privacy_direction: "Provider-assigned privacy direction.",
  privacy_relation: "Provider-assigned privacy relation.",
  strength: "Provider-assigned strength, 1–3.",
};

function makeReadme(workbook, payload, candidateMeta, statementMeta) {
  const sheet = workbook.worksheets.getItem("README");
  sheet.showGridLines = false;
  title(sheet, "H", `CBDC v10.2e — AI candidate master — ${payload.scope === "full" ? "FULL UNION" : payload.reviewer}`);
  subtitle(sheet, "H", "SEALED ANSWER KEY — DO NOT OPEN UNTIL BOTH INDEPENDENT HUMAN-REVIEW WORKBOOKS ARE RETURNED AND HASH-LOCKED.", true);
  sheet.getRange("A4:H4").values = [["METRIC", "VALUE", "METRIC", "VALUE", "METRIC", "VALUE", "METRIC", "VALUE"]];
  sheet.getRange("A4:H4").format = { fill: COLORS.teal, font: { bold: true, color: COLORS.white }, horizontalAlignment: "center" };
  const candidateIdCol = colName(candidateMeta.headers.indexOf("candidate_id"));
  const originCol = colName(candidateMeta.headers.indexOf("origin_type"));
  const candidateEnd = candidateMeta.endRow;
  const statementEnd = statementMeta.endRow;
  sheet.getRange("A5:H6").values = [
    ["Candidate rows", null, "Provider statement rows", null, "Dual-empty audit rows", payload.dual_empty_sample.length, "Scope", payload.scope],
    ["OpenAI only", null, "Claude only", null, "Both providers", null, "Reviewer", payload.reviewer],
  ];
  sheet.getRange("B5").formulas = [[`=COUNTA('Candidates'!$${candidateIdCol}$4:$${candidateIdCol}$${candidateEnd})`]];
  sheet.getRange("D5").formulas = [[`=COUNTA('Provider Statements'!$A$4:$A$${statementEnd})`]];
  sheet.getRange("B6").formulas = [[`=COUNTIF('Candidates'!$${originCol}$4:$${originCol}$${candidateEnd},"openai_only")`]];
  sheet.getRange("D6").formulas = [[`=COUNTIF('Candidates'!$${originCol}$4:$${originCol}$${candidateEnd},"claude_only")`]];
  sheet.getRange("F6").formulas = [[`=COUNTIF('Candidates'!$${originCol}$4:$${originCol}$${candidateEnd},"both")`]];
  sheet.getRange("A5:H6").format = { borders: thin, verticalAlignment: "center" };
  sheet.getRange("A5:A6").format.fill = COLORS.paleGray;
  sheet.getRange("C5:C6").format.fill = COLORS.paleGray;
  sheet.getRange("E5:E6").format.fill = COLORS.paleGray;
  sheet.getRange("G5:G6").format.fill = COLORS.paleGray;
  sheet.getRange("B5:B6").format = { fill: COLORS.paleBlue, font: { bold: true, color: COLORS.navy }, horizontalAlignment: "center", borders: thin, numberFormat: "#,##0" };
  sheet.getRange("D5:D6").format = { fill: COLORS.paleBlue, font: { bold: true, color: COLORS.navy }, horizontalAlignment: "center", borders: thin, numberFormat: "#,##0" };
  sheet.getRange("F5:F6").format = { fill: COLORS.paleBlue, font: { bold: true, color: COLORS.navy }, horizontalAlignment: "center", borders: thin, numberFormat: "#,##0" };
  sheet.getRange("H5:H6").format = { fill: COLORS.paleBlue, font: { bold: true, color: COLORS.navy }, horizontalAlignment: "center", borders: thin };
  const notes = [
    ["Purpose", "Unblinded, row-level archive of every AI candidate and every underlying provider statement. It is the answer key for later comparison with human decisions."],
    ["Candidate grain", "One row per deduplicated union candidate. Provider code fields use ` || ` when within-provider same-span deduplication retained more than one distinct value."],
    ["Statement grain", "One row per underlying canonical provider statement. Use this sheet when a candidate-level aggregate contains multiple codes or ODR values."],
    ["Sample masters", "Martin and Dominik files contain the same 365 SV cases and 36 dual-empty units; only the reviewer label differs."],
    ["Timing rule", "Do not inspect this workbook, its previews, or its unblinded mapping before both blind reviewer workbooks are returned and hash-locked."],
    ["After lock", "Join Candidate Review.candidate_id to sample_case_id, calculate pre-consensus agreement, then adjudicate disagreements only."],
    ["Recall boundary", "Candidate masters support validity and coding-agreement estimates. They do not estimate full-production recall; use frozen calibration recall separately."],
  ];
  sheet.getRange(`A9:B${8 + notes.length}`).values = notes;
  sheet.getRange(`A9:A${8 + notes.length}`).format = { fill: COLORS.paleBlue, font: { bold: true, color: COLORS.navy }, borders: thin, verticalAlignment: "top" };
  sheet.getRange(`B9:B${8 + notes.length}`).format = { wrapText: true, borders: thin, verticalAlignment: "top" };
  sheet.getRange(`A9:B${8 + notes.length}`).format.rowHeight = 48;
  sheet.getRange("A18:H18").merge();
  sheet.getRange("A18").values = [[`Payload SHA-256: ${freeze.payload_hashes[payload.scope === "full" ? "master_full.json" : `master_${payload.reviewer.toLowerCase()}.json`]}`]];
  sheet.getRange("A18:H18").format = { fill: COLORS.paleGray, font: { color: COLORS.ink, size: 9 }, wrapText: true };
  for (const [col, width] of Object.entries({ A: 23, B: 75, C: 23, D: 16, E: 23, F: 16, G: 18, H: 22 })) sheet.getRange(`${col}:${col}`).format.columnWidth = width;
  sheet.freezePanes.freezeRows(2);
}

function makeDictionary(workbook, payload) {
  const fields = [];
  const seen = new Set();
  for (const [sheet, rows] of [["Candidates", payload.candidates], ["Provider Statements", payload.provider_statements], ["Dual Empty Sample", payload.dual_empty_sample]]) {
    if (!rows.length) continue;
    for (const field of Object.keys(rows[0])) {
      const key = `${sheet}|${field}`;
      if (seen.has(key)) continue;
      seen.add(key);
      fields.push({
        sheet,
        field,
        type: typeof rows[0][field],
        meaning: DEFINITIONS[field] ?? field.replaceAll("_", " "),
      });
    }
  }
  return tableSheet(workbook, "Data Dictionary", "Data dictionary", fields, "DataDictionaryTable", "Machine-readable field definitions. Formatting never carries analytic meaning.");
}

function makeProvenance(workbook, payloadName) {
  const rows = [
    { field: "schema", value: freeze.schema, meaning: "Freeze-manifest schema" },
    { field: "status", value: freeze.status, meaning: "Access-control state" },
    { field: "payload", value: payloadName, meaning: "Workbook source payload" },
    { field: "payload_sha256", value: freeze.payload_hashes[payloadName], meaning: "Source payload hash" },
    ...Object.entries(freeze.input_hashes).map(([field, value]) => ({ field: `input_${field}_sha256`, value, meaning: "Frozen input hash" })),
  ];
  return tableSheet(workbook, "Provenance", "Frozen provenance", rows, "ProvenanceTable", "Hash lineage for every machine input used to build this workbook.");
}

async function build(payloadName, outputName) {
  const audit = { removed_illegal_xml_characters: 0 };
  const raw = JSON.parse(await fs.readFile(path.join(dataDir, payloadName), "utf8"));
  const payload = sanitize(raw, audit);
  const workbook = Workbook.create();
  workbook.worksheets.add("README");
  const candidates = tableSheet(
    workbook,
    "Candidates",
    payload.scope === "full" ? "All 6,949 AI candidates" : `${payload.reviewer} — 365 sampled AI candidates`,
    payload.candidates,
    "CandidatesTable",
    "One row per deduplicated candidate. Provider identity and AI coding are unblinded in this sealed workbook.",
  );
  const statements = tableSheet(
    workbook,
    "Provider Statements",
    "Underlying provider statements",
    payload.provider_statements,
    "ProviderStatementsTable",
    "One row per canonical OpenAI or Claude statement retained inside a union candidate.",
  );
  tableSheet(
    workbook,
    "Dual Empty Sample",
    "Dual-empty audit sample",
    payload.dual_empty_sample,
    "DualEmptySampleTable",
    "Both providers returned zero candidates for each source unit. Included for later missed-claim-yield analysis.",
  );
  tableSheet(workbook, "Codebook", "Frozen codebook", payload.codebook, "CodebookTable", "Definitions applied by both providers and human reviewers.");
  makeDictionary(workbook, payload);
  makeProvenance(workbook, payloadName);
  makeReadme(workbook, payload, candidates, statements);

  const previews = [
    ["README", "A1:H18"],
    ["Candidates", `A1:${colName(Math.min(candidates.headers.length - 1, 15))}12`],
    ["Provider Statements", `A1:${colName(Math.min(Object.keys(payload.provider_statements[0]).length - 1, 15))}12`],
    ["Dual Empty Sample", "A1:J12"],
    ["Codebook", "A1:F12"],
    ["Data Dictionary", "A1:D18"],
    ["Provenance", "A1:C14"],
  ];
  for (const [sheetName, range] of previews) {
    const preview = await workbook.render({ sheetName, range, scale: 0.85, format: "png" });
    await fs.writeFile(path.join(previewDir, `${outputName}_${sheetName.replaceAll(" ", "_")}.png`), new Uint8Array(await preview.arrayBuffer()));
  }
  const errors = await workbook.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    options: { useRegex: true, maxResults: 300 },
    summary: "formula error scan",
  });
  const xlsx = await SpreadsheetFile.exportXlsx(workbook);
  const outputPath = path.join(outputDir, `${outputName}.xlsx`);
  await xlsx.save(outputPath);
  const bytes = await fs.readFile(outputPath);
  return {
    output: outputPath,
    sha256: sha256(bytes),
    bytes: bytes.length,
    candidates: payload.candidates.length,
    provider_statements: payload.provider_statements.length,
    dual_empty: payload.dual_empty_sample.length,
    payload: payloadName,
    payload_sha256: freeze.payload_hashes[payloadName],
    formula_error_scan: errors.ndjson,
    sanitation: audit,
  };
}

const specifications = [
  ["master_full.json", "AI_CANDIDATE_MASTER_v10_2e_FULL_SEALED"],
  ["master_martin.json", "AI_CANDIDATE_MASTER_v10_2e_MARTIN_SAMPLE_SEALED"],
  ["master_dominik.json", "AI_CANDIDATE_MASTER_v10_2e_DOMINIK_SAMPLE_SEALED"],
];
const results = [];
for (const [payload, output] of specifications) results.push(await build(payload, output));
const manifest = {
  schema: "cbdc-v10.2e-ai-master-workbooks-v1",
  status: freeze.status,
  workbooks: results,
};
await fs.writeFile(path.join(outputDir, "AI_MASTER_WORKBOOK_MANIFEST.json"), JSON.stringify(manifest, null, 2) + "\n", "utf8");
console.log(JSON.stringify(manifest));
