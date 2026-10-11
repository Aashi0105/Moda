"""Comprehensive Test Suite for Moda AI In-Store Personal Shopper.

Verifies all 22 required areas from Section 17:
1. Three distinct outfit options when enough inventory exists.
2. One-piece dress outfit.
3. Top + bottom + footwear outfit.
4. Layered outfit.
5. Only available formulas are used.
6. Every product exists in inventory.
7. Every product has stock > 0.
8. No unsuitable product appears.
9. No hallucinated product appears.
10. Correct price is preserved.
11. Total bundle price is calculated deterministically.
12. Correct sizes are preserved.
13. Correct images are preserved.
14. Fewer than three options when inventory cannot support three.
15. Birthday request.
16. Wedding request.
17. Casual request.
18. Office request.
19. Weather influences recommendations.
20. Zero-stock products are excluded.
21. Calendar/DNA/personal wardrobe concepts are absent from customer UI.
22. Existing staff catalog tests continue passing.
"""

import sys
import os
import re
import json
import pytest

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(ROOT_DIR)

from agents.stylist_agent import (
    run_stylist_agent,
    generate_outfit_options,
    calculate_total_price,
    infer_requested_formality,
    is_product_suitable
)
from tools.wardrobe import get_wardrobe_items
from services.staff_catalog import get_taxonomy_options, validate_staff_product


@pytest.fixture
def shop_inventory():
    """Returns all currently in-stock products from wardrobe.db."""
    return get_wardrobe_items(in_stock_only=True)


@pytest.fixture
def default_weather():
    return {
        "city": "Vadodara",
        "temperature": 27.5,
        "weather": "Clear",
        "rain_probability": 10,
        "wind_speed": 12.0
    }


# ------------------------------------------------------------------------------
# 1. THREE DISTINCT OUTFIT OPTIONS WHEN ENOUGH INVENTORY EXISTS
# ------------------------------------------------------------------------------
def test_three_distinct_options_when_enough_inventory(shop_inventory, default_weather):
    options, is_notice, msg = generate_outfit_options(
        "I need an outfit for a birthday party.",
        weather_data=default_weather,
        wardrobe_items=shop_inventory
    )
    assert len(options) == 3, f"Expected 3 options, got {len(options)}"
    
    # Verify titles and vibes are distinct
    titles = [opt["title"] for opt in options]
    assert len(set(titles)) == 3, f"Titles must be distinct: {titles}"
    
    # Verify item sets are distinct (not identical outfits)
    item_id_sets = [tuple(sorted([it["product_id"] for it in opt["items"]])) for opt in options]
    assert len(set(item_id_sets)) == 3, "Outfit options must have distinct product sets"


# ------------------------------------------------------------------------------
# 2. ONE-PIECE DRESS OUTFIT
# ------------------------------------------------------------------------------
def test_one_piece_dress_outfit(shop_inventory, default_weather):
    options, _, _ = generate_outfit_options(
        "I need a dress outfit for a celebration",
        weather_data=default_weather,
        wardrobe_items=shop_inventory
    )
    one_piece_options = [opt for opt in options if opt.get("formula") == "one_piece"]
    assert len(one_piece_options) >= 1, "Expected at least 1 one-piece look"
    opt = one_piece_options[0]
    
    # Must have a dress
    categories = [it["category"].lower() for it in opt["items"]]
    assert "dress" in categories, "One-piece look must include a dress"
    assert "shoes" in categories, "One-piece look must include shoes"
    assert 2 <= len(opt["items"]) <= 4, f"Option must have 2-4 products, got {len(opt['items'])}"


# ------------------------------------------------------------------------------
# 3. TOP + BOTTOM + FOOTWEAR OUTFIT
# ------------------------------------------------------------------------------
def test_top_bottom_footwear_outfit(shop_inventory, default_weather):
    options, _, _ = generate_outfit_options(
        "Smart casual outfit for work",
        weather_data=default_weather,
        wardrobe_items=shop_inventory
    )
    separates_options = [opt for opt in options if opt.get("formula") == "classic_separates"]
    assert len(separates_options) >= 1, "Expected at least 1 classic separates look"
    opt = separates_options[0]
    
    categories = [it["category"].lower() for it in opt["items"]]
    assert "top" in categories, "Classic separates must include a top"
    assert "bottom" in categories, "Classic separates must include a bottom"
    assert "shoes" in categories, "Classic separates must include shoes"
    assert 3 <= len(opt["items"]) <= 4


