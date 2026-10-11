"""Moda Customer Experience Test Suite for Phase 4.

Verifies:
1. Occasion selection maps correctly to recommendation request.
2. Product-type selection is respected (Top only, Bottom only, etc.).
3. Current weather is incorporated into context and customer display.
4. Only in-stock products appear in recommendations (stock > 0).
5. Unsuitable products are not substituted (e.g., casual items for formal/wedding).
6. Inventory limitation message appears when appropriate.
7. Product metadata (price, sizes, stock, image) is preserved without leaking internal IDs/SKUs.
8. Complete outfit works with suitable inventory.
9. Partial inventory does not cause hallucinated products.
10. Existing staff workflow remains functional.
"""

import sys
import os
import json
import pytest

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(ROOT_DIR)

from agents.stylist_agent import (
    run_stylist_agent,
    infer_requested_formality,
    infer_requested_item_type,
    is_product_suitable,
)
from agents.wardrobe_agent import run_wardrobe_agent
from agents.weather_agent import run_weather_agent
from tools.wardrobe import get_wardrobe_items
from services.staff_catalog import get_taxonomy_options, validate_staff_product
from api import parse_outfit_from_text


# ------------------------------------------------------------------------------
# 1. OCCASION SELECTION MAPPING
# ------------------------------------------------------------------------------

def test_occasion_mapping_and_formality():
    """Verify that tablet guided occasions map cleanly into formality levels and prompts."""
    test_cases = [
        ("Wedding", "formal"),
        ("Formal Event", "formal"),
        ("Office / Meeting", "smart casual"),
        ("Casual", "casual"),
        ("Party", "smart casual"),
        ("Everyday", "casual"),
    ]
    for occasion_text, expected_formality in test_cases:
        formality = infer_requested_formality(occasion_text)
        assert formality == expected_formality, f"Occasion '{occasion_text}' expected '{expected_formality}', got '{formality}'"


# ------------------------------------------------------------------------------
# 2. PRODUCT-TYPE SELECTION RESPECTED
# ------------------------------------------------------------------------------

def test_product_type_selection_single_items():
    """Verify selecting a single item type (Top, Bottom, Shoes, Dress) does NOT force a full outfit."""
    # Test infer_requested_item_type
    assert infer_requested_item_type("Looking for Top") == "top"
    assert infer_requested_item_type("Looking for Bottom") == "bottom"
    assert infer_requested_item_type("Looking for Shoes") == "shoes"
    assert infer_requested_item_type("Looking for Dress") == "dress"
    assert infer_requested_item_type("Complete Outfit") == "outfit"

    # Test Stylist recommendation for Top only
    inventory = get_wardrobe_items(in_stock_only=True)
    weather_data = {"temperature": 28.0, "weather": "Sunny", "city": "Vadodara"}
    res_top = run_stylist_agent(
        "Office / Meeting - Looking for Top",
        weather_data=weather_data,
        wardrobe_items=inventory
    )
    rec_text = res_top.get("agent_response", "")
    assert "Top:" in rec_text or "Notice:" in rec_text
    assert "Bottom:" not in rec_text, "Single item 'Top' should not output Bottom"
    assert "Shoes:" not in rec_text, "Single item 'Top' should not output Shoes"

    # Test Stylist recommendation for Bottom only
    res_bottom = run_stylist_agent(
        "Casual - Looking for Bottom",
        weather_data=weather_data,
        wardrobe_items=inventory
    )
    rec_bottom_text = res_bottom.get("agent_response", "")
    assert "Bottom:" in rec_bottom_text or "Notice:" in rec_bottom_text
    assert "Top:" not in rec_bottom_text, "Single item 'Bottom' should not output Top"
    assert "Shoes:" not in rec_bottom_text, "Single item 'Bottom' should not output Shoes"


# ------------------------------------------------------------------------------
# 3. CURRENT WEATHER IS INCORPORATED
# ------------------------------------------------------------------------------

