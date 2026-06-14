#!/usr/bin/env python3
"""
Mealie MCP Server — SSE transport (Docker-hosted).

Exposes recipe-management tools so an AI agent can read a cookbook, extract
recipes (translating if needed) and store them in Mealie, then verify its work.

Endpoints:
  GET  /sse        — MCP SSE connection endpoint
  POST /messages/  — MCP message endpoint (used by SSE transport internally)
  GET  /health     — liveness check

Configuration:
  Mount /config/config.json  OR  set MEALIE_BASE_URL + MEALIE_API_TOKEN
  (or MEALIE_USERNAME / MEALIE_PASSWORD) env vars. See client.py.
"""

import json
import os

import httpx
import mcp.types as types
import uvicorn
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

import tools

# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp_server = Server("mealie")


@mcp_server.list_tools()
async def list_tools() -> list[types.Tool]:
    return tools.ALL_TOOLS


@mcp_server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        result = tools.dispatch(name, arguments)
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, default=str))]
    except httpx.HTTPStatusError as e:
        # Surface the Mealie status code + body so the agent can self-correct.
        return [types.TextContent(
            type="text",
            text=f"HTTP {e.response.status_code} from Mealie: {e.response.text}",
        )]
    except Exception as e:
        return [types.TextContent(type="text", text=f"Error: {e}")]


# ---------------------------------------------------------------------------
# SSE transport + Starlette app
# ---------------------------------------------------------------------------

sse = SseServerTransport("/messages/")


async def handle_sse(request: Request):
    async with sse.connect_sse(
        request.scope, request.receive, request._send
    ) as streams:
        await mcp_server.run(
            streams[0], streams[1],
            mcp_server.create_initialization_options(),
        )


async def health(request: Request):
    return JSONResponse({"status": "ok"})


app = Starlette(
    routes=[
        Route("/sse", endpoint=handle_sse),
        Mount("/messages", app=sse.handle_post_message),
        Route("/health", endpoint=health),
    ]
)

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    host = os.environ.get("SERVER_HOST", "0.0.0.0")
    port = int(os.environ.get("SERVER_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)
