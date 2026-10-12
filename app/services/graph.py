from typing import Any, TypedDict
import re

from langgraph.graph import END, StateGraph

from app.services.agent import get_history
from app.services.vector_store import retrieve
from app.services.tools import (
    search_products,
    find_or_create_customer,
    create_order,
    edit_order,
    cancel_order,
    track_order,
    tool_result_text,
    recommend_products,
    query_price_info,
    _extract_order_code,
)
from app.services.order_session import (
    get_draft,
    clear_draft,
    update_draft,
    add_item_to_draft,
    remove_item_from_draft,
    calculate_draft_totals,
    get_missing_fields,
    format_draft_summary,
    commit_confirmed_order,
    parse_user_entities,
    get_upsell_suggestions,
    upgrade_draft_combos,
    AVAILABLE_BRANCHES,
)


class AgentState(TypedDict, total=False):
    session_id: str
    message: str
    intent: str
    history: list[dict[str, Any]]
    response: str
    context: str
    tool_name: str
    tool_result: dict


def _format_meal_includes(desc: str) -> str:
    """Extract a clean, concise comma-separated list of items included in a meal."""
    if not desc:
        return ""
    translations = {
        "ورك فرخة بروستد": "Broasted chicken thigh",
        "نصف فرخة بروستد": "Half broasted chicken",
        "ثلاث قطع ستربس": "Three strips pieces",
        "خمس قطع ستربس": "Five strips pieces",
        "بطاطس": "fries",
        "خبز": "bread",
        "ثومية صغيرة": "garlic dip",
        "ثومية": "garlic dip",
        "كاتشب": "ketchup",
        "كول سلو": "coleslaw",
        "رز بسمتي": "Basmati rice",
        "أرز بسمتي": "Basmati rice",
        "ستربس": "strips",
    }
    raw_lines = [ln.strip().lstrip("-*•").strip() for ln in desc.splitlines() if ln.strip()]
    items = [ln for ln in raw_lines if not any(w in ln for w in ("تحتوي على", "يحتوي على", "وجبة"))]
    if not items:
        clean = desc.replace("\n", " ").strip()
        for pfx in (
            "وجبة ربع فرخة بروستد تحتوي على:", "وجبة ستربس 3 قطع تحتوي على:",
            "وجبة ستربس 5 قطع تحتوي على:", "وجبة بريك تحتوي على:",
            "الفتة تحتوي على:", "البسمتيو يحتوي على:",
        ):
            clean = clean.replace(pfx, "").strip()
        items = [i.strip() for i in clean.split("-") if i.strip()]
    cleaned_items = [translations.get(it.strip(" :-"), it.strip(" :-")) for it in items if it.strip(" :-")]
    return ", ".join(cleaned_items) if cleaned_items else desc.replace("\n", " ").strip()


def _format_menu_grouped(items: list[dict]) -> str:
    """Format menu products cleanly grouped by category with EGP prices and combo rules."""
    category_order = ["Meals", "Add-ons", "Sauces", "Drinks", "Extras"]
    category_titles = {
        "Meals": "🍗 Meals",
        "Add-ons": "➕ Add-ons",
        "Sauces": "🥫 Sauces",
        "Drinks": "🥤 Drinks",
        "Extras": "🍟 Extras",
    }
    grouped: dict[str, list[dict]] = {}
    for item in items:
        cat = item.get("category", "Extras")
        grouped.setdefault(cat, []).append(item)

    sections = ["### 📋 Our Menu\n"]

    ordered_cats = [c for c in category_order if c in grouped] + [c for c in grouped if c not in category_order]
    for cat in ordered_cats:
        title = category_titles.get(cat, f"📦 {cat}")
        sections.append(f"#### {title}\n")
        if cat == "Meals":
            for p in grouped[cat]:
                name = p.get("name", "")
                price = p.get("price", 0.0)
                combo = p.get("combo_price", 0.0)
                includes = _format_meal_includes(p.get("description") or "")
                sections.append(f"**{name} — {price:.0f} EGP**")
                if includes:
                    sections.append(f"* Includes: {includes}.")
                if combo and combo > 0:
                    sections.append(f"* Combo upgrade: +{combo:.0f} EGP for fries and a drink.")
                sections.append("")
        else:
            for p in grouped[cat]:
                name = p.get("name", "")
                price = p.get("price", 0.0)
                sections.append(f"* **{name}** — {price:.0f} EGP")
            sections.append("")

    return "\n".join(sections).strip()


