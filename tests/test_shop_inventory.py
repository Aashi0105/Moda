"""Shop Inventory, Grounding & Suitability Guard Test Suite for Moda Phase 2.

Verifies:
1. Shop Inventory Schema (product_id, price, available_sizes, stock_quantity, legacy fields).
2. Stock Filtering (stock_quantity = 5 eligible, 1 eligible, 0 NOT eligible).
3. Grounding & Anti-Hallucination (only supplied products recommended; nonexistent items rejected).
4. Insufficient Inventory Handling (acknowledges limited stock without hallucinating).
5. Product Suitability Guard:
   - Suitable inventory -> recommendation generated.
   - Inventory exists but is unsuitable (e.g., casual items for black-tie gala) -> limitation notice.
   - Mixed inventory -> suitable products preferred.
   - Zero-stock suitable product -> not considered (notice emitted).
   - No suitable products -> no hallucinated substitute.
6. Metadata Preservation (product_id, price, sizes, stock_quantity passed downstream).
"""

import sys
import os
import json
import pytest

# Ensure root project directory is in python path
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(ROOT_DIR)

from tools.wardrobe import get_wardrobe_items, get_product_by_id, add_wardrobe_item
from agents.wardrobe_agent import run_wardrobe_agent
from agents.stylist_agent import run_stylist_agent, infer_requested_formality, is_product_suitable
from api import parse_outfit_from_text


# ------------------------------------------------------------------------------
# 1. INVENTORY SCHEMA TESTS
# ------------------------------------------------------------------------------

def test_inventory_schema_fields():
    """Verify that every inventory item has all new shop fields and legacy fields intact."""
    items = get_wardrobe_items(in_stock_only=False)
    assert len(items) >= 20, f"Expected 20-30 items, found {len(items)}"
    assert len(items) <= 30, f"Expected 20-30 items, found {len(items)}"

    product_ids = set()

    for item in items:
        # Shop-specific fields
        assert "product_id" in item, "Missing product_id"
        assert item["product_id"].startswith("MODA-"), f"Invalid product_id: {item['product_id']}"
        assert item["product_id"] not in product_ids, f"Duplicate product_id: {item['product_id']}"
        product_ids.add(item["product_id"])

        assert "price" in item, "Missing price"
        assert isinstance(item["price"], (int, float)) and item["price"] > 0, f"Invalid price in {item['name']}"

        assert "available_sizes" in item, "Missing available_sizes"
        assert isinstance(item["available_sizes"], list) and len(item["available_sizes"]) > 0, f"Sizes must be a list in {item['name']}"

        assert "stock_quantity" in item, "Missing stock_quantity"
        assert isinstance(item["stock_quantity"], int) and item["stock_quantity"] >= 0, f"Invalid stock in {item['name']}"

        # Existing/taxonomy fields
        assert "id" in item, "Missing id"
        assert "name" in item and len(item["name"]) > 0, "Missing or empty name"
        assert "category" in item and len(item["category"]) > 0, "Missing category"
        assert "subcategory" in item, "Missing subcategory"
        assert "color" in item and len(item["color"]) > 0, "Missing color"
        assert "pattern" in item, "Missing pattern"
        assert "formality" in item, "Missing formality"
        assert "season" in item, "Missing season"
        assert "image" in item, "Missing image"
        assert "temp_min_c" in item, "Missing temp_min_c"
        assert "temp_max_c" in item, "Missing temp_max_c"


def test_inventory_json_schema():
    """Verify that data/inventory.json contains valid 20-30 items matching schema."""
    json_path = os.path.join(ROOT_DIR, "data", "inventory.json")
    assert os.path.exists(json_path), "data/inventory.json must exist"

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert 20 <= len(data) <= 30, f"Expected 20-30 dummy items in JSON, found {len(data)}"
    for item in data:
        assert item["product_id"].startswith("MODA-")
        assert item["price"] > 0
        assert isinstance(item["available_sizes"], list)
        assert item["stock_quantity"] >= 0


