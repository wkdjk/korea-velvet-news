"""
generate.py — Build the main and archive page HTML from Airtable data.

generate_html()         — current month's index.html
generate_archive_html() — /archive/YYYY-MM/index.html for a past month
"""

import re
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from src.airtable.client import get_records

_TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"
_OUTPUT_DIR = Path(__file__).parent.parent.parent / "output"
# KVN Google Form submission URL — update once the form public URL is confirmed.
_FORM_URL = ""


def _format_date(date_str: str) -> str:
    """Convert 'YYYY-MM-DD' to '9 May 2026'."""
    try:
        d = date.fromisoformat(date_str)
        return f"{d.day} {d.strftime('%B')} {d.year}"
    except Exception:
        return date_str


def _sentence_case(s: str) -> str:
    """Safety-net filter: convert title-case to sentence case.
    Preserves all-caps acronyms (MFDS, NZ) and mixed-case proper nouns (KGC)."""
    if not s:
        return s
    words = s.split()
    out = []
    for i, w in enumerate(words):
        if i == 0:
            out.append(w[0].upper() + w[1:] if w else w)
        elif len(w) > 1 and w[0].isupper() and not w[1:].islower():
            out.append(w)   # acronym (MFDS) or mixed-case proper noun (KGC)
        elif w.isupper() and len(w) == 1:
            out.append(w)   # preserve "I"
        else:
            out.append(w.lower())
    return " ".join(out)


def _render_bold(text: str) -> str:
    """Convert **text** markdown bold to <strong>text</strong>.
    Must run on already-escaped text; produces trusted HTML."""
    return re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)


# Canonical category order — matches MVP
_CATEGORY_ORDER = [
    "Regulation & Policy",
    "Market Trends",
    "Products & Brands",
    "Trade & Distribution",
    "Research & Health",
    "Traditional Medicine",
]


def _get_articles_for_month(month_key: str) -> list[dict]:
    """Fetch translated + published articles for a given YYYY-MM month key."""
    formula = (
        f"AND("
        f"OR({{status}}='translated', {{status}}='published'), "
        f"{{month_key}}='{month_key}'"
        f")"
    )
    records = get_records("Articles", filter_formula=formula)
    articles = []
    for r in records:
        f = r["fields"]
        attachments = f.get("image_attachments") or []
        articles.append({
            "id": r["id"],
            "title_en": f.get("title_en", ""),
            "body_en": f.get("body_en", ""),
            "why_it_matters": f.get("why_it_matters", ""),
            "source_attribution": f.get("source_attribution", ""),
            "category": f.get("category", "") or "Market Trends",
            "published_date": f.get("published_date", ""),
            "source_name": f.get("source_name", ""),
            "url": f.get("url", ""),
            "image_url": f.get("image_url", ""),
            "image_attachments": attachments,
            "is_product_news": bool(f.get("is_product_news", False)),
        })

    # Sort: date desc first (stable), then category rank asc (stable).
    # Result: articles grouped by category, newest-first within each group.
    cat_rank = {c: i for i, c in enumerate(_CATEGORY_ORDER)}
    articles.sort(key=lambda a: a.get("published_date", ""), reverse=True)
    articles.sort(key=lambda a: cat_rank.get(a["category"], len(_CATEGORY_ORDER)))
    return articles


def _get_current_month_articles() -> list[dict]:
    """Fetch translated + published articles for the current month."""
    return _get_articles_for_month(date.today().strftime("%Y-%m"))


def generate_html(output_path: Path = None) -> Path:
    """Render index.html and write to output_path (default: /output/index.html)."""
    if output_path is None:
        output_path = _OUTPUT_DIR / "index.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    articles = _get_current_month_articles()
    today = date.today()

    env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)), autoescape=True)
    env.filters["format_date"] = _format_date
    env.filters["sentence_case"] = _sentence_case
    env.filters["render_bold"] = _render_bold

    # Collect the unique categories present in this month's articles (in canonical order)
    present_categories = []
    for cat in _CATEGORY_ORDER:
        if any(a["category"] == cat for a in articles):
            present_categories.append(cat)

    template = env.get_template("current_month.html")
    html = template.render(
        as_of_date=_format_date(str(today)),
        month_label=today.strftime("%B %Y"),
        articles=articles,
        article_count=len(articles),
        categories=present_categories,
        form_url=_FORM_URL,
    )

    output_path.write_text(html, encoding="utf-8")
    print(f"Generated: {output_path} ({len(articles)} articles)")
    return output_path


def generate_archive_html(month_key: str, pdf_url: str = "", output_dir: Path = None) -> tuple[Path, list[dict]]:
    """Render /archive/YYYY-MM/index.html for a past month.

    Args:
        month_key: 'YYYY-MM' (e.g. '2026-05')
        pdf_url: public URL of the Airtable-hosted PDF (empty string = fallback to window.print)
        output_dir: base output directory (default: /output/)

    Returns (output_path, articles) — caller uses article count for Reports row.
    """
    if output_dir is None:
        output_dir = _OUTPUT_DIR
    archive_path = output_dir / "archive" / month_key / "index.html"
    archive_path.parent.mkdir(parents=True, exist_ok=True)

    articles = _get_articles_for_month(month_key)
    month_label = date.fromisoformat(f"{month_key}-01").strftime("%B %Y")

    env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)), autoescape=True)
    env.filters["format_date"] = _format_date
    env.filters["sentence_case"] = _sentence_case
    env.filters["render_bold"] = _render_bold

    template = env.get_template("archive_month.html")
    html = template.render(
        month_label=month_label,
        articles=articles,
        pdf_url=pdf_url,
    )

    archive_path.write_text(html, encoding="utf-8")
    print(f"Archive: {archive_path} ({len(articles)} articles)")
    return archive_path, articles