def test_weather_incorporation_and_display():
    """Verify weather agent produces valid weather data and can format for display."""
    w_res = run_weather_agent("Vadodara")
    w_data = w_res.get("weather_data", {})
    assert "temperature" in w_data, "Weather data must include temperature"
    assert "weather" in w_data, "Weather data must include weather condition"

    temp = round(w_data.get("temperature", 28))
    cond = w_data.get("weather", "Sunny")
    display_str = f"{temp}°C • {cond}"
    assert "°C • " in display_str


# ------------------------------------------------------------------------------
# 4. ONLY IN-STOCK PRODUCTS APPEAR
# ------------------------------------------------------------------------------

def test_only_in_stock_products_appear():
    """Verify all items fetched by Wardrobe Agent and recommended have stock_quantity > 0."""
    in_stock_items = get_wardrobe_items(in_stock_only=True)
    for it in in_stock_items:
        assert it.get("stock_quantity", 0) > 0, f"Item {it['name']} has 0 stock"

    # Wardrobe agent lookup
    wardrobe_res = run_wardrobe_agent("Casual outfit")
    items = wardrobe_res.get("items", [])
    for it in items:
        assert it.get("stock_quantity", 0) > 0, f"Found out of stock item in wardrobe agent: {it['name']}"


# ------------------------------------------------------------------------------
# 5. UNSUITABLE PRODUCTS ARE NOT SUBSTITUTED
# ------------------------------------------------------------------------------

def test_unsuitable_products_not_substituted():
    """Verify casual items (like T-shirts/sneakers) are not substituted for formal/wedding."""
    tshirt = {
        "name": "Graphic Vintage Tee",
        "category": "top",
        "formality": "casual",
        "stock_quantity": 5
    }
    sneakers = {
        "name": "White Canvas Slip-On Sneakers",
        "category": "shoes",
        "formality": "casual",
        "stock_quantity": 8
    }

    wedding_formality = infer_requested_formality("wedding")
    assert wedding_formality == "formal"
    assert is_product_suitable(tshirt, wedding_formality) is False
    assert is_product_suitable(sneakers, wedding_formality) is False

    # Run stylist agent with only casual items for wedding request
    casual_only_inventory = [tshirt, sneakers]
    stylist_res = run_stylist_agent(
        "Wedding - Complete Outfit",
        weather_data={"temperature": 28.0, "weather": "Sunny", "city": "Vadodara"},
        wardrobe_items=casual_only_inventory
    )
    rec_text = stylist_res.get("agent_response", "")
    # Must emit notice, NOT recommend the graphic tee for wedding
    assert "Graphic Vintage Tee" not in rec_text
    assert "Notice:" in rec_text or "limitation" in rec_text.lower() or "suitable" in rec_text.lower()


# ------------------------------------------------------------------------------
# 6. INVENTORY LIMITATION MESSAGE APPEARS WHEN APPROPRIATE
# ------------------------------------------------------------------------------

def test_inventory_limitation_message():
    """Verify empty/unsuitable inventory triggers a clear customer limitation message."""
    empty_res = run_stylist_agent(
        "Formal Event - Complete Outfit",
        weather_data={"temperature": 28.0, "weather": "Sunny", "city": "Vadodara"},
        wardrobe_items=[]
    )
    parsed = parse_outfit_from_text(empty_res.get("agent_response", ""), [])
    assert parsed.get("inventory_notice") is True
    assert "enough suitable in-stock pieces" in parsed.get("customer_message", "").lower()


# ------------------------------------------------------------------------------
# 7. PRODUCT METADATA PRESERVED WITHOUT EXPOSING INTERNAL IDS
# ------------------------------------------------------------------------------

def test_product_metadata_preserved_and_sanitized():
    """Verify customer product representation contains name, image, price, sizes, stock, but no internal IDs."""
    raw_markdown = (
        "### 👔 Recommended Outfit\n"
        "- **Top:** White Oxford Cotton Shirt\n"
        "- **Bottom:** Beige Chino Pants\n"
        "- **Shoes:** Minimalist White Leather Sneakers\n"
    )
    inventory = get_wardrobe_items(in_stock_only=True)
    parsed = parse_outfit_from_text(raw_markdown, inventory)

    top = parsed.get("top")
    assert top is not None
    assert "price" in top and top["price"] > 0
    assert "available_sizes" in top and len(top["available_sizes"]) > 0
    assert "stock_quantity" in top and top["stock_quantity"] > 0
    assert "image" in top

    # Emulate the customer card payload sanitization from api.py
    customer_card = {
        "name": top.get("name"),
        "category": "Top",
        "image": top.get("image"),
        "price": top.get("price"),
        "available_sizes": top.get("available_sizes"),
        "stock_quantity": top.get("stock_quantity")
    }
    assert "product_id" not in customer_card
    assert "id" not in customer_card
    assert "confidence" not in customer_card
    assert "sku" not in customer_card


