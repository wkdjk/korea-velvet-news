# Korea Velvet News — Translation Style Guide

> **Purpose:** Reference for CaptainQ and CommsQ when reviewing LLM-translated articles.
> **Scope:** Phase A plain-text English summaries for the DINZ audience.
> **Applies to:** `body_en`, `title_en` fields in Airtable Articles.

---

## 1. British English Essentials

Common Korean→English translation pitfalls to watch for:

| Wrong (US) | Correct (British) |
|------------|------------------|
| organize   | organise         |
| analyze    | analyse          |
| prioritize | prioritise       |
| recognize  | recognise        |
| color      | colour           |
| flavor     | flavour          |
| center     | centre           |
| license (noun) | licence    |
| program (general) | programme |
| program (software/code) | program ✓ (computing exception) |

---

## 2. Numbers and Units

| Rule | Example |
|------|---------|
| Spell out one to nine | "three companies", "nine months" |
| Digits for 10 and above | "12 brands", "45 respondents" |
| Percentages always use digits | "5%", "12.4%", "0.8%" |
| Korean won: ₩ symbol or KRW | "₩8.2 billion" or "KRW 8.2 billion" |
| Dates: Day Month Year, no ordinals | "9 May 2026" not "9th May 2026" |
| Large numbers: use words for clarity | "6 billion won" or "₩6 billion" |

---

## 3. Sentence Structure

- **Prefer active voice.** "MFDS updated the guidelines" not "The guidelines were updated by MFDS."
- Korean news often uses passive or nominalised constructions; convert to active English.
- Keep sentences under ~30 words. Break compound Korean sentences into two English sentences.
- Avoid starting a sentence with a number (reorder or spell it out).

---

## 4. Length Calibration

| Article length (Korean source) | English output |
|-------------------------------|----------------|
| ≤300 words | 3–5 sentences (one paragraph) |
| 300–700 words | 1–2 paragraphs |
| 700+ words | Intro paragraph + key points in flowing prose |

Phase B: `**bold**` is permitted for one or two key phrases per paragraph. No bullet points, no headers inside `body_en`.

---

## 5. Source Attribution Format

End every `body_en` with a blank line followed by:

```
Source: [Outlet name], [Day Month Year]
```

Examples:
- `Source: Money Today, 9 May 2026`
- `Source: MFDS Policy Briefing, 15 May 2026`
- `Source: Seoul Yakryeong Market Association, 16 May 2026`

No full stop at the end of the source line. No parentheses.

---

## 6. Glossary Compliance

- Every Korean term in the active Glossary that appears in `body_ko` **must** appear in `body_en` using the exact English equivalent.
- The translator retries automatically up to 2 times on glossary failures.
- If a Korean term has no Glossary entry, the translator inserts `[GLOSSARY GAP: term_ko]` as a searchable flag. Search `body_en` for `[GLOSSARY GAP]` when reviewing.
- When a gap is spotted, add the missing term to the Glossary table (`is_active` checked) and it will be used in subsequent translations.

---

## 7. Title Rules

- `title_en` must be ≤15 words.
- Factual, not sensational. Avoid exclamation marks.
- Capitalise headline-style: major words capitalised, articles/prepositions lowercase.
- Example: "KGC인삼공사 Launches New 녹용 SKU for Children" → "KGC Launches New Velvet Product Line for Children Under Seven"

---

## 8. Phase B Formatting Rules

- Use `**bold**` for one or two key phrases per paragraph.
- No italics, no headers, no bullet points inside `body_en`.
- Paragraph breaks: double newline (`\n\n`).
- The template converts `**text**` → `<strong>text</strong>` automatically.