def _route_intent(message: str, session_id: str = "") -> str:
    text = message.strip().lower()

    # Explicit order cancel / edit
    cancel_signals = ["cancel", "cancel my order", "cancel order", "إلغاء"]
    if any(signal in text for signal in cancel_signals):
        return "order_tool"

    edit_signals = ["edit", "change", "remove", "update", "تعديل"]
    if any(signal in text for signal in edit_signals):
        return "order_tool"

    # Order tracking / status inquiry
    tracking_signals = [
        "track order", "track my order", "order status", "status of my order", "status of my meal",
        "where is my order", "has my order been prepared", "is my order cancelled", "is my order ready",
        "where's my order", "what's the status", "check my order", "order state",
        "حالة الطلب", "حالة الأوردر", "حالة طلبي", "تتبع", "الطلب وصل لفين", "طلبي جاهز", "الطلب جاهز", "فين طلبي",
        "فين الأوردر", "أوردر اتلغى", "طلب اتلغى", "حالة الأكل",
    ]
    if any(signal in text for signal in tracking_signals):
        return "order_tool"

    # Confirmation keywords: "confirm", "confirm last order", "place order", "yes please", "تأكيد", "أكد الطلب"
    confirm_signals = [
        "confirm", "confirm order", "confirm last order", "confirm my order", "place order", "place the order", "place my order",
        "submit order", "yes confirm", "yes please",
        "تأكيد", "أكد", "تأكيد الطلب", "اكد الطلب", "اعتمد", "سجل الطلب", "نفذ الطلب"
    ]
    if any(signal in text for signal in confirm_signals):
        return "order_tool"

    # Decline keywords for upselling or offers: "no", "no thanks", "لا شكراً", etc.
    decline_signals = ["no", "no thanks", "no thank you", "none", "لا", "لا شكرا", "لا شكراً", "لا تمام", "تمام كده", "مش عايز", "مش عاوز", "كفاية"]
    if any(text == sig or text.startswith(sig + " ") for sig in decline_signals) and session_id:
        draft = get_draft(session_id)
        if draft.get("items"):
            return "order_tool"

    # Order summary
    summary_signals = ["summarize my order", "summarize order", "summary of my order", "order summary", "my order", "ملخص"]
    if any(signal in text for signal in summary_signals):
        return "order_tool"

    # Deterministic price comparison signals (Must take precedence over recommendation "cheap")
    price_signals = [
        "cheapest", "most expensive", "highest price", "lowest price",
        "less than", "under", "cost less", "price of each", "all meal prices",
        "أرخص", "ارخص", "أغلى", "اغلى", "أقل من", "اقل من", "تحت", "أسعار الوجبات", "سعر كل"
    ]
    if any(signal in text for signal in price_signals):
        return "restaurant_product"

    # Full menu / all meals queries
    menu_signals = [
        "menu", "full menu", "all meals", "available meals", "what meals", "list meals", "show meals",
        "منيو", "قائمة", "كل الوجبات", "الوجبات المتاحة", "قائمة الطعام"
    ]
    if any(signal in text for signal in menu_signals):
        return "restaurant_product"

    # Order creation / fulfillment detail signals
    order_signals = [
        "place an order", "create order", "i want to order", "order now", "عاوز أطلب", "أطلب", "طلب أوردر",
        "i want", "want", "عاوز", "عايز", "أريد", "هاتلي",
        "delivery", "delievery", "delivry", "deliver", "pickup", "dine in", "dine-in", "توصيل", "استلام", "صالة", "طاولة", "ترابيزة",
        "cash", "visa", "كاش", "فيزا",
    ]
    if any(signal in text for signal in order_signals):
        return "order_tool"

    # If the session already has items in draft, treat ongoing messages (giving details) as order flow
    if session_id:
        draft = get_draft(session_id)
        if draft.get("items"):
            # Check if user is answering a detail question
            return "order_tool"

    # Recommendations
    recommendation_signals = ["recommend", "suggest", "best", "hungry", "what should i get", "spicy", "ترشيح", "رشحلي", "اقتراح"]
    if any(signal in text for signal in recommendation_signals):
        return "recommendation"

    # Restaurant / Menu queries
    restaurant_signals = [
        "branch", "branches", "فروع", "فرع", "location", "address", "hour", "hours", "مواعيد",
        "food", "dish", "dishes", "price", "prices", "سعر", "أسعار",
        "shawarma", "pasta", "drink", "drinks", "broasted", "strips",
        "meal", "meals", "chicken", "sauce", "sauces", "add-on", "addon", "extras",
        "بروستد", "ستربس", "وجبة", "وجبات", "صوص", "صوصات", "إضافات",
        "can i see", "show me", "what do you have", "what's on", "list", "comes with", "what comes"
    ]
    if any(signal in text for signal in restaurant_signals):
        return "restaurant_product"

    return "general"


