"""Input validation for company names, websites, pasted text and CSV uploads."""
from __future__ import annotations

import io
import ipaddress
import re
from urllib.parse import urlparse

import pandas as pd

from .models import CompanyInput

MAX_NAME_LEN = 100
MAX_CSV_BYTES = 1_000_000
_NAME_RE = re.compile(r"[\w\s.,&'’\-()/+!:]+", re.UNICODE)
_HOST_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_BLOCKED_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home", ".corp", ".example")

NAME_COLUMNS = ("company_name", "company", "name", "companyname", "company name", "organization")
SITE_COLUMNS = ("website", "url", "domain", "site", "web site", "company_website")


class ValidationError(ValueError):
    """User-facing input problem."""


def validate_company_name(raw: object) -> str:
    if raw is None:
        raise ValidationError("Company name is empty.")
    name = re.sub(r"\s+", " ", str(raw)).strip()
    if len(name) < 2:
        raise ValidationError(f"Company name too short: {name!r}")
    if len(name) > MAX_NAME_LEN:
        raise ValidationError(f"Company name longer than {MAX_NAME_LEN} characters.")
    if re.search(r"https?://|www\.", name, re.I):
        raise ValidationError(f"{name!r} looks like a URL; put it in the website column instead.")
    if not _NAME_RE.fullmatch(name):
        raise ValidationError(f"Company name contains unsupported characters: {name!r}")
    if not re.search(r"[A-Za-z0-9]", name):
        raise ValidationError(f"Company name needs letters or digits: {name!r}")
    return name


def host_is_publicly_routable_literal(host: str) -> bool:
    """False for IP literals that are private/loopback/link-local etc. True for hostnames."""
    try:
        return ipaddress.ip_address(host.strip("[]")).is_global
    except ValueError:
        return True  # not an IP literal; DNS is checked later at fetch time


def normalize_website(raw: object) -> str:
    """Return a safe https/http origin (scheme + host) or raise ValidationError."""
    text = str(raw or "").strip()
    if not text:
        raise ValidationError("Website is empty.")
    if len(text) > 300:
        raise ValidationError("Website value is too long.")
    if "://" not in text:
        text = "https://" + text
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https"):
        raise ValidationError(f"Only http/https websites are allowed: {raw!r}")
    if parsed.username or parsed.password or "@" in parsed.netloc:
        raise ValidationError("Website must not contain credentials.")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise ValidationError(f"No hostname found in {raw!r}")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValidationError(f"Invalid port in {raw!r}") from exc
    if port not in (None, 80, 443):
        raise ValidationError("Only default web ports (80/443) are allowed.")
    is_ip = True
    try:
        ipaddress.ip_address(host)
    except ValueError:
        is_ip = False
    if is_ip:
        if not host_is_publicly_routable_literal(host):
            raise ValidationError("Private or local IP addresses are not allowed.")
    else:
        if host == "localhost" or host.endswith(_BLOCKED_SUFFIXES) or not _HOST_RE.match(host):
            raise ValidationError(f"{host!r} is not a valid public domain name.")
    return f"{parsed.scheme}://{host}"


_SITE_RE = re.compile(r"^(https?://)?([a-z0-9\-]+\.)+[a-z]{2,}(/\S*)?$", re.I)


def _looks_like_site(text: str) -> bool:
    """True for 'example.com' or 'https://example.com/x'; False for 'Inc.' or 'Co. Ltd'."""
    return bool(_SITE_RE.match(text.strip()))


def parse_company_lines(text: str) -> tuple[list[CompanyInput], list[str]]:
    """Parse pasted text. Accepted line formats: `Name`, `Name | site.com`, `Name, site.com`."""
    items: list[CompanyInput] = []
    errors: list[str] = []
    for lineno, line in enumerate((text or "").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        name_part, site_part = line, None
        if "|" in line:
            name_part, site_part = [p.strip() for p in line.split("|", 1)]
        elif "," in line:
            left, right = line.rsplit(",", 1)
            if _looks_like_site(right):
                name_part, site_part = left.strip(), right.strip()
        try:
            name = validate_company_name(name_part)
            site = normalize_website(site_part) if site_part else None
            items.append(CompanyInput(name=name, website=site))
        except ValidationError as exc:
            errors.append(f"Line {lineno}: {exc}")
    return dedupe(items, errors), errors


def parse_csv(data: bytes | str) -> tuple[list[CompanyInput], list[str]]:
    """Parse an uploaded CSV. Requires a company-name column; website column is optional."""
    raw = data.encode("utf-8") if isinstance(data, str) else data
    if len(raw) > MAX_CSV_BYTES:
        raise ValidationError(f"CSV is larger than {MAX_CSV_BYTES // 1000} KB.")
    if not raw.strip():
        raise ValidationError("CSV file is empty.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    try:
        df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    except (pd.errors.ParserError, pd.errors.EmptyDataError, ValueError) as exc:
        raise ValidationError(f"Could not read CSV: {exc}") from exc
    cols = {str(c).strip().lower(): c for c in df.columns}
    name_col = next((cols[c] for c in NAME_COLUMNS if c in cols), None)
    if name_col is None:
        raise ValidationError(
            "CSV needs a company name column (one of: company_name, company, name). "
            f"Found columns: {', '.join(map(str, df.columns)) or 'none'}")
    site_col = next((cols[c] for c in SITE_COLUMNS if c in cols), None)

    items: list[CompanyInput] = []
    errors: list[str] = []
    for idx, row in df.iterrows():
        rownum = int(idx) + 2  # header is row 1
        raw_name = row[name_col]
        if not str(raw_name).strip():
            continue
        try:
            name = validate_company_name(raw_name)
            site_raw = str(row[site_col]).strip() if site_col else ""
            site = normalize_website(site_raw) if site_raw else None
            items.append(CompanyInput(name=name, website=site))
        except ValidationError as exc:
            errors.append(f"Row {rownum}: {exc}")
    return dedupe(items, errors), errors


def dedupe(items: list[CompanyInput], errors: list[str] | None = None) -> list[CompanyInput]:
    seen: dict[str, CompanyInput] = {}
    for item in items:
        key = item.name.lower()
        if key in seen:
            if errors is not None:
                errors.append(f"Duplicate skipped: {item.name}")
            if not seen[key].website and item.website:
                seen[key].website = item.website
            continue
        seen[key] = item
    return list(seen.values())


def limit_companies(items: list[CompanyInput], max_n: int) -> tuple[list[CompanyInput], str | None]:
    if len(items) <= max_n:
        return items, None
    return items[:max_n], (
        f"Only the first {max_n} companies will be processed (limit set by MAX_COMPANIES_PER_RUN).")
