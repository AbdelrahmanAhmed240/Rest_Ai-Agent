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
    """Format meal ingredients as a comma-separated list."""
    if not desc:
        return ""

    translations = {
        "ورك فرخة بروستد": "Broasted chicken thigh",
        "نصف فرخة بروستد": "Half broasted chicken",
        "ثلاث قطع ستربس": "Three strips pieces",
        "خمس قطع ستربس": "Five strips pieces",
        "بطاطس": "Fries",
        "خبز": "Bread",
        "ثومية صغيرة": "Garlic dip",
        "ثومية": "Garlic dip",
        "كاتشب": "Ketchup",
        "كول سلو": "Coleslaw",
        "رز بسمتي": "Basmati rice",
        "أرز بسمتي": "Basmati rice",
        "ستربس": "Strips",
    }

    items = []
    for line in desc.splitlines():
        item = line.strip().lstrip("-*• ").strip()

        if item and not any(word in item for word in ["تحتوي على", "يحتوي على", "وجبة"]):
            items.append(translations.get(item.strip(" :-"), item.strip(" :-")))

    return ", ".join(items) if items else desc.replace("\n", " ").strip()

def _format_menu_grouped(items: list[dict]) -> str:
    """Format menu items grouped by category."""
    order = ["Meals", "Add-ons", "Sauces", "Drinks", "Extras"]
    emojis = {
        "Meals": "🍗", "Add-ons": "➕", "Sauces": "🥫",
        "Drinks": "🥤", "Extras": "🍟",
    }

    grouped = {}
    for item in items:
        category = item.get("category") or "Extras"
        grouped.setdefault(category, []).append(item)

    sections = ["### 📋 Our Menu"]

    categories = [c for c in order if c in grouped]
    categories += [c for c in grouped if c not in order]

    for category in categories:
        sections.append(f"\n#### {emojis.get(category, '📦')} {category}")

        for item in grouped[category]:
            name = item.get("name", "")
            price = item.get("price") or 0
            sections.append(f"* **{name} — {price:.0f} EGP**" if category == "Meals"
                            else f"* **{name}** — {price:.0f} EGP")

            if category == "Meals":
                includes = _format_meal_includes(item.get("description") or "")
                combo = item.get("combo_price") or 0

                if includes:
                    sections.append(f"  * Includes: {includes}.")
                if combo > 0:
                    sections.append(
                        f"  * Combo upgrade: +{combo:.0f} EGP for fries and a drink."
                    )

    return "\n".join(sections)

def _format_product_item_lines(items: list[Any]) -> list[str]:
    """Format structured product details consistently across recommendations, meal listings, and queries."""
    lines = []
    for item in items:
        name = getattr(item, "name", None) or (item.get("name") if isinstance(item, dict) else "")
        price = getattr(item, "price", 0.0) if hasattr(item, "price") else (item.get("price", 0.0) if isinstance(item, dict) else 0.0)
        combo = getattr(item, "combo_price", 0.0) if hasattr(item, "combo_price") else (item.get("combo_price", 0.0) if isinstance(item, dict) else 0.0)
        cat = getattr(item, "category", "") if hasattr(item, "category") else (item.get("category", "") if isinstance(item, dict) else "")
        desc = getattr(item, "description", "") if hasattr(item, "description") else (item.get("description", "") if isinstance(item, dict) else "")
        if cat == "Meals":
            includes = _format_meal_includes(desc or "")
            lines.append(f"**{name} — {price:.0f} EGP**")
            if includes:
                lines.append(f"* Includes: {includes}.")
            if combo and combo > 0:
                lines.append(f"* Combo upgrade: +{combo:.0f} EGP for fries and a drink.")
            lines.append("")
        else:
            lines.append(f"* **{name}** ({cat}) — {price:.0f} EGP")
    return lines

