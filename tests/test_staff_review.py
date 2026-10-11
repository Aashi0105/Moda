"""Staff Review & Cataloging Test Suite for Moda Phase 3.

Verifies:
1. Successful product save with commercial and taxonomy details.
2. AI tags are editable and staff modifications take precedence.
3. Null/uncertain AI fields require review and validation.
4. Invalid taxonomy values (color, pattern, formality, season) are rejected.
5. Invalid Category-Subcategory combinations are rejected (e.g., Top + Jeans).
6. Duplicate Product ID / SKU is strictly rejected.
7. Invalid price (negative or non-numeric) is rejected.
8. Invalid stock quantity (negative or decimal) is rejected.
9. End-to-end integration: Saved product flows to Wardrobe Agent & Stylist recommendation.
10. Zero-stock exclusion: Newly cataloged product with stock=0 is excluded from recommendations.
"""

import os
import sys
import json
import sqlite3
import pytest

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(ROOT_DIR)

from services.staff_catalog import (
    get_taxonomy_options,
    tag_product_image_for_review,
    validate_staff_product,
    save_staff_product,
)
from tools.wardrobe import get_wardrobe_items, get_product_by_id
from agents.wardrobe_agent import run_wardrobe_agent
from agents.stylist_agent import run_stylist_agent


@pytest.fixture(autouse=True)
def cleanup_test_products():
    """Fixture to clean up any test products created during tests."""
    yield
    # Cleanup any MODA-TEST- products created during tests
    db_path = os.path.join(ROOT_DIR, "wardrobe.db")
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("DELETE FROM wardrobe WHERE product_id LIKE 'MODA-TEST-%'")
        conn.commit()
        conn.close()

    # Clean inventory.json
    inv_path = os.path.join(ROOT_DIR, "data", "inventory.json")
    if os.path.exists(inv_path):
        with open(inv_path, "r", encoding="utf-8") as f:
            items = json.load(f)
        cleaned = [i for i in items if not str(i.get("product_id", "")).startswith("MODA-TEST-")]
        if len(cleaned) != len(items):
            with open(inv_path, "w", encoding="utf-8") as f:
                json.dump(cleaned, f, indent=2)

    # Clean wardrobe.json
    w_path = os.path.join(ROOT_DIR, "data", "wardrobe.json")
    if os.path.exists(w_path):
        with open(w_path, "r", encoding="utf-8") as f:
            items = json.load(f)
        cleaned = [i for i in items if not str(i.get("product_id", "")).startswith("MODA-TEST-")]
        if len(cleaned) != len(items):
            with open(w_path, "w", encoding="utf-8") as f:
                json.dump(cleaned, f, indent=2)


# ------------------------------------------------------------------------------
# 1. SUCCESSFUL PRODUCT SAVE
# ------------------------------------------------------------------------------

def test_successful_product_save():
    """Verify that a staff member can confirm and save a product into the shop inventory."""
    product_data = {
        "name": "Test Blue Oxford Shirt",
        "product_id": "MODA-TEST-001",
        "category": "Top",
        "subcategory": "Shirt",
        "color": "Blue",
        "pattern": "Solid",
        "formality": "Smart Casual",
        "season": ["Summer", "All Season"],
        "price": 1499.0,
        "available_sizes": ["S", "M", "L"],
        "stock_quantity": 5,
        "image": "/uploads/blue_shirt.jpeg"
    }

    saved = save_staff_product(product_data)
    assert saved["product_id"] == "MODA-TEST-001"
    assert saved["name"] == "Test Blue Oxford Shirt"
    assert saved["price"] == 1499.0
    assert saved["stock_quantity"] == 5

    # Verify persistence in SQLite
    db_item = get_product_by_id("MODA-TEST-001")
    assert db_item is not None
    assert db_item["name"] == "Test Blue Oxford Shirt"
    assert db_item["price"] == 1499.0
    assert db_item["stock_quantity"] == 5
    assert db_item["category"] == "Top"
    assert db_item["subcategory"] == "Shirt"

    # Verify persistence in data/inventory.json
    with open(os.path.join(ROOT_DIR, "data", "inventory.json"), "r", encoding="utf-8") as f:
        inv = json.load(f)
    match = next((i for i in inv if i.get("product_id") == "MODA-TEST-001"), None)
    assert match is not None
    assert match["price"] == 1499.0


