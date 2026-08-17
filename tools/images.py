"""
Mealie recipe images.

Endpoints used:
  POST   /api/recipes/{slug}/image   Mealie downloads an image from a URL
                                     (body: {"url": "..."} — ScrapeRecipe)
  PUT    /api/recipes/{slug}/image   upload image bytes
                                     (multipart: image=<file>, extension=<ext>)
  DELETE /api/recipes/{slug}/image   remove the recipe's image

Mealie always re-encodes an uploaded image to WebP and stores three sizes under
`/api/media/recipes/{recipe_id}/images/`: `original.webp`, `min-original.webp`
and `tiny-original.webp`. The recipe's own `image` field is only a cache-busting
version key, not a path — so after every write these tools re-read the recipe and
return the recipe id, the new version key and the resulting media URLs, so the
agent can verify its work.

Mealie bumps that version key on the URL endpoint even when its own download
failed (it swallows the fetch error and still returns 2xx), so a success status
does not mean an image was stored. Every write therefore checks that the stored
file actually serves before reporting success; set_recipe_image_from_url also
compares the stored image with the one that was there before, so a failure that
leaves an older image in place is flagged rather than passed off as success.

A recipe must exist before it can have an image: create it first (create_recipe),
then set the image by slug.
"""

import base64
import binascii
import hashlib
from typing import Any

import mcp.types as types

import client
from client import api

_UPDATE = types.ToolAnnotations(read_only_hint=False, destructive_hint=False,
                                idempotent_hint=True, open_world_hint=True)
_DELETE = types.ToolAnnotations(read_only_hint=False, destructive_hint=True,
                                idempotent_hint=True, open_world_hint=True)

TOOLS = [
    types.Tool(
        name="set_recipe_image_from_url",
        description="Set a recipe's image from a public image URL. Mealie downloads "
                    "the image itself, so nothing needs to be uploaded — prefer this "
                    "when the image is reachable on the web. The URL must serve the "
                    "image directly (an image content-type, not an HTML page). "
                    "Replaces any existing image. Use upload_recipe_image instead "
                    "when you hold the image bytes (e.g. extracted from a cookbook PDF).",
        annotations=_UPDATE,
        input_schema={
            "type": "object",
            "properties": {
                "slug": {"type": "string", "description": "Slug of the recipe to set the image on."},
                "url":  {"type": "string",
                         "description": "Direct URL of the image, e.g. "
                                        "'https://example.com/photo.jpg'."},
            },
            "required": ["slug", "url"],
        },
    ),
    types.Tool(
        name="upload_recipe_image",
        description="Set a recipe's image by uploading the image bytes, given as "
                    "base64. Use this for images you extracted yourself (e.g. a photo "
                    "cropped from a cookbook page) or when the source URL is not "
                    "publicly reachable. Replaces any existing image. Mealie re-encodes "
                    "the upload to WebP, so the input format only needs to be readable "
                    "(jpg, png, webp, gif, bmp, heic, avif). Keep uploads modest — a "
                    "few MB at most; base64 inflates size by ~33%.",
        annotations=_UPDATE,
        input_schema={
            "type": "object",
            "properties": {
                "slug": {"type": "string", "description": "Slug of the recipe to set the image on."},
                "imageBase64": {"type": "string",
                                "description": "The image file, base64-encoded. A data URI "
                                               "('data:image/png;base64,...') is also accepted."},
                "extension": {"type": "string",
                              "description": "Optional source image extension, e.g. 'jpg' or "
                                             "'png'. Detected from the image data when omitted; "
                                             "only pass it if detection fails."},
            },
            "required": ["slug", "imageBase64"],
        },
    ),
    types.Tool(
        name="delete_recipe_image",
        description="Remove a recipe's image. The recipe itself is kept; only the "
                    "image is deleted. Not reversible — the image must be re-uploaded "
                    "to restore it.",
        annotations=_DELETE,
        input_schema={
            "type": "object",
            "properties": {"slug": {"type": "string",
                                    "description": "Slug of the recipe to remove the image from."}},
            "required": ["slug"],
        },
    ),
]

TOOL_NAMES = {t.name for t in TOOLS}


# ---------------------------------------------------------------------------
# Image data helpers
# ---------------------------------------------------------------------------

# Mealie names the stored files by size; the format is always WebP.
_MEDIA_FILES = {
    "original": "original.webp",
    "min":      "min-original.webp",
    "tiny":     "tiny-original.webp",
}

_MIME = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "webp": "image/webp", "gif": "image/gif", "bmp": "image/bmp",
    "heic": "image/heic", "avif": "image/avif",
}

# Leading magic bytes -> extension, for formats identified by a simple prefix.
_MAGIC_PREFIX = (
    (b"\xff\xd8\xff",          "jpg"),
    (b"\x89PNG\r\n\x1a\n",     "png"),
    (b"GIF87a",                "gif"),
    (b"GIF89a",                "gif"),
    (b"BM",                    "bmp"),
)


def _decode_image(raw: str) -> bytes:
    """Decode a base64 string (or data URI) into image bytes."""
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("imageBase64 is empty.")
    data = raw.strip()
    if data.startswith("data:"):
        # data:<mime>;base64,<payload> — keep only the payload.
        _, _, data = data.partition(",")
    try:
        blob = base64.b64decode(data, validate=False)
    except (binascii.Error, ValueError) as e:
        raise ValueError(f"imageBase64 is not valid base64: {e}") from e
    if not blob:
        raise ValueError("imageBase64 decoded to zero bytes.")
    return blob


