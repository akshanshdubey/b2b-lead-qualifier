import json

import pytest
import requests

from leadgen.config import Settings, load_settings
from leadgen.llm import (AnthropicClient, LLMAuthError, LLMConfigError, LLMError, LLMRateLimitError,
                         LLMResponseError)
from leadgen.models import CompanyInput
from leadgen.research import DemoResearcher, WebResearcher, html_to_text


class Resp:
    def __init__(self, status=200, body=None, headers=None, text=None, chunks=None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.text = text if text is not None else json.dumps(body or {})
        self.reason = "reason"
        self.encoding = "utf-8"
        self._chunks = chunks if chunks is not None else [self.text.encode()]

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body

    @property
    def is_redirect(self):
        return False

    def iter_content(self, chunk_size=1):
        yield from self._chunks

    def close(self):
        pass


class Session:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def post(self, url, **kw):
        return self._next(url, kw)

    def get(self, url, **kw):
        return self._next(url, kw)

    def _next(self, url, kw):
        self.calls.append((url, kw))
        r = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(r, Exception):
            raise r
        return r


OK = Resp(200, {"content": [{"type": "text", "text": '{"a": 1}'}]})


def client(*resps, key="real-key", retries=3):
    s = Settings(api_key=key, llm_max_retries=retries)
    sleeps = []
    return AnthropicClient(s, Session(*resps), sleep=sleeps.append), sleeps


# ---- LLM client
def test_missing_key_raises_clear_config_error():
    for key in ("", "your_api_key_here"):
        with pytest.raises(LLMConfigError, match=".env"):
            AnthropicClient(Settings(api_key=key))


def test_success_sends_key_in_header_only():
    c, _ = client(OK)
    assert c.complete_json("sys", "user") == {"a": 1}
    _, kw = c.session.calls[0]
    assert kw["headers"]["x-api-key"] == "real-key" and "real-key" not in json.dumps(kw["json"])


def test_retries_rate_limit_then_succeeds():
    c, sleeps = client(Resp(429, {"error": {"message": "slow down"}}, {"retry-after": "3"}), OK)
    assert c.complete("s", "u") == '{"a": 1}'
    assert len(c.session.calls) == 2 and sleeps == [3.0]


def test_rate_limit_exhausted():
    c, _ = client(Resp(429, {"error": {"message": "x"}}))
    with pytest.raises(LLMRateLimitError):
        c.complete("s", "u")


def test_timeout_retries_then_fails():
    c, _ = client(requests.Timeout())
    with pytest.raises(LLMError, match="network problem"):
        c.complete("s", "u")
    assert len(c.session.calls) == 3


def test_auth_error_not_retried_and_key_not_leaked():
    c, _ = client(Resp(401, {"error": {"message": "invalid x-api-key"}}))
    with pytest.raises(LLMAuthError) as e:
        c.complete("s", "u")
    assert len(c.session.calls) == 1 and "real-key" not in str(e.value)


def test_model_not_found_message():
    c, _ = client(Resp(404, {"error": {"message": "model: nope"}}))
    with pytest.raises(LLMError, match="LLM_MODEL"):
        c.complete("s", "u")


def test_unexpected_shape_and_bad_json():
    c, _ = client(Resp(200, {"weird": True}))
    with pytest.raises(LLMResponseError):
        c.complete("s", "u")
    c, _ = client(Resp(200, {"content": [{"type": "text", "text": "not json"}]}))
    with pytest.raises(LLMResponseError):
        c.complete_json("s", "u")


def test_settings_repr_hides_key():
    assert "real-key" not in repr(Settings(api_key="real-key")) and "set" in repr(Settings(api_key="real-key"))


def test_load_settings_clamps_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MAX_COMPANIES_PER_RUN", "99999")
    monkeypatch.setenv("REQUEST_TIMEOUT_SECONDS", "abc")
    s = load_settings(tmp_path / "none.env")
    assert s.max_companies == 200 and s.request_timeout == 15


# ---- web research (no real network: fake session + fake DNS check)
PUBLIC = lambda host: (True, "")  # noqa: E731
HOME = "<html><head><title>Acme</title></head><body><p>Acme builds enterprise software for businesses worldwide.</p></body></html>"


def researcher(*resps, host_check=PUBLIC):
    return WebResearcher(Settings(crawl_delay_seconds=0, max_pages_per_company=2), Session(*resps),
                         sleep=lambda s: None, host_check=host_check)


def test_html_to_text_strips_scripts_and_keeps_meta():
    title, text = html_to_text('<title>T</title><meta name="description" content="Meta desc here">'
                               '<script>var secret=1</script><style>.a{}</style><p>Visible paragraph text</p>')
    assert title == "T" and "secret" not in text and "Meta desc here" in text and "Visible paragraph" in text


def test_web_research_collects_real_sources_only():
    # call order: Wikipedia opensearch (404) -> robots.txt (404 = allowed) -> home page -> later pages (404)
    r = researcher(Resp(404), Resp(404), Resp(200, text=HOME, headers={"Content-Type": "text/html"}), Resp(404))
    res = r.research(CompanyInput("Acme", "https://acme.test"))
    assert [s.url for s in res.sources if s.kind == "website"] == ["https://acme.test/"]
    assert res.website_origin == "provided"


def test_private_hosts_are_blocked():
    r = researcher(Resp(200, text=HOME, headers={"Content-Type": "text/html"}),
                   host_check=lambda h: (False, "resolves to a private/local address"))
    res = r.research(CompanyInput("Evil", "https://evil.test"))
    assert res.sources == [] and any("blocked" in l for l in res.log)
    assert any("No readable pages" in f or "could not be read" in f for f in res.flags)
    assert r.session.calls == []  # nothing was requested


def test_robots_disallow_is_respected():
    robots = Resp(200, text="User-agent: *\nDisallow: /", headers={"Content-Type": "text/plain"})
    r = researcher(robots)
    res = r.research(CompanyInput("Acme", "https://acme.test"))
    assert res.sources == [] and any("robots.txt" in l for l in res.log)


def test_network_errors_become_flags_not_crashes():
    r = researcher(requests.ConnectionError("boom"))
    res = r.research(CompanyInput("Acme", "https://acme.test"))
    assert res.sources == [] and res.flags


def test_no_website_and_no_wikipedia_flags_missing():
    res = researcher(Resp(404)).research(CompanyInput("Totally Unknown Co"))
    assert res.website is None and any("No website found" in f for f in res.flags)


def test_demo_researcher_flags_fictional_data():
    d = DemoResearcher()
    res = d.research(CompanyInput("Lumora Analytics"))
    assert len(res.sources) == 3 and all(s.url.startswith("demo://") for s in res.sources)
    assert any("DEMO DATA" in f for f in res.flags)
    none = d.research(CompanyInput("Unlisted"))
    assert none.sources == [] and none.flags
