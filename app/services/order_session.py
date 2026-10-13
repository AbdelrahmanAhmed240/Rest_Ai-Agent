"""
Order Session & Draft Management Service.
Maintains in-memory conversational draft order state per session.
Tracks order items, combo upgrades, order type (delivery, pickup, dine_in),
customer details (name, phone), destination details (address, pickup_branch, table_number),
and payment_method (Cash, Visa).

Enforces strict field requirements before final confirmation:
- Delivery: customer_name, customer_phone, delivery_address, payment_method
- Pickup: customer_name, customer_phone, pickup_branch, payment_method
- Dine-in: customer_name, customer_phone, table_number, payment_method
"""

import json
import re
from typing import Any, Optional
from flask import has_app_context
from app.models.product import Product
from app.models.customer import Customer
from app.models.order import Order
from app.models.chat import ChatSession
from app.models.base import db
from app.services.tools import create_order, find_or_create_customer, _with_app_context

# Known branches from knowledge/details.md
AVAILABLE_BRANCHES = [
    "فرع المهندسين",
    "فرع المقطم",
    "فرع الشيراتون",
    "فرع جليم",
    "فرع المندرة",
    "فرع كامب شيزار",
    "فرع سموحة 1",
    "فرع سموحة 2",
    "فرع بحري",
    "فرع سيدي بشر",
    "فرع المحروسة",
]

# Session drafts store: session_id -> draft_dict
_drafts: dict[str, dict[str, Any]] = {}

def _load_draft_from_db(session_id: str) -> Optional[dict[str, Any]]:
    """Attempt to load persisted draft from SQLite ChatSession table."""
    # Guard against runtime errors if called outside an active Flask request context
    if not has_app_context():
        return None
    try:
        chat_sess = ChatSession.query.filter_by(session_id=session_id).first()
        # Restore draft JSON so cart items survive server restarts or memory cleanup
        if chat_sess and chat_sess.draft_data:
            data = json.loads(chat_sess.draft_data)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return None

def _save_draft_to_db(session_id: str, draft: Optional[dict[str, Any]]) -> None:
    """Persist draft into SQLite ChatSession table."""
    # Ensure database writes only proceed within a valid Flask context
    if not has_app_context():
        return
    try:
        chat_sess = ChatSession.query.filter_by(session_id=session_id).first()
        if chat_sess:
            # Sync in-memory draft directly to the database column for multi-turn durability
            chat_sess.draft_data = json.dumps(draft, ensure_ascii=False) if draft else None
            db.session.commit()
    except Exception:
        # Roll back failed transaction to prevent poisoning the database connection pool
        try:
            db.session.rollback()
        except Exception:
            pass

def get_draft(session_id: str) -> dict[str, Any]:
    """Retrieve or initialize draft order for a session."""
    # Check cache first; if missing in memory, restore from SQLite before initializing empty draft
    if session_id not in _drafts:
        saved = _load_draft_from_db(session_id)
        if saved:
            _drafts[session_id] = saved
        else:
            _drafts[session_id] = {
                "session_id": session_id,
                "order_type": None,          # "delivery", "pickup", "dine_in"
                "customer_name": None,
                "customer_phone": None,
                "delivery_address": None,
                "pickup_branch": None,
                "table_number": None,
                "payment_method": None,      # "Cash", "Visa"
                "items": [],                 # list of item dicts
                "stage": "selecting_items",   # "selecting_items", "offering_extras", "collecting_details", "awaiting_confirmation", "confirmed"
                "upsell_offered": False,     # whether extras have been suggested
                "upsell_declined": False,    # whether customer declined extras
                "confirmed_order_code": None, # Set only once successfully committed
            }
    return _drafts[session_id]

def clear_draft(session_id: str) -> None:
    """Reset draft after successful order placement."""
    if session_id in _drafts:
        del _drafts[session_id]
    _save_draft_to_db(session_id, None)

