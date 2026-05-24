import json
import os
from pathlib import Path

import anthropic

from src.airtable.client import get_active_glossary

_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"
_MODEL = "claude-sonnet-4-6"
_MAX_RETRIES = 2


def _load_system_prompt(glossary: list[dict]) -> str:
    base = (_PROMPTS_DIR / "translator_system.md").read_text(encoding="utf-8")
    if not glossary:
        return base
    glossary_lines = "\n".join(f"- {g['term_ko']} → {g['term_en']}" for g in glossary)
    return f"{base}\n\n## Active Glossary\n\n{glossary_lines}"


def _validate_glossary(body_ko: str, body_en: str, glossary: list[dict]) -> list[dict]:
    """Return list of glossary entries missing from the English translation."""
    missing = []
    for term in glossary:
        if term["term_ko"] in body_ko and term["term_en"] not in body_en:
            missing.append(term)
    return missing


def _build_retry_message(missing: list[dict]) -> str:
    terms = ", ".join(f"'{t['term_ko']}' → '{t['term_en']}'" for t in missing)
    return (
        f"Your translation is missing mandatory glossary terms. "
        f"Please retranslate and ensure these terms appear exactly as specified: {terms}. "
        f"Return JSON only."
    )


def translate_article(article: dict) -> dict:
    """
    Translate an approved Korean article to English.

    article must have: id, title_ko, body_ko.
    Returns dict with title_en, body_en, and glossary_validated (bool).
    On failure returns status 'translate_failed'.
    """
    body_ko = article.get("body_ko", "") or ""
    if len(body_ko) < 100:
        return {"id": article["id"], "status": "translate_failed"}

    glossary = get_active_glossary()
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    system_prompt = _load_system_prompt(glossary)

    user_content = f"Title: {article['title_ko']}\n\nBody:\n{body_ko}"
    messages = [{"role": "user", "content": user_content}]

    for attempt in range(_MAX_RETRIES + 1):
        response = client.messages.create(
            model=_MODEL,
            max_tokens=1024,
            system=system_prompt,
            messages=messages,
        )
        raw = response.content[0].text.strip()

        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            if attempt < _MAX_RETRIES:
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user", "content": "Your response was not valid JSON. Return JSON only: {\"title_en\": \"...\", \"body_en\": \"...\"}"})
                continue
            return {"id": article["id"], "status": "translate_failed"}

        missing = _validate_glossary(article["body_ko"], result.get("body_en", ""), glossary)
        if not missing:
            return {
                "id": article["id"],
                "title_en": result["title_en"],
                "body_en": result["body_en"],
                "glossary_validated": True,
            }

        if attempt < _MAX_RETRIES:
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": _build_retry_message(missing)})
        else:
            return {"id": article["id"], "status": "translate_failed"}

    return {"id": article["id"], "status": "translate_failed"}
