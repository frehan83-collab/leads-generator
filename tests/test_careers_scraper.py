"""Career-page discovery tests (all HTTP mocked)."""

from unittest.mock import MagicMock, patch

from src.scraper import careers_scraper as careers


def _resp(html, ok=True):
    mock = MagicMock()
    mock.ok = ok
    mock.text = html
    return mock


INDEX_HTML = """
<html><body>
  <h1>Jobb hos oss</h1>
  <a href="/karriere/selger-oslo-123">Selger, Oslo</a>
  <a href="https://external.no/stilling/1">Other company job</a>
  <a href="/om-oss">Om oss</a>
  <a href="/karriere/selger-oslo-123">Selger, Oslo (dup)</a>
</body></html>
"""

JOB_HTML = """
<html><head><meta property="og:title" content="Selger, Oslo"></head>
<body><h1>Selger, Oslo</h1><p>Vi søker selger...</p></body></html>
"""


def _session_for(pages):
    session = MagicMock()

    def get(url, timeout=None):
        return _resp(pages.get(url, ""), ok=url in pages)

    session.get.side_effect = get
    return session


def test_discovers_job_links_same_domain_only():
    pages = {
        "https://acme.no/karriere": INDEX_HTML,
        "https://acme.no/karriere/selger-oslo-123": JOB_HTML,
    }
    with (
        patch.object(careers.requests, "Session", return_value=_session_for(pages)),
        patch.object(careers, "_fetch_robots_disallows", return_value=[]),
    ):
        out = list(
            careers.scrape_career_pages(
                [{"domain": "acme.no", "company_name": "Acme AS"}]
            )
        )
    assert len(out) == 1
    assert out[0]["source"] == "careers"
    assert out[0]["company_name"] == "Acme AS"
    assert out[0]["company_domain"] == "acme.no"
    assert "Selger" in out[0]["title"]
    assert out[0]["external_id"]  # stable hash of URL


def test_external_links_ignored():
    assert careers._same_domain("https://external.no/x", "acme.no") is False
    assert careers._same_domain("https://acme.no/x", "acme.no") is True
    assert careers._same_domain("https://jobs.acme.no/x", "acme.no") is True


def test_robots_blocked_site_skipped():
    with (
        patch.object(careers.requests, "Session") as mock_session,
        patch.object(careers, "_fetch_robots_disallows", return_value=["/"]),
    ):
        out = list(careers.scrape_career_pages([{"domain": "acme.no"}]))
    assert out == []
    mock_session.return_value.get.assert_not_called()


def test_known_ids_skipped():
    pages = {"https://acme.no/karriere": INDEX_HTML}
    with (
        patch.object(careers.requests, "Session", return_value=_session_for(pages)),
        patch.object(careers, "_fetch_robots_disallows", return_value=[]),
    ):
        first = list(careers.scrape_career_pages([{"domain": "acme.no"}]))
        assert len(first) == 1
        second = list(
            careers.scrape_career_pages(
                [{"domain": "acme.no"}],
                known_ids={first[0]["external_id"]},
            )
        )
        assert second == []


def test_max_domains_cap():
    with (
        patch.object(careers.requests, "Session", return_value=_session_for({})),
        patch.object(careers, "_fetch_robots_disallows", return_value=[]),
    ):
        out = list(
            careers.scrape_career_pages(
                [{"domain": "a.no"}, {"domain": "b.no"}, {"domain": "c.no"}],
                max_domains=2,
            )
        )
    assert out == []