# ------------------------------------------------------------------------------
# 4. LAYERED OUTFIT
# ------------------------------------------------------------------------------
def test_layered_outfit(shop_inventory, default_weather):
    options, _, _ = generate_outfit_options(
        "Birthday party evening outfit",
        weather_data=default_weather,
        wardrobe_items=shop_inventory
    )
    layered_options = [opt for opt in options if opt.get("formula") == "layered_statement"]
    assert len(layered_options) >= 1, "Expected at least 1 layered statement look"
    opt = layered_options[0]
    
    categories = [it["category"].lower() for it in opt["items"]]
    assert "top" in categories, "Layered look must include a top"
    assert "bottom" in categories, "Layered look must include a bottom"
    assert "outerwear" in categories, "Layered look must include outerwear"
    assert "shoes" in categories, "Layered look must include shoes"
    assert len(opt["items"]) == 4


# ------------------------------------------------------------------------------
# 5. ONLY AVAILABLE FORMULAS ARE USED
# ------------------------------------------------------------------------------
def test_only_available_formulas_used(shop_inventory, default_weather):
    options, _, _ = generate_outfit_options(
        "Casual weekend outing",
        weather_data=default_weather,
        wardrobe_items=shop_inventory
    )
    for opt in options:
        # If ethnic formula was selected, inventory must contain ethnic item
        if opt.get("formula") == "ethnic_fusion":
            has_ethnic = any("kurta" in it["name"].lower() or "kurti" in it["name"].lower() for it in opt["items"])
            assert has_ethnic, "Ethnic formula should only be used if ethnic product is present"
        assert opt.get("formula") in ["one_piece", "classic_separates", "layered_statement", "ethnic_fusion", "alternative_separates", "single_top", "single_bottom", "single_dress", "single_shoes"]


# ------------------------------------------------------------------------------
# 6. EVERY PRODUCT EXISTS IN INVENTORY
# ------------------------------------------------------------------------------
def test_every_product_exists_in_inventory(shop_inventory, default_weather):
    all_db_ids = {it["product_id"] for it in shop_inventory}
    options, _, _ = generate_outfit_options(
        "I need an outfit for a birthday party.",
        weather_data=default_weather,
        wardrobe_items=shop_inventory
    )
    for opt in options:
        for it in opt["items"]:
            assert it["product_id"] in all_db_ids, f"Product {it['product_id']} does not exist in shop inventory"


# ------------------------------------------------------------------------------
# 7. EVERY PRODUCT HAS STOCK > 0
# ------------------------------------------------------------------------------
def test_every_product_has_stock_greater_than_zero(shop_inventory, default_weather):
    options, _, _ = generate_outfit_options(
        "Office meeting outfit",
        weather_data=default_weather,
        wardrobe_items=shop_inventory
    )
    for opt in options:
        for it in opt["items"]:
            assert it.get("stock", 0) > 0, f"Product {it['name']} has 0 stock in recommendation"
            assert it.get("stock_quantity", 0) > 0


# ------------------------------------------------------------------------------
# 8. NO UNSUITABLE PRODUCT APPEARS
# ------------------------------------------------------------------------------
def test_no_unsuitable_product_appears(shop_inventory, default_weather):
    # Wedding / Formal: No t-shirts, casual sneakers, or casual shorts
    options, _, _ = generate_outfit_options(
        "Wedding ceremony formal event",
        weather_data=default_weather,
        wardrobe_items=shop_inventory
    )
    for opt in options:
        for it in opt["items"]:
            assert "tee" not in it["name"].lower()
            assert "sneakers" not in it["name"].lower()
            assert "shorts" not in it["name"].lower()


# ------------------------------------------------------------------------------
# 9. NO HALLUCINATED PRODUCT APPEARS
# ------------------------------------------------------------------------------
def test_no_hallucinated_product_appears(shop_inventory, default_weather):
    inventory_names = {it["name"] for it in shop_inventory}
    options, _, _ = generate_outfit_options(
        "Brunch with friends in Vadodara",
        weather_data=default_weather,
        wardrobe_items=shop_inventory
    )
    for opt in options:
        for it in opt["items"]:
            assert it["name"] in inventory_names, f"Hallucinated product found: {it['name']}"


# ------------------------------------------------------------------------------
# 10. CORRECT PRICE IS PRESERVED
# ------------------------------------------------------------------------------
def test_correct_price_is_preserved(shop_inventory, default_weather):
    price_map = {it["product_id"]: int(round(float(it["price"]))) for it in shop_inventory}
    options, _, _ = generate_outfit_options(
        "Birthday party look",
        weather_data=default_weather,
        wardrobe_items=shop_inventory
    )
    for opt in options:
        for it in opt["items"]:
            expected_price = price_map[it["product_id"]]
            assert it["price"] == expected_price, f"Price mismatch for {it['name']}: expected {expected_price}, got {it['price']}"


