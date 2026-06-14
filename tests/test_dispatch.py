"""Tests for dispatch() in every tool module — HTTP method/path/body/params + workflows."""

from unittest.mock import patch, MagicMock


def run(module, name, args, api_mock):
    """Call module.dispatch with the module's `api` symbol patched."""
    with patch(f"{module.__name__}.api", api_mock):
        return module.dispatch(name, args)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

from tools import app

class TestAppDispatch:
    def test_server_info(self):
        m = MagicMock(return_value={"version": "v3.19.2"})
        run(app, "get_server_info", {}, m)
        m.assert_called_once_with("GET", "/api/app/about")

    def test_current_user(self):
        m = MagicMock(return_value={"username": "nigel"})
        run(app, "get_current_user", {}, m)
        m.assert_called_once_with("GET", "/api/users/self")


# ---------------------------------------------------------------------------
# Recipes — simple reads/deletes
# ---------------------------------------------------------------------------

from tools import recipes

class TestRecipeSimple:
    def test_list_defaults(self):
        m = MagicMock(return_value={"items": []})
        run(recipes, "list_recipes", {}, m)
        m.assert_called_once_with("GET", "/api/recipes", params={
            "search": None, "categories": None, "tags": None,
            "page": 1, "perPage": 50, "orderBy": None, "orderDirection": None})

    def test_list_with_search(self):
        m = MagicMock(return_value={"items": []})
        run(recipes, "list_recipes", {"search": "soep", "perPage": 10}, m)
        assert m.call_args.kwargs["params"]["search"] == "soep"
        assert m.call_args.kwargs["params"]["perPage"] == 10

    def test_get_recipe(self):
        m = MagicMock(return_value={"slug": "pannenkoek"})
        run(recipes, "get_recipe", {"slug": "pannenkoek"}, m)
        m.assert_called_once_with("GET", "/api/recipes/pannenkoek")

    def test_delete_recipe(self):
        m = MagicMock(return_value={"status": "success"})
        run(recipes, "delete_recipe", {"slug": "pannenkoek"}, m)
        m.assert_called_once_with("DELETE", "/api/recipes/pannenkoek")


# ---------------------------------------------------------------------------
# Recipes — create / update workflow (POST name -> GET -> PUT merged -> GET)
# ---------------------------------------------------------------------------

class TestRecipeCreate:
    def test_create_minimal_flow(self):
        base = {"slug": "appeltaart", "name": "Appeltaart", "recipeIngredient": []}
        m = MagicMock(side_effect=["appeltaart", base, {}, {**base, "verified": True}])
        result = run(recipes, "create_recipe", {"name": "Appeltaart"}, m)
        calls = m.call_args_list
        assert calls[0] == (("POST", "/api/recipes"), {"body": {"name": "Appeltaart"}})
        assert calls[1] == (("GET", "/api/recipes/appeltaart"),)
        assert calls[2][0] == ("PUT", "/api/recipes/appeltaart")
        assert calls[3] == (("GET", "/api/recipes/appeltaart"),)
        assert result == {**base, "verified": True}

    def test_create_with_content_builds_payload(self):
        base = {"slug": "appeltaart", "name": "Appeltaart"}
        m = MagicMock(side_effect=["appeltaart", base, {}, base])
        run(recipes, "create_recipe", {
            "name": "Appeltaart",
            "description": "Klassiek",
            "ingredients": ["200 g bloem", "100 g suiker"],
            "instructions": ["Meng alles", "Bak 45 minuten"],
            "recipeYield": "8 stukken",
            "servings": 8,
            "prepTime": "20 minuten",
            "nutrition": {"calories": 250},
        }, m)
        put = m.call_args_list[2]
        payload = put.kwargs["body"]
        assert payload["description"] == "Klassiek"
        assert payload["recipeYield"] == "8 stukken"
        assert payload["recipeServings"] == 8
        assert payload["prepTime"] == "20 minuten"
        # ingredients -> free-text notes
        assert payload["recipeIngredient"][0]["note"] == "200 g bloem"
        assert payload["recipeIngredient"][0]["quantity"] is None
        # instructions -> step objects
        assert payload["recipeInstructions"][0]["text"] == "Meng alles"
        # nutrition values coerced to strings
        assert payload["nutrition"]["calories"] == "250"

    def test_create_resolves_categories_and_tags(self):
        base = {"slug": "appeltaart", "name": "Appeltaart"}
        recipe_api = MagicMock(side_effect=["appeltaart", base, {}, base])
        # organizers.api: search returns empty, then POST returns created object
        org_api = MagicMock(side_effect=[
            {"items": []}, {"id": "c1", "name": "Nagerecht", "slug": "nagerecht"},  # category
            {"items": []}, {"id": "t1", "name": "Nederlands", "slug": "nederlands"},  # tag
        ])
        with patch("tools.recipes.api", recipe_api), patch("tools.organizers.api", org_api):
            recipes.dispatch("create_recipe", {
                "name": "Appeltaart", "categories": ["Nagerecht"], "tags": ["Nederlands"]})
        payload = recipe_api.call_args_list[2].kwargs["body"]
        assert payload["recipeCategory"] == [{"name": "Nagerecht", "slug": "nagerecht", "id": "c1"}]
        assert payload["tags"] == [{"name": "Nederlands", "slug": "nederlands", "id": "t1"}]