def router_node(state: AgentState) -> AgentState:
    session_id = state.get("session_id", "default")
    message = state.get("message", "")
    state["intent"] = _route_intent(message, session_id=session_id)
    return state


def recommendation_node(state: AgentState) -> AgentState:
    message = state.get("message", "")
    rec_result = recommend_products(message, limit=3)
    pieces = []
    if rec_result.get("ok") and rec_result.get("items"):
        lines = ["### 🌟 Recommended Options\n"]
        for item in rec_result["items"]:
            price = item.get("price", 0.0)
            combo = item.get("combo_price", 0.0)
            cat = item.get("category", "")
            if cat == "Meals":
                includes = _format_meal_includes(item.get("description") or "")
                lines.append(f"**{item['name']} — {price:.0f} EGP**")
                if includes:
                    lines.append(f"* Includes: {includes}.")
                if combo and combo > 0:
                    lines.append(f"* Combo upgrade: +{combo:.0f} EGP for fries and a drink.")
                sections.append("") if False else None
                lines.append("")
            else:
                lines.append(f"* **{item['name']}** ({cat}) — {price:.0f} EGP")
        pieces.append("\n".join(lines).strip())

    if not pieces:
        pieces.append("I couldn't find a suitable recommendation right now.")

    state["context"] = "\n\n".join(pieces)
    state["tool_name"] = "recommend_products"
    state["tool_result"] = rec_result
    return state


def rag_node(state: AgentState) -> AgentState:
    from app.models.product import Product

    message = state.get("message", "")
    text_lower = message.lower()
    pieces = []

    # 1. Deterministic Price Comparison Queries
    price_info = query_price_info(message)
    if price_info.get("ok"):
        pieces.append(price_info.get("text", ""))
        state["context"] = "\n\n".join(pieces)
        state["tool_name"] = "query_price_info"
        state["tool_result"] = price_info
        return state

    # 2. Specific "All Meals" query
    is_meals_query = any(kw in text_lower for kw in (
        "all meals", "available meals", "what meals", "list meals", "show meals", "الوجبات", "كل الوجبات"
    ))
    if is_meals_query:
        meals = Product.query.filter(Product.category == "Meals", Product.is_available == True).order_by(Product.price.asc()).all()
        lines = ["### 🍗 Available Meals\n"]
        for m in meals:
            includes = _format_meal_includes(m.description or "")
            lines.append(f"**{m.name} — {m.price:.0f} EGP**")
            if includes:
                lines.append(f"* Includes: {includes}.")
            if m.combo_price and m.combo_price > 0:
                lines.append(f"* Combo upgrade: +{m.combo_price:.0f} EGP for fries and a drink.")
            lines.append("")
        pieces.append("\n".join(lines).strip())
        state["context"] = "\n\n".join(pieces)
        state["tool_name"] = "list_meals"
        state["tool_result"] = {"ok": True, "count": len(meals)}
        return state

    # 3. Menu/listing queries: return ALL products grouped into categories
    is_menu_query = any(kw in text_lower for kw in (
        "menu", "can i see", "what do you have", "what's on",
        "show me", "i want to see", "list", "available", "منيو", "قائمة",
    ))
    is_sauce_query = any(kw in text_lower for kw in ("sauce", "sauces", "صوص", "صوصات", "الصوصات"))
    is_addon_query = any(kw in text_lower for kw in ("add-on", "addon", "addons", "side", "sides", "إضافة", "إضافات"))

    # 4. Restaurant knowledge queries: use RAG retrieval (hours, branches, policies, etc.)
    is_knowledge_query = any(kw in text_lower for kw in (
        "hour", "open", "close", "branch", "location", "address",
        "policy", "delivery", "payment", "visa", "cash",
        "area", "region", "where", "find", "contact",
        "phone", "social", "facebook", "مواعيد", "فروع", "توصيل",
    ))

    if is_knowledge_query:
        hits = retrieve(message, top_k=3)
        for hit in hits:
            content = hit.get("content") or ""
            if content.strip():
                pieces.append(content.strip())

    if is_menu_query:
        product_results = search_products("", limit=50)
        if product_results.get("ok") and product_results.get("items"):
            pieces.append(_format_menu_grouped(product_results["items"]))
    elif is_sauce_query:
        product_results = search_products("sauce", limit=20)
        if product_results.get("ok") and product_results.get("items"):
            lines = ["### 🥫 Our Sauces\n"]
            for item in product_results["items"]:
                price = item.get("price", 0.0)
                lines.append(f"* **{item['name']}** — {price:.0f} EGP")
            pieces.append("\n".join(lines))
    elif is_addon_query:
        product_results = search_products("add-on", limit=20)
        if product_results.get("ok") and product_results.get("items"):
            lines = ["### ➕ Our Add-ons & Sides\n"]
            for item in product_results["items"]:
                price = item.get("price", 0.0)
                lines.append(f"* **{item['name']}** — {price:.0f} EGP")
            pieces.append("\n".join(lines))
    elif not is_knowledge_query:
        product_results = search_products(message, limit=5)
        if product_results.get("ok") and product_results.get("items"):
            lines = []
            for item in product_results["items"]:
                price = item.get("price", 0.0)
                combo = item.get("combo_price", 0.0)
                cat = item.get("category", "")
                if cat == "Meals":
                    includes = _format_meal_includes(item.get("description") or "")
                    lines.append(f"**{item['name']} — {price:.0f} EGP**")
                    if includes:
                        lines.append(f"* Includes: {includes}.")
                    if combo and combo > 0:
                        lines.append(f"* Combo upgrade: +{combo:.0f} EGP for fries and a drink.")
                    lines.append("")
                else:
                    lines.append(f"* **{item['name']}** ({cat}) — {price:.0f} EGP")
            pieces.append("\n".join(lines).strip())

    if not pieces:
        pieces.append("I don't have specific information for that request.")

    state["context"] = "\n\n".join(pieces)
    return state