@_with_app_context
def parse_user_entities(session_id: str, message: str) -> dict[str, Any]:
    """
    Extract fulfillment details from message and update draft:
    - Order type: Delivery / Pickup / Dine-in
    - Phone number: Egyptian 10-11 digit numbers
    - Payment method: Cash / Visa
    - Branch: matches known branches
    - Table: table number / table id
    - Name: name patterns
    - Delivery Address: address patterns
    - Product additions: recognizes menu products + quantity + combo
    """
    draft = get_draft(session_id)
    text = (message or "").strip()
    text_lower = text.lower()
    changes = {}

    # 0. Check for upselling decline or acceptance
    # If customer says 'no thanks' to combo/drink upsells, transition stage to detail collection without losing cart items
    decline_signals = [
        "no", "no thanks", "no thank you", "nope", "nothing", "neither",
        "لا", "لا شكرا", "لا شكراً", "لا تمام", "تمام كده", "مش عايز", "مش عاوز", "كفاية", "بس كده", "لا مش محتاج", "مش محتاج"
    ]
    clean_text = text_lower.strip(" .!?,")
    if (clean_text in decline_signals or any(clean_text == s for s in decline_signals) or any(clean_text.startswith(s + " ") for s in ["no", "no thanks", "لا", "لا شكرا", "لا شكراً"])) and draft.get("items"):
        draft["upsell_declined"] = True
        draft["upsell_offered"] = True
        draft["stage"] = "collecting_details"
        changes["upsell_declined"] = True

    # Check if customer explicitly opted in to combo upgrade
    combo_signals = ["make it combo", "make them combo", "add combo", "combo please", "upgrade to combo", "خليهم كومبو", "مع كومبو", "ضيف كومبو", "نعم كومبو", "عايز كومبو", "عاوز كومبو"]
    if any(sig in text_lower for sig in combo_signals) and draft.get("items"):
        upgrade_res = upgrade_draft_combos(session_id)
        if upgrade_res.get("upgraded_count", 0) > 0:
            changes["combo_upgraded"] = True

    # 1. Order type extraction: determines which destination fields (address, branch, or table) will be mandatory
    delivery_words = ["delivery", "delievery", "delivry", "deliver", "توصيل", "دليفري", "على البيت", "للمنزل", "home delivery"]
    pickup_words = ["pickup", "pick up", "استلام", "من الفرع", "تيك اواي", "تيك أواي", "takeaway", "take away"]
    dinein_words = ["dine in", "dine-in", "dinein", "صالة", "في المطعم", "داخل المطعم", "على الطاولة", "ترابيزة", "طاولة", "table"]

    if any(w in text_lower for w in delivery_words):
        update_draft(session_id, order_type="delivery")
        changes["order_type"] = "delivery"
    elif any(w in text_lower for w in pickup_words):
        update_draft(session_id, order_type="pickup")
        changes["order_type"] = "pickup"
    elif any(w in text_lower for w in dinein_words):
        update_draft(session_id, order_type="dine_in")
        changes["order_type"] = "dine_in"

    # Refresh draft after type update
    draft = get_draft(session_id)

    # 2. Payment method
    if any(w in text_lower for w in ["visa", "card", "credit", "فيزا", "كارت", "بطاقة"]):
        update_draft(session_id, payment_method="Visa")
        changes["payment_method"] = "Visa"
    elif any(w in text_lower for w in ["cash", "كاش", "نقد", "نقدي", "عند الاستلام"]):
        update_draft(session_id, payment_method="Cash")
        changes["payment_method"] = "Cash"

    # 3. Phone number: matches Egyptian mobile format (010, 011, 012, 015 followed by 8 digits) with optional +20 country prefix
    phone_match = re.search(r"(?:(?:\+?20)|0)?1[0125]\d{8}\b", text)
    if phone_match:
        phone_val = phone_match.group(0).strip()
        update_draft(session_id, customer_phone=phone_val)
        changes["customer_phone"] = phone_val

    # 4. Table number: extracts table ID for dine-in orders while guarding against phone or price numbers
    table_match = re.search(r"(?:table|ترابيزة|طاولة|طاوله)\s*(?:رقم|number|#)?\s*(\d+|[a-zA-Z]\d*)", text, re.IGNORECASE)
    if not table_match and (draft.get("order_type") == "dine_in" or any(w in text_lower for w in dinein_words)):
        # Standalone short answer like "12", "T12", "A5" when system specifically asked for table number
        m_standalone = re.fullmatch(r"\s*(?:#|no\.?|رقم)?\s*(\d+|[a-zA-Z]\d+)\s*", text, re.IGNORECASE)
        if m_standalone and not phone_match:
            tbl_candidate = m_standalone.group(1).strip()
            # Guard against mistaking long numeric inputs (e.g. phone numbers or money amounts) for table IDs
            if len(tbl_candidate) <= 4:
                table_match = m_standalone
    if table_match:
        tbl = table_match.group(1).strip()
        update_draft(session_id, table_number=tbl)
        changes["table_number"] = tbl

    # 5. Branch selection: validates pickup requests against known restaurant locations
    for br in AVAILABLE_BRANCHES:
        br_core = br.replace("فرع", "").strip()
        if br.lower() in text_lower or br_core.lower() in text_lower:
            update_draft(session_id, pickup_branch=br)
            changes["pickup_branch"] = br
            break

    # Helper: Check segmented compound messages (e.g., "عبدالرحمن احمد - وابورالمياة شارع فتح الله - كاش")
    # Allows customers to provide full details in a single delimited message
    segments = [s.strip() for s in re.split(r"[-–—|\n]+", text) if s.strip()]
    if len(segments) >= 2:
        for seg in segments:
            seg_lower = seg.lower()
            if any(w in seg_lower for w in ["cash", "كاش", "نقد", "نقدي"]):
                continue
            if any(w in seg_lower for w in ["visa", "فيزا"]):
                continue
            if re.search(r"(?:(?:\+?20)|0)?1[0125]\d{8}\b", seg):
                continue
            if "شارع" in seg or "street" in seg_lower or "st." in seg_lower or "وابور" in seg:
                update_draft(session_id, delivery_address=seg)
                changes["delivery_address"] = seg
            order_intent_words = [
                "order", "want", "add", "have", "أطلب", "اطلب", "عاوز", "عايز", "أريد", "اريد", "هاتلي", "طلب",
                "بسمتيو", "بروستد", "ستربس", "بريك", "فتة", "فته", "وجبة", "وجبه", "كومبو", "combo", "meal",
                "delivery", "delievery", "pickup", "dine", "dine-in", "توصيل", "استلام", "صالة", "ترابيزة", "طاولة",
            ]
            seg_has_order = any(w in seg_lower for w in order_intent_words)
            if not seg_has_order and not draft.get("customer_name") and 2 <= len(seg.split()) <= 4 and not any(ch.isdigit() for ch in seg):
                update_draft(session_id, customer_name=seg)
                changes["customer_name"] = seg

    # Refresh draft after segment extraction
    draft = get_draft(session_id)

    # 6. Customer name
    order_stop_words = [
        "delivery", "delievery", "pickup", "dine", "dine-in", "dinein", "dining", "cash", "visa", "order", "want", "menu", "confirm", "yes", "table", "branch",
        "شارع", "street", "عاوز", "عايز", "أطلب", "اطلب", "أريد", "اريد", "توصيل", "استلام", "صالة", "ترابيزة", "طاولة",
        "بسمتيو", "بروستد", "ستربس", "بريك", "فتة", "فته", "وجبة", "وجبه", "كومبو", "combo", "meal", "هاتلي", "مع", "بدون",
    ]
    if not draft.get("customer_name"):
        # Matches "my name is X", "i'm X", "اسمي X", "أنا X"
        name_match = re.search(r"(?:my name is\s+|my name\s*:\s*|name\s*:\s*|i am\s+|i\'m\s+|اسمي\s+|أنا\s+|انا\s+)([\w\s]{2,25})", text, re.IGNORECASE)
        if name_match:
            cand_name = name_match.group(1).split(",")[0].strip()
            cand_name = re.split(r"(?:\band\b|\bو\b|phone|رقم|cash|visa|كاش|فيزا|address|عنوان|street|شارع)", cand_name, flags=re.IGNORECASE)[0].strip()
            # Filter out common stop words and order phrases
            cand_lower = cand_name.lower()
            if len(cand_name) >= 2 and not any(w in cand_lower for w in order_stop_words):
                update_draft(session_id, customer_name=cand_name)
                changes["customer_name"] = cand_name
        elif draft.get("order_type") and not draft.get("customer_name"):
            # Standalone name answer (e.g. user just replies "Ahmed" or "كريم")
            words = text.split()
            if 1 <= len(words) <= 3 and len(text) >= 2 and not phone_match and not any(ch.isdigit() for ch in text):
                if not any(w in text_lower for w in order_stop_words):
                    update_draft(session_id, customer_name=text)
                    changes["customer_name"] = text

    # 7. Delivery address (especially if order_type is delivery or message mentions address / street)
    if not draft.get("delivery_address"):
        addr_match = re.search(r"(?:address(?:\s+is)?|عنواني|العنوان|delivery to|deliver to|توصيل\s+إلى|توصيل\s+الي)\s*[:=]?\s*([^,\n\r]+)", text, re.IGNORECASE)
        if not addr_match and ("شارع" in text or "street" in text_lower or "st." in text_lower):
            addr_match = re.search(r"(\d*[\s\w,.\-#]+(?:street|st\.?|شارع)[\s\w,.\-#]*)", text, re.IGNORECASE)
        if addr_match:
            cand_addr = addr_match.group(1).strip()
            # Clean trailing stop words like 'my name is...', 'phone...', 'cash'
            cand_addr = re.split(r"(?:,\s*)?(?:my name|phone|name:|اسمي|رقم|cash|visa|كاش|فيزا)", cand_addr, flags=re.IGNORECASE)[0].strip(" ,.-")
            if len(cand_addr) >= 3:
                update_draft(session_id, delivery_address=cand_addr)
                changes["delivery_address"] = cand_addr
        elif draft.get("order_type") == "delivery" and not draft.get("delivery_address"):
            # If user is directly answering the address question with a standalone address
            if not any(k in text_lower for k in ["order", "menu", "cash", "visa", "confirm", "recommend", "delivery"]):
                if len(text) >= 3 and any(ch.isalpha() for ch in text) and not phone_match:
                    update_draft(session_id, delivery_address=text)
                    changes["delivery_address"] = text

    # 8. Product and item additions
    # Check known menu products in DB sorted longest first to avoid partial overlap
    try:
        products = Product.query.filter(Product.is_available == True).all()
        # Aliases mapping for common names / English transliterations
        english_aliases = {
            "break": "وجبة بريك",
            "basmatio": "بسمتيو",
            "strips 3": "وجبة ستربس 3 قطع",
            "strips 5": "وجبة ستربس 5 قطع",
            "strips": "وجبة ستربس 3 قطع",
            "broasted": "ربع فرخة بروستد",
            "fatta": "فتة",
            "fries": "باكيت بطاطس",
            "rice": "أرز بسمتي",
            "coleslaw": "كول سلو",
            "pepsi": "مشروب",
            "drink": "مشروب",
            "water": "مياه",
        }
        products_sorted = sorted(products, key=lambda x: len(x.name), reverse=True)
        matched_spans = []

        # First check DB product names, then English aliases
        targets = [(p.name, p) for p in products_sorted]
        for alias, real_name in english_aliases.items():
            match_prod = next((p for p in products if p.name == real_name), None)
            if match_prod:
                targets.append((alias, match_prod))

        for target_term, p in targets:
            term_lower = target_term.lower()
            if term_lower in text_lower:
                idx = text_lower.find(term_lower)
                span = (idx, idx + len(term_lower))
                if any(s[0] <= span[0] and span[1] <= s[1] for s in matched_spans):
                    continue
                matched_spans.append(span)

                qty = 1
                qty_match = re.search(rf"(\d+)\s*(?:x|from|of|قطع|قطعة|وجبات|وجبة)?\s*{re.escape(target_term)}", text, re.IGNORECASE)
                if not qty_match:
                    qty_match = re.search(rf"{re.escape(target_term)}\s*(?:x|عدد)?\s*(\d+)", text, re.IGNORECASE)
                if qty_match:
                    try:
                        qty = max(1, int(qty_match.group(1)))
                    except Exception:
                        qty = 1

                is_combo = bool("combo" in text_lower or "كومبو" in text_lower)
                # Protect against adding items to cart when the user is only asking an informational question
                # e.g., "what is the price of basmatio?" should NOT add Basmatio to the draft cart
                is_question = any(q in text_lower for q in ("?", "؟", "what", "how much", "can i see", "do you have", "what is", "سعر", "بكام", "فيه", "مكونات"))
                order_words = ["order", "i want", "add", "place", "أطلب", "عاوز", "عايز", "أريد", "اريد", "هاتلي", "ضيف", "مع"]
                has_order_verb = any(w in text_lower for w in order_words)
                has_explicit_qty = bool(qty_match)
                is_explicit_order = (has_order_verb or has_explicit_qty) and not (is_question and not has_order_verb)
                if is_explicit_order:
                    add_item_to_draft(session_id, product_name=p.name, quantity=qty, is_combo=is_combo)
                    changes["added_product"] = p.name
    except Exception:
        pass

    return changes

