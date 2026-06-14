"""Tool modules for the Mealie MCP server."""

from . import (
    app,
    recipes,
    organizers,
    foods,
    units,
)

_MODULES = [
    app,
    recipes,
    organizers,
    foods,
    units,
]

# Aggregated tool list for MCP registration.
ALL_TOOLS = [tool for mod in _MODULES for tool in mod.TOOLS]


def dispatch(name: str, args: dict):
    """Route a tool call to the owning module's dispatcher."""
    for mod in _MODULES:
        if name in mod.TOOL_NAMES:
            return mod.dispatch(name, args)
    raise ValueError(f"Unknown tool: {name}")
