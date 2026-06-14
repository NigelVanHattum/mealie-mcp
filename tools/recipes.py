"""
Mealie recipes — the core of the cookbook -> Mealie workflow.

Endpoints used:
  GET    /api/recipes              list/search recipes (paginated summaries)
  POST   /api/recipes              create stub recipe (body: {name}) -> slug
  GET    /api/recipes/{slug}       full recipe (Recipe-Output)
  PUT    /api/recipes/{slug}       replace recipe (body: Recipe-Input)
  DELETE /api/recipes/{slug}       delete recipe

Mealie creates a recipe in two steps: POST a name to mint a slug, then PUT the
full content. `create_recipe` does both in one call. Both create_recipe and
update_recipe merge onto the recipe's current state, so unspecified fields are
preserved (non-destructive). Categories, tags and tools may be given as plain
names — they are looked up and created on demand.
"""

from typing import Any

import mcp.types as types

from client import api
from . import organizers

# ---------------------------------------------------------------------------
# Content fields shared by create_recipe and update_recipe
# ---------------------------------------------------------------------------

_CONTENT_PROPS = {
    "description":  {"type": "string", "description": "Short recipe description / intro."},
    "ingredients": {
        "type": "array",
        "items": {"type": ["string", "object"]},
        "description": "Ingredient lines. Each item is normally a single string "
                       "(e.g. '200 g bloem'); it is stored as a free-text ingredient. "
                       "Advanced: an object {quantity, unit, food, note, title} for a "
                       "structured ingredient.",
    },
    "instructions": {
        "type": "array",
        "items": {"type": ["string", "object"]},
        "description": "Ordered preparation steps. Each item is a string, or an "
                       "object {title, text} to group/label a step.",
    },
    "recipeYield":  {"type": "string", "description": "Yield text, e.g. '4 personen' / '12 koekjes'."},
    "servings":     {"type": "number", "description": "Number of servings (numeric)."},
    "prepTime":     {"type": "string", "description": "Prep time, free text e.g. '20 minuten'."},
    "cookTime":     {"type": "string", "description": "Cook time, free text e.g. '45 minuten'."},
    "totalTime":    {"type": "string", "description": "Total time, free text."},
    "categories":   {"type": "array", "items": {"type": "string"},
                     "description": "Category names; created if they don't exist."},
    "tags":         {"type": "array", "items": {"type": "string"},
                     "description": "Tag names; created if they don't exist."},
    "tools":        {"type": "array", "items": {"type": "string"},
                     "description": "Tool names; created if they don't exist."},
    "nutrition":    {"type": "object",
                     "description": "Optional nutrition, e.g. {\"calories\": \"250\", "
                                    "\"proteinContent\": \"8\"}. Values are strings."},
    "orgURL":       {"type": "string", "description": "Source URL, if the recipe came from the web."},
    "extras":       {"type": "object",
                     "description": "Optional key/value metadata, e.g. {\"source_book\": \"...\", "
                                    "\"page\": \"42\"}."},
}

_RO = types.ToolAnnotations(readOnlyHint=True, openWorldHint=True)
_CREATE = types.ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True)
_UPDATE = types.ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                idempotentHint=True, openWorldHint=True)
_OVERWRITE = types.ToolAnnotations(readOnlyHint=False, destructiveHint=True,
                                   idempotentHint=True, openWorldHint=True)
_DELETE = types.ToolAnnotations(readOnlyHint=False, destructiveHint=True,
                                idempotentHint=True, openWorldHint=True)

