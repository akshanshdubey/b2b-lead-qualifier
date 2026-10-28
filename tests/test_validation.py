import pytest

from leadgen.validation import (ValidationError, limit_companies, normalize_website, parse_company_lines,
                                parse_csv, validate_company_name)


@pytest.mark.parametrize("name", ["HubSpot", "Acme, Inc.", "AT&T", "Ünïcode GmbH", "7-Eleven"])
def test_valid_names(name):
    assert validate_company_name(name)


@pytest.mark.parametrize("name", ["", "A", " ", "x" * 101, "https://evil.com", "<script>alert(1)</script>", "!!!"])
def test_invalid_names(name):
    with pytest.raises(ValidationError):
        validate_company_name(name)


@pytest.mark.parametrize("raw,expected", [("example.com", "https://example.com"),
                                          ("HTTP://Example.com/about?x=1", "http://example.com"),
                                          ("https://www.example.co.uk/", "https://www.example.co.uk")])
def test_normalize_website_ok(raw, expected):
    assert normalize_website(raw) == expected


@pytest.mark.parametrize("raw", ["", "ftp://example.com", "http://127.0.0.1", "http://10.0.0.5", "localhost",
                                 "http://192.168.1.1", "http://169.254.169.254", "https://user:pw@example.com",
                                 "example.com:8080", "not a domain", "printer.local", "javascript:alert(1)"])
def test_normalize_website_rejects(raw):
    with pytest.raises(ValidationError):
        normalize_website(raw)


def test_parse_lines_formats_and_errors():
    items, errs = parse_company_lines("Acme, Inc.\nHubSpot | hubspot.com\nFoo Bar, foobar.io\n\nhttp://x\nacme, inc.")
    assert [(i.name, i.website) for i in items] == [
        ("Acme, Inc.", None), ("HubSpot", "https://hubspot.com"), ("Foo Bar", "https://foobar.io")]
    assert any("Line 5" in e for e in errs) and any("Duplicate" in e for e in errs)


def test_parse_csv_aliases_and_bad_rows():
    csv = "Company,URL\nAcme,acme.com\n,\nBad,http://localhost\nAcme,dup.com\n"
    items, errs = parse_csv(csv)
    assert [(i.name, i.website) for i in items] == [("Acme", "https://acme.com")]
    assert any("Row 4" in e for e in errs)


def test_parse_csv_requires_name_column():
    with pytest.raises(ValidationError, match="company name column"):
        parse_csv("foo,bar\n1,2\n")


@pytest.mark.parametrize("data", [b"", b"   \n", b"x" * 1_000_001])
def test_parse_csv_rejects_empty_or_huge(data):
    with pytest.raises(ValidationError):
        parse_csv(data)


def test_parse_csv_handles_bom_and_latin1():
    assert parse_csv("\ufeffcompany_name\nCaf\u00e9 Corp\n".encode("utf-8"))[0][0].name == "Caf\u00e9 Corp"
    assert parse_csv("company_name\nCaf\u00e9 Corp\n".encode("latin-1"))[0][0].name == "Caf\u00e9 Corp"


def test_limit_companies():
    items, _ = parse_company_lines("\n".join(f"Company {i}" for i in range(5)))
    kept, note = limit_companies(items, 3)
    assert len(kept) == 3 and "first 3" in note
    assert limit_companies(items, 10)[1] is None