def get_missing_fields(draft: dict[str, Any]) -> list[str]:
    """
    Determine which required fields are still missing according to order_type.
    """
    missing = []

    # Order cannot be processed without items
    if not draft.get("items"):
        missing.append("items")

    # Order type dictates destination requirements; prompt for type first if unset
    order_type = draft.get("order_type")
    if not order_type:
        missing.append("order_type")
        return missing

    # Common required contact details for all order types
    if not draft.get("customer_name"):
        missing.append("customer_name")
    if not draft.get("customer_phone"):
        missing.append("customer_phone")
    if not draft.get("payment_method"):
        missing.append("payment_method")

    # Destination requirements specific to each fulfillment channel
    if order_type == "delivery":
        if not draft.get("delivery_address"):
            missing.append("delivery_address")
    elif order_type == "pickup":
        if not draft.get("pickup_branch"):
            missing.append("pickup_branch")
    elif order_type == "dine_in":
        if not draft.get("table_number"):
            missing.append("table_number")

    return missing

def calculate_draft_totals(draft: dict[str, Any]) -> dict[str, Any]:
    """
    Calculate accurate prices using trusted DB product prices.
    Applies combo upgrade once per item/quantity.
    Returns calculated summary dict.
    """
    items = draft.get("items", [])
    total = 0.0
    item_summaries = []

    for it in items:
        qty = int(it.get("quantity", 1))
        unit = float(it.get("unit_price", 0.0))
        is_combo = bool(it.get("is_combo", False))
        combo_p = float(it.get("combo_price", 0.0)) if is_combo else 0.0
        # Combo fee is added to each individual unit before multiplying by quantity
        line_unit = unit + combo_p
        line_tot = round(line_unit * qty, 2)
        total += line_tot

        combo_label = " (Combo)" if is_combo else ""
        item_summaries.append({
            "name": it.get("product_name"),
            "product_id": it.get("product_id"),
            "quantity": qty,
            "unit_price": unit,
            "is_combo": is_combo,
            "combo_price": combo_p,
            "line_unit_price": line_unit,
            "line_total": line_tot,
            "notes": it.get("notes"),
            "label": f"{it.get('product_name')}{combo_label} x{qty} — {line_tot:.0f} EGP",
        })

    # Round final cart total to guard against floating point inaccuracies
    total = round(total, 2)
    return {
        "items": item_summaries,
        "total_price": total,
        "items_count": sum(it.get("quantity", 1) for it in items),
    }