class TestRecipeUpdate:
    def test_update_merges_onto_existing(self):
        base = {"slug": "appeltaart", "name": "Appeltaart", "description": "oud",
                "prepTime": "10 min"}
        m = MagicMock(side_effect=[base, {}, {**base, "description": "nieuw"}])
        run(recipes, "update_recipe", {"slug": "appeltaart", "description": "nieuw"}, m)
        assert m.call_args_list[0] == (("GET", "/api/recipes/appeltaart"),)
        put = m.call_args_list[1]
        assert put.kwargs["body"]["description"] == "nieuw"
        assert put.kwargs["body"]["name"] == "Appeltaart"   # preserved
        assert put.kwargs["body"]["prepTime"] == "10 min"   # untouched field preserved


class TestRecipeOverwrite:
    def test_overwrite_clears_unspecified_keeps_identity(self):
        base = {
            "id": "r1", "slug": "appeltaart", "name": "Appeltaart",
            "description": "oud", "prepTime": "10 min",
            "recipeIngredient": [{"note": "200 g bloem"}],
            "tags": [{"name": "oud", "slug": "oud"}],
            "settings": {"locked": True}, "image": "img.jpg",
        }
        m = MagicMock(side_effect=[base, {}, {"slug": "appeltaart"}])
        run(recipes, "overwrite_recipe",
            {"slug": "appeltaart", "instructions": ["Bak het"]}, m)
        put = m.call_args_list[1]
        body = put.kwargs["body"]
        # provided content applied
        assert body["recipeInstructions"] == [{"text": "Bak het"}]
        # unspecified content cleared
        assert body["description"] is None
        assert body["prepTime"] is None
        assert body["recipeIngredient"] == []
        assert body["tags"] == []
        assert body["recipeServings"] == 0
        # identity + settings + image preserved
        assert body["id"] == "r1"
        assert body["name"] == "Appeltaart"
        assert body["settings"] == {"locked": True}
        assert body["image"] == "img.jpg"

    def test_overwrite_can_change_name(self):
        base = {"id": "r1", "slug": "appeltaart", "name": "Appeltaart"}
        m = MagicMock(side_effect=[base, {}, {"slug": "appeltaart"}])
        run(recipes, "overwrite_recipe",
            {"slug": "appeltaart", "name": "Nieuwe Appeltaart"}, m)
        assert m.call_args_list[1].kwargs["body"]["name"] == "Nieuwe Appeltaart"


# ---------------------------------------------------------------------------
# Recipe content transform helpers
# ---------------------------------------------------------------------------

