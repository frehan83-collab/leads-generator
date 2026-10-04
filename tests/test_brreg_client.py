"""BRREG client tests: name search, session lifecycle, error behavior."""

from unittest.mock import MagicMock, patch

from src.brreg.client import BRREGClient


def _resp(payload, status=200):
    mock = MagicMock()
    mock.status_code = status
    mock.ok = status < 400
    mock.json.return_value = payload
    if status >= 400:
        import requests
        mock.raise_for_status.side_effect = requests.exceptions.HTTPError(f"HTTP {status}")
    else:
        mock.raise_for_status.return_value = None
    return mock


def test_search_by_name_returns_companies():
    client = BRREGClient()
    with patch.object(client.session, "get",
                      return_value=_resp({"_embedded": {"enheter": [
                          {"organisasjonsnummer": "123456789", "navn": "Acme AS"}]}})):
        out = client.search_by_name("Acme", size=5)
    assert out[0]["organisasjonsnummer"] == "123456789"
    client.close()


def test_search_by_name_empty_on_error():
    client = BRREGClient()
    with patch.object(client.session, "get", side_effect=Exception("down")):
        assert client.search_by_name("Acme") == []
    client.close()


def test_session_recreated_after_close():
    client = BRREGClient()
    client.close()
    assert client.session is None
    # lazily recreated on next use
    with patch("requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_session.get.return_value = _resp({"_embedded": {"enheter": []}})
        mock_session_cls.return_value = mock_session
        assert client.search_by_name("Acme") == []
        assert client.session is mock_session
    client.close()


def test_context_manager_closes():
    with BRREGClient() as client:
        assert client.session is not None
    assert client.session is None
