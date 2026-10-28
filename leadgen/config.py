"""Settings loaded from environment variables / a local .env file.

The API key is read ONLY from the environment. It is never written to disk by this
app, never shown in the UI, and never included in logs or exports.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"

USER_AGENT = (
    "LeadResearchBot/1.0 (educational assessment project; reads public pages only; "
    "no outreach)"
)


def _int_env(name: str, default: int, lo: int, hi: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(lo, min(hi, value))


def _float_env(name: str, default: float, lo: float, hi: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(lo, min(hi, value))


@dataclass(frozen=True, repr=False)
class Settings:
    api_key: str = ""
    model: str = "claude-haiku-5-5"
    api_url: str = "https://api.anthropic.com/v1/messages"
    request_timeout: int = 15
    llm_max_retries: int = 3
    max_pages_per_company: int = 3
    max_companies: int = 25
    crawl_delay_seconds: float = 1.0
    user_agent: str = USER_AGENT

    @property
    def has_api_key(self) -> bool:
        key = self.api_key.strip()
        if not key:
            return False
        # Ignore the placeholder text shipped in .env.example
        return not key.lower().startswith(("your", "sk-ant-xxx", "paste"))

    def __repr__(self) -> str:  # never leak the key
        masked = "set" if self.has_api_key else "not set"
        return f"Settings(api_key=<{masked}>, model={self.model!r}, max_companies={self.max_companies})"


def load_settings(env_file: Path | str | None = None) -> Settings:
    """Load settings from .env (if present) and the process environment."""
    load_dotenv(env_file or ROOT / ".env", override=False)
    return Settings(
        api_key=os.getenv("ANTHROPIC_API_KEY", "").strip(),
        model=os.getenv("LLM_MODEL", "").strip() or "claude-haiku-5-5",
        request_timeout=_int_env("REQUEST_TIMEOUT_SECONDS", 15, 3, 60),
        llm_max_retries=_int_env("LLM_MAX_RETRIES", 3, 1, 6),
        max_pages_per_company=_int_env("MAX_PAGES_PER_COMPANY", 3, 1, 6),
        max_companies=_int_env("MAX_COMPANIES_PER_RUN", 25, 1, 200),
        crawl_delay_seconds=_float_env("CRAWL_DELAY_SECONDS", 1.0, 0.0, 10.0),
    )