def format_draft_summary(draft: dict[str, Any]) -> str:
    """Format full human-readable Markdown summary of the draft order."""
    calc = calculate_draft_totals(draft)
    order_type = draft.get("order_type") or "Not specified"
    type_display = {
        "delivery": "🚀 Delivery (توصيل)",
        "pickup": "🏬 Pickup (استلام من الفرع)",
        "dine_in": "🍽️ Dine-in (صالة المطعم)",
    }.get(order_type, order_type)

    lines = ["### 🧾 Order Summary\n"]
    lines.append(f"* **Order Type**: {type_display}")
    if draft.get("customer_name"):
        lines.append(f"* **Customer Name**: {draft['customer_name']}")
    if draft.get("customer_phone"):
        lines.append(f"* **Phone Number**: {draft['customer_phone']}")

    if order_type == "delivery":
        lines.append(f"* **Delivery Address**: {draft.get('delivery_address') or '*(Missing)*'}")
    elif order_type == "pickup":
        lines.append(f"* **Pickup Branch**: {draft.get('pickup_branch') or '*(Missing)*'}")
    elif order_type == "dine_in":
        lines.append(f"* **Table Number**: {draft.get('table_number') or '*(Missing)*'}")

    lines.append(f"* **Payment Method**: {draft.get('payment_method') or '*(Missing)*'}")
    lines.append("\n#### 🛒 Items:")
    if not calc["items"]:
        lines.append("* *(No items added yet)*")
    else:
        for it in calc["items"]:
            combo_note = f" *(+Combo: {it['combo_price']:.0f} EGP)*" if it["is_combo"] else ""
            notes_str = f" [{it['notes']}]" if it.get("notes") else ""
            lines.append(f"* **{it['name']}** x{it['quantity']}{combo_note}{notes_str} — {it['line_total']:.0f} EGP")

    lines.append(f"\n**Total Amount**: {calc['total_price']:.0f} EGP")
    return "\n".join(lines)

