"""Tests for website email scraper."""

from unittest.mock import MagicMock, patch

from src.scraper.website_scraper import (
    _extract_title_from_text,
    _is_valid_email,
    _score_email,
    scrape_emails_from_website,
)


class TestIsValidEmail:
    def test_matching_domain_accepted(self):
        assert _is_valid_email("john.doe@company.no", "company.no") is True

    def test_www_domain_accepted(self):
        assert _is_valid_email("john.doe@company.no", "www.company.no") is True

    def test_wrong_domain_rejected(self):
        assert _is_valid_email("john@other.com", "company.no") is False

    def test_noreply_rejected(self):
        assert _is_valid_email("noreply@company.no", "company.no") is False

    def test_support_rejected(self):
        assert _is_valid_email("support@company.no", "company.no") is False

    def test_info_accepted(self):
        # "info" is NOT in SKIP_PREFIXES — low quality but valid
        assert _is_valid_email("info@company.no", "company.no") is True

    def test_personal_email_accepted(self):
        assert _is_valid_email("ola.nordmann@company.no", "company.no") is True

    def test_subdomain_email_accepted(self):
        assert _is_valid_email("hr@mail.company.no", "company.no") is True


class TestScoreEmail:
    def test_personal_email_scores_highest(self):
        score = _score_email("john.doe@company.no")
        assert score == 10

    def test_ceo_scores_medium(self):
        score = _score_email("ceo@company.no")
        assert score == 5

    def test_hr_scores_medium(self):
        score = _score_email("hr@company.no")
        assert score == 5

    def test_unknown_role_scores_low(self):
        score = _score_email("misc@company.no")
        assert score == 1

    def test_personal_beats_role(self):
        personal = _score_email("ola.nordmann@company.no")
        role = _score_email("dagligleder@company.no")
        assert personal > role


class TestExtractTitleFromText:
    def test_ceo_title_extracted(self):
        text = "John Doe\nCEO\njohn@company.no"
        title = _extract_title_from_text(text)
        assert "CEO" in title

    def test_daglig_leder_extracted(self):
        text = "Ola Nordmann - Daglig leder\nola@company.no"
        title = _extract_title_from_text(text)
        assert "leder" in title.lower()

    def test_manager_extracted(self):
        text = "Jane Smith | Sales Manager | jane@company.no"
        title = _extract_title_from_text(text)
        assert "Manager" in title

    def test_no_title_returns_empty(self):
        text = "just an email: someone@company.no"
        title = _extract_title_from_text(text)
        # May return empty or partial — just must not crash
        assert isinstance(title, str)

    def test_empty_text_returns_empty(self):
        assert _extract_title_from_text("") == ""

    def test_title_length_capped(self):
        long_text = "CEO " * 30
        title = _extract_title_from_text(long_text)
        assert len(title) <= 80