def _is_confirmation_intent(text: str, draft: dict[str, Any]) -> bool:
    """Check if message represents an order confirmation intent.
    Matches explicit confirmation phrases anytime, or natural affirmative responses
    when the draft order is awaiting confirmation or all required fields are present.
    """
    t = (text or "").strip().lower()
    if not t:
        return False

    explicit_confirm = [
        "confirm", "confirm order", "confirm last order", "confirm my order", "place order", "place the order", "place my order",
        "submit order", "submit my order", "complete order", "finish order",
        "yes confirm", "yes please place", "yes place order",
        "تأكيد", "أكد", "اعتمد", "سجل الطلب", "نفذ الطلب", "أكد الطلب", "اكد الطلب", "اعتمد الطلب", "تأكيد الطلب", "أكد أخر طلب", "اكد اخر طلب"
    ]
    if any(sig in t for sig in explicit_confirm):
        return True

    # When the draft is already awaiting confirmation or has items with no missing fields
    is_awaiting = draft.get("stage") == "awaiting_confirmation"
    has_items = bool(draft.get("items"))
    missing = get_missing_fields(draft) if has_items else ["items"]
    if is_awaiting or (has_items and not missing):
        words = set(re.findall(r"[\w]+", t))
        affirmative_tokens = {
            "yes", "yeah", "yep", "sure", "ok", "okay", "proceed",
            "تمام", "أيوة", "ايوة", "نعم", "موافق", "ماشي", "اه", "أه", "أكيد", "اكيد"
        }
        if any(w in affirmative_tokens for w in words):
            return True
        if any(t.startswith(prefix) for prefix in ("yes", "ok", "okay", "تمام", "أيوة", "ايوة", "نعم", "موافق", "اه", "أه")):
            return True

    return False


