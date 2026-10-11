"""Unit tests for the Moda Clothing Photo-Tagging module (tools/item_tagger.py).

Tests taxonomy validation, category/subcategory hierarchy enforcement,
rejection logging, confidence clamping, and image file integrity checks.
"""

import os
import json
import pytest
from pathlib import Path
from tools.item_tagger import (
    ALLOWED_CATEGORIES,
    ALLOWED_SUBCATEGORIES,
    ALLOWED_COLORS,
    ALLOWED_PATTERNS,
    ALLOWED_FORMALITIES,
    ALLOWED_SEASONS,
    ALLOWED_IMAGE_QUALITIES,
    validate_image_file,
    validate_field,
    validate_tags,
    tag_clothing_item,
)


class TestTaxonomyConstants:
    """Ensure all required taxonomy definitions are strictly defined."""

    def test_categories_presence(self):
        expected = {"Top", "Bottom", "Outerwear", "Dress", "Shoes", "Accessory"}
        assert ALLOWED_CATEGORIES == expected

    def test_subcategories_mapping(self):
        for cat in ALLOWED_CATEGORIES:
            assert cat in ALLOWED_SUBCATEGORIES
            assert len(ALLOWED_SUBCATEGORIES[cat]) > 0
            assert "Other" in ALLOWED_SUBCATEGORIES[cat]

    def test_colors_presence(self):
        assert "Blue" in ALLOWED_COLORS
        assert "Multicolor" in ALLOWED_COLORS
        assert "Sky Blue" not in ALLOWED_COLORS
        assert len(ALLOWED_COLORS) == 17

    def test_patterns_presence(self):
        assert "Solid" in ALLOWED_PATTERNS
        assert "Striped" in ALLOWED_PATTERNS
        assert "Graphic/Printed" in ALLOWED_PATTERNS

    def test_formalities(self):
        assert ALLOWED_FORMALITIES == {"Casual", "Smart Casual", "Formal"}

    def test_seasons(self):
        assert ALLOWED_SEASONS == {"Summer", "Winter", "Monsoon/Rainy", "All Season"}


class TestFieldValidation:
    """Test validation of individual fields."""

    def test_valid_field(self):
        rejected = []
        payload = {"value": "Top", "confidence": 0.95}
        result = validate_field("test.jpg", "category", payload, ALLOWED_CATEGORIES, rejected)
        assert result["value"] == "Top"
        assert result["confidence"] == 0.95
        assert len(rejected) == 0

    def test_null_value_accepted(self):
        rejected = []
        payload = {"value": None, "confidence": 0.0}
        result = validate_field("test.jpg", "color", payload, ALLOWED_COLORS, rejected)
        assert result["value"] is None
        assert result["confidence"] == 0.0
        assert len(rejected) == 0

    def test_invalid_taxonomy_value_rejected(self):
        rejected = []
        payload = {"value": "Sky Blue", "confidence": 0.9}
        result = validate_field("test.jpg", "color", payload, ALLOWED_COLORS, rejected)
        assert result["value"] is None
        assert result["confidence"] == 0.0
        assert len(rejected) == 1
        assert rejected[0]["field_name"] == "color"
        assert rejected[0]["returned_value"] == "Sky Blue"
        assert "Sky Blue" in rejected[0]["reason"]

    def test_out_of_bounds_confidence_reset(self):
        rejected = []
        payload = {"value": "Blue", "confidence": 1.5}
        result = validate_field("test.jpg", "color", payload, ALLOWED_COLORS, rejected)
        assert result["value"] == "Blue"
        assert result["confidence"] == 0.0
        assert len(rejected) == 1
        assert "Confidence must be between 0.0 and 1.0" in rejected[0]["reason"]

    def test_non_dict_payload_rejected(self):
        rejected = []
        result = validate_field("test.jpg", "color", "Blue", ALLOWED_COLORS, rejected)
        assert result["value"] is None
        assert result["confidence"] == 0.0
        assert len(rejected) == 1


class TestHierarchyValidation:
    """Test category and subcategory compatibility."""

    def test_compatible_subcategory(self):
        raw = json.dumps({
            "image_quality": "Good",
            "category": {"value": "Top", "confidence": 0.99},
            "subcategory": {"value": "Shirt", "confidence": 0.95},
            "color": {"value": "Blue", "confidence": 0.98},
            "pattern": {"value": "Solid", "confidence": 0.9},
            "formality": {"value": "Smart Casual", "confidence": 0.85},
            "season": {"value": ["Summer"], "confidence": 0.8}
        })
        val, _, rej, status, summary = validate_tags(raw, "shirt.jpg")
        assert status == "SUCCESS"
        assert val["category"]["value"] == "Top"
        assert val["subcategory"]["value"] == "Shirt"
        assert len(rej) == 0
        assert summary["fields_accepted"] == 6

    def test_incompatible_subcategory_rejected(self):
        """Top with Jeans subcategory must be rejected."""
        raw = json.dumps({
            "image_quality": "Good",
            "category": {"value": "Top", "confidence": 0.99},
            "subcategory": {"value": "Jeans", "confidence": 0.95},
            "color": {"value": "Blue", "confidence": 0.98},
            "pattern": {"value": "Solid", "confidence": 0.9},
            "formality": {"value": "Casual", "confidence": 0.85},
            "season": {"value": ["Summer"], "confidence": 0.8}
        })
        val, _, rej, status, summary = validate_tags(raw, "conflict.jpg")
        assert status == "PARTIAL"
        assert val["category"]["value"] == "Top"
        assert val["subcategory"]["value"] is None
        assert any(r["field_name"] == "subcategory" for r in rej)
        assert summary["fields_rejected"] == 1

    def test_null_category_forces_null_subcategory(self):
        raw = json.dumps({
            "image_quality": "Good",
            "category": {"value": None, "confidence": 0.0},
            "subcategory": {"value": "Shirt", "confidence": 0.95},
            "color": {"value": "Blue", "confidence": 0.98},
            "pattern": {"value": "Solid", "confidence": 0.9},
            "formality": {"value": "Casual", "confidence": 0.85},
            "season": {"value": ["Summer"], "confidence": 0.8}
        })
        val, _, rej, status, summary = validate_tags(raw, "null_cat.jpg")
        assert val["subcategory"]["value"] is None
        assert any("Subcategory was provided but Category is null" in r["reason"] for r in rej)


class TestImageValidation:
    """Test image file validation."""

    def test_non_existent_file(self):
        is_valid, err, b, mime = validate_image_file("non_existent_file.jpg")
        assert not is_valid
        assert "not found" in err

    def test_unsupported_format(self, tmp_path):
        bad_file = tmp_path / "document.pdf"
        bad_file.write_text("dummy")
        is_valid, err, b, mime = validate_image_file(str(bad_file))
        assert not is_valid
        assert "Unsupported image extension" in err

    def test_valid_image(self):
        valid_path = "test_images/blue_shirt.jpeg"
        if os.path.exists(valid_path):
            is_valid, err, b, mime = validate_image_file(valid_path)
            assert is_valid
            assert err is None
            assert len(b) > 0
            assert mime == "image/jpeg"
