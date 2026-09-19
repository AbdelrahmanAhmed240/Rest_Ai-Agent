import sys
from datetime import datetime, timezone, timedelta
from flask import Flask
from config import config
from app.models import db, Product, Customer, Order, OrderItem, KnowledgeItem
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


def seed_database():
    """Populates the database with initial restaurant menu, customers, and orders."""
    app = create_app()

    with app.app_context():
        print("========================================")
        print("    STEP 3: SEEDING RESTAURANT DB       ")
        print("========================================")

        # 1. Recreate tables
        db.drop_all()
        db.create_all()
        print("[OK] Recreated SQLite database tables.")

        # 2. Seed Menu Products (Restaurant Domain)
        products_data = [
            # Shawarma Meals & Sandwiches
            {
                "name": "ساندوتش شاورما فراخ عربي",
                "category": "Sandwiches",
                "description": "شاورما دجاج متبلة في خبز صاج محمص مع صوص ثومية وخيار مخلل وبطاطس",
                "price": 120.0,
                "combo_price": 40.0,
                "is_available": True,
            },
            {
                "name": "ساندوتش شاورما لحم عربي",
                "category": "Sandwiches",
                "description": "شاورما لحم بلدي في خبز صاج مع بقدونس وبصل وطحينة وبطاطس",
                "price": 140.0,
                "combo_price": 40.0,
                "is_available": True,
            },
            {
                "name": "وجبة شاورما دجاج فرط (عائلي)",
                "category": "Meals",
                "description": "نصف كيلو شاورما دجاج مع أرز بسمتي، 2 بطاطس، 2 ثومية، خبز صاج",
                "price": 260.0,
                "combo_price": 0.0,
                "is_available": True,
            },
            {
                "name": "وجبة شاورما لحم فرط (عائلي)",
                "category": "Meals",
                "description": "نصف كيلو شاورما لحم مع أرز بسمتي، 2 طحينة، مخلل، خبز صاج",
                "price": 300.0,
                "combo_price": 0.0,
                "is_available": True,
            },
            {
                "name": "ساندوتش كريسبي دجاج حار",
                "category": "Sandwiches",
                "description": "قطع صدور دجاج كريسبي مقرمشة مع جبنة شيدر وصوص مايونيز حار وخس",
                "price": 110.0,
                "combo_price": 35.0,
                "is_available": True,
            },
            {
                "name": "وجبة دجاج بروستد 4 قطع",
                "category": "Meals",
                "description": "4 قطع دجاج بروستد مقرمش مع بطاطس، كول سلو، ثومية، خبز",
                "price": 180.0,
                "combo_price": 30.0,
                "is_available": True,
            },
            # Sides & Add-ons
            {
                "name": "بطاطس محمرة مبهرة",
                "category": "Sides",
                "description": "علبة بطاطس مقلية ذهبية بتوابل بريك الخاصة",
                "price": 35.0,
                "combo_price": 0.0,
                "is_available": True,
            },
            {
                "name": "علبة صوص ثومية",
                "category": "Sides",
                "description": "صوص ثومية شامي كريمي طازج",
                "price": 15.0,
                "combo_price": 0.0,
                "is_available": True,
            },
            {
                "name": "علبة صوص طحينة",
                "category": "Sides",
                "description": "طحينة سمسم فاخرة متبلة بالليمون والكمون",
                "price": 15.0,
                "combo_price": 0.0,
                "is_available": True,
            },
            # Drinks
            {
                "name": "كانز كوكاكولا",
                "category": "Drinks",
                "description": "مشروب كوكاكولا بارد 330 مل",
                "price": 25.0,
                "combo_price": 0.0,
                "is_available": True,
            },
            {
                "name": "كانز سبرايت",
                "category": "Drinks",
                "description": "مشروب سبرايت ليمون منعش 330 مل",
                "price": 25.0,
                "combo_price": 0.0,
                "is_available": True,
            },
            {
                "name": "زجاجة مياه معدنية",
                "category": "Drinks",
                "description": "مياه معدنية طبيعية 600 مل",
                "price": 10.0,
                "combo_price": 0.0,
                "is_available": True,
            },
        ]

        product_objects = {}
        for p in products_data:
            prod = Product(**p)
            db.session.add(prod)
            product_objects[p["name"]] = prod

        db.session.commit()
        print(f"[OK] Seeded {len(products_data)} products into menu.")

        # 3. Seed Sample Customers
        customers_data = [
            {"phone": "1093016152", "name": "أحمد محمود", "address": "مدينة نصر - شارع عباس العقاد عمارة 12"},
            {"phone": "1193016152", "name": "سارة علي", "address": "التجمع الخامس - حي النرجس عمارة 45"},
            {"phone": "1293016152", "name": "محمد إبراهيم", "address": "مصر الجديدة - ميدان روكسي"},
        ]

        customer_objects = {}
        for c in customers_data:
            cust = Customer(**c)
            db.session.add(cust)
            customer_objects[c["phone"]] = cust

        db.session.commit()
        print(f"[OK] Seeded {len(customers_data)} sample customers.")

        # 4. Seed Sample Orders
        now = datetime.now(timezone.utc)

        order1 = Order(
            order_code="ORD-60689",
            customer_id=customer_objects["1093016152"].id,
            order_type="delivery",
            payment_method="Cash",
            delivery_address="مدينة نصر - شارع عباس العقاد عمارة 12",
            status="In Kitchen",
            total_price=160.0,
            created_at=now - timedelta(minutes=5),
        )
        db.session.add(order1)
        db.session.commit()

        item1 = OrderItem(
            order_id=order1.id,
            product_id=product_objects["ساندوتش شاورما فراخ عربي"].id,
            product_name="ساندوتش شاورما فراخ عربي (كومبو)",
            quantity=1,
            unit_price=160.0,
            line_total=160.0,
            notes="ثومية إضافية بدون مخلل",
        )
        db.session.add(item1)

        order2 = Order(
            order_code="ORD-45210",
            customer_id=customer_objects["1193016152"].id,
            order_type="pickup",
            payment_method="Visa",
            pickup_branch="فرع التجمع الخامس",
            status="Delivered",
            total_price=300.0,
            created_at=now - timedelta(days=1),
        )
        db.session.add(order2)
        db.session.commit()

        item2 = OrderItem(
            order_id=order2.id,
            product_id=product_objects["وجبة شاورما لحم فرط (عائلي)"].id,
            product_name="وجبة شاورما لحم فرط (عائلي)",
            quantity=1,
            unit_price=300.0,
            line_total=300.0,
            notes="طحينة زيادة",
        )
        db.session.add(item2)

        order3 = Order(
            order_code="ORD-77123",
            customer_id=customer_objects["1293016152"].id,
            order_type="dine_in",
            payment_method="Cash",
            table_number="T-12",
            status="In Kitchen",
            total_price=120.0,
            created_at=now - timedelta(minutes=15),
        )
        db.session.add(order3)
        db.session.commit()

        item3 = OrderItem(
            order_id=order3.id,
            product_id=product_objects["بطاطس محمرة مبهرة"].id,
            product_name="بطاطس محمرة مبهرة",
            quantity=3,
            unit_price=35.0,
            line_total=105.0,
            notes=None,
        )
        db.session.add(item3)

        item4 = OrderItem(
            order_id=order3.id,
            product_id=product_objects["زجاجة مياه معدنية"].id,
            product_name="زجاجة مياه معدنية",
            quantity=2,
            unit_price=10.0,
            line_total=20.0,
            notes=None,
        )
        db.session.add(item4)
        db.session.commit()
        print("[OK] Seeded 3 sample orders with line items (1 Delivery, 1 Pickup, 1 Dine-in).")

        # 5. Sync Markdown knowledge into DB + Chroma
        sync_all()
        print("[OK] Synced Markdown knowledge into KnowledgeItem and Chroma.")

        print("\n[SUCCESS] DATABASE SEEDING COMPLETED SUCCESSFULLY!")


if __name__ == "__main__":
    seed_database()
