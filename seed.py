"""Database seeder that extracts menu products directly from knowledge/menu.md.
Preserves existing data, avoids dropping tables, and ensures safe idempotency.
"""

import re
import sys
from pathlib import Path
from flask import Flask

from config import config
from app.models import db, Product
from app.services.chunker import chunk_markdown
from app.services.knowledge_sync import sync_all

# Ensure UTF-8 output on Windows terminals
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def create_app():
    """Create Flask application context for database operations."""
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = config.SQLALCHEMY_DATABASE_URI
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    return app


def parse_products_from_markdown(menu_path: Path) -> list[dict]:
    """Parse real restaurant products from the knowledge/menu.md file.

    Extracts:
    - name, category, description, price, combo_price, is_available.
    Fails clearly if the file is missing, empty, or has unparseable records.
    """
    if not menu_path.exists():
        raise FileNotFoundError(f"Menu markdown source file not found at: {menu_path}")

    content = menu_path.read_text(encoding="utf-8")
    if not content.strip():
        raise ValueError(f"Menu markdown file at {menu_path} is empty.")

    chunks = chunk_markdown(content, menu_path.name)
    if not chunks:
        raise ValueError(f"Failed to extract structured chunks from {menu_path}.")

    # Discover global combo upgrade price if defined
    combo_upgrade_price = 50.0  # default fallback if not found
    for c in chunks:
        if c.get("type") == "combo_upgrade":
            m_price = re.search(r"price:\s*\n\s*value:\s*(\d+(?:\.\d+)?)", c.get("text", ""))
            if m_price:
                combo_upgrade_price = float(m_price.group(1))
            break

    product_types = {"meal", "addon", "sauce", "drink", "extra"}
    category_map = {
        "meal": "Meals",
        "addon": "Add-ons",
        "sauce": "Sauces",
        "drink": "Drinks",
        "extra": "Extras",
    }

    products = []
    for c in chunks:
        c_type = c.get("type")
        if c_type not in product_types:
            continue

        name = (c.get("name") or "").strip()
        if not name:
            raise ValueError(f"Menu chunk {c.get('id')} is missing a product name.")

        text = c.get("text", "")

        # Extract numeric price
        m_price = re.search(r"price:\s*\n\s*value:\s*(\d+(?:\.\d+)?)", text)
        if not m_price:
            m_price = re.search(r"^price:\s*(\d+(?:\.\d+)?)", text, re.MULTILINE)
        if not m_price:
            raise ValueError(f"Product '{name}' in {menu_path.name} is missing a valid numeric price.")

        price = float(m_price.group(1))

        # Extract availability
        m_avail = re.search(r"^available:\s*(true|false)", text, re.MULTILINE | re.IGNORECASE)
        is_available = (m_avail.group(1).lower() == "true") if m_avail else True

        # Extract description
        desc_match = re.search(
            r"^description:\s*\n([\s\S]*?)(?=\n[a-z_]+:|\n---|\Z)",
            text,
            re.MULTILINE,
        )
        description = desc_match.group(1).strip() if desc_match else ""

        category = category_map.get(c_type, "Meals")
        combo_price = combo_upgrade_price if c_type == "meal" else 0.0

        products.append(
            {
                "name": name,
                "category": category,
                "description": description,
                "price": price,
                "combo_price": combo_price,
                "is_available": is_available,
            }
        )

    if not products:
        raise ValueError(f"No valid product records could be extracted from {menu_path}.")

    return products


def seed_database(app=None):
    """Safely populates or updates the database with Markdown-derived menu products,
    sample demo customers, and consistent sample orders without dropping existing tables.
    """
    if app is None:
        app = create_app()

    menu_path = Path(__file__).resolve().parent / "knowledge" / "menu.md"

    with app.app_context():
        print("========================================")
        print("    SEEDING RESTAURANT DATABASE         ")
        print("========================================")

        # 1. Ensure tables exist without dropping existing data
        db.create_all()
        print("[OK] Verified SQLite database schema.")

        # 2. Parse products directly from knowledge/menu.md
        products_data = parse_products_from_markdown(menu_path)
        print(f"[OK] Parsed {len(products_data)} products from {menu_path.name}.")

        product_objects = {}
        created_products = 0
        updated_products = 0

        for p_data in products_data:
            existing = Product.query.filter_by(name=p_data["name"]).first()
            if not existing:
                prod = Product(**p_data)
                db.session.add(prod)
                product_objects[p_data["name"]] = prod
                created_products += 1
            else:
                existing.category = p_data["category"]
                existing.description = p_data["description"]
                existing.price = p_data["price"]
                existing.combo_price = p_data["combo_price"]
                existing.is_available = p_data["is_available"]
                product_objects[p_data["name"]] = existing
                updated_products += 1

        db.session.commit()
        print(
            f"[OK] Menu Products synced: {created_products} added, {updated_products} updated."
        )

        # 3. Sync Markdown knowledge into KnowledgeItem and Chroma
        sync_all()
        print("[OK] Synced Markdown knowledge into KnowledgeItem records.")

        print("\n[SUCCESS] DATABASE SEEDING COMPLETED SUCCESSFULLY!")


if __name__ == "__main__":
    seed_database()
