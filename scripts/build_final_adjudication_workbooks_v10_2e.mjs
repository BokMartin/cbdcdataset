import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const dataDir = process.argv[2];
const outputDir = process.argv[3];
const previewDir = process.argv[4];
if (!dataDir || !outputDir || !previewDir) {
  throw new Error("usage: build_workbooks.mjs data_dir output_dir preview_dir");
}

await fs.mkdir(outputDir, { recursive: true });
await fs.mkdir(previewDir, { recursive: true });
async function readFreezeManifest() {
  for (const name of ["SAMPLED_VALIDATION_FREEZE_MANIFEST.json", "HUMAN_REVIEW_FREEZE_MANIFEST.json"]) {
    try {
      return JSON.parse(await fs.readFile(path.join(dataDir, name), "utf8"));
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
    }
  }
  throw new Error(`no supported freeze manifest found in ${dataDir}`);
}
const freeze = await readFreezeManifest();
const sampled = freeze.schema === "cbdc-v10.2e-sampled-human-validation-freeze-v1";

const COLORS = {
  navy: "#17365D",
  teal: "#0F6B78",
  teal2: "#DDEBF7",
  paleBlue: "#EAF3F8",
  paleYellow: "#FFF2CC",
  paleGreen: "#E2F0D9",
  paleRed: "#FCE4D6",
  paleGray: "#F2F2F2",
  white: "#FFFFFF",
  ink: "#1F2937",
  grid: "#CBD5E1",
  muted: "#64748B",
};

const thinGrid = { preset: "all", style: "thin", color: COLORS.grid };
const titleFormat = {
  fill: COLORS.navy,
  font: { bold: true, color: COLORS.white, size: 16 },
  verticalAlignment: "center",
};
const subtitleFormat = {
  fill: COLORS.teal2,
  font: { italic: true, color: COLORS.ink },
  wrapText: true,
  verticalAlignment: "center",
};
const headerFormat = {
  fill: COLORS.teal,
  font: { bold: true, color: COLORS.white },
  wrapText: true,
  verticalAlignment: "center",
  horizontalAlignment: "center",
  borders: thinGrid,
};

function sanitizeForXml(value, audit) {
  if (typeof value === "string") {
    const cleaned = value.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\uFFFE\uFFFF]/g, "");
    if (cleaned !== value) audit.removed_illegal_xml_characters += value.length - cleaned.length;
    return cleaned;
  }
  if (Array.isArray(value)) return value.map((x) => sanitizeForXml(x, audit));
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, sanitizeForXml(item, audit)]));
  }
  return value;
}

function writeTitle(sheet, range, text) {
  sheet.mergeCells(range);
  const cell = range.split(":")[0];
  sheet.getRange(cell).values = [[text]];
  sheet.getRange(range).format = titleFormat;
  sheet.getRange(range).format.rowHeight = 30;
}

function writeSubtitle(sheet, range, text) {
  sheet.mergeCells(range);
  const cell = range.split(":")[0];
  sheet.getRange(cell).values = [[text]];
  sheet.getRange(range).format = subtitleFormat;
  sheet.getRange(range).format.rowHeight = 34;
}

function setWidths(sheet, widths) {
  for (const [col, width] of Object.entries(widths)) {
    sheet.getRange(`${col}:${col}`).format.columnWidth = width;
  }
}

function applyQcColors(range) {
  range.conditionalFormats.add("containsText", {
    text: "COMPLETE",
    format: { fill: COLORS.paleGreen, font: { bold: true, color: "#2E5E18" } },
  });
  range.conditionalFormats.add("containsText", {
    text: "PENDING",
    format: { fill: COLORS.paleYellow, font: { color: "#7F6000" } },
  });
  range.conditionalFormats.add("containsText", {
    text: "INCOMPLETE",
    format: { fill: COLORS.paleRed, font: { bold: true, color: "#9C0006" } },
  });
  range.conditionalFormats.add("containsText", {
    text: "MISSING",
    format: { fill: COLORS.paleRed, font: { bold: true, color: "#9C0006" } },
  });
  range.conditionalFormats.add("containsText", {
    text: "SET_INITIALS",
    format: { fill: COLORS.paleRed, font: { bold: true, color: "#9C0006" } },
  });
  range.conditionalFormats.add("containsText", {
    text: "NEEDS_CONTEXT",
    format: { fill: COLORS.paleYellow, font: { bold: true, color: "#7F6000" } },
  });
}

