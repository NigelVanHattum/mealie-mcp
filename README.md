# Mealie MCP Server

Docker-hosted MCP server for [Mealie](https://mealie.io). It gives an AI agent
the tools to **read a cookbook (e.g. a PDF), extract the recipes (translating
them if needed) and store them in Mealie** — then verify its own work.

Built against **Mealie API v3.19.2**. Transport: **SSE**
(`http://localhost:8001/sse`) — persistent container, no subprocess spawning.

It deliberately covers only the endpoints that serve the cookbook → Mealie
workflow (recipes, organizers, foods, units) plus read endpoints for
verification. The rest of the Mealie API is intentionally omitted.

## Prerequisites

- Docker (with Compose)
- A reachable Mealie instance
- A Mealie API token (or a username/password)

## Generate an API token

In Mealie: **avatar → Settings → API Tokens → Create** (or
`/user/profile/api-tokens`). Copy the token — it is shown only once.

## Quick Start

```bash
git clone https://github.com/NigelVanHattum/mealie-mcp.git
cd mealie-mcp

# Configure credentials
mkdir -p ~/.config/mealie-mcp
cat > ~/.config/mealie-mcp/config.json << 'EOF'
{
  "base_url": "https://mealie.example.com",
  "api_token": "your-api-token-here",
  "verify_ssl": true
}
EOF

# Start the server
docker compose up -d
```

The server runs at `http://localhost:8001`. Verify:

```bash
curl http://localhost:8001/health
# {"status": "ok"}
```

## Connect to Claude

### Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "mealie": {
      "url": "http://localhost:8001/sse"
    }
  }
}
```

Restart Claude Desktop, then try: _"Check my Mealie connection"_ → it calls
`get_current_user`.

### Claude Code

```bash
claude mcp add mealie --url http://localhost:8001/sse
```

## Configuration

Loaded in this order (first found wins):

| Priority | Method | Details |
|---|---|---|
| 1 | Config file | Mount `/config/config.json` via Docker volume |
| 2 | Environment vars | `MEALIE_BASE_URL`, `MEALIE_API_TOKEN`, … |

| Variable | Required | Description |
|---|---|---|
| `MEALIE_BASE_URL` | yes | Base URL, no trailing slash, e.g. `https://mealie.example.com` |
| `MEALIE_API_TOKEN` | yes | Long-lived API token (sent as `Authorization: Bearer`) |
| `MEALIE_VERIFY_SSL` | no | `false` to skip TLS verification (default `true`) |
| `SERVER_HOST` / `SERVER_PORT` | no | Bind address / port (default `0.0.0.0:8000` in-container) |

The server authenticates to Mealie with **API keys only** — there is no
username/password path.

## Exposure & security

The MCP API itself is **unauthenticated**: `/sse`, `/messages/` and `/health`
have no inbound auth. Anyone who can reach the port can call every tool —
including `create_recipe`, `overwrite_recipe` and `delete_recipe` — using the
server's Mealie API key.

So treat the server as a private backend: let **Obot** (or your MCP host)
connect to it over localhost or a private/Docker network, and do **not** expose
the port to the public internet. If it must traverse an untrusted network, put a
reverse proxy with authentication in front of it. Transport is SSE; Streamable
HTTP can be added if your host prefers it.

## Recommended agent workflow

1. **`get_current_user`** — confirm the token works and note the active group.
2. **`list_recipes`** with `search` — check the recipe doesn't already exist.
3. **`create_recipe`** — one call stores a full recipe. Translate fields to the
   target language (e.g. Dutch) *before* calling. Pass ingredients and
   instructions as plain strings; pass `categories` / `tags` / `tools` as names
   (they are created automatically if missing).
4. **`get_recipe`** with the returned slug — verify the stored content.

`create_recipe` and `update_recipe` merge onto the recipe's current state, so
they never wipe fields you didn't provide. When you want a clean re-import, use
**`overwrite_recipe`** instead: it replaces all recipe content explicitly —
every content field you omit is cleared (identity, settings and image are kept).

## Tools Reference

| Group | Tools |
|---|---|
| App / verify | `get_server_info`, `get_current_user` |
| Recipes | `list_recipes`, `get_recipe`, `create_recipe`, `update_recipe`, `overwrite_recipe`, `delete_recipe` |
| Organizers | `list_categories`, `create_category`, `list_tags`, `create_tag`, `list_tools`, `create_tool` |
| Foods | `list_foods`, `create_food` |
| Units | `list_units`, `create_unit` |

### `create_recipe` — key fields

`name` (required), `description`, `ingredients` (string[]), `instructions`
(string[]), `recipeYield`, `servings`, `prepTime`, `cookTime`, `totalTime`,
`categories` (string[]), `tags` (string[]), `tools` (string[]), `nutrition`
(object), `orgURL`, `extras` (object).

Ingredients are stored as free text by default — ideal for cookbook imports.
For structured ingredients, pass an object per line
(`{quantity, unit, food, note}`) and manage `foods` / `units` with their tools.

## Development

```bash
pip install -e ".[dev]"
pytest

# Build image locally (tests run in the build stage — build fails if tests fail)
docker build -t mealie-mcp .

docker compose up
```

## API Reference

Interactive docs for your instance: `https://<your-mealie>/docs` ·
OpenAPI: `https://<your-mealie>/openapi.json`
