"""Staff Cataloging & Review Service for Moda Phase 3.

Provides backend logic for the Staff Review Screen:
1. Taxonomy options retrieval based on tools/item_tagger.py constants.
2. AI-tagging invocation with confidence scores and 'needs_review' detection.
3. Strict validation of staff-confirmed products against taxonomy and commercial rules.
4. Synchronized persistence across wardrobe.db, data/inventory.json, and data/wardrobe.json.
"""

import os
import json
import sqlite3
from typing import Dict, Any, List, Tuple, Optional, Union

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_PATH = os.path.join(ROOT_DIR, "wardrobe.db")
INVENTORY_JSON_PATH = os.path.join(ROOT_DIR, "data", "inventory.json")
WARDROBE_JSON_PATH = os.path.join(ROOT_DIR, "data", "wardrobe.json")

# Import taxonomy constants and tagger from tools/item_tagger
from tools.item_tagger import (
    ALLOWED_CATEGORIES,
    ALLOWED_SUBCATEGORIES,
    ALLOWED_COLORS,
    ALLOWED_PATTERNS,
    ALLOWED_FORMALITIES,
    ALLOWED_SEASONS,
    ALLOWED_IMAGE_QUALITIES,
    tag_clothing_item,
)
from tools.wardrobe import get_wardrobe_items, add_wardrobe_item


def get_taxonomy_options() -> Dict[str, Any]:
    """Returns the fixed taxonomy lists and category-subcategory mapping for staff dropdowns."""
    return {
        "categories": sorted(list(ALLOWED_CATEGORIES)),
        "subcategories": {cat: sorted(subs) for cat, subs in ALLOWED_SUBCATEGORIES.items()},
        "colors": sorted(list(ALLOWED_COLORS)),
        "patterns": sorted(list(ALLOWED_PATTERNS)),
        "formalities": ["Casual", "Smart Casual", "Formal"],  # Ordered by formality level
        "seasons": ["Summer", "Winter", "Monsoon/Rainy", "All Season"],
        "image_qualities": sorted(list(ALLOWED_IMAGE_QUALITIES)),
    }


def tag_product_image_for_review(image_path: str) -> Dict[str, Any]:
    """Runs item_tagger on an image and formats results with confidence scores and needs_review flags.

    Args:
        image_path: Path to the product image.

    Returns:
        Structured dictionary with AI suggestions, confidence scores, and review status.
    """
    # Resolve relative or filename-only paths to public/uploads or test_images if needed
    resolved_path = image_path
    if not os.path.isabs(resolved_path):
        candidates = [
            os.path.join(ROOT_DIR, resolved_path),
            os.path.join(ROOT_DIR, "public", "uploads", os.path.basename(resolved_path)),
            os.path.join(ROOT_DIR, "test_images", os.path.basename(resolved_path)),
        ]
        for c in candidates:
            if os.path.exists(c):
                resolved_path = c
                break

    tagger_model = os.getenv("GEMINI_TAGGER_MODEL", "gemini-2.5-flash")
    tagger_output = tag_clothing_item(resolved_path, model_name=tagger_model)
    val_tags = tagger_output.get("validated_tags", {})

    def _extract_field(field_name: str) -> Dict[str, Any]:
        info = val_tags.get(field_name, {})
        val = info.get("value")
        conf = info.get("confidence", 0.0)
        # Needs review if value is null, rejected, or low confidence
        needs_review = val is None or conf < 0.70
        return {
            "value": val,
            "confidence": round(float(conf), 2),
            "needs_review": needs_review,
        }

    web_image_url = f"/uploads/{os.path.basename(resolved_path)}"

    return {
        "status": tagger_output.get("status", "SUCCESS"),
        "image_path": resolved_path,
        "image_url": web_image_url,
        "image_quality": tagger_output.get("image_quality", "Good"),
        "suggested_tags": {
            "category": _extract_field("category"),
            "subcategory": _extract_field("subcategory"),
            "color": _extract_field("color"),
            "pattern": _extract_field("pattern"),
            "formality": _extract_field("formality"),
            "season": _extract_field("season"),
        },
        "rejected_fields": tagger_output.get("rejected_fields", []),
        "model_used": tagger_output.get("model_used", "gemini-2.5-flash"),
    }