function makeInstructions(workbook, payload) {
  const sheet = workbook.worksheets.add("Instructions");
  sheet.showGridLines = false;
  writeTitle(sheet, "A1:F1", sampled
    ? `CBDC v10.2e — blind probability validation sample — ${payload.reviewer}`
    : `CBDC v10.2e — blind final adjudication — ${payload.reviewer}`);
  sheet.getRange("A2:F2").merge();
  sheet.getRange("A2").values = [[sampled
    ? "Vyplňuj pouze žlutá pole. Oba hodnotitelé kódují tentýž zmrazený pravděpodobnostní vzorek; identita modelu, jeho kód i výběrová vrstva jsou skryté."
    : "Vyplňuj pouze žlutá pole. Identita modelu, jeho původní kód a členství v překryvu jsou záměrně skryté."]];
  sheet.getRange("A2:F2").format = subtitleFormat;
  sheet.getRange("A3").values = [["Reviewer initials"]];
  sheet.getRange("B3").values = [[""]];
  sheet.getRange("A3").format = headerFormat;
  sheet.getRange("B3").format = {
    fill: COLORS.paleYellow,
    font: { bold: true, color: COLORS.ink },
    borders: thinGrid,
    horizontalAlignment: "center",
  };
  sheet.getRange("D3").values = [["Candidate rows"]];
  sheet.getRange("E3").values = [[payload.candidates.length]];
  sheet.getRange("D4").values = [["Dual-empty rows"]];
  sheet.getRange("E4").values = [[payload.dual_empty_units.length]];
  sheet.getRange("D3:D4").format = headerFormat;
  sheet.getRange("E3:E4").format = { fill: COLORS.paleBlue, font: { bold: true }, borders: thinGrid, horizontalAlignment: "center" };

  const rows = [
    ["1. Candidate Review", "Rozhodni keep / exclude / needs_context. Keep znamená konkrétní, zdrojem podložené rozhodnutí, návrh nebo zjištění dané autority k jejímu CBDC. Obecný kontext, cizí projekty, citovaný výzkum a neadoptované názory vyřaď."],
    ["2. Kódování keep", "Vyplň final_code1, final_odr, privacy_direction, privacy_relation, strength a confidence. final_span_override použij jen pokud je zobrazený span příliš široký nebo nepřesný; vlož přesný podřetězec zdroje."],
    ["3. Kódování exclude", "Vyplň exclusion_reason a confidence. Pole s kódy mohou zůstat prázdná."],
    ["4. needs_context", "Použij jen když nelze rozhodnout ani po otevření plného textu na listu Contexts nebo odpovídajícího obrázku stránky."],
    ["5. Dual Empty Audit", "Jde o zvláštní zaslepený vzorek jednotek, kde oba modely nevrátily kandidáta. Odhaduje pouze výskyt přehlédnutých tvrzení mezi dual-empty jednotkami, nikoli recall celé produkce."],
    ["6. Empty Supplements", "Pokud v Dual Empty Audit zvolíš yes, přepiš každý chybějící přesný span do samostatného slotu a vyplň jeho finální kódování. Připraveno je pět slotů na jednotku."],
    ["7. Jazyk a obrázky", "U cizojazyčného zdroje kóduj jen tehdy, když mu rozumíš nebo máš spolehlivý překlad. render_file je relativní cesta v přiložené složce renders."],
    ["8. Dokončení", "QC Summary musí mít Candidate incomplete = 0, Candidate pending = 0, Empty incomplete = 0 a Empty pending = 0. needs_context musí být vyřešeno před konsensem."],
    ["9. Neotevírat rezervu", "Nepracuj s held-out reserve materiálem. Tento sešit patří jen k produkční kandidátní unii a předem zmrazenému dual-empty vzorku."],
  ];
  if (sampled) {
    rows.push(["10. Co vzorek měří", "Vzorek slouží k odhadu validity kandidátů a shody kódování. Produkční recall se z něj neodhaduje; v článku zůstává samostatný zmrazený kalibrační odhad."]);
    rows.push(["11. Nezávislost", "S druhým hodnotitelem neporovnávej rozhodnutí, dokud oba neodevzdáte uzamčené kopie. Poté se konsensem řeší jen neshody."]);
  }
  sheet.getRange(`A6:B${5 + rows.length}`).values = rows;
  sheet.getRange(`A6:A${5 + rows.length}`).format = { fill: COLORS.teal2, font: { bold: true, color: COLORS.navy }, wrapText: true, borders: thinGrid, verticalAlignment: "top" };
  sheet.getRange(`B6:B${5 + rows.length}`).format = { fill: COLORS.white, font: { color: COLORS.ink }, wrapText: true, borders: thinGrid, verticalAlignment: "top" };
  sheet.getRange(`A6:B${5 + rows.length}`).format.rowHeight = 52;
  setWidths(sheet, { A: 24, B: 92, C: 3, D: 22, E: 16, F: 3 });
  sheet.freezePanes.freezeRows(3);
  return sheet;
}

