"""
config.py — Environment variable validation for Korea Velvet News.

All secrets are read from environment variables (never hardcoded).
Loaded from .env locally; from GitHub Secrets in Actions.
"""
import json
import os

from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        raise EnvironmentError(
            f"Missing required environment variable: {name}. "
            "Set it in .env (local) or GitHub Secrets (Actions)."
        )
    return val


# Google Sheets
GOOGLE_SERVICE_ACCOUNT_JSON: dict = json.loads(_require("GOOGLE_SERVICE_ACCOUNT_JSON"))
KVN_SHEETS_ID: str = _require("KVN_SHEETS_ID")

# AI
ANTHROPIC_API_KEY: str = _require("ANTHROPIC_API_KEY")

# Naver Search API
NAVER_CLIENT_ID: str = _require("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET: str = _require("NAVER_CLIENT_SECRET")

# Email (optional — only needed for monthly report send)
GMAIL_APP_PASSWORD: str = os.environ.get("GMAIL_APP_PASSWORD", "")
GMAIL_SENDER: str = os.environ.get("GMAIL_SENDER", "seouldesk.help@gmail.com")
GMAIL_RECIPIENT: str = os.environ.get("GMAIL_RECIPIENT", "seouldesk.help@gmail.com")
