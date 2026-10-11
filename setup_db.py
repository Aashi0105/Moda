"""Database setup and seeding script for Moda Shop Inventory (Phase 2).

Creates and seeds the SQLite database ('wardrobe.db') with the shop inventory schema:
- product_id (unique product SKU, e.g. MODA-0001)
- name, image
- category, subcategory
- color, pattern
- formality, season
- price, available_sizes, stock_quantity
- temp_min_c, temp_max_c
"""

import sqlite3
import os
import json
from typing import List, Dict, Any

DB_PATH = os.path.join(os.path.dirname(__file__), "wardrobe.db")
INVENTORY_JSON_PATH = os.path.join(os.path.dirname(__file__), "data", "inventory.json")


def init_wardrobe_db(force_reseed: bool = False):
    """Initializes the SQLite database with shop inventory schema and realistic items."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Check if table exists and inspect columns
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='wardrobe'")
    table_exists = cursor.fetchone() is not None

    needs_migration = False
    if table_exists:
        cursor.execute("PRAGMA table_info(wardrobe)")
        cols = {row[1] for row in cursor.fetchall()}
        required_cols = {"product_id", "price", "available_sizes", "stock_quantity", "subcategory", "pattern"}
        if not required_cols.issubset(cols):
            print("[setup_db] Old schema detected. Rebuilding table with Phase 2 Shop Inventory schema...")
            needs_migration = True

    if force_reseed or needs_migration or not table_exists:
        cursor.execute("DROP TABLE IF EXISTS wardrobe")
        cursor.execute("""
            CREATE TABLE wardrobe (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                image TEXT,
                category TEXT NOT NULL,
                subcategory TEXT,
                color TEXT NOT NULL,
                pattern TEXT,
                formality TEXT NOT NULL,
                season TEXT NOT NULL,
                price REAL NOT NULL DEFAULT 0.0,
                available_sizes TEXT NOT NULL DEFAULT '[]',
                stock_quantity INTEGER NOT NULL DEFAULT 0,
                temp_min_c REAL NOT NULL DEFAULT 10.0,
                temp_max_c REAL NOT NULL DEFAULT 30.0
            );
        """)
        conn.commit()

    # Check if table already has data
    cursor.execute("SELECT COUNT(*) FROM wardrobe")
    count = cursor.fetchone()[0]

    if count == 0:
        items_to_insert: List[Dict[str, Any]] = []

        if os.path.exists(INVENTORY_JSON_PATH):
            with open(INVENTORY_JSON_PATH, "r", encoding="utf-8") as f:
                items_to_insert = json.load(f)
            print(f"[setup_db] Loaded {len(items_to_insert)} items from '{INVENTORY_JSON_PATH}'.")
        else:
            print(f"[setup_db] Warning: '{INVENTORY_JSON_PATH}' not found. Seeding minimal default set.")
            items_to_insert = [
                {
                    "id": 1,
                    "product_id": "MODA-0001",
                    "name": "Navy Blue Wool Trench Coat",
                    "image": "/uploads/image-1781693192020-605948074.jpg",
                    "category": "Outerwear",
                    "subcategory": "Coat",
                    "color": "Navy",
                    "pattern": "Solid",
                    "formality": "Formal",
                    "season": ["Winter"],
                    "price": 5499.0,
                    "available_sizes": ["M", "L", "XL"],
                    "stock_quantity": 4,
                    "temp_min_c": -5.0,
                    "temp_max_c": 15.0
                }
            ]

        for item in items_to_insert:
            sizes_str = json.dumps(item.get("available_sizes", [])) if isinstance(item.get("available_sizes"), list) else str(item.get("available_sizes", "[]"))
            season_str = json.dumps(item.get("season", ["All Season"])) if isinstance(item.get("season"), list) else str(item.get("season", "All Season"))

            cursor.execute("""
                INSERT INTO wardrobe (
                    id, product_id, name, image, category, subcategory,
                    color, pattern, formality, season, price, available_sizes,
                    stock_quantity, temp_min_c, temp_max_c
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                item.get("id"),
                item.get("product_id"),
                item.get("name"),
                item.get("image", ""),
                item.get("category"),
                item.get("subcategory", ""),
                item.get("color"),
                item.get("pattern", "Solid"),
                item.get("formality"),
                season_str,
                float(item.get("price", 0.0)),
                sizes_str,
                int(item.get("stock_quantity", 0)),
                float(item.get("temp_min_c", 10.0)),
                float(item.get("temp_max_c", 30.0))
            ))

        conn.commit()
        print(f"[setup_db] Database initialized successfully with {len(items_to_insert)} shop inventory items at '{DB_PATH}'.")
    else:
        print(f"[setup_db] Database already contains {count} items at '{DB_PATH}'. Skipping seed.")

    conn.close()


if __name__ == "__main__":
    init_wardrobe_db(force_reseed=True)