function makeCandidateReview(workbook, payload) {
  const sheet = workbook.worksheets.add("Candidate Review");
  sheet.showGridLines = false;
  writeTitle(sheet, "A1:AB1", sampled ? `Candidate Validation Sample — ${payload.reviewer}` : `Candidate Review — ${payload.reviewer}`);
  writeSubtitle(sheet, "A2:AB2", sampled
    ? "Každý řádek je kandidát z téhož zmrazeného pravděpodobnostního vzorku pro oba hodnotitele. Nejprve rozhodni P; žlutá pole Q–Z vyplň podle rozhodnutí. Zdroj a kontext neměň."
    : "Každý řádek je jeden deduplikovaný kandidát. Nejprve rozhodni P; žlutá pole Q–Z vyplň podle rozhodnutí. Zdroj a kontext neměň.");
  const headers = [
    "candidate_id", "candidate_span", "candidate_translation", "alternate_span", "alternate_translation", "source_excerpt",
    "context_unit_id", "alternate_context_unit_id", "doc_id", "page", "language", "project_owner", "authority_note", "source_mode", "render_file",
    "inclusion_decision", "final_code1", "final_odr", "privacy_direction", "privacy_relation", "strength", "exclusion_reason", "confidence",
    "final_span_override", "quote_en_override", "notes", "reviewer_initials", "qc_status",
  ];
  const start = 4;
  const end = start + payload.candidates.length - 1;
  sheet.getRange("A3:AB3").values = [headers];
  sheet.getRange("A3:AB3").format = headerFormat;
  sheet.getRange("A3:AB3").format.rowHeight = 42;
  const rows = payload.candidates.map((x) => [
    x.candidate_id, x.candidate_span, x.candidate_translation, x.alternate_span, x.alternate_translation, x.source_excerpt,
    x.context_unit_id, x.alternate_context_unit_id, x.doc_id, x.page, x.language, x.project_owner, x.authority_note, x.source_mode, x.render_file,
    "", "", "", "", "", "", "", "", "", "", "", "", "",
  ]);
  sheet.getRange(`A${start}:AB${end}`).values = rows;
  sheet.getRange(`A${start}:O${end}`).format = { fill: COLORS.paleBlue, font: { color: COLORS.ink }, wrapText: true, verticalAlignment: "top", borders: thinGrid };
  sheet.getRange(`P${start}:Z${end}`).format = { fill: COLORS.paleYellow, font: { color: COLORS.ink }, wrapText: true, verticalAlignment: "top", borders: thinGrid };
  sheet.getRange(`AA${start}:AB${end}`).format = { fill: COLORS.paleGray, font: { color: COLORS.ink }, wrapText: true, verticalAlignment: "top", borders: thinGrid };
  sheet.getRange(`AA${start}`).formulas = [["=IF('Instructions'!$B$3=\"\",\"\",'Instructions'!$B$3)"]];
  sheet.getRange(`AA${start}:AA${end}`).fillDown();
  sheet.getRange(`AB${start}`).formulas = [[`=IF(P${start}="","PENDING",IF('Instructions'!$B$3="","SET_INITIALS",IF(P${start}="keep",IF(OR(Q${start}="",R${start}="",S${start}="",T${start}="",U${start}="",W${start}=""),"INCOMPLETE_KEEP","COMPLETE"),IF(P${start}="exclude",IF(OR(V${start}="",W${start}=""),"INCOMPLETE_EXCLUDE","COMPLETE"),"NEEDS_CONTEXT"))))`]];
  sheet.getRange(`AB${start}:AB${end}`).fillDown();
  sheet.getRange(`P${start}:P${end}`).dataValidation = { rule: { type: "list", values: payload.lists.inclusion_decision } };
  sheet.getRange(`Q${start}:Q${end}`).dataValidation = { rule: { type: "list", formula1: `Codebook!$A$4:$A$${3 + payload.codebook.length}` } };
  sheet.getRange(`R${start}:R${end}`).dataValidation = { rule: { type: "list", values: payload.lists.odr } };
  sheet.getRange(`S${start}:S${end}`).dataValidation = { rule: { type: "list", values: payload.lists.privacy_direction } };
  sheet.getRange(`T${start}:T${end}`).dataValidation = { rule: { type: "list", values: payload.lists.privacy_relation } };
  sheet.getRange(`U${start}:U${end}`).dataValidation = { rule: { type: "list", values: payload.lists.strength.map(String) } };
  sheet.getRange(`V${start}:V${end}`).dataValidation = { rule: { type: "list", values: payload.lists.exclusion_reason } };
  sheet.getRange(`W${start}:W${end}`).dataValidation = { rule: { type: "list", values: payload.lists.confidence } };
  applyQcColors(sheet.getRange(`AB${start}:AB${end}`));
  const table = sheet.tables.add(`A3:AB${end}`, true, `CandidateReview${payload.reviewer}`);
  table.style = "TableStyleMedium2";
  table.showBandedRows = true;
  sheet.getRange(`P${start}:Z${end}`).format.fill = COLORS.paleYellow;
  sheet.getRange(`A${start}:AB${end}`).format.rowHeight = 62;
  sheet.freezePanes.freezeRows(3);
  sheet.freezePanes.freezeColumns(1);
  setWidths(sheet, {
    A: 15, B: 48, C: 38, D: 43, E: 34, F: 72, G: 22, H: 22, I: 27, J: 8, K: 10, L: 32, M: 49, N: 13, O: 30,
    P: 18, Q: 21, R: 13, S: 17, T: 19, U: 9, V: 28, W: 12, X: 48, Y: 38, Z: 38, AA: 16, AB: 21,
  });
  return { sheet, start, end };
}