# ------------------------------------------------------------------------------
# 2. STOCK FILTERING TESTS (5 -> eligible, 1 -> eligible, 0 -> NOT eligible)
# ------------------------------------------------------------------------------

def test_stock_filtering_levels():
    """Test critical rule: stock_quantity > 0 is eligible, stock_quantity = 0 is NOT eligible."""
    test_p5_id = add_wardrobe_item(
        name="Test Item Five Stock",
        category="top",
        color="blue",
        formality="casual",
        product_id="TEST-STOCK-5",
        price=999,
        available_sizes=["M"],
        stock_quantity=5
    )
    test_p1_id = add_wardrobe_item(
        name="Test Item One Stock",
        category="top",
        color="blue",
        formality="casual",
        product_id="TEST-STOCK-1",
        price=999,
        available_sizes=["M"],
        stock_quantity=1
    )
    test_p0_id = add_wardrobe_item(
        name="Test Item Zero Stock",
        category="top",
        color="blue",
        formality="casual",
        product_id="TEST-STOCK-0",
        price=999,
        available_sizes=["M"],
        stock_quantity=0
    )

    try:
        in_stock_items = get_wardrobe_items(in_stock_only=True)
        in_stock_ids = [i["product_id"] for i in in_stock_items]

        # stock_quantity = 5 -> eligible
        assert "TEST-STOCK-5" in in_stock_ids, "Item with stock_quantity = 5 MUST be eligible."
        # stock_quantity = 1 -> eligible
        assert "TEST-STOCK-1" in in_stock_ids, "Item with stock_quantity = 1 MUST be eligible."
        # stock_quantity = 0 -> NOT eligible
        assert "TEST-STOCK-0" not in in_stock_ids, "Item with stock_quantity = 0 MUST NOT be eligible."

        # Verify zero stock items still exist in database without deletion
        all_items = get_wardrobe_items(in_stock_only=False)
        all_ids = [i["product_id"] for i in all_items]
        assert "TEST-STOCK-0" in all_ids, "Zero-stock product must exist in database without deletion."

    finally:
        import sqlite3
        conn = sqlite3.connect(os.path.join(ROOT_DIR, "wardrobe.db"))
        c = conn.cursor()
        c.execute("DELETE FROM wardrobe WHERE product_id LIKE 'TEST-STOCK-%'")
        conn.commit()
        conn.close()


def test_wardrobe_agent_only_returns_in_stock():
    """Verify Wardrobe Agent never returns out-of-stock products for recommendations."""
    res = run_wardrobe_agent("Show formal dresses")
    returned_ids = [i.get("product_id") for i in res.get("wardrobe_items", [])]
    assert "MODA-0024" not in returned_ids, "Zero-stock dress MODA-0024 must NOT be returned by Wardrobe Agent."

    for item in res.get("wardrobe_items", []):
        assert item["stock_quantity"] > 0, f"Wardrobe Agent returned out-of-stock item: {item['name']}"


# ------------------------------------------------------------------------------
# 3. GROUNDING & ANTI-HALLUCINATION TESTS
# ------------------------------------------------------------------------------