TOOLS = [
    types.Tool(
        name="list_recipes",
        description="List or search recipes (paginated summaries). Use to verify a "
                    "recipe was stored, or to check for duplicates before creating one.",
        annotations=_RO,
        inputSchema={
            "type": "object",
            "properties": {
                "search":     {"type": "string", "description": "Full-text search across recipes."},
                "categories": {"type": "array", "items": {"type": "string"},
                               "description": "Filter by category name(s) or slug(s)."},
                "tags":       {"type": "array", "items": {"type": "string"},
                               "description": "Filter by tag name(s) or slug(s)."},
                "page":       {"type": "integer", "description": "1-based page number (default 1)."},
                "perPage":    {"type": "integer", "description": "Items per page (default 50)."},
                "orderBy":    {"type": "string", "description": "Field to order by, e.g. 'created_at'."},
                "orderDirection": {"type": "string", "enum": ["asc", "desc"],
                                   "description": "Sort direction (default desc)."},
            },
        },
    ),
    types.Tool(
        name="get_recipe",
        description="Get a single recipe in full by its slug, including ingredients "
                    "and instructions. Use to verify stored content.",
        annotations=_RO,
        inputSchema={
            "type": "object",
            "properties": {"slug": {"type": "string", "description": "Recipe slug."}},
            "required": ["slug"],
        },
    ),
    types.Tool(
        name="create_recipe",
        description="Create a complete recipe in one call. Mints the recipe from "
                    "its name, then fills in all provided content. Returns the full "
                    "stored recipe (including its slug). Ideal for storing a recipe "
                    "extracted from a cookbook; translate fields to the target "
                    "language before calling.",
        annotations=_CREATE,
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Recipe title (must be unique-ish; "
                                                          "Mealie derives the slug from it)."},
                **_CONTENT_PROPS,
            },
            "required": ["name"],
        },
    ),
    types.Tool(
        name="update_recipe",
        description="Update an existing recipe by slug. Only the fields you provide "
                    "are changed; everything else is preserved. Use to correct or "
                    "enrich a recipe after verifying it.",
        annotations=_UPDATE,
        inputSchema={
            "type": "object",
            "properties": {
                "slug": {"type": "string", "description": "Slug of the recipe to update."},
                "name": {"type": "string", "description": "New title (optional)."},
                **_CONTENT_PROPS,
            },
            "required": ["slug"],
        },
    ),
    types.Tool(
        name="overwrite_recipe",
        description="Replace a recipe's entire content by slug (explicit overwrite, "
                    "NOT a merge). Every content field is set to what you provide; "
                    "any content field you omit is CLEARED (description, ingredients, "
                    "instructions, times, yield, categories, tags, tools, nutrition, "
                    "orgURL, extras). The recipe's identity, settings and image are "
                    "kept. Use to fully re-import a recipe from scratch; use "
                    "update_recipe instead to change only some fields.",
        annotations=_OVERWRITE,
        inputSchema={
            "type": "object",
            "properties": {
                "slug": {"type": "string", "description": "Slug of the recipe to overwrite."},
                "name": {"type": "string", "description": "New title (kept as-is if omitted)."},
                **_CONTENT_PROPS,
            },
            "required": ["slug"],
        },
    ),
    types.Tool(
        name="delete_recipe",
        description="Delete a recipe by slug. Destructive and not reversible.",
        annotations=_DELETE,
        inputSchema={
            "type": "object",
            "properties": {"slug": {"type": "string", "description": "Slug of the recipe to delete."}},
            "required": ["slug"],
        },
    ),
]

TOOL_NAMES = {t.name for t in TOOLS}


# ---------------------------------------------------------------------------
# Content transforms
# ---------------------------------------------------------------------------

def _ingredient(item: Any) -> dict:
    """Normalise one ingredient into a Mealie RecipeIngredient object."""
    if isinstance(item, str):
        # Free-text ingredient: no parsed amount, render the line as-is.
        return {"quantity": None, "unit": None, "food": None,
                "note": item.strip(), "originalText": item.strip()}
    if isinstance(item, dict):
        ing = dict(item)
        # Allow unit/food given as plain strings for convenience.
        if isinstance(ing.get("unit"), str):
            ing["unit"] = {"name": ing["unit"]}
        if isinstance(ing.get("food"), str):
            ing["food"] = {"name": ing["food"]}
        return ing
    return {"note": str(item)}


def _instruction(item: Any) -> dict:
    if isinstance(item, str):
        return {"text": item.strip()}
    if isinstance(item, dict):
        return item
    return {"text": str(item)}


def _nutrition(value: dict) -> dict:
    # Mealie stores nutrition values as strings.
    return {k: (None if v is None else str(v)) for k, v in value.items()}


