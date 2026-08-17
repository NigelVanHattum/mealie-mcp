"""Tests for the tools registry — ALL_TOOLS completeness and dispatch routing."""

import pytest
from collections import Counter

import tools
from tools import app, recipes, images, organizers, foods, units


# ---------------------------------------------------------------------------
# Registry integrity
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_total_tool_count(self):
        assert len(tools.ALL_TOOLS) == 21

    def test_no_duplicate_names(self):
        names = [t.name for t in tools.ALL_TOOLS]
        dupes = [n for n, c in Counter(names).items() if c > 1]
        assert dupes == [], f"Duplicate tool names: {dupes}"

    def test_all_tools_have_name_and_schema(self):
        for t in tools.ALL_TOOLS:
            assert t.name, "Tool missing name"
            assert t.input_schema, f"Tool {t.name} missing input_schema"
            assert t.input_schema.get("type") == "object"

    def test_all_tools_have_description(self):
        for t in tools.ALL_TOOLS:
            assert t.description and len(t.description) > 10, \
                f"Tool {t.name} has a weak description"

    def test_tool_names_sets_match_tools(self):
        for mod in [app, recipes, images, organizers, foods, units]:
            declared = {t.name for t in mod.TOOLS}
            assert mod.TOOL_NAMES == declared, f"{mod.__name__}: TOOL_NAMES mismatch"

    def test_dispatch_raises_for_unknown(self):
        with pytest.raises(ValueError, match="Unknown tool"):
            tools.dispatch("nonexistent_tool", {})

    @pytest.mark.parametrize("tool", tools.ALL_TOOLS)
    def test_required_fields_are_in_properties(self, tool):
        schema = tool.input_schema
        required = schema.get("required", [])
        props = schema.get("properties", {})
        missing = [f for f in required if f not in props]
        assert not missing, f"{tool.name}: required not in properties: {missing}"

    @pytest.mark.parametrize("tool", tools.ALL_TOOLS)
    def test_tools_have_annotations(self, tool):
        assert tool.annotations is not None, f"{tool.name} missing annotations"

    def test_expected_tool_names_present(self):
        names = {t.name for t in tools.ALL_TOOLS}
        expected = {
            "get_server_info", "get_current_user",
            "list_recipes", "get_recipe", "create_recipe", "update_recipe",
            "overwrite_recipe", "delete_recipe",
            "set_recipe_image_from_url", "upload_recipe_image", "delete_recipe_image",
            "list_categories", "create_category", "list_tags", "create_tag",
            "list_tools", "create_tool",
            "list_foods", "create_food", "list_units", "create_unit",
        }
        assert names == expected


# ---------------------------------------------------------------------------
# Module tool counts
# ---------------------------------------------------------------------------

class TestModuleCounts:
    def test_app(self):        assert len(app.TOOLS) == 2
    def test_recipes(self):    assert len(recipes.TOOLS) == 6
    def test_images(self):     assert len(images.TOOLS) == 3
    def test_organizers(self): assert len(organizers.TOOLS) == 6
    def test_foods(self):      assert len(foods.TOOLS) == 2
    def test_units(self):      assert len(units.TOOLS) == 2


# ---------------------------------------------------------------------------
# Annotation correctness for destructive / read-only tools
# ---------------------------------------------------------------------------

class TestAnnotations:
    def _byname(self, name):
        return next(t for t in tools.ALL_TOOLS if t.name == name)

    def test_read_tools_are_readonly(self):
        for n in ["list_recipes", "get_recipe", "get_server_info", "get_current_user"]:
            assert self._byname(n).annotations.read_only_hint is True

    def test_delete_is_destructive(self):
        for n in ["delete_recipe", "delete_recipe_image"]:
            ann = self._byname(n).annotations
            assert ann.destructive_hint is True, n
            assert ann.read_only_hint is False, n

    def test_image_writes_are_not_destructive(self):
        for n in ["set_recipe_image_from_url", "upload_recipe_image"]:
            ann = self._byname(n).annotations
            assert ann.destructive_hint is False, n
            assert ann.idempotent_hint is True, n

    def test_overwrite_is_destructive_update_is_not(self):
        assert self._byname("overwrite_recipe").annotations.destructive_hint is True
        assert self._byname("update_recipe").annotations.destructive_hint is False
