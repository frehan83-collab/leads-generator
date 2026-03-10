"""
Tests for the AI email drafter module.
All Anthropic API calls are mocked — no real API calls are made.
"""

import sys
import pytest
from unittest.mock import patch, MagicMock

from src.emails.ai_drafter import generate_ai_opener


class TestGenerateAiOpener:
    """Tests for generate_ai_opener function."""

    def test_returns_none_when_no_api_key(self):
        with patch.dict("os.environ", {}, clear=True):
            result = generate_ai_opener(
                "Kari Nordmann", "HR Manager", "AquaCorp", "Biolog", "seafood"
            )
            assert result is None

    def test_returns_opener_with_valid_api_key(self):
        mock_client = MagicMock()
        mock_content = MagicMock()
        mock_content.text = "Vi la merke til at AquaCorp søker en ny biolog.\nDet er spennende!\nVi kan hjelpe."
        mock_response = MagicMock()
        mock_response.content = [mock_content]
        mock_client.messages.create.return_value = mock_response

        mock_anthropic = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key-123"}):
            with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
                result = generate_ai_opener(
                    "Kari Nordmann", "HR Manager", "AquaCorp", "Biolog", "seafood"
                )

        assert result is not None
        assert "AquaCorp" in result
        mock_client.messages.create.assert_called_once()

        # Check that correct model is used
        call_kwargs = mock_client.messages.create.call_args[1]
        assert "haiku" in call_kwargs["model"]

    def test_returns_none_when_anthropic_not_installed(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            with patch.dict("sys.modules", {"anthropic": None}):
                # Force ImportError by patching the import
                with patch("builtins.__import__", side_effect=_import_raiser("anthropic")):
                    result = generate_ai_opener(
                        "Ole Hansen", "CEO", "Corp AS", "Daglig leder", "HR"
                    )
                    assert result is None

    def test_returns_none_on_api_error(self):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("API error")

        mock_anthropic = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
                result = generate_ai_opener(
                    "Test User", "Manager", "TestCo", "Job Title", "keyword"
                )

        assert result is None


def _import_raiser(blocked_module):
    """Create an import function that blocks a specific module."""
    original_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

    def custom_import(name, *args, **kwargs):
        if name == blocked_module:
            raise ImportError(f"No module named '{blocked_module}'")
        return original_import(name, *args, **kwargs)

    return custom_import