def test_stylist_grounding_with_strict_inventory():
    """Given smart-casual inventory containing ONLY Blue Shirt, Beige Chinos, White Sneakers,
    for a smart-casual request, verify only supplied products are recommended.
    """
    strict_inventory = [
        {
            "id": 18,
            "product_id": "MODA-0018",
            "name": "Blue Striped Shirt",
            "category": "top",
            "subcategory": "Shirt",
            "color": "Blue",
            "formality": "smart casual",
            "price": 1299,
            "available_sizes": ["S", "M", "L", "XL"],
            "stock_quantity": 7,
            "temp_min_c": 10.0,
            "temp_max_c": 35.0
        },
        {
            "id": 10,
            "product_id": "MODA-0010",
            "name": "Beige Chino Pants",
            "category": "bottom",
            "subcategory": "Chinos",
            "color": "Beige",
            "formality": "smart casual",
            "price": 1899,
            "available_sizes": ["30", "32", "34", "36"],
            "stock_quantity": 8,
            "temp_min_c": 10.0,
            "temp_max_c": 35.0
        },
        {
            "id": 14,
            "product_id": "MODA-0014",
            "name": "Minimalist White Leather Sneakers",
            "category": "shoes",
            "subcategory": "Sneakers",
            "color": "White",
            "formality": "casual",
            "price": 2699,
            "available_sizes": ["7", "8", "9", "10"],
            "stock_quantity": 14,
            "temp_min_c": 5.0,
            "temp_max_c": 35.0
        }
    ]

    weather = {"city": "Vadodara", "temperature": 26.0, "weather": "Sunny", "rain_probability": 0}
    res = run_stylist_agent("I need a smart casual meeting outfit", weather, strict_inventory)
    response_text = res["agent_response"]

    assert "Blue Striped Shirt" in response_text
    assert "Beige Chino Pants" in response_text
    assert "Minimalist White Leather Sneakers" in response_text

    hallucinated_candidates = [
        "Black Blazer", "Leather Loafers", "Gold Watch",
        "Trench Coat", "Chelsea Boots", "Puffer Jacket"
    ]
    for hallucination in hallucinated_candidates:
        assert hallucination not in response_text, f"Hallucinated item detected: '{hallucination}'"


def test_stylist_insufficient_inventory_no_hallucination():
    """Verify that when inventory is completely empty, the system acknowledges limitation."""
    empty_inventory = []
    weather = {"city": "Vadodara", "temperature": 26.0, "weather": "Sunny", "rain_probability": 0}

    res = run_stylist_agent("Formal evening dinner outfit", weather, empty_inventory)
    response_text = res["agent_response"]

    assert "Inventory Notice" in response_text or "does not contain enough suitable" in response_text
    assert "White Oxford Cotton Shirt" not in response_text
    assert "Navy Blue Wool Trench Coat" not in response_text


def test_stylist_zero_stock_product_cannot_be_recommended():
    """Verify that a product with stock_quantity = 0 is never recommended by Stylist."""
    inventory_with_zero_stock_top = [
        {
            "id": 99,
            "product_id": "MODA-0099",
            "name": "Sold Out Silk Shirt",
            "category": "top",
            "color": "White",
            "formality": "casual",
            "price": 3000,
            "available_sizes": ["M"],
            "stock_quantity": 0,  # OUT OF STOCK
            "temp_min_c": 10.0,
            "temp_max_c": 35.0
        },
        {
            "id": 10,
            "product_id": "MODA-0010",
            "name": "Beige Chino Pants",
            "category": "bottom",
            "color": "Beige",
            "formality": "casual",
            "price": 1899,
            "available_sizes": ["32"],
            "stock_quantity": 8,  # IN STOCK
            "temp_min_c": 10.0,
            "temp_max_c": 35.0
        }
    ]

    weather = {"city": "Vadodara", "temperature": 24.0, "weather": "Clear", "rain_probability": 0}
    res = run_stylist_agent("Casual look", weather, inventory_with_zero_stock_top)
    response_text = res["agent_response"]

    assert "Sold Out Silk Shirt" not in response_text


# ------------------------------------------------------------------------------
# 4. DOWNSTREAM METADATA PRESERVATION TESTS
# ------------------------------------------------------------------------------