def _format_confirmed_order_response(result: dict[str, Any], draft: dict[str, Any]) -> str:
    """Format the authoritative confirmed order message strictly using persisted database data."""
    order_code = result.get("order_code") or draft.get("confirmed_order_code", "UNKNOWN")
    calc = calculate_draft_totals(draft)
    order_type = result.get("order_type") or draft.get("order_type", "")
    type_display = {
        "delivery": "🚀 Delivery (توصيل)",
        "pickup": "🏬 Pickup (استلام من الفرع)",
        "dine_in": "🍽️ Dine-in (صالة المطعم)",
    }.get(order_type, order_type)

    customer_name = result.get("customer_name") or draft.get("customer_name", "")
    customer_phone = result.get("customer_phone") or draft.get("customer_phone", "")
    payment_method = result.get("payment_method") or draft.get("payment_method", "")
    status = result.get("status", "In Kitchen")

    lines = [
        "🎉 **Your order has been placed successfully!**\n",
        f"📋 **Order Code**: `{order_code}`",
        f"👤 **Customer**: {customer_name}",
        f"📞 **Phone**: {customer_phone}",
        f"📦 **Order Type**: {type_display}",
    ]

    addr = result.get("delivery_address") or draft.get("delivery_address")
    branch = result.get("pickup_branch") or draft.get("pickup_branch")
    table = result.get("table_number") or draft.get("table_number")
    if addr:
        lines.append(f"📍 **Delivery Address**: {addr}")
    elif branch:
        lines.append(f"🏬 **Pickup Branch**: {branch}")
    elif table:
        lines.append(f"🍽️ **Table Number**: {table}")

    lines.append(f"💳 **Payment Method**: {payment_method}")
    lines.append(f"Status: **{status}**\n")

    lines.append("#### 🛒 Order Items:")
    items = result.get("items")
    if items:
        for it in items:
            p_name = it.get("product_name", "")
            qty = it.get("quantity", 1)
            unit_p = it.get("unit_price", 0.0)
            combo_str = " *(Combo)*" if it.get("is_combo") else ""
            notes_str = f" [{it['notes']}]" if it.get("notes") else ""
            lines.append(f"* **{p_name}**{combo_str} x{qty}{notes_str} — {unit_p * qty:.0f} EGP")
    else:
        for it in calc.get("items", []):
            combo_str = " *(Combo)*" if it.get("is_combo") else ""
            notes_str = f" [{it['notes']}]" if it.get("notes") else ""
            lines.append(f"* **{it['name']}**{combo_str} x{it['quantity']}{notes_str} — {it['line_total']:.0f} EGP")

    total = result.get("total_price", calc.get("total_price", 0.0))
    lines.append(f"\n**Total Amount**: {total:.0f} EGP\n")
    lines.append(f"Thank you for choosing our restaurant! You can track your order status anytime using order code `{order_code}`.")
    return "\n".join(lines)