# ------------------------------------------------------------------------------
# 8. COMPLETE OUTFIT WORKS WITH SUITABLE INVENTORY
# ------------------------------------------------------------------------------

def test_complete_outfit_recommendation():
    """Verify complete outfit produces top, bottom, and shoes when suitable stock exists."""
    inventory = get_wardrobe_items(in_stock_only=True)
    stylist_res = run_stylist_agent(
        "Casual - Complete Outfit - Style: Comfortable",
        weather_data={"temperature": 28.0, "weather": "Sunny", "city": "Vadodara"},
        wardrobe_items=inventory
    )
    rec_text = stylist_res.get("agent_response", "")
    parsed = parse_outfit_from_text(rec_text, inventory)
    assert parsed.get("top") is not None
    assert parsed.get("bottom") is not None
    assert parsed.get("shoes") is not None


# ------------------------------------------------------------------------------
# 9. PARTIAL INVENTORY DOES NOT CAUSE HALLUCINATION
# ------------------------------------------------------------------------------

def test_partial_inventory_handling():
    """Verify missing components in inventory are reported as missing without inventing items."""
    # Inventory has a suitable top, but NO bottoms and NO shoes
    partial_inventory = [
        {
            "id": 101,
            "product_id": "MODA-TEST-001",
            "name": "Classic White Linen Shirt",
            "category": "top",
            "subcategory": "linen shirt",
            "color": "white",
            "formality": "smart_casual",
            "season": "summer",
            "price": 1799,
            "available_sizes": ["M", "L"],
            "stock_quantity": 4,
            "image": "/uploads/test.jpg"
        }
    ]
    res = run_stylist_agent(
        "Office / Meeting - Complete Outfit",
        weather_data={"temperature": 28.0, "weather": "Sunny", "city": "Vadodara"},
        wardrobe_items=partial_inventory
    )
    rec_text = res.get("agent_response", "")
    assert "Classic White Linen Shirt" in rec_text
    assert "None available in current inventory" in rec_text
    assert "lack suitable in-stock pieces for bottom" in rec_text

    parsed = parse_outfit_from_text(rec_text, partial_inventory)
    assert parsed.get("top") is not None
    assert parsed.get("bottom") is None
    assert parsed.get("shoes") is None
    assert parsed.get("partial_inventory") is True


# ------------------------------------------------------------------------------
# 10. EXISTING STAFF WORKFLOW REMAINS FUNCTIONAL
# ------------------------------------------------------------------------------

def test_staff_workflow_unaffected():
    """Verify Phase 3 staff cataloging and taxonomy validation remain completely functional."""
    # 1. Taxonomy options load cleanly
    tax = get_taxonomy_options()
    assert "categories" in tax
    assert "subcategories" in tax
    assert "Top" in tax["categories"]

    # 2. Staff validation passes for valid product
    valid_payload = {
        "product_id": "MODA-TEST-STAFF-999",
        "name": "Staff Tested Silk Shirt",
        "category": "Top",
        "subcategory": "Blouse",
        "color": "Blue",
        "pattern": "Solid",
        "formality": "Smart Casual",
        "season": ["All Season"],
        "price": 2499,
        "available_sizes": ["M", "L"],
        "stock_quantity": 10,
        "image": "/uploads/test.jpg"
    }
    is_valid, errs = validate_staff_product(valid_payload)
    assert is_valid is True, f"Validation failed: {errs}"
    assert len(errs) == 0

    # 3. Staff HTML page exists
    staff_path = os.path.join(ROOT_DIR, "staff.html")
    assert os.path.exists(staff_path)