def test_recommendation_pipeline_preserves_shop_metadata():
    """Verify that parsed recommendation output preserves product_id, price, available_sizes, stock_quantity."""
    mock_markdown = (
        "### 👔 Recommended Outfit\n"
        "- **Top:** Blue Striped Shirt (MODA-0018) - ₹1,299 | Sizes: S, M, L, XL | In Stock: 7\n"
        "- **Bottom:** Beige Chino Pants (MODA-0010) - ₹1,899 | Sizes: 30, 32, 34, 36 | In Stock: 8\n"
        "- **Outerwear:** None needed\n"
        "- **Shoes:** Minimalist White Leather Sneakers (MODA-0014) - ₹2,699 | Sizes: 7, 8, 9, 10, 11 | In Stock: 14\n"
        "- **Accessories:** None\n\n"
        "### 💡 Stylist Rationale\n"
        "A stylish smart casual outfit."
    )

    items = get_wardrobe_items(in_stock_only=True)
    parsed = parse_outfit_from_text(mock_markdown, items)

    top = parsed["top"]
    assert top["id"] == 18
    assert top["product_id"] == "MODA-0018"
    assert top["name"] == "Blue Striped Shirt"
    assert top["price"] == 1299
    assert "M" in top["available_sizes"]
    assert top["stock_quantity"] == 7
    assert "/uploads/" in top["image"]

    bottom = parsed["bottom"]
    assert bottom["id"] == 10
    assert bottom["product_id"] == "MODA-0010"
    assert bottom["name"] == "Beige Chino Pants"
    assert bottom["price"] == 1899
    assert bottom["stock_quantity"] == 8

    shoes = parsed["shoes"]
    assert shoes["id"] == 14
    assert shoes["product_id"] == "MODA-0014"
    assert shoes["price"] == 2699
    assert shoes["stock_quantity"] == 14


# ------------------------------------------------------------------------------
# 5. PRODUCT SUITABILITY GUARD TESTS (PHASE 2 ENHANCEMENT)
# ------------------------------------------------------------------------------

def test_suitability_suitable_inventory_generates_recommendation():
    """Test 1: When suitable inventory exists for the requested occasion, recommendation is generated."""
    formal_inventory = [
        {
            "id": 4,
            "product_id": "MODA-0004",
            "name": "Dark Grey Tailored Suit Jacket",
            "category": "outerwear",
            "formality": "formal",
            "price": 4999,
            "stock_quantity": 3,
            "temp_min_c": 10.0,
            "temp_max_c": 30.0
        },
        {
            "id": 5,
            "product_id": "MODA-0005",
            "name": "White Oxford Cotton Shirt",
            "category": "top",
            "formality": "formal",
            "price": 1599,
            "stock_quantity": 10,
            "temp_min_c": 10.0,
            "temp_max_c": 35.0
        },
        {
            "id": 11,
            "product_id": "MODA-0011",
            "name": "Black Tailored Dress Trousers",
            "category": "bottom",
            "formality": "formal",
            "price": 2499,
            "stock_quantity": 4,
            "temp_min_c": 10.0,
            "temp_max_c": 30.0
        },
        {
            "id": 15,
            "product_id": "MODA-0015",
            "name": "Black Oxfords Leather Shoes",
            "category": "shoes",
            "formality": "formal",
            "price": 3799,
            "stock_quantity": 5,
            "temp_min_c": 10.0,
            "temp_max_c": 35.0
        }
    ]

    weather = {"city": "Vadodara", "temperature": 24.0, "weather": "Clear", "rain_probability": 0}
    res = run_stylist_agent("Dress me for a black-tie gala event", weather, formal_inventory)
    response_text = res["agent_response"]

    assert "Recommended Outfit" in response_text
    assert "White Oxford Cotton Shirt" in response_text
    assert "Black Tailored Dress Trousers" in response_text
    assert "Black Oxfords Leather Shoes" in response_text