def update_draft(session_id: str, **kwargs) -> dict[str, Any]:
    """Update draft fields and return the updated draft."""
    draft = get_draft(session_id)
    old_type = draft.get("order_type")
    new_type = kwargs.get("order_type")

    # If order type changed, clear fields specific to other types
    if new_type and new_type != old_type:
        draft["order_type"] = new_type
        if new_type == "delivery":
            draft["pickup_branch"] = None
            draft["table_number"] = None
        elif new_type == "pickup":
            draft["delivery_address"] = None
            draft["table_number"] = None
        elif new_type == "dine_in":
            draft["delivery_address"] = None
            draft["pickup_branch"] = None

    for key, val in kwargs.items():
        if key == "order_type":
            continue
        if val is not None:
            draft[key] = val

    _save_draft_to_db(session_id, draft)
    return draft

@_with_app_context
def add_item_to_draft(session_id: str, product_name: str, quantity: int = 1, is_combo: bool = False, notes: str = "") -> dict[str, Any]:
    """
    Add or update an item in the session draft using database product metadata.
    Avoids duplicate entries for the exact same product and combo option by combining quantities.
    If the session previously completed and confirmed an order, clear the previous draft so
    the new order starts clean without old customer data bleeding through.
    """
    draft = get_draft(session_id)
    # If a prior order was already placed in this chat, start a fresh cart so old customer data does not bleed through
    if draft.get("stage") == "confirmed" or draft.get("confirmed_order_code"):
        clear_draft(session_id)
        draft = get_draft(session_id)

    p_clean = product_name.strip()
    alias_map = {
        "بيبسي": "مشروب",
        "pepsi": "مشروب",
        "cola": "مشروب",
        "drink": "مشروب",
        "water": "مياه",
    }
    p_clean = alias_map.get(p_clean.lower(), p_clean)
    product = Product.query.filter(Product.name.ilike(p_clean)).first()
    if not product:
        product = Product.query.filter(Product.name.ilike(f"%{p_clean}%")).first()

    if not product:
        return {"ok": False, "error": f"Product '{product_name}' not found."}

    # Block ordering out-of-stock items before adding to cart
    if not product.is_available:
        return {"ok": False, "error": f"Product '{product.name}' is currently out of stock."}

    # Only charge combo fees if the product has a configured combo upgrade price
    combo_fee = product.combo_price if (is_combo and product.combo_price) else 0.0
    actual_combo = bool(is_combo and combo_fee > 0)

    # Combine quantities if the customer orders the exact same item and combo tier again
    existing_item = None
    for it in draft["items"]:
        if it["product_name"] == product.name and it.get("is_combo") == actual_combo:
            existing_item = it
            break

    if existing_item:
        existing_item["quantity"] += max(1, quantity)
        if notes:
            existing_item["notes"] = f"{existing_item.get('notes', '')}, {notes}".strip(", ")
    else:
        draft["items"].append({
            "product_id": product.id,
            "product_name": product.name,
            "quantity": max(1, quantity),
            "unit_price": product.price,
            "is_combo": actual_combo,
            "combo_price": combo_fee,
            "notes": notes or None,
        })

    _save_draft_to_db(session_id, draft)
    return {"ok": True, "draft": draft, "calc": calculate_draft_totals(draft)}

