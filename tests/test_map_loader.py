"""Tests for tui/data/map_loader.py."""
from __future__ import annotations

import pytest
from tui.data.map_loader import load_world_map


class TestMapLoader:
    """Tests for load_world_map()."""

    def test_returns_list_of_strings(self):
        result = load_world_map()
        assert isinstance(result, list)
        for line in result:
            assert isinstance(line, str)

    def test_has_expected_row_count(self):
        result = load_world_map()
        assert len(result) == 19

    def test_all_rows_same_length(self):
        result = load_world_map()
        lengths = {len(line) for line in result}
        assert len(lengths) == 1  # All rows same width

    def test_rows_are_non_empty(self):
        result = load_world_map()
        for line in result:
            assert len(line) > 0

    def test_cache_returns_same_object(self):
        """lru_cache returns the same list object on repeated calls."""
        r1 = load_world_map()
        r2 = load_world_map()
        assert r1 is r2

    def test_first_row_starts_with_braille(self):
        """First row should start with Braille blank character."""
        result = load_world_map()
        assert result[0][0] == "\u2800"  # Braille blank ⠀

    def test_contains_land_characters(self):
        """Map should contain non-blank Braille characters (land)."""
        result = load_world_map()
        all_chars = "".join(result)
        # Braille patterns (non-blank) should be present
        assert any(c != "\u2800" for c in all_chars)