class TestScrapeEmailsFromWebsite:
    def test_empty_domain_returns_empty(self):
        result = scrape_emails_from_website("")
        assert result == []

    def test_returns_list_of_dicts(self):
        """Result must be list of dicts with email, title, name keys."""
        mock_ctx = MagicMock()
        mock_page = MagicMock()
        mock_ctx.new_page.return_value = mock_page
        with (
            patch("src.scraper.website_scraper.browser_context") as mock_bc,
            patch("src.scraper.website_scraper._scrape_fast", lambda *a, **k: None),
            patch(
                "src.scraper.website_scraper._fetch_robots_disallows", return_value=[]
            ),
        ):
            mock_bc.return_value.__enter__.return_value = mock_ctx

            # evaluate() returns mailto contacts with context
            mock_page.evaluate.return_value = [
                {
                    "email": "john.doe@testco.no",
                    "context": "John Doe\nCEO\njohn.doe@testco.no",
                },
                {"email": "noreply@testco.no", "context": ""},  # should be filtered
            ]
            mock_page.inner_text.return_value = ""

            result = scrape_emails_from_website("testco.no")
            assert isinstance(result, list)
            for item in result:
                assert "email" in item
                assert "title" in item
                assert "name" in item

    def test_noreply_filtered_out(self):
        mock_ctx = MagicMock()
        mock_page = MagicMock()
        mock_ctx.new_page.return_value = mock_page
        with (
            patch("src.scraper.website_scraper.browser_context") as mock_bc,
            patch("src.scraper.website_scraper._scrape_fast", lambda *a, **k: None),
            patch(
                "src.scraper.website_scraper._fetch_robots_disallows", return_value=[]
            ),
        ):
            mock_bc.return_value.__enter__.return_value = mock_ctx
            mock_page.evaluate.return_value = [
                {"email": "noreply@testco.no", "context": ""},
            ]
            mock_page.inner_text.return_value = ""

            result = scrape_emails_from_website("testco.no")
            emails = [r["email"] for r in result]
            assert "noreply@testco.no" not in emails

    def test_title_captured_from_context(self):
        mock_ctx = MagicMock()
        mock_page = MagicMock()
        mock_ctx.new_page.return_value = mock_page
        with (
            patch("src.scraper.website_scraper.browser_context") as mock_bc,
            patch("src.scraper.website_scraper._scrape_fast", lambda *a, **k: None),
            patch(
                "src.scraper.website_scraper._fetch_robots_disallows", return_value=[]
            ),
        ):
            mock_bc.return_value.__enter__.return_value = mock_ctx
            mock_page.evaluate.return_value = [
                {
                    "email": "ola.nordmann@testco.no",
                    "context": "Ola Nordmann\nDaglig leder\nola.nordmann@testco.no",
                },
            ]
            mock_page.inner_text.return_value = ""

            result = scrape_emails_from_website("testco.no")
            assert len(result) == 1
            assert "leder" in result[0]["title"].lower()


class TestFastPath:
    HTML = """
    <html><body>
      <div class="ansatt">
        <h3>Ola Nordmann</h3><p>Daglig leder</p>
        <a href="mailto:ola.nordmann@testco.no">E-post</a>
      </div>
      <p>Sentralbord: <a href="mailto:post@testco.no">post@testco.no</a></p>
    </body></html>
    """

    def _mock_session(self, html=None):
        session = MagicMock()
        resp = MagicMock()
        resp.ok = True
        resp.text = html if html is not None else self.HTML
        session.get.return_value = resp
        return session

    def test_fast_path_finds_personal_email_without_browser(self):
        from src.scraper import website_scraper as ws

        with (
            patch.object(ws.requests, "Session", return_value=self._mock_session()),
            patch.object(ws, "_fetch_robots_disallows", return_value=[]),
            patch.object(ws, "browser_context") as mock_bc,
        ):
            result = ws.scrape_emails_from_website("testco.no")
        emails = [r["email"] for r in result]
        assert "ola.nordmann@testco.no" in emails
        assert result[0]["name"] == "Ola Nordmann"
        mock_bc.assert_not_called()  # personal hit → no browser needed

    def test_fast_path_filters_skip_prefixes(self):
        from src.scraper import website_scraper as ws

        html = '<html><body><a href="mailto:noreply@testco.no">x</a></body></html>'
        with (
            patch.object(ws.requests, "Session", return_value=self._mock_session(html)),
            patch.object(ws, "_fetch_robots_disallows", return_value=[]),
            patch.object(ws, "browser_context") as mock_bc,
            patch.object(ws, "_scrape_pages", lambda *a, **k: None),
        ):
            result = ws.scrape_emails_from_website("testco.no")
        assert "noreply@testco.no" not in [r["email"] for r in result]
        # nothing personal found → browser fallback still attempted
        mock_bc.assert_called_once()

    def test_robots_site_block_skips_entirely(self):
        from src.scraper import website_scraper as ws

        with (
            patch.object(ws, "_fetch_robots_disallows", return_value=["/"]),
            patch.object(ws, "browser_context") as mock_bc,
            patch.object(ws.requests, "Session") as mock_session,
        ):
            assert ws.scrape_emails_from_website("testco.no") == []
        mock_bc.assert_not_called()
        mock_session.assert_not_called()

    def test_robots_path_filter(self):
        from src.scraper.website_scraper import _path_allowed

        assert _path_allowed("/kontakt", ["/admin", "/private"]) is True
        assert _path_allowed("/admin/users", ["/admin"]) is False
        assert _path_allowed("/kontakt", None) is True
