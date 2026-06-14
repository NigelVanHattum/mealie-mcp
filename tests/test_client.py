"""Tests for client.py — HTTP + auth helpers."""

import pytest
import httpx
from unittest.mock import patch, MagicMock

import client


# ---------------------------------------------------------------------------
# omit()
# ---------------------------------------------------------------------------

class TestOmit:
    def test_removes_specified_keys(self):
        assert client.omit({"a": 1, "b": 2, "c": 3}, "b") == {"a": 1, "c": 3}

    def test_strips_none_values(self):
        assert client.omit({"a": 1, "b": None, "c": 0}) == {"a": 1, "c": 0}

    def test_strips_none_and_omits_keys(self):
        assert client.omit({"slug": "x", "limit": None, "offset": 10}, "slug") == {"offset": 10}

    def test_false_not_stripped(self):
        assert client.omit({"enabled": False, "x": None}) == {"enabled": False}

    def test_zero_not_stripped(self):
        assert client.omit({"page": 0}) == {"page": 0}


# ---------------------------------------------------------------------------
# api()
# ---------------------------------------------------------------------------

def _mock_response(json_data=None, status=200, content=b"{}"):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.content = content
    if json_data is not None:
        resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


class TestApi:
    def test_get_returns_json(self):
        mock_resp = _mock_response(json_data={"items": [1, 2]}, content=b'{"items":[1,2]}')
        with patch("client._make_client") as mk:
            mk.return_value.__enter__.return_value.request.return_value = mock_resp
            assert client.api("GET", "/api/recipes") == {"items": [1, 2]}

    def test_empty_response_returns_success(self):
        mock_resp = _mock_response(content=b"")
        with patch("client._make_client") as mk:
            mk.return_value.__enter__.return_value.request.return_value = mock_resp
            assert client.api("DELETE", "/api/recipes/x") == {"status": "success"}

    def test_bare_string_response_returned_as_text(self):
        """POST /api/recipes returns a bare quoted slug string."""
        mock_resp = _mock_response(json_data="my-recipe", content=b'"my-recipe"')
        with patch("client._make_client") as mk:
            mk.return_value.__enter__.return_value.request.return_value = mock_resp
            assert client.api("POST", "/api/recipes", body={"name": "My Recipe"}) == "my-recipe"

    def test_non_json_response_falls_back_to_text(self):
        mock_resp = _mock_response(content=b"plain-slug")
        mock_resp.json.side_effect = ValueError("no json")
        mock_resp.text = "plain-slug"
        with patch("client._make_client") as mk:
            mk.return_value.__enter__.return_value.request.return_value = mock_resp
            assert client.api("POST", "/api/recipes", body={"name": "x"}) == "plain-slug"

    def test_strips_none_params(self):
        mock_resp = _mock_response(json_data={}, content=b"{}")
        with patch("client._make_client") as mk:
            req = mk.return_value.__enter__.return_value.request
            req.return_value = mock_resp
            client.api("GET", "/api/recipes", params={"page": 1, "search": None})
        assert req.call_args.kwargs["params"] == {"page": 1}

    def test_all_none_params_become_none(self):
        mock_resp = _mock_response(json_data={}, content=b"{}")
        with patch("client._make_client") as mk:
            req = mk.return_value.__enter__.return_value.request
            req.return_value = mock_resp
            client.api("GET", "/api/recipes", params={"search": None})
        assert req.call_args.kwargs["params"] is None

    def test_passes_body_as_json(self):
        mock_resp = _mock_response(json_data={}, content=b"{}")
        with patch("client._make_client") as mk:
            req = mk.return_value.__enter__.return_value.request
            req.return_value = mock_resp
            client.api("POST", "/api/foods", body={"name": "flour"})
        assert req.call_args.kwargs["json"] == {"name": "flour"}

    def test_raises_on_http_error(self):
        mock_resp = _mock_response(status=404)
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Not Found", request=MagicMock(), response=mock_resp
        )
        with patch("client._make_client") as mk:
            mk.return_value.__enter__.return_value.request.return_value = mock_resp
            with pytest.raises(httpx.HTTPStatusError):
                client.api("GET", "/api/recipes/bad")


# ---------------------------------------------------------------------------
# Auth — API key only
# ---------------------------------------------------------------------------

class TestAuth:
    def test_api_token_returned(self):
        with patch.object(client, "MEALIE_API_TOKEN", "tok-123"):
            assert client._bearer() == "tok-123"

    def test_missing_token_raises(self):
        with patch.object(client, "MEALIE_API_TOKEN", ""):
            with pytest.raises(RuntimeError, match="API token"):
                client._bearer()

    def test_client_sets_bearer_header(self):
        with patch.object(client, "MEALIE_API_TOKEN", "tok-123"), \
             patch.object(client, "MEALIE_BASE_URL", "https://m.example.com"):
            c = client._make_client()
            try:
                assert c.headers["authorization"] == "Bearer tok-123"
            finally:
                c.close()

    def test_no_username_password_support(self):
        """The client must not carry any username/password auth path."""
        assert not hasattr(client, "_login")
        assert not hasattr(client, "MEALIE_USERNAME")