function makeDualEmpty(workbook, payload) {
  const sheet = workbook.worksheets.add("Dual Empty Audit");
  sheet.showGridLines = false;
  writeTitle(sheet, "A1:O1", `Dual Empty Audit — ${payload.reviewer}`);
  writeSubtitle(sheet, "A2:O2", "Nezávislý audit jednotek, v nichž oba modely nevrátily kandidáta. Pokud K=yes, založ alespoň jeden přesný span na listu Empty Supplements.");
  const headers = ["empty_case_id", "unit_id", "doc_id", "page", "language", "project_owner", "authority_note", "source_mode", "render_file", "source_text", "missed_claims", "confidence", "notes", "reviewer_initials", "qc_status"];
  const start = 4;
  const end = start + payload.dual_empty_units.length - 1;
  sheet.getRange("A3:O3").values = [headers];
  sheet.getRange("A3:O3").format = headerFormat;
  sheet.getRange("A3:O3").format.rowHeight = 42;
  sheet.getRange(`A${start}:O${end}`).values = payload.dual_empty_units.map((x) => [
    x.empty_case_id, x.unit_id, x.doc_id, x.page, x.language, x.project_owner, x.authority_note, x.source_mode, x.render_file, x.source_text,
    "", "", "", "", "",
  ]);
  sheet.getRange(`A${start}:J${end}`).format = { fill: COLORS.paleBlue, wrapText: true, verticalAlignment: "top", borders: thinGrid };
  sheet.getRange(`K${start}:M${end}`).format = { fill: COLORS.paleYellow, wrapText: true, verticalAlignment: "top", borders: thinGrid };
  sheet.getRange(`N${start}:O${end}`).format = { fill: COLORS.paleGray, wrapText: true, verticalAlignment: "top", borders: thinGrid };
  sheet.getRange(`N${start}`).formulas = [["=IF('Instructions'!$B$3=\"\",\"\",'Instructions'!$B$3)"]];
  sheet.getRange(`N${start}:N${end}`).fillDown();
  const suppEnd = 3 + payload.dual_empty_units.length * payload.supplement_slots_per_unit;
  sheet.getRange(`O${start}`).formulas = [[`=IF(K${start}="","PENDING",IF('Instructions'!$B$3="","SET_INITIALS",IF(K${start}="yes",IF(COUNTIFS('Empty Supplements'!$B$4:$B$${suppEnd},B${start},'Empty Supplements'!$D$4:$D$${suppEnd},"<>")>0,"COMPLETE","MISSING_SUPPLEMENT"),IF(K${start}="no","COMPLETE","NEEDS_CONTEXT"))))`]];
  sheet.getRange(`O${start}:O${end}`).fillDown();
  sheet.getRange(`K${start}:K${end}`).dataValidation = { rule: { type: "list", values: payload.lists.missed_claims } };
  sheet.getRange(`L${start}:L${end}`).dataValidation = { rule: { type: "list", values: payload.lists.confidence } };
  applyQcColors(sheet.getRange(`O${start}:O${end}`));
  const table = sheet.tables.add(`A3:O${end}`, true, `DualEmpty${payload.reviewer}`);
  table.style = "TableStyleMedium2";
  table.showBandedRows = true;
  sheet.getRange(`K${start}:M${end}`).format.fill = COLORS.paleYellow;
  sheet.getRange(`A${start}:O${end}`).format.rowHeight = 92;
  sheet.freezePanes.freezeRows(3);
  sheet.freezePanes.freezeColumns(2);
  setWidths(sheet, { A: 15, B: 22, C: 27, D: 8, E: 10, F: 32, G: 50, H: 13, I: 30, J: 92, K: 16, L: 12, M: 38, N: 16, O: 22 });
  return { sheet, start, end };
}

