import json
import os
import re
from pathlib import Path

import anthropic

_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"
_MODEL = "claude-haiku-4-5-20251001"
_BATCH_SIZE = 10


def _load_system_prompt() -> str:
    return (_PROMPTS_DIR / "classifier_system.md").read_text(encoding="utf-8")


def _build_user_message(articles: list[dict]) -> str:
    lines = ["Classify the following articles. Return a JSON array only.\n"]
    for a in articles:
        body_preview = (a.get("body_ko") or a.get("description") or "")[:200]
        lines.append(f"ID: {a['id']}\nTitle: {a['title_ko']}\nBody: {body_preview}\n---")
    return "\n".join(lines)


def classify_articles(articles: list[dict]) -> list[dict]:
    """
    Classify a list of articles for 녹용 industry relevance.

    Each article dict must have: id, title_ko, and body_ko or description.
    Returns list of {id, relevance_score, recommendation, tags_internal}.
    Processes in batches of up to BATCH_SIZE.
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    system_prompt = _load_system_prompt()
    results = []

    for i in range(0, len(articles), _BATCH_SIZE):
        batch = articles[i : i + _BATCH_SIZE]
        message = client.messages.create(
            model=_MODEL,
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": _build_user_message(batch)}],
        )
        raw = message.content[0].text.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw).strip()
        try:
            batch_results = json.loads(raw)
            results.extend(batch_results)
        except json.JSONDecodeError as e:
            print(f"Classifier JSON parse error on batch {i // _BATCH_SIZE}: {e}")
            print(f"Raw response: {raw[:300]}")
            for article in batch:
                results.append({
                    "id": article["id"],
                    "relevance_score": 3,
                    "recommendation": "분류 실패 — 수동 검토 필요",
                    "tags_internal": ["other"],
                })

    return results
