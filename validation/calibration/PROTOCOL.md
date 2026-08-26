# v10.2 final calibration candidate

This is the single cause-mapped revision permitted after the sealed v10.1 calibration. It uses the same 78 development pages and frozen renders. It changes only prospective metadata, scope wording, code boundaries, and the shared schema's integer constraint. The 40-page reserve remains sealed.

The changes address documented causes rather than individual model errors:

- source authority is explicit and must not be inferred from filenames;
- issuer responses/preferences are separated from consultant, respondent, literature, and foreign material;
- a whole-unit coverage pass targets missed conclusions without semantic screening;
- atomic complete spans exclude fragments while preserving complete claims before a trailing fragment;
- specific substantive codes take precedence over process/audit-only codes;
- high-confusion code boundaries are explicit;
- `strength` uses the same `[1,2,3]` schema for both providers.

Both models receive identical prompt, codebook, inputs, authority metadata, schema, and renders. Provider task files contain interface instructions only. Human labels, prior model outputs, and the reserve are excluded from both packages. Raw results are archived and hashed before span checking, matching, or deduplication. One source-only retry is allowed for failed units; unsupported spans remain rejected.

Evaluate Model A, Model B, and their source-verified union against the author-confirmed v10.2 development reference. Apply the existing gates without relaxation: E1 recall >=0.90 with document-cluster bootstrap lower bound >=0.85; E2 subgroup recall >=0.85 when n>=15; E3 precision >=0.80 and workload <=3x reference; S1 span fidelity >=0.95; C1 classification recall >=0.80 when n>=15. Calibration performance is development evidence, not the paper's confirmatory result.

Two prospective claims are distinguished before this run. A fully automated extraction-and-classification claim requires E1, E2, E3, S1, and C1. An LLM-assisted candidate-retrieval claim requires E1, E2, E3, and S1; if C1 fails, every retained statement receives its final code through documented human adjudication and the paper must not claim automated classification. C1 is still reported unchanged. This is a different production workflow, not a relaxed classification gate.

If a predeclared production rule passes, freeze prompt, codebook, model versions, provider settings, inputs, verifier, matcher, deduplication, human-adjudication rule if used, and hashes before opening the reserve once. Do not tune after reserve access. If no retrieval rule passes, report the extraction as exploratory. If retrieval passes but C1 fails, use only the assisted-retrieval claim and disclose the human coding workload.
