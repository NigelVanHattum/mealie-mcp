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
from mcp.server import Server, ServerRequestContext
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

import tools

# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

async def list_tools(
    ctx: ServerRequestContext,
    params: types.PaginatedRequestParams | None,
) -> types.ListToolsResult:
    return types.ListToolsResult(tools=tools.ALL_TOOLS)


async def call_tool(
    ctx: ServerRequestContext,
    params: types.CallToolRequestParams,
) -> types.CallToolResult:
    try:
        result = tools.dispatch(params.name, params.arguments or {})
        text = json.dumps(result, indent=2, default=str)
        is_error = False
    except httpx.HTTPStatusError as e:
        # Surface the Mealie status code + body so the agent can self-correct.
        text = f"HTTP {e.response.status_code} from Mealie: {e.response.text}"
        is_error = True
    except Exception as e:
        text = f"Error: {e}"
        is_error = True
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)],
        isError=is_error,
    )


mcp_server = Server(
    "mealie",
    version="1.0.0",
    on_list_tools=list_tools,
    on_call_tool=call_tool,
)


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
    # SSE response is already sent by connect_sse; Starlette still wants a Response.
    return Response()


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