def test_suitability_inventory_exists_but_unsuitable_emits_notice():
    """Test 2: When inventory exists in stock but is unsuitable (casual items for black-tie gala),
    the system MUST emit an inventory limitation notice and NOT recommend casual pieces.
    """
    casual_only_inventory = [
        {
            "id": 7,
            "product_id": "MODA-0007",
            "name": "Graphic Vintage Tee",
            "category": "top",
            "formality": "casual",
            "price": 999,
            "stock_quantity": 9,
            "temp_min_c": 10.0,
            "temp_max_c": 35.0
        },
        {
            "id": 9,
            "product_id": "MODA-0009",
            "name": "Dark Wash Slim Jeans",
            "category": "bottom",
            "formality": "casual",
            "price": 2299,
            "stock_quantity": 11,
            "temp_min_c": 10.0,
            "temp_max_c": 35.0
        },
        {
            "id": 14,
            "product_id": "MODA-0014",
            "name": "Minimalist White Leather Sneakers",
            "category": "shoes",
            "formality": "casual",
            "price": 2699,
            "stock_quantity": 14,
            "temp_min_c": 5.0,
            "temp_max_c": 35.0
        },
        {
            "id": 10,
            "product_id": "MODA-0010",
            "name": "Beige Chino Pants",
            "category": "bottom",
            "formality": "smart casual",
            "price": 1899,
            "stock_quantity": 8,
            "temp_min_c": 10.0,
            "temp_max_c": 35.0
        }
    ]

    weather = {"city": "Vadodara", "temperature": 25.0, "weather": "Clear", "rain_probability": 0}
    res = run_stylist_agent("Dress me for a black-tie gala event", weather, casual_only_inventory)
    response_text = res["agent_response"]

    # Must emit Inventory Notice
    assert "Inventory Notice" in response_text or "lacks suitable" in response_text
    # Crucial: MUST NOT fill the black-tie outfit with casual items
    assert "Graphic Vintage Tee" not in response_text
    assert "Dark Wash Slim Jeans" not in response_text
    assert "Minimalist White Leather Sneakers" not in response_text


def test_suitability_mixed_inventory_prefers_suitable_products():
    """Test 3: Mixed inventory (casual + formal) -> formal request prefers formal pieces;
    casual request prefers casual pieces.
    """
    mixed_inventory = [
        # Formal items
        {
            "id": 11,
            "product_id": "MODA-0011",
            "name": "Black Tailored Dress Trousers",
            "category": "bottom",
            "formality": "formal",
            "price": 2499,
            "stock_quantity": 4,
            "temp_min_c": 10.0,
            "temp_max_c": 35.0
        },
        {
            "id": 5,
            "product_id": "MODA-0005",
            "name": "White Oxford Cotton Shirt",
            "category": "top",
            "formality": "formal",
            "price": 1599,
            "stock_quantity": 10,
            "temp_min_c": 10.0,
            "temp_max_c": 35.0
        },
        {
            "id": 15,
            "product_id": "MODA-0015",
            "name": "Black Oxfords Leather Shoes",
            "category": "shoes",
            "formality": "formal",
            "price": 3799,
            "stock_quantity": 5,
            "temp_min_c": 10.0,
            "temp_max_c": 35.0
        },
        # Casual items
        {
            "id": 7,
            "product_id": "MODA-0007",
            "name": "Graphic Vintage Tee",
            "category": "top",
            "formality": "casual",
            "price": 999,
            "stock_quantity": 9,
            "temp_min_c": 10.0,
            "temp_max_c": 35.0
        },
        {
            "id": 9,
            "product_id": "MODA-0009",
            "name": "Dark Wash Slim Jeans",
            "category": "bottom",
            "formality": "casual",
            "price": 2299,
            "stock_quantity": 11,
            "temp_min_c": 10.0,
            "temp_max_c": 35.0
        },
        {
            "id": 14,
            "product_id": "MODA-0014",
            "name": "Minimalist White Leather Sneakers",
            "category": "shoes",
            "formality": "casual",
            "price": 2699,
            "stock_quantity": 14,
            "temp_min_c": 5.0,
            "temp_max_c": 35.0
        }
    ]

    weather = {"city": "Vadodara", "temperature": 25.0, "weather": "Clear", "rain_probability": 0}

    # Case A: Formal Wedding request -> must prefer formal items
    formal_res = run_stylist_agent("Formal wedding ceremony outfit", weather, mixed_inventory)
    formal_text = formal_res["agent_response"]
    assert "Black Tailored Dress Trousers" in formal_text
    assert "Black Oxfords Leather Shoes" in formal_text
    assert "Graphic Vintage Tee" not in formal_text
    assert "Dark Wash Slim Jeans" not in formal_text

    # Case B: Casual outing request -> must prefer casual items, not force formal suit pieces
    casual_res = run_stylist_agent("Casual weekend outing to the park", weather, mixed_inventory)
    casual_text = casual_res["agent_response"]
    assert "Graphic Vintage Tee" in casual_text
    assert "Dark Wash Slim Jeans" in casual_text
    assert "Minimalist White Leather Sneakers" in casual_text
    assert "Black Tailored Dress Trousers" not in casual_text