function makeSupplements(workbook, payload) {
  const sheet = workbook.worksheets.add("Empty Supplements");
  sheet.showGridLines = false;
  writeTitle(sheet, "A1:M1", `Empty Supplements — ${payload.reviewer}`);
  writeSubtitle(sheet, "A2:M2", "Používej jen pro jednotky označené missed_claims=yes. exact_span musí být přesný podřetězec source_text; každý samostatný claim patří do vlastního řádku.");
  const headers = ["empty_case_id", "unit_id", "slot", "exact_span", "quote_en", "final_code1", "final_odr", "privacy_direction", "privacy_relation", "strength", "notes", "reviewer_initials", "qc_status"];
  const start = 4;
  const slots = [];
  for (const x of payload.dual_empty_units) {
    for (let i = 1; i <= payload.supplement_slots_per_unit; i += 1) {
      slots.push([x.empty_case_id, x.unit_id, i, "", "", "", "", "", "", "", "", "", ""]);
    }
  }
  const end = start + slots.length - 1;
  sheet.getRange("A3:M3").values = [headers];
  sheet.getRange("A3:M3").format = headerFormat;
  sheet.getRange("A3:M3").format.rowHeight = 42;
  sheet.getRange(`A${start}:M${end}`).values = slots;
  sheet.getRange(`A${start}:C${end}`).format = { fill: COLORS.paleBlue, borders: thinGrid, verticalAlignment: "top" };
  sheet.getRange(`D${start}:K${end}`).format = { fill: COLORS.paleYellow, wrapText: true, borders: thinGrid, verticalAlignment: "top" };
  sheet.getRange(`L${start}:M${end}`).format = { fill: COLORS.paleGray, wrapText: true, borders: thinGrid, verticalAlignment: "top" };
  sheet.getRange(`L${start}`).formulas = [["=IF('Instructions'!$B$3=\"\",\"\",'Instructions'!$B$3)"]];
  sheet.getRange(`L${start}:L${end}`).fillDown();
  sheet.getRange(`M${start}`).formulas = [[`=IF(D${start}="","UNUSED",IF('Instructions'!$B$3="","SET_INITIALS",IF(OR(F${start}="",G${start}="",H${start}="",I${start}="",J${start}=""),"INCOMPLETE","COMPLETE")))`]];
  sheet.getRange(`M${start}:M${end}`).fillDown();
  sheet.getRange(`F${start}:F${end}`).dataValidation = { rule: { type: "list", formula1: `Codebook!$A$4:$A$${3 + payload.codebook.length}` } };
  sheet.getRange(`G${start}:G${end}`).dataValidation = { rule: { type: "list", values: payload.lists.odr } };
  sheet.getRange(`H${start}:H${end}`).dataValidation = { rule: { type: "list", values: payload.lists.privacy_direction } };
  sheet.getRange(`I${start}:I${end}`).dataValidation = { rule: { type: "list", values: payload.lists.privacy_relation } };
  sheet.getRange(`J${start}:J${end}`).dataValidation = { rule: { type: "list", values: payload.lists.strength.map(String) } };
  applyQcColors(sheet.getRange(`M${start}:M${end}`));
  const table = sheet.tables.add(`A3:M${end}`, true, `EmptySupplements${payload.reviewer}`);
  table.style = "TableStyleMedium2";
  table.showBandedRows = true;
  sheet.getRange(`D${start}:K${end}`).format.fill = COLORS.paleYellow;
  sheet.getRange(`A${start}:M${end}`).format.rowHeight = 52;
  sheet.freezePanes.freezeRows(3);
  sheet.freezePanes.freezeColumns(3);
  setWidths(sheet, { A: 15, B: 22, C: 7, D: 60, E: 44, F: 21, G: 13, H: 17, I: 19, J: 9, K: 38, L: 16, M: 18 });
  return { sheet, start, end };
}

function makeContexts(workbook, payload) {
  const sheet = workbook.worksheets.add("Contexts");
  sheet.showGridLines = false;
  writeTitle(sheet, "A1:G1", `Full source contexts — ${payload.reviewer}`);
  writeSubtitle(sheet, "A2:G2", "Vyhledej context_unit_id z Candidate Review. Tento list je pouze referenční; nic zde neměň.");
  const headers = ["context_unit_id", "doc_id", "page", "language", "source_mode", "render_file", "source_text"];
  const start = 4;
  const end = start + payload.contexts.length - 1;
  sheet.getRange("A3:G3").values = [headers];
  sheet.getRange("A3:G3").format = headerFormat;
  sheet.getRange(`A${start}:G${end}`).values = payload.contexts.map((x) => [x.context_unit_id, x.doc_id, x.page, x.language, x.source_mode, x.render_file, x.source_text]);
  sheet.getRange(`A${start}:G${end}`).format = { fill: COLORS.paleBlue, wrapText: true, verticalAlignment: "top", borders: thinGrid };
  const table = sheet.tables.add(`A3:G${end}`, true, `Contexts${payload.reviewer}`);
  table.style = "TableStyleMedium2";
  table.showBandedRows = true;
  sheet.getRange(`A${start}:G${end}`).format.rowHeight = 110;
  sheet.freezePanes.freezeRows(3);
  sheet.freezePanes.freezeColumns(1);
  setWidths(sheet, { A: 22, B: 28, C: 8, D: 10, E: 13, F: 30, G: 110 });
  return { sheet, start, end };
}