def _sniff_extension(blob: bytes) -> str | None:
    """Identify the image format from its magic bytes, or None if unrecognised."""
    for prefix, ext in _MAGIC_PREFIX:
        if blob.startswith(prefix):
            return ext
    if blob[0:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return "webp"
    if blob[4:8] == b"ftyp":
        brand = blob[8:12]
        if brand in (b"heic", b"heix", b"hevc", b"mif1", b"msf1"):
            return "heic"
        if brand in (b"avif", b"avis"):
            return "avif"
    return None


def _extension(a: dict, blob: bytes) -> str:
    """Resolve the extension to send to Mealie: caller's value, else sniffed."""
    given = (a.get("extension") or "").strip().lstrip(".").lower()
    if given:
        return given
    sniffed = _sniff_extension(blob)
    if not sniffed:
        raise ValueError(
            "Could not identify the image format from its contents. Pass "
            "'extension' explicitly (e.g. 'jpg' or 'png'), and check that "
            "imageBase64 holds an image file rather than something else."
        )
    return sniffed


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def _media_path(recipe_id: str, name: str) -> str:
    return f"/api/media/recipes/{recipe_id}/images/{name}"


def _thumb_signature(recipe_id: str) -> str | None:
    """Hash the stored thumbnail, to tell one stored image from another.

    Uses the tiny size so the read stays small whatever the source image was.
    """
    blob = client.fetch(_media_path(recipe_id, _MEDIA_FILES["tiny"]))
    return hashlib.sha256(blob).hexdigest() if blob else None


def _image_state(slug: str, *, expect_image: bool, before: str | None = None) -> dict:
    """Re-read the recipe and report its image state, for the agent to verify.

    A recipe's `image` field is only a cache-busting version key, and Mealie
    bumps it even when no image was actually stored (see _set_from_url). So
    `hasImage` is taken from whether the stored file really serves, falling
    back to the version key only when that check can't be made.

    `before` is the thumbnail signature from before the write. When the stored
    image is byte-identical afterwards, the write may have been a no-op that
    Mealie reported as success — that can't be proven either way, so it is
    surfaced as a warning rather than an error.
    """
    recipe = api("GET", f"/api/recipes/{slug}")
    recipe_id = recipe.get("id") if isinstance(recipe, dict) else None
    version = recipe.get("image") if isinstance(recipe, dict) else None

    stored = client.exists(_media_path(recipe_id, _MEDIA_FILES["original"])) if recipe_id else False

    out: dict[str, Any] = {
        "slug": slug,
        "recipeId": recipe_id,
        "imageVersion": version,
        "hasImage": bool(version) if stored is None else stored,
    }
    if expect_image and recipe_id and stored is not False:
        base = client.MEALIE_BASE_URL.rstrip("/")
        out["imageUrls"] = {
            key: f"{base}{_media_path(recipe_id, name)}"
            for key, name in _MEDIA_FILES.items()
        }
    if before and recipe_id and out["hasImage"] and _thumb_signature(recipe_id) == before:
        out["imageChanged"] = False
        out["warning"] = (
            "The recipe's stored image is byte-identical to the one it had before "
            "this call, so Mealie may not have fetched anything and the previous "
            "image is still in place. Harmless if you re-applied the same image; "
            "otherwise check the URL is reachable from the Mealie server and serves "
            "the image directly, or use upload_recipe_image with the image bytes."
        )
    elif before:
        out["imageChanged"] = True
    return out


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def _set_from_url(a: dict) -> Any:
    slug = a["slug"]
    url = (a.get("url") or "").strip()
    if not url:
        raise ValueError("url is required and must not be empty.")
    # Note what the recipe already shows, so a silent no-op can be spotted below.
    recipe = api("GET", f"/api/recipes/{slug}")
    recipe_id = recipe.get("id") if isinstance(recipe, dict) else None
    before = _thumb_signature(recipe_id) if recipe_id else None
    # Mealie fetches the image server-side; the endpoint returns no body.
    api("POST", f"/api/recipes/{slug}/image", body={"url": url})
    state = _image_state(slug, expect_image=True, before=before)
    # Mealie bumps the recipe's image version key even when the download failed,
    # so a 2xx here does not mean an image was stored. Report the truth instead.
    if state["hasImage"] is False:
        raise RuntimeError(
            f"Mealie accepted the request but stored no image from {url!r}. It "
            "usually means Mealie itself could not fetch that URL: the address is "
            "unreachable from the Mealie server, it resolves to a private/local "
            "address (Mealie blocks those), it needs authentication, or it serves "
            "an HTML page rather than the image file. Check the URL opens the "
            "image directly, or use upload_recipe_image with the image bytes."
        )
    return state


def _upload(a: dict) -> Any:
    slug = a["slug"]
    blob = _decode_image(a.get("imageBase64", ""))
    ext = _extension(a, blob)
    # Multipart: `image` is the file part, `extension` a plain form field.
    api(
        "PUT",
        f"/api/recipes/{slug}/image",
        files={"image": (f"image.{ext}", blob, _MIME.get(ext, "application/octet-stream"))},
        body={"extension": ext},
    )
    return _image_state(slug, expect_image=True)


def _delete(a: dict) -> Any:
    slug = a["slug"]
    api("DELETE", f"/api/recipes/{slug}/image")
    return _image_state(slug, expect_image=False)


def dispatch(name: str, a: dict) -> Any:
    if name == "set_recipe_image_from_url":
        return _set_from_url(a)
    if name == "upload_recipe_image":
        return _upload(a)
    if name == "delete_recipe_image":
        return _delete(a)
    raise ValueError(f"Unknown tool: {name}")