def test_suitability_zero_stock_suitable_product_not_considered():
    """Test 4: When a suitable product has stock_quantity = 0, it must NOT be considered,
    and the system should emit an inventory limitation notice instead of recommending it
    or falling back to unsuitable items.
    """
    inventory_with_zero_stock_formal = [
        {
            "id": 24,
            "product_id": "MODA-0024",
            "name": "Crimson Silk Evening Maxi Dress",
            "category": "dress",
            "formality": "formal",
            "price": 3999,
            "stock_quantity": 0,  # OUT OF STOCK
            "temp_min_c": 10.0,
            "temp_max_c": 35.0
        },
        {
            "id": 7,
            "product_id": "MODA-0007",
            "name": "Graphic Vintage Tee",
            "category": "top",
            "formality": "casual",
            "price": 999,
            "stock_quantity": 9,  # IN STOCK but UNSUITABLE
            "temp_min_c": 10.0,
            "temp_max_c": 35.0
        },
        {
            "id": 9,
            "product_id": "MODA-0009",
            "name": "Dark Wash Slim Jeans",
            "category": "bottom",
            "formality": "casual",
            "price": 2299,
            "stock_quantity": 11, # IN STOCK but UNSUITABLE
            "temp_min_c": 10.0,
            "temp_max_c": 35.0
        }
    ]

    weather = {"city": "Vadodara", "temperature": 25.0, "weather": "Clear", "rain_probability": 0}
    res = run_stylist_agent("Black-tie evening gala", weather, inventory_with_zero_stock_formal)
    response_text = res["agent_response"]

    # Must NOT recommend the sold-out formal dress
    assert "Crimson Silk Evening Maxi Dress" not in response_text
    # Must NOT fall back to recommending casual items for a gala
    assert "Graphic Vintage Tee" not in response_text
    assert "Dark Wash Slim Jeans" not in response_text
    # Must emit Inventory Notice
    assert "Inventory Notice" in response_text or "lacks suitable" in response_text


def test_suitability_no_suitable_products_no_hallucination():
    """Test 5: When no suitable products exist, the system emits an inventory notice
    and does NOT hallucinate substitute products (e.g. tuxedo, black blazer, gold watch).
    """
    casual_inventory = [
        {
            "id": 12,
            "product_id": "MODA-0012",
            "name": "Linen Blend Shorts",
            "category": "bottom",
            "formality": "casual",
            "price": 1199,
            "stock_quantity": 7,
            "temp_min_c": 10.0,
            "temp_max_c": 38.0
        }
    ]

    weather = {"city": "Vadodara", "temperature": 25.0, "weather": "Clear", "rain_probability": 0}
    res = run_stylist_agent("Dress me for a black-tie gala event", weather, casual_inventory)
    response_text = res["agent_response"]

    assert "Inventory Notice" in response_text or "lacks suitable" in response_text

    hallucinations = ["Tuxedo", "Black Blazer", "Gold Watch", "Leather Loafers", "Silk Tie"]
    for h in hallucinations:
        assert h.lower() not in response_text.lower(), f"Detected hallucinated product: '{h}'"