function makeCodebook(workbook, payload) {
  const sheet = workbook.worksheets.add("Codebook");
  sheet.showGridLines = false;
  writeTitle(sheet, "A1:F1", "Frozen CBDC codebook");
  writeSubtitle(sheet, "A2:F2", "Používej přesně uvedené kódy. Primární kód má zachytit hlavní substantivní pointu tvrzení.");
  const headers = ["code", "family", "label", "definition", "code_when", "dont_code_when"];
  const start = 4;
  const end = start + payload.codebook.length - 1;
  sheet.getRange("A3:F3").values = [headers];
  sheet.getRange("A3:F3").format = headerFormat;
  sheet.getRange(`A${start}:F${end}`).values = payload.codebook.map((x) => [x.code, x.family, x.label, x.definition, x.code_when, x.dont_code_when]);
  sheet.getRange(`A${start}:F${end}`).format = { fill: COLORS.paleBlue, wrapText: true, verticalAlignment: "top", borders: thinGrid };
  const table = sheet.tables.add(`A3:F${end}`, true, `Codebook${payload.reviewer}`);
  table.style = "TableStyleMedium2";
  table.showBandedRows = true;
  sheet.getRange(`A${start}:F${end}`).format.rowHeight = 86;
  sheet.freezePanes.freezeRows(3);
  setWidths(sheet, { A: 22, B: 11, C: 30, D: 72, E: 72, F: 72 });
  return sheet;
}

function makeQc(workbook, payload, candidateEnd, emptyEnd, supplementEnd) {
  const sheet = workbook.worksheets.add("QC Summary");
  sheet.showGridLines = false;
  writeTitle(sheet, "A1:D1", `QC Summary — ${payload.reviewer}`);
  writeSubtitle(sheet, "A2:D2", "Odevzdej až po odstranění všech pending/incomplete stavů a vyřešení needs_context.");
  const rows = [
    ["Candidate total", "=COUNTA('Candidate Review'!$A$4:$A$" + candidateEnd + ")", "Expected", payload.candidates.length],
    ["Candidate complete", "=COUNTIF('Candidate Review'!$AB$4:$AB$" + candidateEnd + ",\"COMPLETE\")", "Target", payload.candidates.length],
    ["Candidate pending", "=COUNTIF('Candidate Review'!$AB$4:$AB$" + candidateEnd + ",\"PENDING\")", "Target", 0],
    ["Candidate incomplete", "=COUNTIF('Candidate Review'!$AB$4:$AB$" + candidateEnd + ",\"INCOMPLETE*\")+COUNTIF('Candidate Review'!$AB$4:$AB$" + candidateEnd + ",\"SET_INITIALS\")", "Target", 0],
    ["Candidate needs context", "=COUNTIF('Candidate Review'!$AB$4:$AB$" + candidateEnd + ",\"NEEDS_CONTEXT\")", "Target", 0],
    ["", "", "", ""],
    ["Dual-empty total", "=COUNTA('Dual Empty Audit'!$A$4:$A$" + emptyEnd + ")", "Expected", payload.dual_empty_units.length],
    ["Dual-empty complete", "=COUNTIF('Dual Empty Audit'!$O$4:$O$" + emptyEnd + ",\"COMPLETE\")", "Target", payload.dual_empty_units.length],
    ["Dual-empty pending", "=COUNTIF('Dual Empty Audit'!$O$4:$O$" + emptyEnd + ",\"PENDING\")", "Target", 0],
    ["Dual-empty incomplete", "=COUNTIF('Dual Empty Audit'!$O$4:$O$" + emptyEnd + ",\"MISSING_SUPPLEMENT\")+COUNTIF('Dual Empty Audit'!$O$4:$O$" + emptyEnd + ",\"SET_INITIALS\")", "Target", 0],
    ["Dual-empty needs context", "=COUNTIF('Dual Empty Audit'!$O$4:$O$" + emptyEnd + ",\"NEEDS_CONTEXT\")", "Target", 0],
    ["Supplements used", "=COUNTIF('Empty Supplements'!$M$4:$M$" + supplementEnd + ",\"<>UNUSED\")", "Information", ""],
    ["Supplements incomplete", "=COUNTIF('Empty Supplements'!$M$4:$M$" + supplementEnd + ",\"INCOMPLETE\")+COUNTIF('Empty Supplements'!$M$4:$M$" + supplementEnd + ",\"SET_INITIALS\")", "Target", 0],
  ];
  sheet.getRange("A3:D3").values = [["Metric", "Current", "Reference", "Value"]];
  sheet.getRange("A3:D3").format = headerFormat;
  const vals = rows.map((r) => [r[0], "", r[2], r[3]]);
  sheet.getRange(`A4:D${3 + rows.length}`).values = vals;
  for (let i = 0; i < rows.length; i += 1) {
    if (rows[i][1]) sheet.getRange(`B${4 + i}`).formulas = [[rows[i][1]]];
  }
  sheet.getRange(`A4:D${3 + rows.length}`).format = { borders: thinGrid, wrapText: true, verticalAlignment: "center" };
  sheet.getRange(`A4:A${3 + rows.length}`).format.fill = COLORS.teal2;
  sheet.getRange(`B4:B${3 + rows.length}`).format.fill = COLORS.paleYellow;
  sheet.getRange(`C4:D${3 + rows.length}`).format.fill = COLORS.paleGray;
  for (const range of ["B4:B5", "B10:B11"]) {
    const firstRow = range.match(/\d+/)[0];
    sheet.getRange(range).conditionalFormats.addCustom(`=B${firstRow}=$D${firstRow}`, { fill: COLORS.paleGreen, font: { color: "#2E5E18", bold: true } });
    sheet.getRange(range).conditionalFormats.addCustom(`=B${firstRow}<>$D${firstRow}`, { fill: COLORS.paleRed, font: { color: "#9C0006", bold: true } });
  }
  for (const range of ["B6:B8", "B12:B14", "B16:B16"]) {
    const firstRow = range.match(/\d+/)[0];
    sheet.getRange(range).conditionalFormats.addCustom(`=B${firstRow}=0`, { fill: COLORS.paleGreen, font: { color: "#2E5E18", bold: true } });
    sheet.getRange(range).conditionalFormats.addCustom(`=B${firstRow}<>0`, { fill: COLORS.paleRed, font: { color: "#9C0006", bold: true } });
  }
  sheet.getRange(`B4:B${3 + rows.length}`).format.numberFormat = "0";
  setWidths(sheet, { A: 31, B: 16, C: 16, D: 16 });
  sheet.freezePanes.freezeRows(3);
  return sheet;
}

