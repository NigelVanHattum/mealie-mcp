# Mealie MCP Server

Docker-hosted MCP server for [Mealie](https://mealie.io). It gives an AI agent
the tools to **read a cookbook (e.g. a PDF), extract the recipes (translating
them if needed) and store them in Mealie** — then verify its own work.

Built against **Mealie API v3.19.2**. Transport: **SSE**
(`http://localhost:8001/sse`) — persistent container, no subprocess spawning.

It deliberately covers only the endpoints that serve the cookbook → Mealie
workflow (recipes, recipe images, organizers, foods, units) plus read endpoints
for verification. The rest of the Mealie API is intentionally omitted.

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
4. **`set_recipe_image_from_url`** (or **`upload_recipe_image`**) — give the
   recipe a picture. Optional, but a recipe without one looks empty in Mealie.
5. **`get_recipe`** with the returned slug — verify the stored content.

`create_recipe` and `update_recipe` merge onto the recipe's current state, so
they never wipe fields you didn't provide. When you want a clean re-import, use
**`overwrite_recipe`** instead: it replaces all recipe content explicitly —
every content field you omit is cleared (identity, settings and image are kept).

## Tools Reference

| Group | Tools |
|---|---|
| App / verify | `get_server_info`, `get_current_user` |
| Recipes | `list_recipes`, `get_recipe`, `create_recipe`, `update_recipe`, `overwrite_recipe`, `delete_recipe` |
| Recipe images | `set_recipe_image_from_url`, `upload_recipe_image`, `delete_recipe_image` |
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

### Recipe images

Images are set on an existing recipe, by slug — create the recipe first. Both
write tools replace whatever image the recipe already had.

| Tool | Input | Use when |
|---|---|---|
| `set_recipe_image_from_url` | `slug`, `url` | The image is on the public web. Mealie downloads it server-side, so nothing is uploaded through the MCP connection. The URL must serve the image directly (image content-type, not an HTML page). |
| `upload_recipe_image` | `slug`, `imageBase64`, optional `extension` | You hold the bytes — e.g. a photo cropped out of a cookbook PDF — or the source isn't publicly reachable. |
| `delete_recipe_image` | `slug` | Remove the image, keep the recipe. |

`imageBase64` takes raw base64 or a data URI (`data:image/png;base64,…`). The
format is detected from the image's magic bytes (jpg, png, webp, gif, bmp, heic,
avif); pass `extension` only if detection fails. Base64 inflates payloads by
~33%, so keep uploads to a few MB — use the URL tool where you can.

Mealie re-encodes every image to WebP and stores three sizes. A recipe's `image`
field is a cache-busting version key, not a path, so all three tools re-read the
recipe and return the id, the new version key and the resulting media URLs:

```json
{
  "slug": "pannenkoeken",
  "recipeId": "a1b2c3d4-…",
  "imageVersion": "GhIjKl",
  "hasImage": true,
  "imageUrls": {
    "original": "https://mealie.example.com/api/media/recipes/a1b2c3d4-…/images/original.webp",
    "min":      ".../min-original.webp",
    "tiny":     ".../tiny-original.webp"
  }
}
```

Those media URLs are served by Mealie's `/api/media` routes, which do not
require the API token — anyone who can reach the Mealie instance can fetch them.

**`hasImage` is checked, not assumed.** Mealie's URL endpoint returns success and
bumps the version key even when its own download failed — it swallows the fetch
error — so a 2xx there does not mean an image was stored. The most common cause
is Mealie's SSRF guard: it refuses URLs that resolve to a private or local
address, which rules out serving the image from another host on your LAN. So:

- `hasImage` reflects whether the stored file actually serves, not the version key.
- `set_recipe_image_from_url` **raises** when nothing was stored, with the likely
  causes, instead of reporting a false success.
- If the recipe already had an image, a failed download leaves the old one in
  place. That case can't be proven either way, so the result carries
  `imageChanged: false` plus a `warning` rather than an error.

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