def _build_overrides(a: dict) -> dict:
    """Map provided snake/camel args to a partial Recipe-Input override dict."""
    o: dict = {}
    if "name" in a:
        o["name"] = a["name"]
    if "description" in a:
        o["description"] = a["description"]
    if "recipeYield" in a:
        o["recipeYield"] = a["recipeYield"]
    if "servings" in a:
        o["recipeServings"] = a["servings"]
    for k in ("prepTime", "cookTime", "totalTime", "orgURL", "extras"):
        if k in a:
            o[k] = a[k]
    if "ingredients" in a:
        o["recipeIngredient"] = [_ingredient(x) for x in a["ingredients"]]
    if "instructions" in a:
        o["recipeInstructions"] = [_instruction(x) for x in a["instructions"]]
    if "categories" in a:
        o["recipeCategory"] = organizers.resolve_categories(a["categories"])
    if "tags" in a:
        o["tags"] = organizers.resolve_tags(a["tags"])
    if "tools" in a:
        o["tools"] = organizers.resolve_tools(a["tools"])
    if "nutrition" in a:
        o["nutrition"] = _nutrition(a["nutrition"])
    return o


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def _list_recipes(a: dict) -> Any:
    params = {
        "search":         a.get("search"),
        "categories":     a.get("categories"),
        "tags":           a.get("tags"),
        "page":           a.get("page", 1),
        "perPage":        a.get("perPage", 50),
        "orderBy":        a.get("orderBy"),
        "orderDirection": a.get("orderDirection"),
    }
    return api("GET", "/api/recipes", params=params)


def _create_recipe(a: dict) -> Any:
    # 1) Mint the recipe from its name -> returns the new slug (a bare string).
    slug = api("POST", "/api/recipes", body={"name": a["name"]})
    if isinstance(slug, dict):
        slug = slug.get("slug") or slug.get("value")
    # 2) Fetch the freshly created recipe so we PUT a complete, valid object.
    base = api("GET", f"/api/recipes/{slug}")
    # 3) Merge content on top and PUT. `name` already set; drop it from overrides
    #    unless the caller explicitly wants a different title.
    overrides = _build_overrides({k: v for k, v in a.items() if k != "name"})
    payload = {**base, **overrides}
    api("PUT", f"/api/recipes/{slug}", body=payload)
    # 4) Return the stored recipe (verification-friendly).
    return api("GET", f"/api/recipes/{slug}")


def _update_recipe(a: dict) -> Any:
    slug = a["slug"]
    base = api("GET", f"/api/recipes/{slug}")
    overrides = _build_overrides({k: v for k, v in a.items() if k != "slug"})
    payload = {**base, **overrides}
    api("PUT", f"/api/recipes/{slug}", body=payload)
    return api("GET", f"/api/recipes/{slug}")


# Content fields cleared by an explicit overwrite when not supplied by the caller.
# Numeric fields use 0 (Mealie requires a number); everything else uses null/empty.
_CLEARED_CONTENT = {
    "description": None,
    "recipeYield": None,
    "recipeServings": 0,
    "recipeYieldQuantity": 0,
    "prepTime": None,
    "cookTime": None,
    "totalTime": None,
    "performTime": None,
    "recipeIngredient": [],
    "recipeInstructions": [],
    "recipeCategory": [],
    "tags": [],
    "tools": [],
    "nutrition": None,
    "orgURL": None,
    "extras": {},
}


def _overwrite_recipe(a: dict) -> Any:
    """Full replace: start from the current recipe, clear all content fields,
    then apply only what the caller provided. Identity, settings and image are
    preserved; every other content field is wiped unless supplied."""
    slug = a["slug"]
    base = api("GET", f"/api/recipes/{slug}")
    payload = dict(base)
    payload.update(_CLEARED_CONTENT)
    payload.update(_build_overrides({k: v for k, v in a.items() if k != "slug"}))
    api("PUT", f"/api/recipes/{slug}", body=payload)
    return api("GET", f"/api/recipes/{slug}")


def dispatch(name: str, a: dict) -> Any:
    if name == "list_recipes":
        return _list_recipes(a)
    if name == "get_recipe":
        return api("GET", f"/api/recipes/{a['slug']}")
    if name == "create_recipe":
        return _create_recipe(a)
    if name == "update_recipe":
        return _update_recipe(a)
    if name == "overwrite_recipe":
        return _overwrite_recipe(a)
    if name == "delete_recipe":
        return api("DELETE", f"/api/recipes/{a['slug']}")
    raise ValueError(f"Unknown tool: {name}")
