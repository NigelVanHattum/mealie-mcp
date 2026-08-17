"""
Mealie foods (ingredient foods).

Endpoints:
  GET    /api/foods            list foods
  POST   /api/foods            create food   (body: CreateIngredientFood)
  GET    /api/foods/{item_id}  get one food

Foods are the canonical ingredient items used by structured recipe ingredients.
For the common cookbook-import flow ingredients are stored as free text on the
recipe itself, so these tools are optional — use them only when you want a
recipe's ingredients linked to reusable, structured food records.
"""

from typing import Any

import mcp.types as types

from client import api, omit

_RO = types.ToolAnnotations(read_only_hint=True, open_world_hint=True)
_WRITE = types.ToolAnnotations(read_only_hint=False, idempotent_hint=True, open_world_hint=True)

TOOLS = [
    types.Tool(
        name="list_foods",
        description="List ingredient foods (paginated). Use to check whether a "
                    "food already exists before creating it.",
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
        name="create_food",
        description="Create an ingredient food. Returns the created food with its id.",
        annotations=_WRITE,
        input_schema={
            "type": "object",
            "properties": {
                "name":        {"type": "string", "description": "Food name, e.g. 'flour'."},
                "pluralName":  {"type": "string", "description": "Optional plural form, e.g. 'eggs'."},
                "description": {"type": "string", "description": "Optional description."},
            },
            "required": ["name"],
        },
    ),
]

TOOL_NAMES = {t.name for t in TOOLS}


def dispatch(name: str, a: dict) -> Any:
    if name == "list_foods":
        return api("GET", "/api/foods", params={
            "search":  a.get("search"),
            "page":    a.get("page", 1),
            "perPage": a.get("perPage", 50),
        })
    if name == "create_food":
        return api("POST", "/api/foods", body=omit(a))
    raise ValueError(f"Unknown tool: {name}")