def order_tool_node(state: AgentState) -> AgentState:
    """
    Intelligent Order Tool Node:
    - Parses conversational entities (order type, customer name, phone, destination, payment).
    - Maintains the session's active draft order.
    - Conducts Guided Upselling (combo upgrades, drinks, sauces) before customer info collection.
    - Handles final confirmation and commits to SQLite DB.
    - Asks only for missing required fields one at a time.
    """
    session_id = state.get("session_id", "default")
    message = state.get("message", "")
    text_lower = message.strip().lower()

    # 1. Parse entities from the current message into the session draft
    parse_user_entities(session_id, message)
    draft = get_draft(session_id)

    result: dict = {"ok": True}
    context_lines = []

    # 2. Check for Order Tracking / Status Inquiry
    tracking_words = [
        "track", "status", "where is my order", "where's my order", "has my order",
        "is my order", "حالة", "تتبع", "وصل لفين", "جاهز", "فين طلبي", "فين الأوردر",
    ]
    is_tracking_inquiry = any(k in text_lower for k in tracking_words)
    explicit_code = _extract_order_code(message)
    target_code = explicit_code or draft.get("confirmed_order_code")

    if is_tracking_inquiry:
        if target_code:
            phone_val = draft.get("customer_phone")
            track_res = track_order(order_code=target_code, phone=phone_val)
            if track_res.get("ok"):
                cur_status = track_res.get("status", "Unknown")
                c_name = track_res.get("customer_name") or "Valued Customer"
                total_val = track_res.get("total_price", 0.0)
                status_expl = {
                    "In Kitchen": "Being prepared in our kitchen right now 👨‍🍳🔥",
                    "Ready": "Ready for pickup or handover! 📦✨",
                    "Delivered": "Delivered successfully! Enjoy your meal! 🎉🚀",
                    "Cancelled": "Cancelled. ❌",
                }.get(cur_status, cur_status)

                resp_text = (
                    f"### 📍 Order Status: `{target_code}`\n\n"
                    f"* **Current Status**: **{cur_status}** ({status_expl})\n"
                    f"* **Customer**: {c_name}\n"
                    f"* **Order Total**: {total_val:.0f} EGP\n\n"
                    f"Our database reflects the latest real-time status of your order."
                )
                state["tool_name"] = "track_order"
                state["tool_result"] = track_res
                state["response"] = resp_text
                state["context"] = resp_text
                return state
            else:
                err_msg = track_res.get("error", "Order not found.")
                resp_text = f"❌ {err_msg} Please double-check your order code."
                state["tool_name"] = "track_order"
                state["tool_result"] = track_res
                state["response"] = resp_text
                state["context"] = resp_text
                return state
        else:
            resp_text = (
                "Please provide your **Order Code** (e.g., `ORD-12345`) so I can retrieve "
                "the real-time status of your order from our database."
            )
            state["tool_name"] = "track_order"
            state["tool_result"] = {"ok": False, "missing": "order_code"}
            state["response"] = resp_text
            state["context"] = resp_text
            return state

    # 3. Check for Cancel Order
    if any(k in text_lower for k in ("cancel", "إلغاء")):
        order_code = _extract_order_code(message)
        phone = draft.get("customer_phone") or ""
        if order_code and phone:
            result = cancel_order(order_code=order_code, phone=phone)
            context_lines.append(tool_result_text(result))
        else:
            clear_draft(session_id)
            context_lines.append("Your draft order has been cancelled.")
        state["tool_name"] = "cancel_order"
        state["tool_result"] = result
        state["context"] = "\n\n".join(context_lines)
        return state

    # 3. Check for Confirmation
    if _is_confirmation_intent(message, draft):
        if not draft.get("items"):
            result = {"ok": False, "error": "Cannot confirm empty order."}
            state["tool_name"] = "confirm_order"
            state["tool_result"] = result
            state["response"] = "⚠️ Cannot confirm an empty order. Please select your desired meal first."
            state["context"] = state["response"]
            return state

        if draft.get("stage") == "offering_extras" and not draft.get("upsell_declined"):
            result = {"ok": False, "error": "Order still in upselling stage."}
            state["tool_name"] = "confirm_order"
            state["tool_result"] = result
            state["response"] = "Please first choose if you'd like to add combo upgrades, drinks, or sauces, then we will collect your details and confirm."
            state["context"] = state["response"]
            return state

        missing = get_missing_fields(draft)
        if missing:
            result = {
                "ok": False,
                "error": f"Cannot confirm order. Missing required information: {', '.join(missing)}.",
                "missing_fields": missing,
            }
            state["tool_name"] = "confirm_order"
            state["tool_result"] = result
            state["response"] = (
                f"⚠️ Cannot confirm order yet. We still need some required information:\n\n"
                f"{format_draft_summary(draft)}\n\n"
                f"Please provide your **{missing[0].replace('_', ' ')}**."
            )
            state["context"] = state["response"]
            return state

        result = commit_confirmed_order(session_id)
        state["tool_name"] = "confirm_order"
        state["tool_result"] = result
        if result.get("ok"):
            state["response"] = _format_confirmed_order_response(result, draft)
            state["context"] = state["response"]
        else:
            state["response"] = f"❌ Order placement failed: {result.get('error', 'Database error')}. Please try again."
            state["context"] = state["response"]
        return state

    # 4. Draft Ongoing Flow: Item Selection, Guided Upselling, & Details Collection
    calc = calculate_draft_totals(draft)
    context_lines.append(format_draft_summary(draft))

    if not draft.get("items"):
        draft["stage"] = "selecting_items"
        context_lines.append("\nCustomer has not added any items yet. Ask what meal they would like to order.")
    elif not draft.get("upsell_offered") and not draft.get("upsell_declined"):
        suggestions = get_upsell_suggestions(draft)
        if suggestions.get("needs_upsell"):
            draft["stage"] = "offering_extras"
            draft["upsell_offered"] = True

            offer_parts = []
            if suggestions.get("suggest_combo"):
                offer_parts.append("Combo upgrade (+50 EGP for French fries and a soft drink)")
            if suggestions.get("suggest_drink"):
                offer_parts.append("Cold drinks (Pepsi 20 EGP, Water 10 EGP)")
            if suggestions.get("suggest_sauce"):
                offer_parts.append("Sauces (Garlic dip, BBQ, Ranch, Sweet Chili, Cheddar 15 EGP)")

            context_lines.append(
                f"\n💡 Guided Upselling Stage:\n"
                f"Present the current draft order to the customer. Then ask if they would like to add any extras before proceeding:\n"
                f"- " + "\n- ".join(offer_parts) + "\n"
                f"(If they say 'no' or decline, we will proceed directly to fulfillment details. Do NOT pressure the customer)."
            )
            state["tool_name"] = "order_upsell"
            state["tool_result"] = {"ok": True, "draft": draft, "calc": calc, "stage": "offering_extras"}
            state["context"] = "\n\n".join(context_lines)
            return state
        else:
            draft["stage"] = "collecting_details"

    # 5. Missing fulfillment details collection
    missing = get_missing_fields(draft)
    if missing:
        draft["stage"] = "collecting_details"
        field_names = {
            "order_type": "Order Type (هل تحب التوصيل Delivery، الاستلام من الفرع Pickup، أم الصالة Dine-in؟)",
            "customer_name": "Customer Name (الاسم)",
            "customer_phone": "Phone Number (رقم الهاتف)",
            "delivery_address": "Full Delivery Address (العنوان بالتفصيل: المنطقة، الشارع، العمارة، الشقة)",
            "pickup_branch": f"Pickup Branch (اختر فرع الاستلام من: {', '.join(AVAILABLE_BRANCHES[:5])})",
            "table_number": "Table Number (رقم الطاولة / الترابيزة)",
            "payment_method": "Payment Method (طريقة الدفع: Cash كاش أو Visa فيزا)",
        }
        first_missing = missing[0]
        context_lines.append(f"\nNext required information to ask for: {field_names.get(first_missing, first_missing)}. Ask for this field clearly.")
    else:
        # All required details complete!
        draft["stage"] = "awaiting_confirmation"
        context_lines.append(
            "\nAll required order details are complete! Present the final order summary with itemized prices, "
            "combo upgrades, destination, payment method, and final total in EGP. "
            "Ask the customer to explicitly confirm their order ('confirm' / 'تأكيد' / 'yes').\n"
            "CRITICAL: Do NOT state that the order has been placed or invent an order code yet. "
            "The order is NOT confirmed until the customer replies to confirm."
        )

    state["tool_name"] = "order_draft"
    state["tool_result"] = {
        "ok": True,
        "draft": draft,
        "calc": calc,
        "stage": draft.get("stage"),
        "missing_fields": missing,
    }
    state["context"] = "\n\n".join(context_lines)
    return state


