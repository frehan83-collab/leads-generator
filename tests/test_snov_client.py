"""
Tests for Snov.io client.
All HTTP calls are mocked — no real API calls are made.
"""

import pytest
from unittest.mock import patch, MagicMock

from src.snov.client import SnovClient


@pytest.fixture
def client():
    with patch.dict("os.environ", {
        "SNOV_CLIENT_ID": "test_client_id",
        "SNOV_CLIENT_SECRET": "test_client_secret",
    }):
        c = SnovClient()
        # Pre-set a fake token so we skip the auth call
        c._access_token = "fake_token"
        c._token_expires_at = 9999999999.0
        return c


def mock_response(data: dict, status_code: int = 200):
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = data
    mock.raise_for_status = MagicMock()
    return mock


def test_get_balance(client):
    with patch("requests.get") as mock_get:
        mock_get.return_value = mock_response({
            "data": {"balance": 500, "recipients_used": 10}
        })
        result = client.get_balance()
        assert result["data"]["balance"] == 500


def test_find_domain_by_company_name(client):
    with patch("requests.post") as mock_post, patch("requests.get") as mock_get:
        mock_post.return_value = mock_response({"data": {"task_hash": "abc123"}})
        mock_get.return_value = mock_response({
            "status": "complete",
            "data": [{"company": "AquaCorp", "domain": "aquacorp.no"}],
        })
        domain = client.find_domain_by_company_name("AquaCorp")
        assert domain == "aquacorp.no"


def test_find_domain_returns_none_on_empty(client):
    with patch("requests.post") as mock_post, patch("requests.get") as mock_get:
        mock_post.return_value = mock_response({"data": {"task_hash": "abc123"}})
        mock_get.return_value = mock_response({"status": "complete", "data": []})
        domain = client.find_domain_by_company_name("Unknown Corp")
        assert domain is None


def test_find_email_by_name_domain(client):
    with patch("requests.post") as mock_post, patch("requests.get") as mock_get:
        mock_post.return_value = mock_response({"data": {"task_hash": "xyz789"}})
        mock_get.return_value = mock_response({
            "status": "complete",
            "data": [{"email": "kari@aquacorp.no", "smtp_status": "valid"}],
        })
        result = client.find_email_by_name_domain("Kari", "Nordmann", "aquacorp.no")
        assert result is not None
        assert result["email"] == "kari@aquacorp.no"
        assert result["smtp_status"] == "valid"


def test_verify_email(client):
    with patch("requests.post") as mock_post, patch("requests.get") as mock_get:
        mock_post.return_value = mock_response({"data": {"task_hash": "ver123"}})
        mock_get.return_value = mock_response({
            "status": "complete",
            "data": [{"email": "test@corp.no", "smtp_status": "valid"}],
        })
        status = client.verify_email("test@corp.no")
        assert status == "valid"


def test_get_domain_email_count(client):
    with patch("requests.post") as mock_post:
        mock_post.return_value = mock_response({"data": {"total": 12}})
        count = client.get_domain_email_count("aquacorp.no")
        assert count == 12


def test_add_prospect_to_list(client):
    with patch("requests.post") as mock_post:
        mock_post.return_value = mock_response({"added": True})
        result = client.add_prospect_to_list("list_001", {
            "email": "ole@aquacorp.no",
            "first_name": "Ole",
            "last_name": "Hansen",
            "position": "CEO",
            "company_name": "AquaCorp",
            "company_domain": "aquacorp.no",
        })
        assert result is True
