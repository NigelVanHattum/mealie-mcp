"""
Mealie app / account checks — used to verify connectivity and authentication.

Endpoints:
  GET /api/app/about    server info (version, etc.) — no auth required
  GET /api/users/self   the authenticated user — confirms the token works
"""

from typing import Any

import mcp.types as types

from client import api

_RO = types.ToolAnnotations(read_only_hint=True, open_world_hint=True)

TOOLS = [
    types.Tool(
        name="get_server_info",
        description="Get Mealie server info (version, production flag). Use as a "
                    "connectivity check.",
        annotations=_RO,
        input_schema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="get_current_user",
        description="Get the authenticated Mealie user. Use to verify the API token "
                    "is valid and to discover the active group/household.",
        annotations=_RO,
        input_schema={"type": "object", "properties": {}},
    ),
]

TOOL_NAMES = {t.name for t in TOOLS}


def dispatch(name: str, a: dict) -> Any:
    if name == "get_server_info":
        return api("GET", "/api/app/about")
    if name == "get_current_user":
        return api("GET", "/api/users/self")
    raise ValueError(f"Unknown tool: {name}")
