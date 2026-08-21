Extract every source-supported, design-relevant statement about the issuing authority's own CBDC project from the supplied input units. Use the supplied 35-code codebook. Return only the JSON object required by `output_schema.json`; do not add commentary.

Keep a statement only when it is a complete substantive claim and at least one of these is true:

- the issuer decides, commits to, rejects, prefers, or explicitly proposes a CBDC design or policy;
- the issuer reports a concrete feature of its own CBDC system;
- the document reports an empirical result from an executed own-project pilot or test;
- the issuer states a supported CBDC-specific risk, trade-off, limit, requirement, or operating rule.

Exclude headings, captions without a claim, glossaries, definitions, generic context, cited literature, foreign projects, stakeholder lists, questions, agendas, consultation or research plans, possibilities without an issuer position, and incomplete fragments. Exclude preliminary consultant or workshop material unless the issuer explicitly adopts it. A statement that something was discussed, studied, or will be researched is not a design conclusion. Search the whole unit for the conclusion rather than extracting its preamble.

Relevance and classification are separate decisions. If a complete own-project claim is relevant but no specific family fits, use `OTHER.keep`. Never retain text merely because it contains a codebook keyword.

Quote the smallest complete sufficient span verbatim in the original language. Do not paraphrase, repair OCR silently, or use a translation as `quote`. Preserve a list's lead-in and the necessary list items. Set `quote_en` to null for English; otherwise provide a faithful English translation. When a render is supplied, use it to verify or transcribe the original-language quote and set `source_mode` accordingly.

Classification constraints:

- `TECH.DLT` is distributed-ledger/blockchain versus centralized-ledger architecture. `TECH.TOKEN.*` is token/bearer/value versus account representation. Do not treat them as synonyms.
- `PRIV.OFF` requires a privacy property of offline payment. Connectivity, fraud, continuity, or resilience without a privacy claim belongs elsewhere.
- `PRIV.PET` requires an actual privacy-enhancing technique, not generic internal information security or governance.
- `PROG.generic` includes programmable or conditional payment logic and, for this study, CBDC-specific confirmation, cancellation, or refund rules. General consumer law without CBDC payment logic is excluded.
- `PROC.pilot_learning` requires an empirical result from an executed pilot or test. A plan, agenda, working-group purpose, or future research does not qualify.

Use `odr=decision` for adopted/rejected features and commitments, `proposal` for explicit recommendations or preferences not yet adopted, and `finding` only for empirical pilot/test results. For non-privacy codes use `privacy_direction=neutral` and `privacy_relation=not_applicable`. Strength is 3 for a clear commitment or central result, 2 for an explicit but qualified claim, and 1 for a retained minor claim.

Process each input unit independently. Return every eligible statement, including multiple distinct claims in one block. Do not deduplicate across units; deterministic post-processing handles overlaps after raw outputs are archived.
