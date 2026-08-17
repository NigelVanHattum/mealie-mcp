"""Tests for server.py — MCP handler wiring against the installed SDK.

These guard the SDK integration itself: the rest of the suite never imports
server.py, so an API break in the mcp package (handler signatures, result
types, transport) would otherwise only surface at runtime.
"""

from unittest.mock import patch

import httpx
import mcp.types as types

import server
import tools


class TestRoutes:
    def test_expected_routes(self):
        paths = {getattr(r, "path", None) for r in server.app.routes}
        assert {"/sse", "/messages", "/health"} <= paths


class TestListTools:
    async def test_returns_full_registry(self):
        result = await server.list_tools(None, None)
        assert isinstance(result, types.ListToolsResult)
        assert [t.name for t in result.tools] == [t.name for t in tools.ALL_TOOLS]


class TestCallTool:
    async def test_success_serializes_result(self):
        params = types.CallToolRequestParams(name="get_server_info", arguments={})
        with patch.object(tools, "dispatch", return_value={"ok": True}) as disp:
            result = await server.call_tool(None, params)
        disp.assert_called_once_with("get_server_info", {})
        assert result.is_error is False
        assert result.content[0].text == '{\n  "ok": true\n}'

    async def test_missing_arguments_defaults_to_empty_dict(self):
        params = types.CallToolRequestParams(name="get_server_info")
        with patch.object(tools, "dispatch", return_value={}) as disp:
            await server.call_tool(None, params)
        disp.assert_called_once_with("get_server_info", {})

    async def test_unknown_tool_is_error(self):
        params = types.CallToolRequestParams(name="nope", arguments={})
        result = await server.call_tool(None, params)
        assert result.is_error is True
        assert "Unknown tool" in result.content[0].text

    async def test_http_error_surfaces_mealie_status_and_body(self):
        exc = httpx.HTTPStatusError(
            "boom",
            request=httpx.Request("GET", "http://mealie/api/x"),
            response=httpx.Response(422, text="bad payload"),
        )
        params = types.CallToolRequestParams(name="get_server_info", arguments={})
        with patch.object(tools, "dispatch", side_effect=exc):
            result = await server.call_tool(None, params)
        assert result.is_error is True
        assert result.content[0].text == "HTTP 422 from Mealie: bad payload"