def remove_item_from_draft(session_id: str, product_name: str) -> dict[str, Any]:
    """Remove item(s) matching product_name from draft."""
    draft = get_draft(session_id)
    initial_len = len(draft["items"])
    draft["items"] = [it for it in draft["items"] if product_name.strip().lower() not in it["product_name"].lower()]
    _save_draft_to_db(session_id, draft)
    return {"ok": True, "removed": initial_len - len(draft["items"]), "draft": draft}

@_with_app_context
def get_upsell_suggestions(draft: dict[str, Any]) -> dict[str, Any]:
    """
    Detects relevant available extras from menu data:
    - Meal combo upgrades (+50 EGP for fries & drink) for any meal without combo.
    - Popular drinks (Pepsi 20 EGP, Water 10 EGP) if no drink is in draft.
    - Popular sauces (Garlic dip, BBQ, Ranch, Cheddar 15 EGP) if no sauce is in draft.
    """
    items = draft.get("items", [])
    eligible_meals_for_combo = []
    has_drink = False
    has_sauce = False

    # Inspect current basket to avoid annoying customers by recommending items they already selected
    for item in items:
        prod = db.session.get(Product, item.get("product_id")) if item.get("product_id") else None
        cat = prod.category if prod else ""
        if cat == "Meals" and not item.get("is_combo") and prod and prod.combo_price and prod.combo_price > 0:
            eligible_meals_for_combo.append(item["product_name"])
        elif cat == "Drinks" or any(w in item["product_name"].lower() for w in ["drink", "مياه", "مشروب", "بيبسي"]):
            has_drink = True
        elif cat == "Sauces" or any(w in item["product_name"].lower() for w in ["ثومية", "صوص", "sauce"]):
            has_sauce = True

    needs_upsell = bool(eligible_meals_for_combo or not has_drink or not has_sauce)

    return {
        "needs_upsell": needs_upsell,
        "eligible_meals_for_combo": eligible_meals_for_combo,
        "suggest_combo": len(eligible_meals_for_combo) > 0,
        "suggest_drink": not has_drink,
        "suggest_sauce": not has_sauce,
    }

