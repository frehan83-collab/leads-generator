"""
Tests for the BrowserManager shared browser lifecycle manager.
"""

import pytest
from unittest.mock import MagicMock, patch

from src.scraper.browser_manager import BrowserManager, USER_AGENT


class TestBrowserManager:
    """Tests for BrowserManager context manager."""

    @patch("src.scraper.browser_manager.sync_playwright")
    def test_context_manager_launches_and_closes_browser(self, mock_sync_pw):
        mock_pw = MagicMock()
        mock_browser = MagicMock()
        mock_pw.chromium.launch.return_value = mock_browser

        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_pw)
        mock_cm.__exit__ = MagicMock(return_value=False)
        mock_sync_pw.return_value = mock_cm

        with BrowserManager() as bm:
            assert bm.browser is mock_browser
            mock_pw.chromium.launch.assert_called_once_with(headless=True)

        mock_browser.close.assert_called_once()

    @patch("src.scraper.browser_manager.sync_playwright")
    def test_proxy_from_env(self, mock_sync_pw):
        mock_pw = MagicMock()
        mock_browser = MagicMock()
        mock_pw.chromium.launch.return_value = mock_browser

        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_pw)
        mock_cm.__exit__ = MagicMock(return_value=False)
        mock_sync_pw.return_value = mock_cm

        with patch.dict("os.environ", {"PROXY_URL": "http://proxy:8080"}):
            with BrowserManager() as bm:
                pass

        call_kwargs = mock_pw.chromium.launch.call_args[1]
        assert call_kwargs["proxy"] == {"server": "http://proxy:8080"}

    @patch("src.scraper.browser_manager.sync_playwright")
    def test_new_context_sets_defaults(self, mock_sync_pw):
        mock_pw = MagicMock()
        mock_browser = MagicMock()
        mock_context = MagicMock()
        mock_pw.chromium.launch.return_value = mock_browser
        mock_browser.new_context.return_value = mock_context

        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_pw)
        mock_cm.__exit__ = MagicMock(return_value=False)
        mock_sync_pw.return_value = mock_cm

        with BrowserManager() as bm:
            ctx = bm.new_context()

        call_kwargs = mock_browser.new_context.call_args[1]
        assert call_kwargs["user_agent"] == USER_AGENT
        assert call_kwargs["locale"] == "nb-NO"

    @patch("src.scraper.browser_manager.sync_playwright")
    def test_new_context_custom_overrides(self, mock_sync_pw):
        mock_pw = MagicMock()
        mock_browser = MagicMock()
        mock_context = MagicMock()
        mock_pw.chromium.launch.return_value = mock_browser
        mock_browser.new_context.return_value = mock_context

        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_pw)
        mock_cm.__exit__ = MagicMock(return_value=False)
        mock_sync_pw.return_value = mock_cm

        with BrowserManager() as bm:
            ctx = bm.new_context(locale="en-US", viewport={"width": 800, "height": 600})

        call_kwargs = mock_browser.new_context.call_args[1]
        assert call_kwargs["locale"] == "en-US"  # overridden
        assert call_kwargs["viewport"] == {"width": 800, "height": 600}

    def test_user_agent_constant_exists(self):
        assert "Mozilla" in USER_AGENT
        assert "Chrome" in USER_AGENT
