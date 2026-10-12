from typing import Optional
from app.models.base import db
from app.models.product import Product
from app.models.customer import Customer
from app.models.order import Order, OrderItem
from sqlalchemy.exc import IntegrityError
import datetime
import functools
from flask import has_app_context

def _with_app_context(func):
    """Ensure database query executes within a Flask application context."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if not has_app_context():
            from app import create_app
            app = create_app()
            with app.app_context():
                return func(*args, **kwargs)
        return func(*args, **kwargs)
    return wrapper

@_with_app_context
def search_products(query: str, limit: int = 10) -> dict:
    """
    Search available products by name or category.
    Supports common English synonyms that map to Arabic product terms.
    Returns a list of matching products or an error.
    """
    try:
        q = (query or "").strip()
        if not q:
            # Empty query — return all available products (used for menu listing).
            results = (
                Product.query.filter(Product.is_available == True)
                .order_by(Product.category, Product.name)
                .limit(limit)
                .all()
            )
            items = [
                {
                    "id": p.id,
                    "name": p.name,
                    "category": p.category,
                    "price": p.price,
                    "combo_price": p.combo_price,
                    "is_available": p.is_available,
                    "description": p.description,
                }
                for p in results
            ]
            return {"ok": True, "items": items, "count": len(items)}

        # Expand English queries with Arabic equivalents for common terms.
        _ENGLISH_SYNONYMS = {
            "chicken": "دجاج",
            "frank": "فراخ",
            "beef": "لحم",
            "meat": "لحم",
            "sandwich": "ساندوتش",
            "meal": "وجبة",
            "combo": "كومبو",
            "cola": "كولا",
            "coke": "كوكاكولا",
            "fries": "بطاطس",
            "water": "مياه",
            "garlic": "ثومية",
            "tahina": "طحينة",
            "sauce": "صوص",
            "drink": "مشروب",
            "sides": "إضافات",
            "addon": "إضافة",
            "addons": "إضافات",
            "shawarma": "شاورما",
            "kfc": "كريسبي",
            "crispy": "كريسبي",
            "broasted": "بروستد",
            "strips": "ستربس",
            "strip": "ستربس",
            "fatta": "فتة",
            "rice": "أرز",
            "basmati": "بسمتي",
            "spicy": "حار",
            "hot": "حار",
            "pepper": "فلفل",
            "حار": "حار",
        }
        expanded_terms = [q]
        lowered = q.lower()
        for english, arabic in _ENGLISH_SYNONYMS.items():
            if english in lowered:
                expanded_terms.append(arabic)

        results = (
            Product.query.filter(Product.is_available == True)
            .filter(
                db.or_(
                    *[Product.name.ilike(f"%{term}%") | Product.category.ilike(f"%{term}%") for term in expanded_terms]
                )
            )
            .limit(limit)
            .all()
        )
        items = [
            {
                "id": p.id,
                "name": p.name,
                "category": p.category,
                "price": p.price,
                "combo_price": p.combo_price,
                "is_available": p.is_available,
                "description": p.description,
            }
            for p in results
        ]
        return {"ok": True, "items": items, "count": len(items)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

def _matches_spicy(product: Product) -> bool:
    spicy_signals = ["spicy", "حار", "hot", "pepper"]
    text = " ".join(
        [
            (product.name or ""),
            (product.description or ""),
            (product.category or ""),
        ]
    ).lower()
    return any(signal in text for signal in spicy_signals)

def _meal_priority(product: Product) -> int:
    category = (product.category or "").lower()
    name = (product.name or "").lower()
    if any(key in category for key in ["meal", "sandwich", "chicken", "shawarma", "pasta", "rice"]):
        return 2
    if any(key in category for key in ["drink", "side", "addon", "sauce"]):
        return 0
    return 1

@_with_app_context
def recommend_products(message: str, limit: int = 3) -> dict:
    """
    Simple recommendation helper based on actual product data.
    Supports lightweight hints:
    - budget mentions like '150 egp'
    - spicy mentions like 'spicy'
    - group mentions like 'for two'
    """
    try:
        text = (message or "").strip().lower()
        budget = None
        try:
            import re

            match = re.search(r"(\d{2,5})\s*egp", text)
            if match:
                budget = float(match.group(1))
        except Exception:
            budget = None

        query = Product.query.filter(Product.is_available == True)
        if "spicy" in text or "حار" in text:
            query = query.filter(
                (Product.name.ilike("%spicy%"))
                | (Product.description.ilike("%spicy%"))
                | (Product.name.ilike("%حار%"))
                | (Product.description.ilike("%حار%"))
            )
        results = list(query.all())

        scored = []
        for p in results:
            score = float(_meal_priority(p))
            price = p.price

            if budget is not None:
                if price > budget:
                    continue
                score += 1.0

            if "spicy" in text or "حار" in text:
                if _matches_spicy(p):
                    score += 2.0

            if any(k in text for k in ("lunch", "dinner", "meal", "غداء", "عشاء", "وجبة", "جوعان", "hungry")):
                if (p.category or "").lower() == "meals":
                    score += 3.0

            scored.append((score, p))

        scored.sort(key=lambda x: (-x[0], x[1].price))
        items = [
            {
                "id": p.id,
                "name": p.name,
                "category": p.category,
                "price": p.price,
                "combo_price": p.combo_price,
                "is_available": p.is_available,
                "description": p.description,
            }
            for _, p in scored[:limit]
        ]
        return {"ok": True, "items": items, "count": len(items)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

@_with_app_context
def query_price_info(message: str) -> dict:
    """
    Deterministic calculation for menu price questions:
    - cheapest meal / أرخص وجبة
    - most expensive meal / أغلى وجبة
    - meals under X EGP / وجبات أقل من X
    - price of each meal / أسعار كل الوجبات
    """
    try:
        text = (message or "").strip().lower()
        meals = Product.query.filter(Product.is_available == True, Product.category == "Meals").order_by(Product.price.asc()).all()
        if not meals:
            return {"ok": False, "error": "No available meals found in the menu."}

        # Check for threshold like 'under 200 egp' or 'less than 200'
        import re
        under_match = re.search(r"(?:under|less than|أقل من|تحت)\s*(\d{2,5})", text)
        if under_match:
            threshold = float(under_match.group(1))
            matched_meals = [m for m in meals if m.price <= threshold]
            lines = [f"### 💰 Meals Under {threshold:.0f} EGP\n"]
            if not matched_meals:
                lines.append(f"There are currently no meals under {threshold:.0f} EGP.")
            else:
                for m in matched_meals:
                    lines.append(f"* **{m.name}** — {m.price:.0f} EGP *(Combo upgrade: +{m.combo_price:.0f} EGP)*")
            return {"ok": True, "type": "threshold", "text": "\n".join(lines), "items": [m.to_dict() for m in matched_meals]}

        if any(k in text for k in ["cheapest", "ارخص", "أرخص"]):
            min_price = meals[0].price
            cheapest = [m for m in meals if m.price == min_price]
            lines = ["### 🏷️ Cheapest Meal Option\n"]
            for m in cheapest:
                lines.append(f"* **{m.name}** — {m.price:.0f} EGP *(Combo upgrade: +{m.combo_price:.0f} EGP for fries and drink)*")
            return {"ok": True, "type": "cheapest", "text": "\n".join(lines), "items": [m.to_dict() for m in cheapest]}

        if any(k in text for k in ["most expensive", "highest", "اغلى", "أغلى"]):
            max_price = max(m.price for m in meals)
            expensive = [m for m in meals if m.price == max_price]
            lines = ["### 👑 Most Premium Meal Option\n"]
            for m in expensive:
                lines.append(f"* **{m.name}** — {m.price:.0f} EGP *(Combo upgrade: +{m.combo_price:.0f} EGP)*")
            return {"ok": True, "type": "most_expensive", "text": "\n".join(lines), "items": [m.to_dict() for m in expensive]}

        # Price of each meal / all meal prices
        if any(k in text for k in ["price of each", "all meal prices", "سعر كل", "أسعار الوجبات"]):
            lines = ["### 🍗 Prices of All Meals\n"]
            for m in meals:
                lines.append(f"* **{m.name}** — {m.price:.0f} EGP *(Combo: +{m.combo_price:.0f} EGP)*")
            return {"ok": True, "type": "all_prices", "text": "\n".join(lines), "items": [m.to_dict() for m in meals]}

        return {"ok": False, "error": "Not a specific price comparison query."}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

@_with_app_context
def find_or_create_customer(name: str, phone: str, address: str = "") -> dict:
    """
    Find an existing customer by phone or create one if missing.
    Normalizes Egyptian phone formats so equivalent numbers resolve to the same customer.
    Returns the customer data or an error.
    """
    try:
        phone = (phone or "").strip()
        name = (name or "").strip()
        if not phone:
            return {"ok": False, "error": "Customer phone is required."}

        normalized = _normalize_egyptian_phone(phone)
        customer = Customer.query.filter(
            (Customer.phone == phone)
            | (Customer.phone == normalized)
            | (Customer.phone == f"20{normalized}")
            | (Customer.phone == f"0{normalized}")
        ).first()
        if customer:
            if name and customer.name != name:
                customer.name = name
            if address:
                customer.address = address
            db.session.commit()
            return {
                "ok": True,
                "created": False,
                "id": customer.id,
                "phone": customer.phone,
                "name": customer.name,
                "address": customer.address,
            }

        customer = Customer(name=name or None, phone=phone, address=address or None)
        db.session.add(customer)
        db.session.commit()
        return {
            "ok": True,
            "created": True,
            "id": customer.id,
            "phone": customer.phone,
            "name": customer.name,
            "address": customer.address,
        }
    except IntegrityError:
        db.session.rollback()
        return {"ok": False, "error": "Customer already exists."}
    except Exception as exc:
        db.session.rollback()
        return {"ok": False, "error": str(exc)}

@_with_app_context
def create_order(
    customer_id: int,
    items: list[dict],
    order_type: str = "delivery",
    payment_method: str = "Cash",
    delivery_address: str = "",
    pickup_branch: str = "",
    table_number: str = "",
    status: str = "In Kitchen",
) -> dict:
    """
    Create a real order with order items.
    `items` should be a list of dicts with:
      - product_id or product_name
      - quantity > 0
      - optional unit_price override
    Returns order summary or error.
    """
    try:
        customer = db.session.get(Customer, customer_id)
        if not customer:
            return {"ok": False, "error": "Customer not found."}

        if not items:
            return {"ok": False, "error": "Order must include at least one item."}

        # Generate unique 5-digit order code (e.g. 'ORD-60689') matching the assessment format
        import random
        for _ in range(20):
            candidate_code = f"ORD-{random.randint(10000, 99999)}"
            if not Order.query.filter_by(order_code=candidate_code).first():
                order_code = candidate_code
                break
        else:
            order_code = f"ORD-{int(datetime.datetime.now(datetime.timezone.utc).timestamp() % 100000):05d}"
        order = Order(
            order_code=order_code,
            customer_id=customer.id,
            customer_name=customer.name,
            customer_phone=customer.phone,
            order_type=order_type or "delivery",
            payment_method=payment_method or "Cash",
            delivery_address=delivery_address or None,
            pickup_branch=pickup_branch or None,
            table_number=table_number or None,
            status=status or "In Kitchen",
            total_price=0.0,
        )
        db.session.add(order)
        db.session.flush()

        total = 0.0
        order_items = []
        for item in items:
            product = None
            if item.get("product_id") is not None:
                product = db.session.get(Product, item.get("product_id"))
            if product is None and item.get("product_name"):
                product = Product.query.filter(
                    Product.name.ilike(item.get("product_name"))
                ).first()

            if not product:
                db.session.rollback()
                return {
                    "ok": False,
                    "error": f"Product not found for item: {item}",
                }

            if not product.is_available:
                db.session.rollback()
                return {
                    "ok": False,
                    "error": f"Product '{product.name}' is currently unavailable.",
                }

            quantity_raw = item.get("quantity")
            if quantity_raw is None:
                quantity = 1
            else:
                try:
                    quantity = int(quantity_raw)
                except (TypeError, ValueError):
                    db.session.rollback()
                    return {
                        "ok": False,
                        "error": f"Invalid quantity for {product.name}.",
                    }
                if quantity <= 0:
                    db.session.rollback()
                    return {
                        "ok": False,
                        "error": f"Invalid quantity for {product.name}.",
                    }

            unit_price = item.get("unit_price")
            if unit_price is None:
                if item.get("is_combo") and product.combo_price:
                    unit_price = product.price + product.combo_price
                else:
                    unit_price = product.price
            unit_price = float(unit_price)
            line_total = round(unit_price * quantity, 2)
            total += line_total

            order_item = OrderItem(
                order_id=order.id,
                product_id=product.id,
                product_name=product.name,
                quantity=quantity,
                unit_price=unit_price,
                line_total=line_total,
                notes=item.get("notes"),
            )
            db.session.add(order_item)
            order_items.append(
                {
                    "product_id": product.id,
                    "product_name": product.name,
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "line_total": line_total,
                }
            )

        order.total_price = round(total, 2)
        db.session.commit()

        return {
            "ok": True,
            "order_id": order.id,
            "order_code": order.order_code,
            "customer_id": customer.id,
            "customer_name": customer.name,
            "customer_phone": customer.phone,
            "order_type": order.order_type,
            "payment_method": order.payment_method,
            "delivery_address": order.delivery_address,
            "pickup_branch": order.pickup_branch,
            "table_number": order.table_number,
            "status": order.status,
            "total_price": order.total_price,
            "items": order_items,
        }
    except Exception as exc:
        db.session.rollback()
        return {"ok": False, "error": str(exc)}

def _normalize_egyptian_phone(value: str) -> str:
    digits = "".join(ch for ch in value if ch.isdigit())
    if digits.startswith("20"):
        digits = digits[2:]
    if digits.startswith("0"):
        digits = digits[1:]
    return digits

def _extract_order_code(text: str) -> str | None:
    import re

    match = re.search(r"\bORD[-\s]*(\d{5,})\b", text or "", re.IGNORECASE)
    if match:
        return f"ORD-{match.group(1)}"
    return None

def _find_order_for_customer(order_code: str, phone: str) -> Order | None:
    if not order_code or not phone:
        return None
    normalized_phone = _normalize_egyptian_phone(phone)
    customer = Customer.query.filter(
        (Customer.phone == phone)
        | (Customer.phone == normalized_phone)
        | (Customer.phone == f"20{normalized_phone}")
        | (Customer.phone == f"0{normalized_phone}")
    ).first()
    if not customer:
        return None
    return Order.query.filter_by(order_code=order_code, customer_id=customer.id).first()

@_with_app_context
def edit_order(order_code: str, phone: str, items: list[dict] | None = None, status: str | None = None) -> dict:
    try:
        order = _find_order_for_customer(order_code, phone)
        if not order:
            return {"ok": False, "error": "Order not found for this customer."}

        if status is not None:
            order.status = status

        if items is not None:
            OrderItem.query.filter_by(order_id=order.id).delete()
            total = 0.0
            for item in items:
                product_name = (item.get("product_name") or "").strip()
                quantity = int(item.get("quantity", 1) or 1)
                if not product_name or quantity <= 0:
                    db.session.rollback()
                    return {"ok": False, "error": f"Invalid item: {item}"}

                product = Product.query.filter(Product.name.ilike(product_name)).first()
                if not product:
                    db.session.rollback()
                    return {"ok": False, "error": f"Product not found: {product_name}"}

                is_combo = bool(item.get("is_combo"))
                combo_fee = product.combo_price if (is_combo and product.combo_price) else 0.0
                unit_price = product.price + combo_fee
                line_total = round(unit_price * quantity, 2)
                total += line_total
                db.session.add(
                    OrderItem(
                        order_id=order.id,
                        product_id=product.id,
                        product_name=product.name,
                        quantity=quantity,
                        unit_price=unit_price,
                        line_total=line_total,
                    )
                )
            order.total_price = round(total, 2)

        db.session.commit()
        return {
            "ok": True,
            "order_code": order.order_code,
            "status": order.status,
            "total_price": order.total_price,
            "items": [
                {
                    "product_name": item.product_name,
                    "quantity": item.quantity,
                    "unit_price": item.unit_price,
                    "line_total": item.line_total,
                }
                for item in order.items
            ],
        }
    except Exception as exc:
        db.session.rollback()
        return {"ok": False, "error": str(exc)}

@_with_app_context
def cancel_order(order_code: str, phone: str) -> dict:
    try:
        order = _find_order_for_customer(order_code, phone)
        if not order:
            return {"ok": False, "error": "Order not found for this customer."}

        if order.status == "Cancelled":
            return {"ok": False, "error": "Order is already cancelled."}

        order.status = "Cancelled"
        db.session.commit()
        return {
            "ok": True,
            "order_code": order.order_code,
            "status": order.status,
        }
    except Exception as exc:
        db.session.rollback()
        return {"ok": False, "error": str(exc)}

@_with_app_context
def track_order(order_code: str, phone: Optional[str] = None) -> dict:
    """
    Look up authoritative order status from the database.
    If phone is provided, verifies customer ownership.
    If phone is not provided, requires the exact order code.
    Returns authoritative current status and details.
    """
    try:
        if not order_code:
            return {"ok": False, "error": "Order code is required."}

        order = Order.query.filter_by(order_code=order_code.strip()).first()
        if not order:
            return {"ok": False, "error": f"No order found with code '{order_code}'."}

        # Privacy check if phone is provided
        if phone:
            normalized_req = _normalize_egyptian_phone(phone)
            cust_phone = order.customer.phone if order.customer else (order.customer_phone or "")
            normalized_cust = _normalize_egyptian_phone(cust_phone)
            if normalized_req and normalized_cust and normalized_req != normalized_cust:
                return {"ok": False, "error": "Phone number does not match this order."}

        c_name = order.customer.name if order.customer else (order.customer_name or "Valued Customer")
        c_phone = order.customer.phone if order.customer else (order.customer_phone or "")

        return {
            "ok": True,
            "order_code": order.order_code,
            "status": order.status,
            "customer_name": c_name,
            "customer_phone": c_phone,
            "order_type": order.order_type,
            "delivery_address": order.delivery_address,
            "pickup_branch": order.pickup_branch,
            "table_number": order.table_number,
            "total_price": order.total_price,
            "created_at": order.created_at.strftime("%Y-%m-%d %H:%M:%S") if order.created_at else None,
            "items": [it.to_dict() for it in order.items],
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

def tool_result_text(result: dict) -> str:
    """
    Convert a tool result dict into a concise text summary for the LLM.
    """
    if not isinstance(result, dict):
        return str(result)
    if result.get("ok"):
        if "items" in result and "order_code" in result and "status" in result and "total_price" in result:
            items_lines = "\n".join(f"* **{i['product_name']}** x{i['quantity']} — {i['unit_price']} EGP (Total: {i['line_total']} EGP)" for i in result.get("items", []))
            return (
                f"### 🧾 Order Update: {result['order_code']}\n\n"
                f"* **Status**: {result['status']}\n"
                f"* **Total**: {result['total_price']} EGP\n\n"
                f"#### Items:\n{items_lines}"
            )
        if "items" in result:
            if not result["items"]:
                return "No products matched the search."
            lines = []
            for item in result["items"]:
                price = item.get("price", 0.0)
                combo = item.get("combo_price", 0.0)
                combo_str = f" *(Combo upgrade: +{combo:.0f} EGP)*" if combo and combo > 0 else ""
                desc = (item.get("description") or "").replace("\n", " ").strip()
                desc_str = f" — {desc}" if desc and desc != item["name"] else ""
                lines.append(f"* **{item['name']}** ({item['category']}) — {price:.0f} EGP{combo_str}{desc_str}")
            return "\n".join(lines)
        if "order_code" in result:
            items_lines = "\n".join(f"* **{i['product_name']}** x{i['quantity']} — {i['unit_price']} EGP (Total: {i['line_total']} EGP)" for i in result.get("items", []))
            dest = ""
            otype = result.get('order_type')
            if otype == "delivery":
                dest = f"* **Delivery Address**: {result.get('delivery_address')}\n"
            elif otype == "pickup":
                dest = f"* **Pickup Branch**: {result.get('pickup_branch')}\n"
            elif otype == "dine_in":
                dest = f"* **Table Number**: {result.get('table_number')}\n"
            return (
                f"### 🧾 Order Confirmation: {result['order_code']}\n\n"
                f"* **Customer**: {result.get('customer_name')} ({result.get('customer_phone')})\n"
                f"* **Order Type**: {otype}\n"
                f"{dest}"
                f"* **Payment Method**: {result.get('payment_method')}\n"
                f"* **Status**: {result.get('status', 'In Kitchen')}\n"
                f"* **Total**: {result.get('total_price')} EGP\n\n"
                f"#### Items:\n{items_lines}"
            )
        if result.get("created"):
            return f"Customer created: {result.get('name')} ({result.get('phone')})."
        return f"Result: {result}"
    return f"Error: {result.get('error', result)}"