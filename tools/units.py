"""
Mealie units (ingredient units).

Endpoints:
  GET    /api/units            list units
  POST   /api/units            create unit   (body: CreateIngredientUnit)
  GET    /api/units/{item_id}  get one unit

Units pair with foods for structured ingredients. Optional for the common
free-text cookbook-import flow.
"""

from typing import Any

import mcp.types as types

from client import api, omit

_RO = types.ToolAnnotations(read_only_hint=True, open_world_hint=True)
_WRITE = types.ToolAnnotations(read_only_hint=False, idempotent_hint=True, open_world_hint=True)

TOOLS = [
    types.Tool(
        name="list_units",
        description="List ingredient units (paginated). Use to check whether a "
                    "unit already exists before creating it.",
        annotations=_RO,
        input_schema={
            "type": "object",
            "properties": {
                "search":  {"type": "string", "description": "Case-insensitive name filter."},
                "page":    {"type": "integer", "description": "1-based page number (default 1)."},
                "perPage": {"type": "integer", "description": "Items per page (default 50)."},
            },
        },
    ),
    types.Tool(
        name="create_unit",
        description="Create an ingredient unit. Returns the created unit with its id.",
        annotations=_WRITE,
        input_schema={
            "type": "object",
            "properties": {
                "name":         {"type": "string", "description": "Unit name, e.g. 'gram'."},
                "abbreviation": {"type": "string", "description": "Optional abbreviation, e.g. 'g'."},
                "pluralName":   {"type": "string", "description": "Optional plural form, e.g. 'grams'."},
                "description":  {"type": "string", "description": "Optional description."},
            },
            "required": ["name"],
        },
    ),
]

TOOL_NAMES = {t.name for t in TOOLS}


def dispatch(name: str, a: dict) -> Any:
    if name == "list_units":
        return api("GET", "/api/units", params={
            "search":  a.get("search"),
            "page":    a.get("page", 1),
            "perPage": a.get("perPage", 50),
        })
    if name == "create_unit":
        return api("POST", "/api/units", body=omit(a))
    raise ValueError(f"Unknown tool: {name}")
