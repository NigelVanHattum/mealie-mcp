"""
Mealie organizers: categories, tags, and tools.

Endpoints:
  GET    /api/organizers/categories          list categories
  POST   /api/organizers/categories          create category   (body: {name})
  GET    /api/organizers/tags                 list tags
  POST   /api/organizers/tags                 create tag        (body: {name})
  GET    /api/organizers/tools                list tools
  POST   /api/organizers/tools                create tool       (body: {name})

Organizers must exist before they can be attached to a recipe. The resolve_*
helpers below look an organizer up by name (case-insensitive) and create it if
missing, returning the {id, name, slug} reference a recipe PUT expects. The
recipe tools use these so an agent can pass plain category/tag/tool names.
"""

from typing import Any

import mcp.types as types

from client import api

_RO = types.ToolAnnotations(readOnlyHint=True, openWorldHint=True)
_WRITE = types.ToolAnnotations(readOnlyHint=False, idempotentHint=True, openWorldHint=True)

_PAGE_PROPS = {
    "search":  {"type": "string", "description": "Case-insensitive name filter."},
    "page":    {"type": "integer", "description": "1-based page number (default 1)."},
    "perPage": {"type": "integer", "description": "Items per page (default 50)."},
}


def _make_list_tools() -> list[types.Tool]:
    out = []
    for kind in ("categories", "tags", "tools"):
        out.append(types.Tool(
            name=f"list_{kind}",
            description=f"List recipe {kind} (paginated). Use to verify which "
                        f"{kind} already exist before creating or assigning them.",
            annotations=_RO,
            inputSchema={"type": "object", "properties": dict(_PAGE_PROPS)},
        ))
    return out


def _make_create_tools() -> list[types.Tool]:
    out = []
    for kind, sing in (("categories", "category"), ("tags", "tag"), ("tools", "tool")):
        out.append(types.Tool(
            name=f"create_{sing}",
            description=f"Create a recipe {sing} by name. Returns the created "
                        f"{sing} with its id and slug. No-op friendly: if a {sing} "
                        f"with the same name exists, prefer assigning it instead.",
            annotations=_WRITE,
            inputSchema={
                "type": "object",
                "properties": {"name": {"type": "string", "description": f"{sing.capitalize()} name."}},
                "required": ["name"],
            },
        ))
    return out


TOOLS = _make_list_tools() + _make_create_tools()
TOOL_NAMES = {t.name for t in TOOLS}

# Path fragments per organizer kind.
_PATH = {
    "categories": "/api/organizers/categories",
    "tags":       "/api/organizers/tags",
    "tools":      "/api/organizers/tools",
}


def _list(kind: str, a: dict) -> Any:
    params = {
        "search":  a.get("search"),
        "page":    a.get("page", 1),
        "perPage": a.get("perPage", 50),
    }
    return api("GET", _PATH[kind], params=params)


def _create(kind: str, a: dict) -> Any:
    return api("POST", _PATH[kind], body={"name": a["name"]})


def dispatch(name: str, a: dict) -> Any:
    if name == "list_categories":
        return _list("categories", a)
    if name == "list_tags":
        return _list("tags", a)
    if name == "list_tools":
        return _list("tools", a)
    if name == "create_category":
        return _create("categories", a)
    if name == "create_tag":
        return _create("tags", a)
    if name == "create_tool":
        return _create("tools", a)
    raise ValueError(f"Unknown tool: {name}")


# ---------------------------------------------------------------------------
# Resolve helpers (used by the recipe tools)
# ---------------------------------------------------------------------------

def _ref(item: dict) -> dict:
    """Reduce a full organizer object to the reference a recipe PUT needs."""
    ref = {"name": item.get("name"), "slug": item.get("slug")}
    if item.get("id"):
        ref["id"] = item["id"]
    return ref


def _resolve(kind: str, names: list[str]) -> list[dict]:
    """Look each name up (case-insensitive) and create it if missing."""
    refs: list[dict] = []
    for raw in names:
        nm = (raw or "").strip()
        if not nm:
            continue
        existing = api("GET", _PATH[kind], params={"search": nm, "perPage": 100})
        match = next(
            (it for it in existing.get("items", []) if it.get("name", "").lower() == nm.lower()),
            None,
        )
        refs.append(_ref(match) if match else _ref(api("POST", _PATH[kind], body={"name": nm})))
    return refs


def resolve_categories(names: list[str]) -> list[dict]:
    return _resolve("categories", names)


def resolve_tags(names: list[str]) -> list[dict]:
    return _resolve("tags", names)


def resolve_tools(names: list[str]) -> list[dict]:
    return _resolve("tools", names)
