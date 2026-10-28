"""Evidence verification: a fact earns points only if its quote really appears in a fetched page.

This is the main defence against hallucinated research. The LLM (or rules) must supply a
verbatim quote; we re-check that quote against the stored page text in plain Python.
"""
from __future__ import annotations

import re
import unicodedata

from .models import Source

MIN_QUOTE_CHARS = 12
_NUM_RE = re.compile(r"(\d[\d,]*\.?\d*)\s*([kKmM])?(?![\w])")


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = (text.replace("\u2019", "'").replace("\u2018", "'")
            .replace("\u201c", '"').replace("\u201d", '"'))
    return re.sub(r"\s+", " ", text).strip().lower()


def numbers_in(text: str) -> set[int]:
    """All integers mentioned in text; understands 1,200 / 2.5k / 1m."""
    found: set[int] = set()
    for num, suffix in _NUM_RE.findall(text or ""):
        try:
            value = float(num.replace(",", ""))
        except ValueError:
            continue
        if suffix.lower() == "k":
            value *= 1_000
        elif suffix.lower() == "m":
            value *= 1_000_000
        found.add(int(round(value)))
    return found


class EvidenceChecker:
    def __init__(self, sources: list[Source]):
        self._norm = {s.url: normalize_text(s.text) for s in sources}

    def check(self, quote: object, url: str | None = None) -> tuple[bool, str | None, str | None]:
        """Return (verified, resolved_source_url, issue)."""
        if not isinstance(quote, str) or not quote.strip():
            return False, None, "No evidence quote was provided."
        q = normalize_text(quote).rstrip(".… ")
        q = q[:-3] if q.endswith("...") else q
        if len(q) < MIN_QUOTE_CHARS:
            return False, None, "Evidence quote is too short to verify."
        if url and url in self._norm and q in self._norm[url]:
            return True, url, None
        for src_url, text in self._norm.items():
            if q in text:
                return True, src_url, None
        return False, None, "Quote not found in any retrieved page (possible hallucination)."