function makeLists(workbook, payload) {
  const sheet = workbook.worksheets.add("Lists");
  sheet.showGridLines = false;
  const entries = [
    ["inclusion_decision", payload.lists.inclusion_decision],
    ["exclusion_reason", payload.lists.exclusion_reason],
    ["odr", payload.lists.odr],
    ["privacy_direction", payload.lists.privacy_direction],
    ["privacy_relation", payload.lists.privacy_relation],
    ["strength", payload.lists.strength],
    ["confidence", payload.lists.confidence],
    ["missed_claims", payload.lists.missed_claims],
  ];
  const maxLen = Math.max(...entries.map((x) => x[1].length));
  sheet.getRange(`A1:H${maxLen + 1}`).values = Array.from({ length: maxLen + 1 }, (_, row) => entries.map(([name, values]) => row === 0 ? name : (values[row - 1] ?? "")));
  sheet.getRange("A1:H1").format = headerFormat;
  sheet.getRange(`A2:H${maxLen + 1}`).format = { fill: COLORS.paleGray, borders: thinGrid };
  setWidths(sheet, { A: 22, B: 37, C: 17, D: 19, E: 21, F: 12, G: 14, H: 16 });
  sheet.freezePanes.freezeRows(1);
  return sheet;
}

function makeMetadata(workbook, payload) {
  const sheet = workbook.worksheets.add("Metadata");
  sheet.showGridLines = false;
  writeTitle(sheet, "A1:C1", "Frozen review metadata");
  const commonRows = [
    ["schema", payload.schema, "Workbook payload schema"],
    ["reviewer", payload.reviewer, "Assigned reviewer"],
    ["created_utc", sampled ? "2026-08-25T00:00:00Z" : new Date().toISOString(), sampled ? "Protocol freeze date (normalized)" : "Workbook build time"],
    ["seed", freeze.seed, "Deterministic allocation/sample seed"],
    ["blinding", payload.blinding, "Fields excluded from coder view"],
    ["candidate_rows", payload.candidates.length, "Rows assigned to this reviewer"],
    ["dual_empty_rows", payload.dual_empty_units.length, "Common independently reviewed sample"],
    ["supplement_slots_per_unit", payload.supplement_slots_per_unit, "Maximum preallocated slots"],
  ];
  const rows = sampled ? [
    ...commonRows,
    ["population_candidates", freeze.population_candidates, "Deduplicated production candidate union"],
    ["sample_candidates", freeze.sample_candidates, "Common probability sample coded by both reviewers"],
    ["sample_fraction", freeze.sample_fraction, "Sample / candidate population"],
    ["confidence_level", freeze.confidence_level, "Design confidence level"],
    ["target_margin", freeze.target_margin, "Worst-case target half-width"],
    ["achieved_worst_case_margin", freeze.achieved_worst_case_margin, "Finite-population corrected half-width at p=0.5"],
    ["sampled_documents", freeze.sampled_documents, "Documents represented in sample"],
    ["dual_empty_eligible", freeze.dual_empty_population, "Separate dual-empty sampling frame"],
    ["dual_empty_sample", freeze.dual_empty_sample, "Common dual-empty sample"],
    ["payload_sha256", freeze.hashes[`payload_${payload.reviewer.toLowerCase()}`], "Blind payload hash"],
    ["selection_rule", "SHA-256 rank without replacement within language × provider-origin stratum", "Frozen probability selection"],
    ["analysis_weight", "inverse inclusion probability", "Required for population point estimates"],
  ] : [
    ...commonRows,
    ["union_candidates", freeze.counts.deduplicated_union_candidates, "Frozen union before reviewer allocation"],
    ["independent_overlap_candidates", freeze.counts.independent_overlap_candidates, "Stored aggregate only; row membership remains blinded"],
    ["overlap_fraction", freeze.counts.overlap_fraction, "Frozen protocol proportion"],
    ["dual_empty_eligible", freeze.counts.dual_empty_eligible_units, "Sampling frame size"],
    ["dual_empty_sample", freeze.counts.dual_empty_sample_units, "Frozen sample size"],
    ["package_inputs_sha256", freeze.hashes.package_inputs, "Production package input hash"],
    ["codebook_sha256", freeze.hashes.codebook, "Frozen codebook hash"],
    ["source_authority_sha256", freeze.hashes.source_authority, "Authority mapping hash"],
    ["payload_sha256", freeze.hashes[`payload_${payload.reviewer.toLowerCase()}`], "Blind payload hash"],
    ["allocation_rule", freeze.rules.single_assignment, "Deterministic single-review assignment"],
    ["overlap_rule", freeze.rules.overlap, "Aggregate protocol rule"],
    ["dual_empty_rule", freeze.rules.dual_empty_sample, "Aggregate protocol rule"],
  ];
  sheet.getRange("A3:C3").values = [["Field", "Value", "Meaning"]];
  sheet.getRange("A3:C3").format = headerFormat;
  sheet.getRange(`A4:C${3 + rows.length}`).values = rows;
  sheet.getRange(`A4:C${3 + rows.length}`).format = { fill: COLORS.paleBlue, wrapText: true, verticalAlignment: "top", borders: thinGrid };
  sheet.getRange(`A4:C${3 + rows.length}`).format.rowHeight = 42;
  if (sampled) sheet.getRange("B14:B17").format.numberFormat = "0.0%";
  else sheet.getRange("B14").format.numberFormat = "0.0%";
  setWidths(sheet, { A: 31, B: 92, C: 48 });
  sheet.freezePanes.freezeRows(3);
  return sheet;
}