def validate_staff_product(data: Dict[str, Any], is_update: bool = False) -> Tuple[bool, List[str]]:
    """Validates final staff-entered product values against taxonomy and commercial rules.

    Validation rules:
    - Product Name: required, non-empty.
    - Product ID / SKU: required, unique.
    - Price: numeric, non-negative.
    - Stock Quantity: integer, non-negative.
    - Available Sizes: non-empty list.
    - Category: must be in ALLOWED_CATEGORIES.
    - Subcategory: must be valid for the chosen Category.
    - Color: must be in ALLOWED_COLORS.
    - Pattern: must be in ALLOWED_PATTERNS.
    - Formality: must be in ALLOWED_FORMALITIES.
    - Season: list or string of valid seasons in ALLOWED_SEASONS.
    """
    errors: List[str] = []

    # 1. Product Name
    name = str(data.get("name", "")).strip()
    if not name:
        errors.append("Product Name is required.")

    # 2. Product ID / SKU
    product_id = str(data.get("product_id", "")).strip()
    if not product_id:
        errors.append("Product ID / SKU is required.")
    elif not is_update:
        # Check uniqueness in database
        if os.path.exists(DB_PATH):
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT id FROM wardrobe WHERE LOWER(product_id) = LOWER(?)", (product_id,))
            exists = c.fetchone()
            conn.close()
            if exists:
                errors.append(f"Product ID / SKU '{product_id}' already exists in inventory. Must be unique.")

    # 3. Price
    raw_price = data.get("price")
    try:
        price_val = float(raw_price)
        if price_val < 0:
            errors.append("Price must be a non-negative number.")
    except (ValueError, TypeError):
        errors.append("Price must be a valid numeric value.")

    # 4. Stock Quantity
    raw_stock = data.get("stock_quantity")
    try:
        stock_val = int(raw_stock)
        if stock_val < 0:
            errors.append("Stock quantity must be a non-negative integer.")
        elif float(raw_stock) != stock_val:
            errors.append("Stock quantity must be an integer, not a decimal.")
    except (ValueError, TypeError):
        errors.append("Stock quantity must be a valid integer.")

    # 5. Available Sizes
    sizes = data.get("available_sizes")
    if isinstance(sizes, str):
        sizes = [s.strip() for s in sizes.split(",") if s.strip()]
    if not sizes or not isinstance(sizes, list) or len(sizes) == 0:
        errors.append("At least one available size must be specified.")

    # 6. Taxonomy: Category
    category = str(data.get("category", "")).strip()
    # Case-insensitive match against allowed categories
    cat_match = next((c for c in ALLOWED_CATEGORIES if c.lower() == category.lower()), None)
    if not cat_match:
        errors.append(f"Invalid category '{category}'. Must be one of: {sorted(list(ALLOWED_CATEGORIES))}")
    else:
        # 7. Taxonomy: Subcategory (must be valid for category)
        subcategory = str(data.get("subcategory", "")).strip()
        allowed_subs = ALLOWED_SUBCATEGORIES.get(cat_match, [])
        sub_match = next((s for s in allowed_subs if s.lower() == subcategory.lower()), None)
        if not sub_match:
            errors.append(f"Invalid subcategory '{subcategory}' for category '{cat_match}'. Allowed: {sorted(allowed_subs)}")

    # 8. Taxonomy: Color
    color = str(data.get("color", "")).strip()
    col_match = next((c for c in ALLOWED_COLORS if c.lower() == color.lower()), None)
    if not col_match:
        errors.append(f"Invalid color '{color}'. Must be one of: {sorted(list(ALLOWED_COLORS))}")

    # 9. Taxonomy: Pattern
    pattern = str(data.get("pattern", "Solid")).strip()
    pat_match = next((p for p in ALLOWED_PATTERNS if p.lower() == pattern.lower()), None)
    if not pat_match:
        errors.append(f"Invalid pattern '{pattern}'. Must be one of: {sorted(list(ALLOWED_PATTERNS))}")

    # 10. Taxonomy: Formality
    formality = str(data.get("formality", "")).strip()
    form_match = next((f for f in ALLOWED_FORMALITIES if f.lower() == formality.lower()), None)
    if not form_match:
        errors.append(f"Invalid formality '{formality}'. Must be one of: {sorted(list(ALLOWED_FORMALITIES))}")

    # 11. Taxonomy: Season
    raw_season = data.get("season", ["All Season"])
    if isinstance(raw_season, str):
        if raw_season.startswith("["):
            try:
                raw_season = json.loads(raw_season)
            except Exception:
                raw_season = [s.strip() for s in raw_season.split(",") if s.strip()]
        else:
            raw_season = [s.strip() for s in raw_season.split(",") if s.strip()]

    if not raw_season:
        errors.append("At least one season must be selected.")
    else:
        for s in raw_season:
            seas_match = next((as_seas for as_seas in ALLOWED_SEASONS if as_seas.lower() == s.lower()), None)
            if not seas_match:
                errors.append(f"Invalid season '{s}'. Allowed: {sorted(list(ALLOWED_SEASONS))}")

    return len(errors) == 0, errors


