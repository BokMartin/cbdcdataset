# Provider-prefilled reviewer workbooks

OpenAI and Claude machine outputs were mapped into the same row and column structure as the two blind human workbooks. The plaintext workbooks remain outside Git; this directory stores only their SHA-256 seal and methodological semantics.

In these answer keys, `keep` means the provider emitted the candidate. `exclude` with `not_extracted_by_provider` means the provider did not emit it. These values are not human relevance judgments. `not_reported` is used instead of inventing provider confidence. For dual-empty units, `missed_claims=no` records zero provider output and does not assert that no eligible source claim exists.

Do not disclose the provider workbooks before both human workbooks are returned and hash-locked. After lock, join on `candidate_id`, retain both provider assignments, calculate pre-consensus human agreement and human-to-provider agreement, and adjudicate human disagreements separately.
