"""Collect PUBLIC information about a company. Nothing here contacts people.

Sources used (all public):
  * the company's own website pages (home, about, careers) - only if robots.txt allows
  * Wikipedia's official API (summary + official-website link) as a free reference source
  * bundled fictional demo fixtures (offline demo mode)

Every page that is retrieved becomes a `Source`. Failures are logged in `ResearchResult.log`
and never turned into data.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import re
import socket
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable
from urllib.parse import quote, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests

from .config import DATA_DIR, Settings
from .models import CompanyInput, Source
from .validation import ValidationError, normalize_website

log = logging.getLogger(__name__)

MAX_BYTES = 1_500_000
MAX_TEXT_CHARS = 20_000
MAX_REDIRECTS = 3
EXTRA_PATHS = ("/about", "/about-us", "/company", "/careers", "/jobs")
COMPANY_WORDS = re.compile(
    r"\b(company|corporation|business|firm|startup|manufacturer|retailer|provider|conglomerate|"
    r"chain|brand|inc\.?|ltd\.?|plc|gmbh|multinational|vendor|developer)\b", re.I)


@dataclass
class ResearchResult:
    website: str | None = None
    website_origin: str | None = None  # "provided" | "wikipedia" | "demo" | None
    sources: list[Source] = field(default_factory=list)
    log: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- HTML -> text
class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "template", "iframe"}
    BLOCK = {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section",
             "article", "header", "footer", "ul", "ol", "table"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.title = ""
        self.meta = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            a = {k.lower(): (v or "") for k, v in attrs}
            if a.get("name", "").lower() in ("description", "og:description") or \
               a.get("property", "").lower() == "og:description":
                self.meta = self.meta or a.get("content", "")
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> tuple[str, str]:
    """Return (title, plain_text) with the meta description included."""
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:  # malformed HTML should never crash the run
        log.debug("HTML parse problem", exc_info=True)
    body = "".join(parser.parts)
    lines = [re.sub(r"[ \t\r\f\v]+", " ", ln).strip() for ln in body.splitlines()]
    lines = [ln for ln in lines if len(ln) >= 3]
    title = re.sub(r"\s+", " ", parser.title).strip()
    head = [x for x in (title, re.sub(r"\s+", " ", parser.meta).strip()) if x]
    return title, "\n".join(head + lines)[:MAX_TEXT_CHARS]


# --------------------------------------------------------------------------- helpers
def _alnum(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def name_matches(company: str, other: str) -> bool:
    a, b = _alnum(company), _alnum(other)
    return bool(a) and bool(b) and (a in b or b in a)


def host_is_public(host: str) -> tuple[bool, str]:
    """SSRF guard: every address the host resolves to must be globally routable."""
    try:
        addrs = {host} if _is_ip(host) else {ai[4][0] for ai in socket.getaddrinfo(host, None)}
    except socket.gaierror:
        return False, "DNS lookup failed"
    for addr in addrs:
        try:
            if not ipaddress.ip_address(addr.split("%")[0]).is_global:
                return False, "resolves to a private/local address"
        except ValueError:
            return False, "invalid address"
    return True, ""


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


# --------------------------------------------------------------------------- live research
class WebResearcher:
    def __init__(self, settings: Settings, session: requests.Session | None = None,
                 sleep: Callable[[float], None] = time.sleep,
                 host_check: Callable[[str], tuple[bool, str]] = host_is_public):
        self.settings = settings
        self.session = session or requests.Session()
        self._sleep = sleep
        self._host_check = host_check
        self._robots: dict[str, RobotFileParser | None] = {}

    # ---- public API
    def research(self, company: CompanyInput) -> ResearchResult:
        res = ResearchResult()
        wiki_title, wiki_source = self._wikipedia_summary(company.name, res)
        if wiki_source:
            res.sources.append(wiki_source)

        site = company.website
        if site:
            res.website, res.website_origin = site, "provided"
        elif wiki_title:
            found = self._wikipedia_official_site(wiki_title, company.name, res)
            if found:
                res.website, res.website_origin = found, "wikipedia"
                res.flags.append(
                    "Website was taken from the company's Wikipedia page; confirm it is correct.")
        if not res.website:
            res.flags.append(
                "No website found. Add it in the CSV 'website' column for better research.")
            return res

        self._crawl_site(res.website, res)
        return res

    # ---- website crawl
    def _crawl_site(self, origin: str, res: ResearchResult) -> None:
        limit = self.settings.max_pages_per_company
        pages = 0
        for path in ("/",) + EXTRA_PATHS:
            if pages >= limit:
                break
            url = origin + path if path != "/" else origin + "/"
            if pages:
                self._sleep(self.settings.crawl_delay_seconds)
            html, err = self._fetch(url)
            if html is None:
                res.log.append(f"SKIPPED {url}: {err}")
                if path == "/" and err and not err.startswith("HTTP 404"):
                    res.flags.append(f"Website home page could not be read ({err}).")
                continue
            title, text = html_to_text(html)
            if len(text) < 40:
                res.log.append(f"SKIPPED {url}: page had almost no readable text (JavaScript-only?)")
                continue
            res.sources.append(Source(url=url, kind="website", title=title or url, text=text))
            res.log.append(f"FETCHED {url} ({len(text)} chars)")
            pages += 1
        if pages == 0:
            res.flags.append("No readable pages could be retrieved from the website.")

    # ---- safe HTTP
    def _fetch(self, url: str, accept: str = "text/html") -> tuple[str | None, str | None]:
        if not self._robots_allows(url):
            return None, "disallowed by robots.txt"
        return self._get(url, accept)

    def _get(self, url: str, accept: str) -> tuple[str | None, str | None]:
        current = url
        headers = {"User-Agent": self.settings.user_agent, "Accept": accept}
        for _ in range(MAX_REDIRECTS + 1):
            parsed = urlparse(current)
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                return None, "unsupported URL"
            ok, why = self._host_check(parsed.hostname)
            if not ok:
                return None, why if why.startswith("DNS") else f"blocked ({why})"
            try:
                resp = self.session.get(current, headers=headers, timeout=self.settings.request_timeout,
                                        allow_redirects=False, stream=True)
            except requests.Timeout:
                return None, "timeout"
            except requests.RequestException as exc:
                return None, f"network error ({type(exc).__name__})"
            try:
                if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("Location"):
                    current = urljoin(current, resp.headers["Location"])
                    continue
                if resp.status_code != 200:
                    return None, f"HTTP {resp.status_code}"
                ctype = resp.headers.get("Content-Type", "").lower()
                if "html" not in ctype and "json" not in ctype and "text" not in ctype:
                    return None, f"unsupported content type {ctype or 'unknown'}"
                chunks, size = [], 0
                for chunk in resp.iter_content(chunk_size=65536):
                    size += len(chunk)
                    chunks.append(chunk)
                    if size > MAX_BYTES:
                        break
                return b"".join(chunks).decode(resp.encoding or "utf-8", errors="replace"), None
            finally:
                resp.close()
        return None, "too many redirects"

    def _robots_allows(self, url: str) -> bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._robots:
            body, _err = self._get(origin + "/robots.txt", "text/plain")
            if body is None:
                self._robots[origin] = None  # no robots.txt available -> allowed
            else:
                rp = RobotFileParser()
                rp.parse(body.splitlines())
                self._robots[origin] = rp
        rp = self._robots[origin]
        return True if rp is None else rp.can_fetch(self.settings.user_agent, url)

    # ---- Wikipedia (official API, free)
    def _wiki_json(self, url: str, res: ResearchResult):
        body, err = self._get(url, "application/json")
        if body is None:
            res.log.append(f"Wikipedia lookup skipped: {err}")
            return None
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            res.log.append("Wikipedia lookup skipped: invalid JSON")
            return None

    def _wikipedia_summary(self, name: str, res: ResearchResult):
        data = self._wiki_json(
            "https://en.wikipedia.org/w/api.php?action=opensearch&limit=3&format=json&search="
            + quote(name), res)
        titles = data[1] if isinstance(data, list) and len(data) > 1 else []
        for title in titles:
            if not name_matches(name, title):
                continue
            summary = self._wiki_json(
                "https://en.wikipedia.org/api/rest_v1/page/summary/" + quote(title.replace(" ", "_")), res)
            if not isinstance(summary, dict) or summary.get("type") != "standard":
                continue
            extract = str(summary.get("extract", "")).strip()
            if not COMPANY_WORDS.search(extract):
                res.log.append(f"Wikipedia page '{title}' ignored: does not look like a company page")
                continue
            page_url = (summary.get("content_urls", {}).get("desktop", {}).get("page")
                        or "https://en.wikipedia.org/wiki/" + quote(title.replace(" ", "_")))
            res.log.append(f"FETCHED {page_url} (Wikipedia summary)")
            return title, Source(url=page_url, kind="wikipedia", title=f"Wikipedia: {title}", text=extract)
        return None, None

    def _wikipedia_official_site(self, title: str, name: str, res: ResearchResult) -> str | None:
        data = self._wiki_json(
            "https://en.wikipedia.org/w/api.php?action=query&prop=extlinks&ellimit=30&format=json"
            "&formatversion=2&titles=" + quote(title), res)
        try:
            links = [l["url"] for l in data["query"]["pages"][0].get("extlinks", [])]
        except (KeyError, IndexError, TypeError):
            return None
        for link in links:
            link = "https:" + link if link.startswith("//") else link
            host = urlparse(link).hostname or ""
            if not name_matches(name, host.split(".")[-2] if host.count(".") else host):
                continue
            try:
                return normalize_website(link)
            except ValidationError:
                continue
        return None


# --------------------------------------------------------------------------- demo mode
class DemoResearcher:
    """Serves FICTIONAL company pages from data/demo_pages.json so the app works offline."""

    def __init__(self, path: Path | str | None = None):
        path = Path(path) if path else DATA_DIR / "demo_pages.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        self._db = {_alnum(k): v for k, v in raw.items() if not k.startswith("_")}

    def research(self, company: CompanyInput) -> ResearchResult:
        res = ResearchResult()
        entry = self._db.get(_alnum(company.name))
        if not entry:
            res.flags.append("Demo mode: no bundled fixture for this name, so nothing was researched.")
            res.log.append("No demo fixture found.")
            return res
        res.website, res.website_origin = entry.get("website"), "demo"
        for page in entry.get("pages", []):
            res.sources.append(Source(url=page["url"], kind="demo", title=page.get("title", ""),
                                      text=page["text"]))
            res.log.append(f"LOADED demo fixture {page['url']}")
        res.flags.append("DEMO DATA: fictional company text bundled with the project, not real research.")
        return res