def llm_node(state: AgentState) -> AgentState:
    from app.services.agent import reply

    # If authoritative response already generated by deterministic tool node
    if state.get("response"):
        session_id = state.get("session_id", "default")
        state["history"] = get_history(session_id)
        return state

    session_id = state.get("session_id", "default")
    message = state.get("message", "")
    context = state.get("context", "")
    response = reply(session_id=session_id, user_message=message, context=context)

    # Hallucination guard: prevent LLM from fabricating order numbers without a DB commit
    draft = get_draft(session_id)
    if not draft.get("confirmed_order_code") and (
        "ORD-" in response or "order has been placed" in response.lower() or "تم تأكيد طلبك" in response
    ):
        summary = format_draft_summary(draft)
        response = (
            f"{summary}\n\n"
            f"Please reply **confirm** (or **تأكيد**) to place your order!"
        )

    state["response"] = response
    state["history"] = get_history(session_id)
    return state


def output_node(state: AgentState) -> AgentState:
    return state


def build_graph():
    workflow = StateGraph(AgentState)
    workflow.add_node("router", router_node)
    workflow.add_node("recommendation", recommendation_node)
    workflow.add_node("rag", rag_node)
    workflow.add_node("order_tool", order_tool_node)
    workflow.add_node("llm", llm_node)
    workflow.add_node("output", output_node)

    workflow.set_entry_point("router")
    workflow.add_conditional_edges(
        "router",
        lambda state: state.get("intent", "general"),
        {
            "general": "llm",
            "restaurant_product": "rag",
            "recommendation": "recommendation",
            "order_tool": "order_tool",
            "future_tool_request": "order_tool",
        },
    )
    workflow.add_edge("recommendation", "llm")
    workflow.add_edge("rag", "llm")
    workflow.add_edge("order_tool", "llm")
    workflow.add_edge("llm", "output")
    workflow.add_edge("output", END)
    return workflow.compile()


_graph = build_graph()


def run(session_id: str, message: str) -> dict:
    return _graph.invoke({
        "session_id": session_id,
        "message": message,
    })
