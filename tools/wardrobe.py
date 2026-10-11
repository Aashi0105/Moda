"""Shop inventory tool module for Moda Multi-Agent Stylist (Phase 2).

Queries the SQLite database ('wardrobe.db') to fetch available shop inventory products,
filtering by category, subcategory, color, formality, season, temperature range, and stock availability.
"""

import sqlite3
import os
import json
from typing import List, Dict, Any, Optional, Union

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "wardrobe.db")


def _deserialize_item(row_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Helper to deserialize JSON fields (available_sizes, season) into native Python types."""
    item = dict(row_dict)

    # Deserialize available_sizes
    raw_sizes = item.get("available_sizes")
    if isinstance(raw_sizes, str):
        try:
            item["available_sizes"] = json.loads(raw_sizes)
        except Exception:
            item["available_sizes"] = [s.strip() for s in raw_sizes.split(",") if s.strip()]

    # Deserialize season
    raw_season = item.get("season")
    if isinstance(raw_season, str) and (raw_season.startswith("[") or raw_season.startswith("{")):
        try:
            item["season"] = json.loads(raw_season)
        except Exception:
            pass

    return item


def get_wardrobe_items(
    category: Optional[str] = None,
    subcategory: Optional[str] = None,
    color: Optional[str] = None,
    formality: Optional[str] = None,
    season: Optional[str] = None,
    max_temp_c: Optional[float] = None,
    in_stock_only: bool = True
) -> List[Dict[str, Any]]:
    """Queries the SQLite shop inventory database for available clothing products with optional filters.

    Args:
        category: Optional category filter (e.g., 'top', 'bottom', 'outerwear', 'shoes', 'dress', 'accessory').
        subcategory: Optional subcategory filter (e.g., 'Shirt', 'Jeans', 'Sneakers', 'Blazer', etc.).
        color: Optional color filter (e.g., 'Blue', 'Black', 'White', etc.).
        formality: Optional formality filter (e.g., 'casual', 'smart casual', 'formal').
        season: Optional season filter (e.g., 'Summer', 'Winter', 'Spring', 'Fall', 'All Season').
        max_temp_c: Optional temperature in °C to filter items comfortable for current weather.
        in_stock_only: If True, only returns products where stock_quantity > 0.
                       If False, returns all products including zero-stock items.

    Returns:
        List of dictionaries containing clothing item attributes including:
        id, product_id, name, image, category, subcategory, color, pattern,
        formality, season, price, available_sizes, stock_quantity, temp_min_c, temp_max_c.

    Raises:
        FileNotFoundError: If wardrobe.db does not exist.
        sqlite3.Error: On database query errors.
    """
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"Database file '{DB_PATH}' not found. Please run 'python setup_db.py'.")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Enables column access by name
    cursor = conn.cursor()

    query = """
        SELECT id, product_id, name, image, category, subcategory, color, pattern,
               formality, season, price, available_sizes, stock_quantity,
               temp_min_c, temp_max_c
        FROM wardrobe
        WHERE 1=1
    """
    params: List[Any] = []

    # Filter stock availability: stock_quantity > 0 for active shop recommendations
    if in_stock_only:
        query += " AND stock_quantity > 0"

    # Category filter (supports singular & plural variations e.g. 'tops' -> 'top')
    if category and category.strip():
        cat_clean = category.strip().lower()
        if cat_clean.endswith("s") and cat_clean not in ("shoes", "dress"):
            cat_clean = cat_clean[:-1]
        query += " AND (LOWER(category) = ? OR LOWER(category) LIKE ?)"
        params.extend([cat_clean, f"%{cat_clean}%"])

    # Subcategory filter
    if subcategory and subcategory.strip():
        sub_clean = subcategory.strip().lower()
        query += " AND (LOWER(subcategory) = ? OR LOWER(subcategory) LIKE ?)"
        params.extend([sub_clean, f"%{sub_clean}%"])

    # Color filter
    if color and color.strip():
        col_clean = f"%{color.strip().lower()}%"
        query += " AND LOWER(color) LIKE ?"
        params.append(col_clean)

    # Formality filter
    if formality and formality.strip():
        form_clean = formality.strip().lower()
        query += " AND LOWER(formality) = ?"
        params.append(form_clean)

    # Season filter
    if season and season.strip():
        seas_clean = f"%{season.strip().lower()}%"
        query += " AND (LOWER(season) LIKE ? OR LOWER(season) LIKE '%all-season%' OR LOWER(season) LIKE '%all season%')"
        params.append(seas_clean)

    # Weather temperature filter
    if max_temp_c is not None:
        query += " AND temp_min_c <= ? AND temp_max_c >= ?"
        params.extend([max_temp_c, max_temp_c])

    query += " ORDER BY id, category, name"

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    items = [_deserialize_item(dict(row)) for row in rows]
    return items


def get_product_by_id(identifier: Union[int, str]) -> Optional[Dict[str, Any]]:
    """Retrieves a single product by numeric id or string product_id (e.g., 'MODA-0001')."""
    if not os.path.exists(DB_PATH):
        return None

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    if isinstance(identifier, int) or (isinstance(identifier, str) and identifier.isdigit()):
        cursor.execute("SELECT * FROM wardrobe WHERE id = ?", (int(identifier),))
    else:
        cursor.execute("SELECT * FROM wardrobe WHERE product_id = ?", (str(identifier).strip(),))

    row = cursor.fetchone()
    conn.close()

    if row:
        return _deserialize_item(dict(row))
    return None


def add_wardrobe_item(
    name: str,
    category: str,
    color: str = "custom",
    season: Union[str, List[str]] = "all-season",
    formality: str = "casual",
    temp_min_c: float = 10.0,
    temp_max_c: float = 30.0,
    product_id: Optional[str] = None,
    image: Optional[str] = None,
    subcategory: Optional[str] = None,
    pattern: Optional[str] = "Solid",
    price: float = 0.0,
    available_sizes: Optional[List[str]] = None,
    stock_quantity: int = 1
) -> int:
    """Inserts a new clothing item into SQLite wardrobe.db."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Generate default product_id if not supplied
    if not product_id:
        cursor.execute("SELECT MAX(id) FROM wardrobe")
        max_id_row = cursor.fetchone()
        next_num = (max_id_row[0] or 0) + 1
        product_id = f"MODA-{next_num:04d}"

    sizes_str = json.dumps(available_sizes or ["One Size"]) if isinstance(available_sizes, list) else str(available_sizes or "[]")
    season_str = json.dumps(season) if isinstance(season, list) else str(season)

    cursor.execute("""
        INSERT INTO wardrobe (
            product_id, name, image, category, subcategory, color,
            pattern, formality, season, price, available_sizes,
            stock_quantity, temp_min_c, temp_max_c
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        product_id, name, image or "", category, subcategory or "", color,
        pattern or "Solid", formality, season_str, price, sizes_str,
        stock_quantity, temp_min_c, temp_max_c
    ))
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    print(f"[WardrobeDB] Inserted product '{name}' ({product_id}, id={new_id}, category={category}, stock={stock_quantity})")
    return new_id