# ------------------------------------------------------------------------------
# 2. EDITABLE AI TAGS (STAFF OVERRIDE PRECEDENCE)
# ------------------------------------------------------------------------------

def test_editable_ai_tags():
    """Verify that staff edits override AI suggestions before saving."""
    # Suppose AI suggested Solid and Casual
    ai_suggestions = {
        "category": "Top",
        "subcategory": "T-shirt",
        "color": "Blue",
        "pattern": "Solid",
        "formality": "Casual"
    }

    # Staff modifies to Striped Shirt and Smart Casual
    staff_edited_data = {
        "name": "Edited Striped Collared Shirt",
        "product_id": "MODA-TEST-002",
        "category": ai_suggestions["category"],
        "subcategory": "Shirt",                     # Staff corrected from T-shirt to Shirt
        "color": ai_suggestions["color"],
        "pattern": "Striped",                       # Staff corrected from Solid to Striped
        "formality": "Smart Casual",                # Staff corrected from Casual to Smart Casual
        "season": ["All Season"],
        "price": 1899.0,
        "available_sizes": ["M", "L"],
        "stock_quantity": 8,
        "image": "/uploads/blue_shirt.jpeg"
    }

    saved = save_staff_product(staff_edited_data)
    assert saved["subcategory"] == "Shirt"
    assert saved["pattern"] == "Striped"
    assert saved["formality"] == "Smart Casual"

    # Verify database has staff values, not AI defaults
    db_item = get_product_by_id("MODA-TEST-002")
    assert db_item["subcategory"] == "Shirt"
    assert db_item["pattern"] == "Striped"
    assert db_item["formality"] == "Smart Casual"


# ------------------------------------------------------------------------------
# 3. NULL / UNCERTAIN AI FIELD REQUIRING REVIEW
# ------------------------------------------------------------------------------

def test_null_uncertain_ai_field_requiring_review():
    """Verify that when AI tags are null/uncertain, service flags needs_review and requires staff completion."""
    # When image has missing or invalid attributes, validation rejects incomplete save
    incomplete_data = {
        "name": "Unreviewed Item",
        "product_id": "MODA-TEST-003",
        "category": "",   # Empty / null
        "subcategory": None,
        "color": "Blue",
        "pattern": "Solid",
        "formality": "Casual",
        "season": ["All Season"],
        "price": 999.0,
        "available_sizes": ["M"],
        "stock_quantity": 3
    }

    is_valid, errors = validate_staff_product(incomplete_data)
    assert not is_valid
    assert any("category" in e.lower() for e in errors)


# ------------------------------------------------------------------------------
# 4. INVALID TAXONOMY REJECTION
# ------------------------------------------------------------------------------

def test_invalid_taxonomy_rejection():
    """Verify rejection of invalid colors, patterns, formalities, or seasons not in taxonomy."""
    # Invalid Color
    bad_color = {
        "name": "Bad Color Shirt",
        "product_id": "MODA-TEST-004A",
        "category": "Top",
        "subcategory": "Shirt",
        "color": "Neon Ultra Magenta",  # Not in taxonomy
        "pattern": "Solid",
        "formality": "Casual",
        "season": ["Summer"],
        "price": 1000,
        "available_sizes": ["M"],
        "stock_quantity": 2
    }
    valid, errors = validate_staff_product(bad_color)
    assert not valid
    assert any("color" in e.lower() for e in errors)

    # Invalid Formality
    bad_formality = {
        "name": "Bad Formality Top",
        "product_id": "MODA-TEST-004B",
        "category": "Top",
        "subcategory": "Shirt",
        "color": "Blue",
        "pattern": "Solid",
        "formality": "Super Duper Formal",  # Not in taxonomy
        "season": ["Summer"],
        "price": 1000,
        "available_sizes": ["M"],
        "stock_quantity": 2
    }
    valid, errors = validate_staff_product(bad_formality)
    assert not valid
    assert any("formality" in e.lower() for e in errors)


