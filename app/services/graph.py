from typing import Any, TypedDict
import re
from langgraph.graph import END, StateGraph
from app.services.agent import get_history
from app.services.vector_store import retrieve
from app.services.tools import (
    search_products,
    track_order,
    recommend_products,
    query_price_info,
    _extract_order_code,
)
from app.services.order_session import (
    get_draft,
    clear_draft,
    calculate_draft_totals,
    get_missing_fields,
    format_draft_summary,
    commit_confirmed_order,
    parse_user_entities,
    get_upsell_suggestions,
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
    """
    Two-path router:
    - 'ordering': Placing an order, giving order details, confirmation, cancel, or tracking.
    - 'information': All customer inquiries (menu, recommendations, prices, policies, RAG).
    """
    text = (message or "").strip().lower()

    # 1. Order tracking: route to ordering so track_order tool can look up DB status
    tracking_signals = ("track", "status", "حالة", "تتبع", "where is my order", "where's my order", "فين طلبي", "وصل لفين")
    has_order_code = bool(_extract_order_code(message))
    if any(sig in text for sig in tracking_signals) or (has_order_code and ("order" in text or "طلب" in text)):
        return "ordering"

    # 2. Confirmation signals: route to ordering to validate required fields and commit
    confirm_signals = [
        "confirm", "place order", "submit order", "yes please",
        "تأكيد", "أكد", "تأكيد الطلب", "اكد الطلب", "اعتمد", "سجل الطلب", "نفذ الطلب"
    ]
    if any(sig in text for sig in confirm_signals):
        return "ordering"

    # Inspect active draft to contextualize short answers (e.g., "no", "yes", "cash")
    draft = get_draft(session_id) if session_id else {}
    has_active_draft = bool(draft.get("items") and draft.get("stage") != "confirmed")

    # 3. Upsell declines or accepts: prevent short answers like "no thanks" from routing to general info
    decline_signals = ["no", "no thanks", "no thank you", "none", "لا", "لا شكرا", "لا شكراً", "لا تمام", "تمام كده", "مش عايز", "مش عاوز", "كفاية", "بس كده"]
    combo_signals = ["make it combo", "make them combo", "add combo", "combo please", "upgrade to combo", "خليهم كومبو", "مع كومبو", "ضيف كومبو", "نعم كومبو", "عايز كومبو", "عاوز كومبو"]
    if has_active_draft:
        clean_text = text.strip(" .!?,")
        if (clean_text in decline_signals or any(clean_text == s for s in decline_signals) or any(clean_text.startswith(s + " ") for s in ["no", "no thanks", "لا", "لا شكرا"])) or any(sig in text for sig in combo_signals):
            return "ordering"

    # 4. Cancellation attempt: route to ordering where policy notice or draft clearing occurs
    if any(sig in text for sig in ("cancel", "إلغاء")):
        return "ordering"

    # Detect informational signals (questions about policies, menu, prices, recommendations, branches, hours)
    info_question_signals = [
        "what", "how", "where", "when", "why", "who", "which", "can i", "do you", "is there", "are there", "tell me",
        "menu", "price", "prices", "cost", "how much", "cheapest", "expensive", "under", "recommend", "suggest",
        "hours", "open", "close", "working hours", "branch", "branches", "location", "address of", "phone of",
        "ingredients", "contain", "include", "policy", "fee", "fees",
        "منيو", "قائمة", "سعر", "أسعار", "اسعار", "بكام", "تكلفة", "أرخص", "ارخص", "أغلى", "اغلى", "اقل من", "أقل من",
        "رشح", "اقتراح", "مواعيد", "شغالين", "بيفتح", "بيقفل", "ساعات العمل", "فروع", "فرعكم", "عنوان", "أين", "فين", "مكان",
        "مكونات", "يحتوي", "فيه", "رسوم", "سياسة", "مصاريف"
    ]
    is_explicit_info_query = any(sig in text for sig in info_question_signals) or "?" in text or "؟" in text

    # Explicit ordering verbs
    order_action_verbs = [
        "place an order", "create order", "i want to order", "order now", "عاوز أطلب", "عايز أطلب", "أطلب", "اطلب", "طلب أوردر",
        "i want", "i'd like", "give me", "bring me", "add", "عاوز", "عايز", "أريد", "اريد", "هاتلي", "ابعتلي", "وصل", "وصلني", "ضيف"
    ]
    has_order_action = any(v in text for v in order_action_verbs) or bool(re.search(r"\bdeliver\b", text))

    # Fulfillment detail mentions
    fulfillment_words = [
        "delivery", "delievery", "pickup", "dine in", "dine-in", "توصيل", "استلام", "صالة", "طاولة", "ترابيزة",
        "cash", "visa", "كاش", "فيزا"
    ]
    has_fulfillment_detail = any(w in text for w in fulfillment_words)

    # Check for phone number pattern or delivery address keyword
    has_phone = bool(re.search(r"(?:(?:\+?20)|0)?1[0125]\d{8}\b", text))
    has_address = bool("شارع" in text or "street" in text or "st." in text)

    # 4. If message has explicit ordering action or fulfillment details
    if has_order_action or has_phone or (has_fulfillment_detail and not is_explicit_info_query):
        return "ordering"

    # If user provided a fulfillment detail (like "delivery" or "cash") but combined with a question:
    # e.g., "Do you have delivery to Nasr City?" -> is_explicit_info_query is True -> routes to information!
    # e.g., "delivery please" -> has_fulfillment_detail is True, is_explicit_info_query is False -> routes to ordering!

    # 5. Active draft continuation
    if has_active_draft:
        # If the user is currently building an order and asks an informational question,
        # route to information so rag_node can answer, while preserving the draft in session.
        if is_explicit_info_query:
            return "information"
        # Otherwise, the user is answering a requested detail (name, address, table, etc.)
        return "ordering"

    # Default: Information & Questions path (handled by RAG + database knowledge)
    return "information"

def router_node(state: AgentState) -> AgentState:
    """Simple Router: Classifies message as 'ordering' or 'information'."""
    session_id = state.get("session_id", "default")
    message = state.get("message", "")
    state["intent"] = _route_intent(message, session_id=session_id)
    return state

def rag_node(state: AgentState) -> AgentState:
    """
    Unified Information Path (Path A):
    Handles all questions using:
    1. Deterministic price comparison calculations (cheapest, most expensive, under X EGP).
    2. Recommendations grounded in real product data.
    3. Full menu listings grouped by category from SQLite.
    4. Semantic RAG retrieval from ChromaDB knowledge base (branches, hours, policies, details).
    """
    from app.models.product import Product

    message = state.get("message", "")
    text_lower = (message or "").lower()
    pieces = []

    # 1. Deterministic price comparison questions (exact calculation in SQL prevents hallucinated math)
    price_info = query_price_info(message)
    if price_info.get("ok"):
        pieces.append(price_info.get("text", ""))
        state["context"] = "\n\n".join(pieces)
        state["tool_name"] = "query_price_info"
        state["tool_result"] = price_info
        return state

    # 2. Recommendation inquiries (grounded directly in available menu products)
    rec_signals = ["recommend", "suggest", "best", "hungry", "what should i get", "spicy", "ترشيح", "رشحلي", "اقتراح"]
    if any(sig in text_lower for sig in rec_signals):
        rec_result = recommend_products(message, limit=3)
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
                    lines.append("")
                else:
                    lines.append(f"* **{item['name']}** ({cat}) — {price:.0f} EGP")
            pieces.append("\n".join(lines).strip())
            state["context"] = "\n\n".join(pieces)
            state["tool_name"] = "recommend_products"
            state["tool_result"] = rec_result
            return state

    # 3. Specific 'All Meals' query: formatted from active DB records to reflect real-time stock
    if any(kw in text_lower for kw in ("all meals", "available meals", "what meals", "list meals", "show meals", "الوجبات", "كل الوجبات")):
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

    # 4. Full menu query: formatted into categorized sections with EGP pricing and combo rules
    is_menu_query = any(kw in text_lower for kw in ("menu", "can i see", "what do you have", "what's on", "show me", "منيو", "قائمة"))
    if is_menu_query:
        product_results = search_products("", limit=50)
        if product_results.get("ok") and product_results.get("items"):
            pieces.append(_format_menu_grouped(product_results["items"]))
            state["context"] = "\n\n".join(pieces)
            state["tool_name"] = "menu_listing"
            state["tool_result"] = {"ok": True, "count": product_results.get("count", 0)}
            return state

    # 5. Semantic RAG retrieval from ChromaDB: filters by score <= 0.72 to drop irrelevant noise
    hits = retrieve(message, top_k=4)
    relevant_hits = [h for h in hits if h.get("score") is None or h.get("score") <= 0.72]
    for hit in relevant_hits:
        content = hit.get("content") or ""
        if content.strip():
            pieces.append(content.strip())

    # Augment with live structured product details if query matches products in SQLite (handles custom DB items)
    product_results = search_products(message, limit=3)
    if product_results.get("ok") and product_results.get("items"):
        p_lines = []
        for item in product_results["items"]:
            price = item.get("price", 0.0)
            combo = item.get("combo_price", 0.0)
            cat = item.get("category", "")
            if cat == "Meals":
                includes = _format_meal_includes(item.get("description") or "")
                p_lines.append(f"**{item['name']} — {price:.0f} EGP**")
                if includes:
                    p_lines.append(f"* Includes: {includes}.")
                if combo and combo > 0:
                    p_lines.append(f"* Combo upgrade: +{combo:.0f} EGP for fries and a drink.")
                p_lines.append("")
            else:
                p_lines.append(f"* **{item['name']}** ({cat}) — {price:.0f} EGP")
        if p_lines:
            pieces.append("\n".join(p_lines).strip())

    # Explicit fallback prevents hallucination when query is unsupported or out-of-domain
    if not pieces:
        pieces.append("I don't have specific information for that request.")

    state["context"] = "\n\n".join(pieces)
    state["tool_name"] = "rag_knowledge"
    state["tool_result"] = {"hits_count": len(relevant_hits)}
    return state

def _is_confirmation_intent(text: str, draft: dict[str, Any]) -> bool:
    """Check if message represents an order confirmation intent."""
    t = (text or "").strip().lower()
    if not t:
        return False

    # Explicit confirmation keywords always trigger confirmation attempt
    explicit_confirm = [
        "confirm", "confirm order", "confirm last order", "confirm my order", "place order", "place the order", "place my order",
        "submit order", "submit my order", "complete order", "finish order",
        "yes confirm", "yes please place", "yes place order",
        "تأكيد", "أكد", "اعتمد", "سجل الطلب", "نفذ الطلب", "أكد الطلب", "اكد الطلب", "اعتمد الطلب", "تأكيد الطلب", "أكد أخر طلب", "اكد اخر طلب"
    ]
    if any(sig in t for sig in explicit_confirm):
        return True

    # Contextual confirmation: affirmative words only count when draft is ready and awaiting confirmation
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
    Order Operations Path (Path B):
    - Manages draft lifecycle: parses entities, adds items, calculates totals.
    - Conducts Guided Upselling before collecting customer fulfillment details.
    - Asks for missing required fields sequentially.
    - Validates and executes transactional order confirmation and tracking.
    - Handles mixed messages by retrieving RAG context if informational questions are present.
    """
    session_id = state.get("session_id", "default")
    message = state.get("message", "")
    text_lower = (message or "").strip().lower()

    # 1. Parse entities into draft
    parse_user_entities(session_id, message)
    draft = get_draft(session_id)

    result: dict = {"ok": True}
    context_lines = []

    # Mixed message support: If customer also asked an informational question (e.g. ingredients, prices, policies, branches)
    info_triggers = ["have", "contain", "ingredients", "what is", "how much", "price", "fee", "cost", "branch", "branches", "hours", "سعر", "مكونات", "فيه", "بكام", "فرع", "فروع", "مواعيد", "رسوم"]
    has_mixed_info = any(k in text_lower for k in info_triggers) or "?" in text_lower or "؟" in text_lower
    hits = []
    if has_mixed_info:
        hits = retrieve(message, top_k=3)
        if hits:
            context_lines.append("### ℹ️ Knowledge Base Context:\n" + "\n".join(h["content"] for h in hits))
            context_lines.append("IMPORTANT FOR MIXED INQUIRY: The customer asked a question alongside their order. You MUST directly answer their question using the Knowledge Base Context above, while also confirming their order draft.")

    # 2. Check for Order Tracking: look up real-time DB status by code and bypass LLM to prevent status hallucinations
    # (Exclude cancellation attempts so that requests to cancel a placed order are met with the non-cancellation policy notice)
    is_cancel_intent = any(k in text_lower for k in ("cancel", "إلغاء"))
    tracking_words = ["track", "status", "where is my order", "where's my order", "where is order", "where's order", "حالة", "تتبع", "وصل لفين", "جاهز", "فين طلبي"]
    explicit_code = _extract_order_code(message)
    target_code = explicit_code or draft.get("confirmed_order_code")
    is_tracking_inquiry = not is_cancel_intent and (any(k in text_lower for k in tracking_words) or bool(explicit_code))

    if is_tracking_inquiry:
        if target_code:
            track_res = track_order(order_code=target_code)
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
            resp_text = "Please provide your **Order Code** (e.g., `ORD-12345`) so I can retrieve the real-time status of your order from our database."
            state["tool_name"] = "track_order"
            state["tool_result"] = {"ok": False, "missing": "order_code"}
            state["response"] = resp_text
            state["context"] = resp_text
            return state

    # 3. Check for Cancellation attempt: placed orders cannot be cancelled once preparation begins
    if any(k in text_lower for k in ("cancel", "إلغاء")):
        order_code = _extract_order_code(message)
        if order_code or draft.get("confirmed_order_code"):
            resp_text = (
                "❌ **Order Cancellation is Not Supported**: "
                "Once an order has been confirmed and placed, it cannot be cancelled as preparation begins immediately in the kitchen. "
                "You can track your order status using your Order Code."
            )
            state["tool_name"] = "cancellation_notice"
            state["tool_result"] = {"ok": False, "error": "Order cancellation is not supported."}
            state["response"] = resp_text
            state["context"] = resp_text
            return state
        else:
            clear_draft(session_id)
            resp_text = "Your unconfirmed draft order has been cleared."
            state["tool_name"] = "clear_draft"
            state["tool_result"] = {"ok": True, "action": "draft_cleared"}
            state["response"] = resp_text
            state["context"] = resp_text
            return state

    # 4. Check for Confirmation: validate completeness before committing transaction to database
    if _is_confirmation_intent(message, draft):
        if not draft.get("items"):
            result = {"ok": False, "error": "Cannot confirm empty order."}
            state["tool_name"] = "confirm_order"
            state["tool_result"] = result
            state["response"] = "⚠️ Cannot confirm an empty order. Please select your desired meal first."
            state["context"] = state["response"]
            return state

        # Prevent premature confirmation during upselling stage until customer accepts or declines
        if draft.get("stage") == "offering_extras" and not draft.get("upsell_declined"):
            result = {"ok": False, "error": "Order still in upselling stage."}
            state["tool_name"] = "confirm_order"
            state["tool_result"] = result
            state["response"] = "Please first choose if you'd like to add combo upgrades, drinks, or sauces, then we will collect your details and confirm."
            state["context"] = state["response"]
            return state

        # Block confirmation if any fulfillment detail required by order_type is missing
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

        # All details valid: commit atomic transaction to SQLite DB and return authoritative code
        result = commit_confirmed_order(session_id)
        state["tool_name"] = "confirm_order"
        state["tool_result"] = result
        if result.get("ok"):
            resp = _format_confirmed_order_response(result, draft)
            # If customer asked a question while confirming, attach the answer to receipt
            if has_mixed_info and hits:
                kb_text = "\n".join(h["content"].strip() for h in hits[:2])
                resp += f"\n\n---\n### ℹ️ Additional Information:\n{kb_text}"
            state["response"] = resp
            state["context"] = state["response"]
        else:
            state["response"] = f"❌ Order placement failed: {result.get('error', 'Database error')}. Please try again."
            state["context"] = state["response"]
        return state

    # 5. Ongoing Draft Flow: Item Selection, Guided Upselling, & Details Collection
    calc = calculate_draft_totals(draft)
    context_lines.append(format_draft_summary(draft))

    if not draft.get("items"):
        draft["stage"] = "selecting_items"
        context_lines.append("\nCustomer has not added any items yet. Ask what meal they would like to order.")
    elif not draft.get("upsell_offered") and not draft.get("upsell_declined"):
        # Guided upselling: suggest combos, drinks, or sauces once before asking fulfillment details
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

    # 6. Sequential details collection: ask for only one missing field at a time for natural pacing
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
        # All required fields present: instruct LLM to present full summary and request explicit confirmation
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
    """Invokes Google Gemini with the grounded context prepared by RAG or order tools."""
    from app.services.agent import reply

    # If authoritative response was already generated deterministically (e.g. tracking/confirmation), bypass LLM
    if state.get("response"):
        session_id = state.get("session_id", "default")
        message = state.get("message", "")
        hist = get_history(session_id)
        # Record turn in conversational history so subsequent LLM calls have full context
        if message and state.get("response"):
            hist.append({"role": "user", "content": message})
            hist.append({"role": "assistant", "content": state["response"]})
        state["history"] = hist
        return state

    session_id = state.get("session_id", "default")
    message = state.get("message", "")
    context = state.get("context", "")
    response = reply(session_id=session_id, user_message=message, context=context)

    # Hallucination guard: intercept fake order numbers if LLM hallucinates confirmation without DB commit
    draft = get_draft(session_id)
    if not draft.get("confirmed_order_code") and (
        "ORD-" in response or "order has been placed" in response.lower() or "تم تأكيد طلبك" in response
    ):
        summary = format_draft_summary(draft)
        response = (
            f"{summary}\n\n"
            f"Please reply **confirm** (or **تأكيد**) to place your order!"
        )
        hist = get_history(session_id)
        if hist and hist[-1].get("role") == "assistant":
            hist[-1]["content"] = response

    state["response"] = response
    state["history"] = get_history(session_id)
    return state

def build_graph():
    """
    Builds the simplified 2-path LangGraph state machine:
    Router -> [rag OR order_tool] -> llm -> END
    """
    workflow = StateGraph(AgentState)
    workflow.add_node("router", router_node)
    workflow.add_node("rag", rag_node)
    workflow.add_node("order_tool", order_tool_node)
    workflow.add_node("llm", llm_node)

    workflow.set_entry_point("router")
    workflow.add_conditional_edges(
        "router",
        lambda state: state.get("intent", "information"),
        {
            "information": "rag",
            "ordering": "order_tool",
        },
    )
    workflow.add_edge("rag", "llm")
    workflow.add_edge("order_tool", "llm")
    workflow.add_edge("llm", END)
    return workflow.compile()

_graph = build_graph()

def run(session_id: str, message: str) -> dict:
    """Entry point invoked by Flask admin_chat route."""
    return _graph.invoke({
        "session_id": session_id,
        "message": message,
    })