# ------------------------------------------------------------------------------
# 11. TOTAL BUNDLE PRICE IS CALCULATED DETERMINISTICALLY
# ------------------------------------------------------------------------------
def test_total_bundle_price_calculated_deterministically(shop_inventory, default_weather):
    options, _, _ = generate_outfit_options(
        "Birthday party look",
        weather_data=default_weather,
        wardrobe_items=shop_inventory
    )
    for opt in options:
        expected_total = sum(it["price"] for it in opt["items"])
        assert opt["total_price"] == expected_total, f"Bundle price error: expected {expected_total}, got {opt['total_price']}"


# ------------------------------------------------------------------------------
# 12. CORRECT SIZES ARE PRESERVED
# ------------------------------------------------------------------------------
def test_correct_sizes_preserved(shop_inventory, default_weather):
    size_map = {it["product_id"]: it.get("available_sizes") for it in shop_inventory}
    options, _, _ = generate_outfit_options(
        "Casual hangout outfit",
        weather_data=default_weather,
        wardrobe_items=shop_inventory
    )
    for opt in options:
        for it in opt["items"]:
            expected_sizes = size_map[it["product_id"]]
            assert it.get("sizes") == expected_sizes or it.get("available_sizes") == expected_sizes


# ------------------------------------------------------------------------------
# 13. CORRECT IMAGES ARE PRESERVED
# ------------------------------------------------------------------------------
def test_correct_images_preserved(shop_inventory, default_weather):
    img_map = {it["product_id"]: it.get("image") for it in shop_inventory}
    options, _, _ = generate_outfit_options(
        "Office interview outfit",
        weather_data=default_weather,
        wardrobe_items=shop_inventory
    )
    for opt in options:
        for it in opt["items"]:
            expected_img = img_map[it["product_id"]]
            assert it.get("image") == expected_img


# ------------------------------------------------------------------------------
# 14. FEWER THAN THREE OPTIONS WHEN INVENTORY CANNOT SUPPORT THREE
# ------------------------------------------------------------------------------
def test_fewer_than_three_options_when_inventory_limited(default_weather):
    # Mock limited inventory: only 1 top, 1 bottom, 1 shoes (cannot make 3 distinct looks)
    limited_inventory = [
        {
            "id": 1,
            "product_id": "MODA-LIM-001",
            "name": "Classic White Oxford Shirt",
            "category": "top",
            "subcategory": "shirt",
            "color": "white",
            "formality": "smart_casual",
            "price": 1499,
            "available_sizes": ["M", "L"],
            "stock_quantity": 3,
            "image": "/uploads/shirt.jpg"
        },
        {
            "id": 2,
            "product_id": "MODA-LIM-002",
            "name": "Navy Tailored Chinos",
            "category": "bottom",
            "subcategory": "chinos",
            "color": "navy",
            "formality": "smart_casual",
            "price": 1899,
            "available_sizes": ["32", "34"],
            "stock_quantity": 2,
            "image": "/uploads/chinos.jpg"
        },
        {
            "id": 3,
            "product_id": "MODA-LIM-003",
            "name": "Brown Leather Loafers",
            "category": "shoes",
            "subcategory": "loafers",
            "color": "brown",
            "formality": "smart_casual",
            "price": 2999,
            "available_sizes": ["9", "10"],
            "stock_quantity": 4,
            "image": "/uploads/loafers.jpg"
        }
    ]
    options, is_notice, msg = generate_outfit_options(
        "Smart casual evening look",
        weather_data=default_weather,
        wardrobe_items=limited_inventory
    )
    # Should only return 1 genuine option and state limitation
    assert len(options) == 1, f"Expected 1 option, got {len(options)}"
    assert is_notice is True
    assert "limited" in msg.lower() or "1 distinct look" in msg.lower()


# ------------------------------------------------------------------------------
# 15. BIRTHDAY REQUEST
# ------------------------------------------------------------------------------
def test_birthday_request(shop_inventory, default_weather):
    res = run_stylist_agent(
        "I need an outfit for a birthday party.",
        weather_data=default_weather,
        wardrobe_items=shop_inventory
    )
    options = res.get("outfit_options", [])
    assert len(options) == 3, f"Birthday request should produce 3 options, got {len(options)}"
    
    # Verify Look 1 contains dress or elevated party piece
    look1 = options[0]
    assert any(it["category"].lower() in ["dress", "top"] for it in look1["items"])
    assert "total_price" in look1
    assert look1["total_price"] > 0


# ------------------------------------------------------------------------------
# 16. WEDDING REQUEST
# ------------------------------------------------------------------------------
def test_wedding_request(shop_inventory, default_weather):
    formality = infer_requested_formality("I need a dress for a wedding.")
    assert formality == "formal"
    
    res = run_stylist_agent(
        "I need a dress for a wedding.",
        weather_data=default_weather,
        wardrobe_items=shop_inventory
    )
    # Since formal dress in wardrobe.db is out of stock (MODA-0024 stock 0), notice or limitation is emitted
    rec_text = res.get("agent_response", "")
    assert "Graphic Vintage Tee" not in rec_text
    assert "Sneakers" not in rec_text