def save_staff_product(data: Dict[str, Any]) -> Dict[str, Any]:
    """Validates and saves a staff-confirmed product into wardrobe.db and syncs to JSON stores.

    Args:
        data: Product attributes confirmed by staff member.

    Returns:
        The saved product dictionary.

    Raises:
        ValueError: If validation fails.
    """
    # 1. Validate
    is_valid, errors = validate_staff_product(data)
    if not is_valid:
        raise ValueError(f"Product validation failed: {'; '.join(errors)}")

    # 2. Normalize taxonomy case
    cat_match = next(c for c in ALLOWED_CATEGORIES if c.lower() == str(data["category"]).strip().lower())
    sub_match = next(s for s in ALLOWED_SUBCATEGORIES[cat_match] if s.lower() == str(data["subcategory"]).strip().lower())
    col_match = next(c for c in ALLOWED_COLORS if c.lower() == str(data["color"]).strip().lower())
    pat_match = next(p for p in ALLOWED_PATTERNS if p.lower() == str(data.get("pattern", "Solid")).strip().lower())
    form_match = next(f for f in ALLOWED_FORMALITIES if f.lower() == str(data["formality"]).strip().lower())

    raw_season = data.get("season", ["All Season"])
    if isinstance(raw_season, str):
        if raw_season.startswith("["):
            try:
                raw_season = json.loads(raw_season)
            except Exception:
                raw_season = [s.strip() for s in raw_season.split(",") if s.strip()]
        else:
            raw_season = [s.strip() for s in raw_season.split(",") if s.strip()]

    norm_seasons = []
    for s in raw_season:
        m = next((as_seas for as_seas in ALLOWED_SEASONS if as_seas.lower() == s.lower()), "All Season")
        if m not in norm_seasons:
            norm_seasons.append(m)

    sizes = data.get("available_sizes", ["One Size"])
    if isinstance(sizes, str):
        sizes = [s.strip() for s in sizes.split(",") if s.strip()]

    # 3. Determine climate temperature ranges (defaults based on category & season if not given)
    temp_min_c = float(data.get("temp_min_c", 10.0))
    temp_max_c = float(data.get("temp_max_c", 36.0))
    if "Winter" in norm_seasons and "Summer" not in norm_seasons:
        temp_min_c = float(data.get("temp_min_c", -5.0))
        temp_max_c = float(data.get("temp_max_c", 18.0))
    elif "Summer" in norm_seasons and "Winter" not in norm_seasons:
        temp_min_c = float(data.get("temp_min_c", 18.0))
        temp_max_c = float(data.get("temp_max_c", 38.0))

    # 4. Insert into SQLite wardrobe.db
    new_db_id = add_wardrobe_item(
        name=str(data["name"]).strip(),
        category=cat_match,
        color=col_match,
        season=norm_seasons,
        formality=form_match,
        temp_min_c=temp_min_c,
        temp_max_c=temp_max_c,
        product_id=str(data["product_id"]).strip(),
        image=str(data.get("image", "")).strip(),
        subcategory=sub_match,
        pattern=pat_match,
        price=float(data["price"]),
        available_sizes=sizes,
        stock_quantity=int(data["stock_quantity"]),
    )

    saved_product = {
        "id": new_db_id,
        "product_id": str(data["product_id"]).strip(),
        "name": str(data["name"]).strip(),
        "image": str(data.get("image", "")).strip(),
        "img": str(data.get("image", "")).strip(),
        "category": cat_match,
        "subcategory": sub_match,
        "color": col_match,
        "pattern": pat_match,
        "formality": form_match,
        "season": norm_seasons,
        "price": float(data["price"]),
        "available_sizes": sizes,
        "stock_quantity": int(data["stock_quantity"]),
        "temp_min_c": temp_min_c,
        "temp_max_c": temp_max_c,
    }

    # 5. Synchronize data/inventory.json
    try:
        inv_items = []
        if os.path.exists(INVENTORY_JSON_PATH):
            with open(INVENTORY_JSON_PATH, "r", encoding="utf-8") as f:
                inv_items = json.load(f)
        # Check if already present to update or append
        existing_idx = next((i for i, item in enumerate(inv_items) if item.get("product_id") == saved_product["product_id"]), None)
        if existing_idx is not None:
            inv_items[existing_idx] = saved_product
        else:
            inv_items.append(saved_product)

        with open(INVENTORY_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(inv_items, f, indent=2)
    except Exception as e:
        print(f"[StaffService] Warning: Failed to sync data/inventory.json: {e}")

    # 6. Synchronize data/wardrobe.json
    try:
        wardrobe_items = []
        if os.path.exists(WARDROBE_JSON_PATH):
            with open(WARDROBE_JSON_PATH, "r", encoding="utf-8") as f:
                wardrobe_items = json.load(f)
        w_idx = next((i for i, item in enumerate(wardrobe_items) if item.get("product_id") == saved_product["product_id"]), None)
        if w_idx is not None:
            wardrobe_items[w_idx] = saved_product
        else:
            wardrobe_items.append(saved_product)

        with open(WARDROBE_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(wardrobe_items, f, indent=2)
    except Exception as e:
        print(f"[StaffService] Warning: Failed to sync data/wardrobe.json: {e}")

    return saved_product
