Extract every source-supported, design-relevant statement about the `project_owner` named in each input unit. Use the supplied 35-code codebook. Return only the compact JSON object required by `output_schema.json`; no rationale or commentary is requested.

## Scope

Retain a statement only when it is a complete claim about that authority's own CBDC project and it is one of:

1. an adopted or rejected design/policy decision or commitment;
2. an explicit issuer proposal, preference, or requirement;
3. a concrete own-system feature;
4. an empirical result from an executed own-project pilot or test;
5. a supported CBDC-specific risk, trade-off, limit, or operating rule.

Use `authority_note` as binding source context. Never infer ownership from `doc_id`, filename, country prefix, or nearby foreign examples. In consultation documents, retain the issuer's response or expressly labelled issuer preference; exclude respondent, consultant, workshop, and stakeholder material unless the issuer explicitly adopts it. In compendia or secondary official reports, retain only concrete claims explicitly attributed to the named focal issuer/project; exclude editorial generalisations, literature, and other jurisdictions.

Exclude headings, captions without a claim, glossaries, definitions, stakeholder lists, agendas, questions, option inventories, generic context, cited or foreign research, future research, plans merely to study or consult, hypothetical possibilities without an issuer position, and incomplete fragments. A sentence that something was discussed, studied, or may be possible is not a conclusion. A trailing fragment does not invalidate an earlier complete claim, but quote only the complete part.

## Coverage and spans

Read the whole unit. First identify all eligible conclusions, decisions, proposals, features, findings, and requirements; then check that every eligible claim is represented once. Do not stop after the first relevant paragraph. Do not retain a preamble when the unit contains a more specific conclusion.

Use one atomic claim per statement. Quote the smallest complete sufficient span verbatim in the original language. Preserve a list's lead-in and only the items needed for the claim. Do not paraphrase or silently repair OCR. Set `quote_en` to null for English; otherwise supply a faithful English translation. When a render is supplied, use it to verify or transcribe the quote and set `source_mode` accurately.

## Classification

Assign the code describing the claim's substantive content, not the document section or research process. When several codes are plausible, apply this order:

1. a specific substantive design family;
2. `SYS.design` for core architecture or operating model not captured more specifically;
3. `PROC.pilot_learning` only for an executed-pilot finding with no more specific substantive code;
4. `LEGAL.basis`, `INST.mandate`, and `OTHER.keep` only when their narrow definitions apply.

Specific boundaries:

- `TECH.DLT` is distributed/blockchain versus centralised ledger architecture. `TECH.TOKEN.*` is token/bearer/value versus account representation. They are not synonyms.
- `KYC.TIER` requires tiered customer due diligence or wallet KYC differentiated by limit or risk. Tiered staff authorisation or internal access control is not KYC.
- `KYC.INTERMED` covers which intermediary or central bank performs customer KYC/AML responsibilities; a generic mention of banks does not qualify.
- `PRIV.OFF` requires an offline-payment privacy property. Offline continuity, fraud, availability, or reach belongs to `OPS.resilience`, `AML.*`, `ADOPT.experience`, or `ACCESS.universal` as appropriate.
- `PRIV.PET` requires a named privacy-enhancing technique, not generic information security or governance.
- `PROG.generic` covers CBDC-specific conditional payment logic and confirmation, cancellation, or refund rules. General consumer law is excluded.
- `INTEROP.crossborder` requires an explicit cross-border flow, foreign jurisdiction/CBDC, corridor, remittance, or FX/cross-currency claim. Visa, Mastercard, card wallets, co-badging, and domestic rails alone are `INTEROP.domestic` when integration is the point.
- `ADOPT.experience` covers user or merchant convenience, acceptance, cost, incentives, and usability. Do not merge it with interoperability.
- `STAB.disintermediation` covers deposits, bank funding/balance sheets, lending, bank runs, and monetary-transmission effects; retain this family.
- `LEGAL.basis` is only CBDC-specific authority to issue, legal-tender status, or necessary CBDC legislation. It is not general financial-market regulation.
- `INST.mandate` is only a concrete CBDC governance or operating role. It is not a stakeholder list.

Use `odr=decision` for adopted/rejected features and commitments, `proposal` for explicit issuer preferences or requirements not yet adopted, and `finding` only for executed pilot/test results. For non-privacy codes use `privacy_direction=neutral` and `privacy_relation=not_applicable`. Strength is 3 for a clear commitment or central result, 2 for an explicit qualified claim, and 1 for a retained minor claim.

Process each unit independently. Return all eligible statements. Do not deduplicate across units; deterministic post-processing occurs after raw outputs are archived.