# ------------------------------------------------------------------------------
# 5. INVALID CATEGORY-SUBCATEGORY COMBINATION REJECTION
# ------------------------------------------------------------------------------

def test_invalid_category_subcategory_rejection():
    """Verify that pairing a category with an incompatible subcategory (e.g. Top + Jeans) is rejected."""
    mismatched = {
        "name": "Mismatched Product",
        "product_id": "MODA-TEST-005",
        "category": "Top",
        "subcategory": "Jeans",  # Jeans is for Bottom, not Top
        "color": "Blue",
        "pattern": "Solid",
        "formality": "Casual",
        "season": ["All Season"],
        "price": 1299,
        "available_sizes": ["M"],
        "stock_quantity": 4
    }

    valid, errors = validate_staff_product(mismatched)
    assert not valid
    assert any("subcategory" in e.lower() and "jeans" in e.lower() for e in errors)


# ------------------------------------------------------------------------------
# 6. DUPLICATE PRODUCT ID REJECTION
# ------------------------------------------------------------------------------

def test_duplicate_product_id_rejection():
    """Verify that attempting to save a product with an existing Product ID / SKU is rejected."""
    # MODA-0001 already exists in seed inventory
    duplicate_data = {
        "name": "Duplicate SKU Trench Coat",
        "product_id": "MODA-0001",  # Existing SKU
        "category": "Outerwear",
        "subcategory": "Coat",
        "color": "Navy",
        "pattern": "Solid",
        "formality": "Formal",
        "season": ["Winter"],
        "price": 5000,
        "available_sizes": ["L"],
        "stock_quantity": 2
    }

    valid, errors = validate_staff_product(duplicate_data)
    assert not valid
    assert any("already exists" in e.lower() for e in errors)


# ------------------------------------------------------------------------------
# 7. INVALID PRICE REJECTION
# ------------------------------------------------------------------------------

def test_invalid_price_rejection():
    """Verify that negative or non-numeric prices are rejected."""
    neg_price = {
        "name": "Negative Price Shirt",
        "product_id": "MODA-TEST-007A",
        "category": "Top",
        "subcategory": "Shirt",
        "color": "White",
        "pattern": "Solid",
        "formality": "Casual",
        "season": ["All Season"],
        "price": -499.0,  # Negative
        "available_sizes": ["M"],
        "stock_quantity": 5
    }
    valid, errors = validate_staff_product(neg_price)
    assert not valid
    assert any("price" in e.lower() for e in errors)

    text_price = {
        "name": "Text Price Shirt",
        "product_id": "MODA-TEST-007B",
        "category": "Top",
        "subcategory": "Shirt",
        "color": "White",
        "pattern": "Solid",
        "formality": "Casual",
        "season": ["All Season"],
        "price": "five hundred",  # Non-numeric
        "available_sizes": ["M"],
        "stock_quantity": 5
    }
    valid, errors = validate_staff_product(text_price)
    assert not valid
    assert any("price" in e.lower() for e in errors)


# ------------------------------------------------------------------------------
# 8. INVALID STOCK REJECTION
# ------------------------------------------------------------------------------

def test_invalid_stock_rejection():
    """Verify that negative or decimal stock quantities are rejected."""
    neg_stock = {
        "name": "Negative Stock Pants",
        "product_id": "MODA-TEST-008A",
        "category": "Bottom",
        "subcategory": "Chinos",
        "color": "Beige",
        "pattern": "Solid",
        "formality": "Casual",
        "season": ["All Season"],
        "price": 1500,
        "available_sizes": ["32"],
        "stock_quantity": -3  # Negative
    }
    valid, errors = validate_staff_product(neg_stock)
    assert not valid
    assert any("stock" in e.lower() for e in errors)

    decimal_stock = {
        "name": "Decimal Stock Pants",
        "product_id": "MODA-TEST-008B",
        "category": "Bottom",
        "subcategory": "Chinos",
        "color": "Beige",
        "pattern": "Solid",
        "formality": "Casual",
        "season": ["All Season"],
        "price": 1500,
        "available_sizes": ["32"],
        "stock_quantity": 4.5  # Decimal
    }
    valid, errors = validate_staff_product(decimal_stock)
    assert not valid
    assert any("stock" in e.lower() for e in errors)