class TestTransforms:
    def test_ingredient_string(self):
        ing = recipes._ingredient("2 eieren")
        assert ing["note"] == "2 eieren"
        assert ing["originalText"] == "2 eieren"
        assert ing["food"] is None and ing["unit"] is None and ing["quantity"] is None

    def test_ingredient_dict_passthrough_wraps_strings(self):
        ing = recipes._ingredient({"quantity": 2, "unit": "gram", "food": "bloem"})
        assert ing["unit"] == {"name": "gram"}
        assert ing["food"] == {"name": "bloem"}
        assert ing["quantity"] == 2

    def test_instruction_string(self):
        assert recipes._instruction("Roer goed") == {"text": "Roer goed"}

    def test_instruction_dict(self):
        step = {"title": "Saus", "text": "Laat sudderen"}
        assert recipes._instruction(step) == step

    def test_nutrition_coerced_to_str(self):
        assert recipes._nutrition({"calories": 250, "fatContent": None}) == \
            {"calories": "250", "fatContent": None}


# ---------------------------------------------------------------------------
# Organizers
# ---------------------------------------------------------------------------

from tools import organizers

class TestOrganizers:
    def test_list_categories(self):
        m = MagicMock(return_value={"items": []})
        run(organizers, "list_categories", {"search": "des"}, m)
        m.assert_called_once_with("GET", "/api/organizers/categories",
                                  params={"search": "des", "page": 1, "perPage": 50})

    def test_create_tag(self):
        m = MagicMock(return_value={"id": "t1", "name": "Vegan", "slug": "vegan"})
        run(organizers, "create_tag", {"name": "Vegan"}, m)
        m.assert_called_once_with("POST", "/api/organizers/tags", body={"name": "Vegan"})

    def test_create_tool(self):
        m = MagicMock(return_value={"id": "x", "name": "Oven", "slug": "oven"})
        run(organizers, "create_tool", {"name": "Oven"}, m)
        m.assert_called_once_with("POST", "/api/organizers/tools", body={"name": "Oven"})

    def test_resolve_existing_match_no_create(self):
        m = MagicMock(return_value={"items": [
            {"id": "c1", "name": "Dessert", "slug": "dessert"}]})
        with patch("tools.organizers.api", m):
            refs = organizers.resolve_categories(["dessert"])  # case-insensitive
        assert refs == [{"name": "Dessert", "slug": "dessert", "id": "c1"}]
        # only the GET search, never a POST
        assert m.call_count == 1

    def test_resolve_creates_when_missing(self):
        m = MagicMock(side_effect=[
            {"items": []}, {"id": "t9", "name": "Snel", "slug": "snel"}])
        with patch("tools.organizers.api", m):
            refs = organizers.resolve_tags(["Snel"])
        assert refs == [{"name": "Snel", "slug": "snel", "id": "t9"}]
        assert m.call_args_list[1] == (("POST", "/api/organizers/tags"), {"body": {"name": "Snel"}})


# ---------------------------------------------------------------------------
# Foods & Units
# ---------------------------------------------------------------------------

from tools import foods, units

class TestFoodsUnits:
    def test_list_foods(self):
        m = MagicMock(return_value={"items": []})
        run(foods, "list_foods", {}, m)
        m.assert_called_once_with("GET", "/api/foods", params={
            "search": None, "page": 1, "perPage": 50})

    def test_create_food(self):
        m = MagicMock(return_value={"id": "f1"})
        run(foods, "create_food", {"name": "bloem", "pluralName": "bloem"}, m)
        m.assert_called_once_with("POST", "/api/foods", body={"name": "bloem", "pluralName": "bloem"})

    def test_create_unit(self):
        m = MagicMock(return_value={"id": "u1"})
        run(units, "create_unit", {"name": "gram", "abbreviation": "g"}, m)
        m.assert_called_once_with("POST", "/api/units", body={"name": "gram", "abbreviation": "g"})