async function build(payloadPath) {
  const sanitationAudit = { removed_illegal_xml_characters: 0 };
  const payload = sanitizeForXml(JSON.parse(await fs.readFile(payloadPath, "utf8")), sanitationAudit);
  const workbook = Workbook.create();
  makeInstructions(workbook, payload);
  const candidate = makeCandidateReview(workbook, payload);
  const empty = makeDualEmpty(workbook, payload);
  const supplements = makeSupplements(workbook, payload);
  makeContexts(workbook, payload);
  makeCodebook(workbook, payload);
  makeQc(workbook, payload, candidate.end, empty.end, supplements.end);
  makeLists(workbook, payload);
  makeMetadata(workbook, payload);

  const base = sampled
    ? `VALIDATION_SAMPLE_v10_2e_${payload.reviewer.toUpperCase()}`
    : `FINAL_ADJUDICATION_v10_2e_${payload.reviewer.toUpperCase()}`;
  const renderRanges = {
    "Instructions": sampled ? "A1:F17" : "A1:F15",
    "Candidate Review": "A1:AB16",
    "Dual Empty Audit": "A1:O14",
    "Empty Supplements": "A1:M18",
    "Contexts": "A1:G12",
    "Codebook": "A1:F12",
    "QC Summary": "A1:D16",
    "Lists": "A1:H12",
    "Metadata": "A1:C23",
  };
  for (const [sheetName, range] of Object.entries(renderRanges)) {
    const preview = await workbook.render({ sheetName, range, scale: 0.8, format: "png" });
    await fs.writeFile(path.join(previewDir, `${base}_${sheetName.replaceAll(" ", "_")}.png`), new Uint8Array(await preview.arrayBuffer()));
  }
  const xlsx = await SpreadsheetFile.exportXlsx(workbook);
  const outputPath = path.join(outputDir, `${base}.xlsx`);
  await xlsx.save(outputPath);
  await fs.writeFile(path.join(outputDir, `${base}_xml_sanitation.json`), JSON.stringify(sanitationAudit, null, 2) + "\n", "utf8");
  return { payload, workbook, outputPath, base, sanitationAudit };
}

const built = [];
for (const name of ["payload_martin.json", "payload_dominik.json"]) {
  built.push(await build(path.join(dataDir, name)));
}
for (const item of built) {
  const summary = await item.workbook.inspect({ kind: "sheet", include: "id,name", maxChars: 5000 });
  await fs.writeFile(path.join(outputDir, `${item.base}_sheets.ndjson`), summary.ndjson, "utf8");
  const qc = await item.workbook.inspect({ kind: "region", sheetId: "QC Summary", range: "A1:D16", maxChars: 10000 });
  await fs.writeFile(path.join(outputDir, `${item.base}_qc.ndjson`), qc.ndjson, "utf8");
  const candidate = await item.workbook.inspect({ kind: "region", sheetId: "Candidate Review", range: "A1:AB8", maxChars: 18000 });
  await fs.writeFile(path.join(outputDir, `${item.base}_candidate.ndjson`), candidate.ndjson, "utf8");
}

console.log(JSON.stringify(built.map((x) => ({ reviewer: x.payload.reviewer, output: x.outputPath, candidates: x.payload.candidates.length, dual_empty: x.payload.dual_empty_units.length, removed_illegal_xml_characters: x.sanitationAudit.removed_illegal_xml_characters }))));