@_with_app_context
def upgrade_draft_combos(session_id: str, product_name: Optional[str] = None) -> dict[str, Any]:
    """
    Upgrade meal items in draft to combo (+50 EGP).
    If product_name is provided, upgrade only that product.
    If product_name is None, upgrade all eligible meals in the draft that do not already have combo.
    Prevents duplicate combo upgrades on the same item.
    """
    draft = get_draft(session_id)
    upgraded_count = 0
    for item in draft.get("items", []):
        if product_name and product_name.strip().lower() not in item["product_name"].lower():
            continue
        # Only upgrade meals that do not already have combo applied
        if not item.get("is_combo"):
            product = db.session.get(Product, item.get("product_id")) if item.get("product_id") else None
            if product and product.combo_price and product.combo_price > 0:
                item["is_combo"] = True
                item["combo_price"] = product.combo_price
                upgraded_count += 1
            elif item.get("combo_price", 0) > 0:
                item["is_combo"] = True
                upgraded_count += 1
    draft["upsell_offered"] = True
    draft["stage"] = "collecting_details"
    _save_draft_to_db(session_id, draft)
    return {"ok": True, "upgraded_count": upgraded_count, "draft": draft, "calc": calculate_draft_totals(draft)}

@_with_app_context
def commit_confirmed_order(session_id: str) -> dict[str, Any]:
    """
    Validate all required fields, persist customer and order to SQLite DB,
    and return the result.
    If required information is missing, refuse confirmation.
    If already confirmed, return the existing confirmation without duplicate creation.
    """
    draft = get_draft(session_id)

    # Idempotency guard: if already committed, return the existing order rather than creating a duplicate
    if draft.get("confirmed_order_code"):
        existing_order = Order.query.filter_by(order_code=draft["confirmed_order_code"]).first()
        if existing_order:
            return {
                "ok": True,
                "already_confirmed": True,
                "order_code": existing_order.order_code,
                "order_id": existing_order.id,
                "customer_name": existing_order.customer.name if existing_order.customer else None,
                "customer_phone": existing_order.customer.phone if existing_order.customer else None,
                "order_type": existing_order.order_type,
                "payment_method": existing_order.payment_method,
                "delivery_address": existing_order.delivery_address,
                "pickup_branch": existing_order.pickup_branch,
                "table_number": existing_order.table_number,
                "status": existing_order.status,
                "total_price": existing_order.total_price,
                "items": [it.to_dict() for it in existing_order.items],
            }

    if not draft.get("items"):
        return {
            "ok": False,
            "error": "Cannot confirm an empty order. Please select at least one item first.",
            "missing_fields": ["items"],
        }

    # Ensure customers make a decision on suggested extras before placing the final order
    if draft.get("stage") == "offering_extras":
        return {
            "ok": False,
            "error": "Cannot confirm order while offering extras. Please accept or decline extras first.",
        }

    missing = get_missing_fields(draft)
    if missing:
        return {
            "ok": False,
            "error": f"Cannot confirm order. Missing required information: {', '.join(missing)}.",
            "missing_fields": missing,
        }

    # 1. Persist or find Customer record: links the order to a canonical customer profile deduplicated by normalized phone
    customer_res = find_or_create_customer(
        name=draft["customer_name"],
        phone=draft["customer_phone"],
        address=draft["delivery_address"] if draft["order_type"] == "delivery" else "",
    )
    if not customer_res.get("ok"):
        return {"ok": False, "error": f"Customer creation failed: {customer_res.get('error')}"}

    customer_id = customer_res["id"]

    # 2. Prepare items for create_order: lock in line unit prices with combo fees included
    items_to_create = []
    for it in draft["items"]:
        items_to_create.append({
            "product_id": it.get("product_id"),
            "product_name": it["product_name"],
            "quantity": it["quantity"],
            "unit_price": it["unit_price"] + (it["combo_price"] if it.get("is_combo") else 0.0),
            "is_combo": it.get("is_combo", False),
            "notes": it.get("notes"),
        })

    # 3. Call create_order within transaction: generates unique ORD-XXXXX code and commits Order + OrderItems atomically
    order_res = create_order(
        customer_id=customer_id,
        items=items_to_create,
        order_type=draft["order_type"],
        payment_method=draft["payment_method"],
        delivery_address=draft.get("delivery_address") or "",
        pickup_branch=draft.get("pickup_branch") or "",
        table_number=draft.get("table_number") or "",
        status="In Kitchen",
    )

    if order_res.get("ok"):
        # Stamp confirmed order code and stage so session idempotency and status tracking are guaranteed
        draft["confirmed_order_code"] = order_res["order_code"]
        draft["stage"] = "confirmed"
        _save_draft_to_db(session_id, draft)

    return order_res