"""
HTTP client and configuration for the Mealie API.

Authentication is API-key only: the server connects to Mealie with a
long-lived API token, sent as "Authorization: Bearer <token>".

Config resolution order (first found wins):
  1. /config/config.json  — Docker volume mount (-v /host/path:/config:ro)
  2. Environment variables

Environment variables:
  MEALIE_BASE_URL    - Base URL of the Mealie instance, no trailing slash
                       (e.g. https://mealie.example.com). Required.
  MEALIE_API_TOKEN   - Long-lived API token (Mealie: Settings -> API Tokens).
                       Required. Sent as "Authorization: Bearer".
  MEALIE_VERIFY_SSL  - "false" to skip TLS verification (default: true).
"""

import json
import os
from pathlib import Path
from typing import Any

import httpx


def _load_config() -> dict:
    """Load config from a Docker volume mount or environment variables."""
    config_file = Path("/config/config.json")
    if config_file.exists():
        try:
            return json.loads(config_file.read_text())
        except Exception:
            pass

    return {
        "base_url":   os.environ.get("MEALIE_BASE_URL", ""),
        "api_token":  os.environ.get("MEALIE_API_TOKEN", ""),
        "verify_ssl": os.environ.get("MEALIE_VERIFY_SSL", "true").lower() != "false",
    }


_cfg = _load_config()

MEALIE_BASE_URL   = _cfg.get("base_url", "").rstrip("/")
MEALIE_API_TOKEN  = _cfg.get("api_token", "")
MEALIE_VERIFY_SSL = _cfg.get("verify_ssl", True)


def _bearer() -> str:
    """Return the configured API token, or raise an actionable error."""
    if not MEALIE_API_TOKEN:
        raise RuntimeError(
            "No Mealie API token configured. Set MEALIE_API_TOKEN (or 'api_token' "
            "in /config/config.json). Create one in Mealie: Settings -> API Tokens."
        )
    return MEALIE_API_TOKEN


def _make_client() -> httpx.Client:
    if not MEALIE_BASE_URL:
        raise RuntimeError("MEALIE_BASE_URL is not configured.")
    return httpx.Client(
        base_url=MEALIE_BASE_URL,
        headers={
            "Authorization": f"Bearer {_bearer()}",
            "Accept": "application/json",
        },
        verify=MEALIE_VERIFY_SSL,
        timeout=60.0,
    )


def api(
    method: str,
    path: str,
    params: dict | None = None,
    body: Any | None = None,
    files: dict | None = None,
) -> Any:
    """Execute an API request and return parsed JSON.

    Returns {"status": "success"} for empty (204) responses.
    Raises httpx.HTTPStatusError on non-2xx; the server layer formats the
    status code and response body into an actionable error message.
    """
    clean_params = {k: v for k, v in (params or {}).items() if v is not None} or None
    with _make_client() as client:
        kwargs: dict = {"params": clean_params}
        if files is not None:
            kwargs["files"] = files
            if body is not None:
                kwargs["data"] = body
        elif body is not None:
            kwargs["json"] = body
        r = client.request(method=method, url=path, **kwargs)
        r.raise_for_status()
        if not r.content:
            return {"status": "success"}
        try:
            return r.json()
        except ValueError:
            return r.text


def omit(d: dict, *keys: str) -> dict:
    """Return dict without the specified keys and without None values."""
    return {k: v for k, v in d.items() if k not in keys and v is not None}
