"""
Tests for the retry decorator and goto_with_retry helper.
"""

import time
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from src.utils.retry import retry, goto_with_retry


class TestRetryDecorator:
    """Tests for the @retry decorator."""

    def test_succeeds_on_first_attempt(self):
        call_count = 0

        @retry(max_attempts=3, base_delay=0.01)
        def succeed():
            nonlocal call_count
            call_count += 1
            return "ok"

        assert succeed() == "ok"
        assert call_count == 1

    def test_retries_on_exception(self):
        call_count = 0

        @retry(max_attempts=3, base_delay=0.01)
        def fail_twice():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("timeout")
            return "recovered"

        result = fail_twice()
        assert result == "recovered"
        assert call_count == 3

    def test_raises_after_max_attempts(self):
        @retry(max_attempts=2, base_delay=0.01)
        def always_fail():
            raise ConnectionError("down")

        with pytest.raises(ConnectionError, match="down"):
            always_fail()

    def test_no_retry_on_4xx_http_error(self):
        """4xx errors (except 429) should NOT be retried."""
        import requests

        call_count = 0

        @retry(max_attempts=3, base_delay=0.01, retryable_exceptions=(requests.exceptions.HTTPError,))
        def client_error():
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            resp.status_code = 404
            raise requests.exceptions.HTTPError(response=resp)

        with pytest.raises(requests.exceptions.HTTPError):
            client_error()

        assert call_count == 1  # No retry on 404

    def test_retry_on_429_rate_limit(self):
        """429 should be retried (rate limiting)."""
        import requests

        call_count = 0

        @retry(max_attempts=3, base_delay=0.01, retryable_exceptions=(requests.exceptions.HTTPError,))
        def rate_limited():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                resp = MagicMock()
                resp.status_code = 429
                resp.headers = {"Retry-After": "0.01"}
                raise requests.exceptions.HTTPError(response=resp)
            return "ok"

        assert rate_limited() == "ok"
        assert call_count == 3

    def test_retry_on_5xx_server_error(self):
        """5xx errors should be retried."""
        import requests

        call_count = 0

        @retry(max_attempts=3, base_delay=0.01, retryable_exceptions=(requests.exceptions.HTTPError,))
        def server_error():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                resp = MagicMock()
                resp.status_code = 500
                raise requests.exceptions.HTTPError(response=resp)
            return "ok"

        assert server_error() == "ok"
        assert call_count == 3

    def test_only_retries_specified_exceptions(self):
        """Should not catch exceptions not in retryable_exceptions."""
        @retry(max_attempts=3, base_delay=0.01, retryable_exceptions=(ValueError,))
        def wrong_error():
            raise TypeError("bad type")

        with pytest.raises(TypeError):
            wrong_error()


class TestGotoWithRetry:
    """Tests for goto_with_retry helper."""

    def test_succeeds_on_first_try(self):
        mock_page = MagicMock()
        mock_page.goto.return_value = "response"

        result = goto_with_retry(mock_page, "https://example.com", max_attempts=3)
        assert result == "response"
        mock_page.goto.assert_called_once()

    def test_retries_on_timeout(self):
        from playwright.sync_api import TimeoutError as PWTimeout

        mock_page = MagicMock()
        mock_page.goto.side_effect = [PWTimeout("timeout"), PWTimeout("timeout"), "ok"]

        result = goto_with_retry(mock_page, "https://example.com", max_attempts=3)
        assert result == "ok"
        assert mock_page.goto.call_count == 3

    def test_raises_after_all_attempts_fail(self):
        from playwright.sync_api import TimeoutError as PWTimeout

        mock_page = MagicMock()
        mock_page.goto.side_effect = PWTimeout("timeout")

        with pytest.raises(PWTimeout):
            goto_with_retry(mock_page, "https://example.com", max_attempts=2)
        assert mock_page.goto.call_count == 2