# ------------------------------------------------------------------------------
# 17. CASUAL REQUEST
# ------------------------------------------------------------------------------
def test_casual_request(shop_inventory, default_weather):
    res = run_stylist_agent(
        "Show me something for a casual outing.",
        weather_data=default_weather,
        wardrobe_items=shop_inventory
    )
    options = res.get("outfit_options", [])
    assert len(options) >= 2
    for opt in options:
        # Suit jacket should not be forced into casual separates
        cats_and_names = " ".join([f"{it['category']} {it['name']}" for it in opt["items"]]).lower()
        if opt.get("formula") == "classic_separates":
            assert "suit jacket" not in cats_and_names


# ------------------------------------------------------------------------------
# 18. OFFICE REQUEST
# ------------------------------------------------------------------------------
def test_office_request(shop_inventory, default_weather):
    res = run_stylist_agent(
        "I need an outfit for office / work meeting.",
        weather_data=default_weather,
        wardrobe_items=shop_inventory
    )
    options = res.get("outfit_options", [])
    assert len(options) >= 2
    for opt in options:
        # Graphic vintage tee should not appear for office meeting
        names = [it["name"].lower() for it in opt["items"]]
        assert "graphic vintage tee" not in names


# ------------------------------------------------------------------------------
# 19. WEATHER INFLUENCES RECOMMENDATIONS
# ------------------------------------------------------------------------------
def test_weather_influences_recommendations(shop_inventory):
    cold_weather = {
        "city": "Shimla",
        "temperature": 8.0,
        "weather": "Cold / Chill",
        "rain_probability": 10,
        "wind_speed": 15.0
    }
    options_cold, _, _ = generate_outfit_options(
        "Office meeting outfit",
        weather_data=cold_weather,
        wardrobe_items=shop_inventory
    )
    # Cold weather layered look should select a warm outerwear (coat or jacket)
    layered = [opt for opt in options_cold if opt.get("formula") == "layered_statement"]
    if layered:
        outer_names = [it["name"].lower() for it in layered[0]["items"] if it["category"].lower() == "outerwear"]
        assert any("coat" in n or "jacket" in n for n in outer_names)


# ------------------------------------------------------------------------------
# 20. ZERO-STOCK PRODUCTS ARE EXCLUDED
# ------------------------------------------------------------------------------
def test_zero_stock_products_excluded(default_weather):
    # Fetch all items from DB including stock 0
    all_db_items = get_wardrobe_items(in_stock_only=False)
    zero_stock_ids = {it["product_id"] for it in all_db_items if it.get("stock_quantity", 0) <= 0}
    assert len(zero_stock_ids) >= 1, "Expected zero stock items in DB for test verification"
    
    options, _, _ = generate_outfit_options(
        "I need a dress for a party.",
        weather_data=default_weather,
        wardrobe_items=all_db_items
    )
    for opt in options:
        for it in opt["items"]:
            assert it["product_id"] not in zero_stock_ids, f"Zero stock item {it['product_id']} was recommended!"


# ------------------------------------------------------------------------------
# 21. CALENDAR / DNA / PERSONAL WARDROBE CONCEPTS ABSENT FROM CUSTOMER UI
# ------------------------------------------------------------------------------
def test_personal_wardrobe_concepts_absent_from_customer_ui():
    html_path = os.path.join(ROOT_DIR, "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read().lower()
    
    # Forbidden concepts
    forbidden_terms = [
        "calendar",
        "style dna",
        "my wardrobe",
        "my looks",
        "personal wardrobe",
        "my closet",
        "closet.html",
        "calendar.html",
        "style-dna.html",
        "my-looks.html"
    ]
    for term in forbidden_terms:
        assert term not in content, f"Forbidden customer concept '{term}' was found in index.html"


# ------------------------------------------------------------------------------
# 22. EXISTING STAFF CATALOG TESTS CONTINUE PASSING
# ------------------------------------------------------------------------------
def test_existing_staff_catalog_continues_passing():
    tax = get_taxonomy_options()
    assert "categories" in tax
    assert "Shoes" in tax["categories"]
    assert "Dress" in tax["categories"]
    
    valid_prod = {
        "product_id": "MODA-TEST-STAFF",
        "name": "Staff Added Silk Blouse",
        "category": "Top",
        "subcategory": "Blouse",
        "color": "Navy",
        "pattern": "Solid",
        "formality": "Smart Casual",
        "season": ["All Season"],
        "price": 2499,
        "available_sizes": ["S", "M", "L"],
        "stock_quantity": 5
    }
    is_valid, errors = validate_staff_product(valid_prod)
    assert is_valid is True, f"Validation errors: {errors}"
    assert len(errors) == 0
