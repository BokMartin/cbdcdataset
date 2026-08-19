import re
import unicodedata
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CONTEXT_TOKENS = 1_600
PROMPT_OVERHEAD = 350
MIN_QUOTE_CHARS = 10
FOLD = {"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-", "\u00ad": ""}


def chars_per_token(text):
    if not text:
        return 4.0
    cjk = sum("\u4e00" <= char <= "\u9fff" for char in text)
    return 2.0 if cjk / len(text) > 0.15 else 4.0


def split_oversized(start, end, text, budget):
    segment = text[start:end]
    parts, current = [], start
    for match in re.finditer(r"[^.!?。？！]+[.!?。？！]+\s*|[^.!?。？！]+$", segment):
        sentence_start, sentence_end = start + match.start(), start + match.end()
        if sentence_end - current > budget and current < sentence_start:
            parts.append((current, sentence_start))
            current = sentence_start
        while sentence_end - current > budget:
            parts.append((current, current + budget))
            current += budget
    if current < end:
        parts.append((current, end))
    return parts


def chunk_page(text, context_tokens=CONTEXT_TOKENS, prompt_overhead=PROMPT_OVERHEAD):
    budget = int((context_tokens - prompt_overhead) * chars_per_token(text))
    if budget <= 0:
        raise ValueError("context_tokens must exceed prompt_overhead")
    paragraphs = []
    for match in re.finditer(r"[^\n]+(?:\n(?!\n)[^\n]+)*", text):
        if not match.group().strip():
            continue
        start, end = match.span()
        paragraphs.extend(split_oversized(start, end, text, budget) if end - start > budget else [(start, end)])
    chunks, current = [], []
    for start, end in paragraphs:
        if current and end - current[0][0] > budget:
            chunks.append((current[0][0], current[-1][1]))
            overlap = current[-1]
            current = [overlap] if end - overlap[0] <= budget else []
        current.append((start, end))
    if current:
        chunks.append((current[0][0], current[-1][1]))
    result = [(f"c{i:03d}", start, end, text[start:end]) for i, (start, end) in enumerate(chunks, 1)]
    assert all(end - start <= budget for _, start, end, _ in result)
    return result


def normalized_with_map(text):
    output, offsets, previous_space = [], [], False
    for offset, char in enumerate(text):
        char = FOLD.get(char, char)
        if not char:
            continue
        if char.isspace():
            if previous_space or not output:
                continue
            output.append(" ")
            offsets.append(offset)
            previous_space = True
        else:
            for normalized in unicodedata.normalize("NFD", char).casefold():
                output.append(normalized)
                offsets.append(offset)
            previous_space = False
    if output and output[-1] == " ":
        output.pop()
        offsets.pop()
    return "".join(output), offsets


def verify_span(quote, source):
    quote = (quote or "").strip()
    if len(quote) < MIN_QUOTE_CHARS:
        return {"status": "invalid_quote", "start": -1, "end": -1, "method": "", "match_count": 0, "ambiguous": False}
    matches = [match.start() for match in re.finditer(re.escape(quote), source)]
    if matches:
        return {"status": "exact", "start": matches[0], "end": matches[0] + len(quote),
                "method": "exact", "match_count": len(matches), "ambiguous": len(matches) > 1}
    normalized_quote, _ = normalized_with_map(quote)
    normalized_source, offsets = normalized_with_map(source)
    if normalized_quote:
        matches = [match.start() for match in re.finditer(re.escape(normalized_quote), normalized_source)]
        if matches:
            start = offsets[matches[0]]
            end = offsets[matches[0] + len(normalized_quote) - 1] + 1
            return {"status": "normalized", "start": start, "end": end,
                    "method": "ws+nfd+quotefold+casefold", "match_count": len(matches), "ambiguous": len(matches) > 1}
    return {"status": "fuzzy_fail", "start": -1, "end": -1, "method": "", "match_count": 0, "ambiguous": False}


def selftest():
    latin = "X" * 5_000 + ".\n\n" + "Y" * 2_000 + "."
    assert all(end - start <= 5_000 for _, start, end, _ in chunk_page(latin))
    cjk = "汉" * 4_000
    assert all(end - start <= 2_500 for _, start, end, _ in chunk_page(cjk))
    source = 'Text says “Managed   Anonymity” here.'
    match = verify_span('"managed anonymity"', source)
    assert match["status"] == "normalized" and source[match["start"]:match["end"]] == "“Managed   Anonymity”"
    unicode_source = "Prefix cafe\u0301 privacy suffix"
    match = verify_span("café privacy", unicode_source)
    assert unicode_source[match["start"]:match["end"]] == "cafe\u0301 privacy"
    assert verify_span("repeated span", "repeated span ... repeated span")["ambiguous"]

    subcodes = pd.read_csv(ROOT / "data/subcodes.csv", keep_default_na=False)
    candidates = pd.read_csv(ROOT / "data/candidates.csv", keep_default_na=False)
    rows = subcodes.merge(candidates[["seg_id", "quote", "quote_en"]], on="seg_id", how="left")
    counts = {name: 0 for name in ["exact", "normalized", "fuzzy_fail", "invalid_quote"]}
    for row in rows.itertuples():
        evidence = str(getattr(row, "v6_evidence", "") or "")
        if evidence:
            source = f"{row.quote_en}\n{row.quote}"
            counts[verify_span(evidence, source)["status"]] += 1
    total = sum(counts.values())
    rate = (counts["exact"] + counts["normalized"]) / total if total else 0
    assert rate >= 0.95
    print(f"spans: self-test passed; evidence match {rate:.1%}")


if __name__ == "__main__":
    selftest()
