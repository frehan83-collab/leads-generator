"""
Tests for the webhook notification module.
HTTP calls are mocked — no real webhooks are sent.
"""

import pytest
from unittest.mock import patch, MagicMock

from src.notifications.webhook import send_pipeline_alert


class TestSendPipelineAlert:
    """Tests for send_pipeline_alert function."""

    def test_returns_false_when_no_webhook_url(self):
        with patch.dict("os.environ", {}, clear=True):
            result = send_pipeline_alert({"postings_scraped": 10}, "completed")
            assert result is False

    @patch("src.notifications.webhook.requests.post")
    def test_sends_completed_alert(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        stats = {
            "postings_scraped": 50,
            "postings_new": 10,
            "prospects_found": 5,
            "emails_verified": 3,
            "drafts_created": 2,
            "errors": 0,
        }

        with patch.dict("os.environ", {"WEBHOOK_URL": "https://hooks.example.com/test"}):
            result = send_pipeline_alert(stats, "completed")

        assert result is True
        mock_post.assert_called_once()

        # Verify payload structure
        call_kwargs = mock_post.call_args[1]
        payload = call_kwargs["json"]
        assert "content" in payload  # Discord compatibility
        assert "text" in payload  # Generic / Mattermost
        assert "title" in payload
        assert "Completed" in payload["title"]
        assert "50" in payload["text"]  # postings_scraped

    @patch("src.notifications.webhook.requests.post")
    def test_sends_failed_alert_with_error(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        stats = {"postings_scraped": 0, "errors": 1}

        with patch.dict("os.environ", {"WEBHOOK_URL": "https://hooks.example.com/test"}):
            result = send_pipeline_alert(stats, "failed", error_message="Connection timeout")

        assert result is True
        payload = mock_post.call_args[1]["json"]
        assert "FAILED" in payload["title"]
        assert "Connection timeout" in payload["text"]

    @patch("src.notifications.webhook.requests.post")
    def test_no_new_postings_alert(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        stats = {"postings_scraped": 50, "postings_new": 0}

        with patch.dict("os.environ", {"WEBHOOK_URL": "https://hooks.example.com/test"}):
            result = send_pipeline_alert(stats, "completed")

        assert result is True
        payload = mock_post.call_args[1]["json"]
        assert "No New Postings" in payload["title"]

    @patch("src.notifications.webhook.requests.post")
    def test_returns_false_on_http_error(self, mock_post):
        mock_post.side_effect = Exception("Connection refused")

        stats = {"postings_scraped": 10}

        with patch.dict("os.environ", {"WEBHOOK_URL": "https://hooks.example.com/test"}):
            result = send_pipeline_alert(stats, "completed")

        assert result is False

    @patch("src.notifications.webhook.requests.post")
    def test_error_message_truncated(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        long_error = "x" * 500
        stats = {"errors": 1}

        with patch.dict("os.environ", {"WEBHOOK_URL": "https://hooks.example.com/test"}):
            send_pipeline_alert(stats, "failed", error_message=long_error)

        payload = mock_post.call_args[1]["json"]
        # Error message should be truncated to 200 chars
        assert len(long_error) > 200
        error_line = [l for l in payload["text"].split("\n") if "Error:" in l][0]
        assert len(error_line) < 250