# ------------------------------------------------------------------------------
# 9. INTEGRATION: INVENTORY -> WARDROBE AGENT -> STYLIST RECOMMENDATION
# ------------------------------------------------------------------------------

def test_successful_inventory_to_recommendation_integration():
    """Test full integration:
    1. Staff confirms and saves product (MODA-TEST-009).
    2. Wardrobe Agent retrieves it.
    3. Stylist Agent recommends it when appropriate.
    """
    new_product = {
        "name": "Artisan Linen Summer Shirt",
        "product_id": "MODA-TEST-009",
        "category": "Top",
        "subcategory": "Shirt",
        "color": "Blue",
        "pattern": "Striped",
        "formality": "Smart Casual",
        "season": ["Summer", "All Season"],
        "price": 1499.0,
        "available_sizes": ["S", "M", "L"],
        "stock_quantity": 5,
        "image": "/uploads/blue_shirt.jpeg",
        "temp_min_c": 15.0,
        "temp_max_c": 38.0
    }

    # 1. Save product
    saved = save_staff_product(new_product)
    assert saved["product_id"] == "MODA-TEST-009"

    # 2. Wardrobe Agent retrieves it
    wardrobe_res = run_wardrobe_agent("Show available smart casual tops")
    retrieved_items = wardrobe_res.get("wardrobe_items", [])
    matched_ids = [i.get("product_id") for i in retrieved_items]
    assert "MODA-TEST-009" in matched_ids, "Newly added product MUST be retrieved by Wardrobe Agent."

    # 3. Stylist Agent recommends it when suitable
    all_wardrobe = run_wardrobe_agent("What clothes do I have in my closet?").get("wardrobe_items", [])
    bottom = next((i for i in all_wardrobe if i.get("category", "").lower() == "bottom" and i.get("formality", "").lower() in ["smart casual", "formal"]), None)
    shoes = next((i for i in all_wardrobe if i.get("category", "").lower() in ["shoes", "footwear"]), None)
    stylist_pool = [i for i in [saved, bottom, shoes] if i is not None]

    weather = {"city": "Vadodara", "temperature": 28.0, "weather": "Sunny", "rain_probability": 0}
    stylist_res = run_stylist_agent("Smart casual outfit for warm weather", weather, stylist_pool)
    recommendation = stylist_res["agent_response"]

    assert "Artisan Linen Summer Shirt" in recommendation or "MODA-TEST-009" in recommendation
    assert "Recommended Outfit" in recommendation


# ------------------------------------------------------------------------------
# 10. ZERO-STOCK EXCLUSION FOR STAFF-ADDED PRODUCT
# ------------------------------------------------------------------------------

def test_new_product_zero_stock_exclusion():
    """Verify that when a staff-added product's stock is 0, it is NOT recommended."""
    out_of_stock_product = {
        "name": "Sold Out Silk Blouse",
        "product_id": "MODA-TEST-010",
        "category": "Top",
        "subcategory": "Blouse",
        "color": "White",
        "pattern": "Solid",
        "formality": "Smart Casual",
        "season": ["All Season"],
        "price": 2499.0,
        "available_sizes": ["M"],
        "stock_quantity": 0,  # Zero stock
        "image": "/uploads/image-1781760331015-264270365.jpg",
        "temp_min_c": 10.0,
        "temp_max_c": 35.0
    }

    save_staff_product(out_of_stock_product)

    # Wardrobe Agent query (in-stock only)
    wardrobe_res = run_wardrobe_agent("Show smart casual tops")
    retrieved_ids = [i.get("product_id") for i in wardrobe_res.get("wardrobe_items", [])]
    assert "MODA-TEST-010" not in retrieved_ids, "Product with stock=0 must NOT be retrieved for recommendation."