def _route_intent(message: str, session_id: str = "") -> str:
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
    has_active_draft = bool((draft.get("items") or draft.get("order_type")) and draft.get("stage") != "confirmed")

    # 3. Upsell declines or accepts: prevent short answers like "no thanks" from routing to general info
    decline_signals = ["no", "no thanks", "no thank you", "none", "لا", "لا شكرا", "لا شكراً", "لا تمام", "تمام كده", "مش عايز", "مش عاوز", "كفاية", "بس كده"]
    combo_signals = ["make it combo", "make them combo", "add combo", "combo please", "upgrade to combo", "خليهم كومبو", "مع كومبو", "ضيف كومبو", "نعم كومبو", "عايز كومبو", "عاوز كومبو"]
    if has_active_draft:
        clean_text = text.strip(" .!?,")
        if (clean_text in decline_signals or any(clean_text.startswith(s + " ") for s in ["no", "no thanks", "لا", "لا شكرا"])) or any(sig in text for sig in combo_signals):
            return "ordering"

    # 4. Cancellation attempt: route to ordering where policy notice or draft clearing occurs
    if any(sig in text for sig in ("cancel", "إلغاء", "الغاء", "الغي", "كنسل")):
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

    # Menu item mentions without question mark or price words indicate intent to add food
    menu_item_signals = (
        "بسمتيو", "بروستد", "ستربس", "بريك", "فتة", "بطاطس", "أرز", "رز", "ثومية", "كول سلو",
        "باربكيو", "شيدر", "رانش", "سويت تشيلي", "مشروب", "بيبسي", "مياه", "شريطي",
        "basmatio", "basmetio", "cheddar", "cheder", "strips", "broasted", "fatta", "fries", "coleslaw"
    )
    has_menu_item = any(item in text for item in menu_item_signals)

    # Check for phone number pattern or delivery address keyword
    has_phone = bool(re.search(r"(?:(?:\+?20)|0)?1[0125]\d{8}\b", text))
    has_address = bool("شارع" in text or "street" in text or "st." in text)

    # 4. If message has explicit ordering action, menu item, or fulfillment details
    if has_order_action or has_phone or ((has_fulfillment_detail or has_menu_item) and not is_explicit_info_query):
        return "ordering"

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
            lines = ["### 🌟 Recommended Options\n"] + _format_product_item_lines(rec_result["items"])
            pieces.append("\n".join(lines).strip())
            state["context"] = "\n\n".join(pieces)
            state["tool_name"] = "recommend_products"
            state["tool_result"] = rec_result
            return state

    # 3. Specific 'All Meals' query: formatted from active DB records to reflect real-time stock
    if any(kw in text_lower for kw in ("all meals", "available meals", "what meals", "list meals", "show meals", "الوجبات", "كل الوجبات")):
        meals = Product.query.filter(Product.category == "Meals", Product.is_available == True).order_by(Product.price.asc()).all()
        lines = ["### 🍗 Available Meals\n"] + _format_product_item_lines(meals)
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

    # 5. Semantic RAG retrieval from ChromaDB: filters by score <= 0.80 to capture relevant matches
    hits = retrieve(message, top_k=4)
    relevant_hits = [h for h in hits if h.get("score") is None or h.get("score") <= 0.80]
    for hit in relevant_hits:
        content = hit.get("content") or ""
        if content.strip():
            pieces.append(content.strip())

    # Detect questions about ordering capability (e.g. "can I order from here?", "ممكن اطلب من هنا؟")
    order_inquiry_patterns = [
        r"\b(?:can\s*i\s*order|how\s*(?:can\s*i|do\s*i|to)\s*order|order\s*(?:from\s*here|online|here)|is\s*ordering\s*available)\b",
        r"(?:ممكن\s*اطلب|اقدر\s*اطلب|ينفع\s*اطلب|عايز\s*اطلب\s*من\s*هنا|عاوز\s*اطلب\s*من\s*هنا|الطلب\s*متاح)",
    ]
    if any(re.search(pat, text_lower) for pat in order_inquiry_patterns):
        ordering_info = (
            "### 🍽️ Ordering Availability:\n"
            "* Yes, ordering is available! Customers can place food orders directly through this chat.\n"
            "* Service options: Delivery (all Cairo areas, 30-45 minutes, 25 EGP delivery fee, Cash on delivery), Pickup (from our branches), or Dine-in.\n"
            "* Customers can view our menu or tell us the items they would like to order."
        )
        pieces.append(ordering_info)

    # Augment with live structured product details if query matches products in SQLite (handles custom DB items)
    product_results = search_products(message, limit=3)
    if product_results.get("ok") and product_results.get("items"):
        p_lines = _format_product_item_lines(product_results["items"])
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
    """
    Check if message represents an unambiguous order confirmation intent.
    Strictly blocks confirmations containing negations, modifications, questions, or conditional words.
    """
    t = (text or "").strip().lower()
    if not t:
        return False

    # 1. Immediate Guards: Any question mark, negation, or modification intent blocks confirmation
    if "?" in t or "؟" in t:
        return False

    # Negation indicators (English & Arabic) e.g. "don't confirm", "not yet", "مش عايز اكد"
    negation_patterns = [
        r"\b(?:don'?t|do not|not|never|no|stop|wait|hold|delay)\b",
        r"(?:مش|لا|بلاش|متأكدش|متاكدش|ما تأكدش|ما تاكدش|استنى|استني|لحظة|ثانية|مهلا|توقف)\b",
    ]
    if any(re.search(pat, t) for pat in negation_patterns):
        return False

    # Modification or conditional indicators (e.g. "okay, but change my address", "تمام بس عدل")
    modification_patterns = [
        r"\b(?:but|however|change|modify|update|remove|delete|cancel|replace|instead|except)\b",
        r"(?:بس|لكن|غير|عدل|احذف|شيل|امسح|بدل|ما عدا|إلا|الا)\b",
    ]
    if any(re.search(pat, t) for pat in modification_patterns):
        return False

    # 2. Explicit confirmation phrases
    explicit_confirm_patterns = [
        r"\b(?:confirm(?:ed|ing)?(?:\s+(?:the|my|last)?\s*order)?|place\s+(?:the|my)?\s*order|submit\s+(?:the|my)?\s*order|complete\s+(?:the|my)?\s*order|finish\s+(?:the|my)?\s*order)\b",
        r"(?:تأكيد|أكد|اكد|اعتمد|سجل|نفذ)(?:\s+(?:الطلب|الأوردر|الاوردر|أخر طلب|اخر طلب))?",
    ]
    if any(re.search(pat, t) for pat in explicit_confirm_patterns):
        return True

    # 3. Contextual affirmative tokens: only valid when draft is ready and awaiting confirmation
    is_awaiting = draft.get("stage") == "awaiting_confirmation"
    has_items = bool(draft.get("items"))
    missing = get_missing_fields(draft) if has_items else ["items"]

    if is_awaiting or (has_items and not missing):
        affirmative_tokens = {
            "yes", "yeah", "yep", "sure", "ok", "okay", "proceed",
            "تمام", "أيوة", "ايوة", "نعم", "موافق", "ماشي", "اه", "أه", "أكيد", "اكيد",
        }
        words = set(re.findall(r"[\w]+", t))
        # Match short affirmative responses (under 5 words) that contain an affirmative token
        if any(w in affirmative_tokens for w in words) and len(words) <= 4:
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

    # 3. Check for Cancellation: distinguish policy inquiries from explicit cancellation commands
    is_cancel_mention = any(k in text_lower for k in ("cancel", "إلغاء", "الغاء", "الغي", "كنسل"))
    if is_cancel_mention:
        order_code = _extract_order_code(message)
        # Check if this is an informational question or inquiry regarding cancellation policy
        is_policy_inquiry = (
            any(w in text_lower for w in ("policy", "rules", "can i", "could i", "how", "what", "fee", "fees", "سياسة", "شروط", "هل", "ممكن", "ينفع", "رسوم", "لو حبيت"))
            or "?" in text_lower
            or "؟" in text_lower
        )
        if is_policy_inquiry:
            # Policy inquiries must NEVER clear an active draft!
            resp_text = (
                "ℹ️ **Cancellation Policy**:\n"
                "- Once an order has been confirmed and placed, it cannot be cancelled as preparation begins immediately in the kitchen.\n"
                "- You can freely modify or cancel an unconfirmed draft at any time before placing your order."
            )
            state["tool_name"] = "cancellation_policy"
            state["tool_result"] = {"ok": True, "action": "policy_info"}
            state["response"] = resp_text
            state["context"] = resp_text
            return state
        elif order_code or draft.get("confirmed_order_code"):
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
            # Explicit command to cancel or clear an unconfirmed draft
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
            # History recovery safeguard: if items were selected earlier in this session, restore them
            try:
                from app.models.chat import ChatMessage
                prior_msgs = ChatMessage.query.filter_by(session_id=session_id, role="user").order_by(ChatMessage.created_at.asc()).all()
                for pm in prior_msgs:
                    parse_user_entities(session_id, pm.content)
                draft = get_draft(session_id)
            except Exception:
                pass

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
    graph = StateGraph(AgentState)

    graph.add_node("router", router_node)
    graph.add_node("rag", rag_node)
    graph.add_node("order", order_tool_node)
    graph.add_node("llm", llm_node)

    graph.set_entry_point("router")

    graph.add_conditional_edges(
        "router",
        lambda state: state["intent"],
        {
            "information": "rag",
            "ordering": "order",
        },
    )

    graph.add_edge("rag", "llm")
    graph.add_edge("order", "llm")
    graph.add_edge("llm", END)

    return graph.compile()

_graph = build_graph()

def run(session_id: str, message: str) -> dict:
    return _graph.invoke({
        "session_id": session_id,
        "message": message,
    })