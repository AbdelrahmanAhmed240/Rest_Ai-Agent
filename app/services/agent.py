from config import config

_gemini_client = None

def get_gemini_client():
    """Lazily initialize Google Gen AI SDK client.
    Does not crash on import or when GEMINI_API_KEY is not yet configured.
    """
    global _gemini_client
    if _gemini_client is None:
        api_key = getattr(config, "GEMINI_API_KEY", "") or ""
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is missing. Please set it in your .env file.")
        from google import genai
        _gemini_client = genai.Client(api_key=api_key)
    return _gemini_client

# In-memory conversation state keyed by session ID.
_conversations: dict[str, list] = {}

def get_history(session_id: str) -> list:
    if session_id not in _conversations:
        _conversations[session_id] = []
        try:
            from flask import has_app_context
            if has_app_context():
                from app.models.chat import ChatMessage
                # Load persisted conversation messages chronologically from SQLite
                messages = (
                    ChatMessage.query.filter_by(session_id=session_id)
                    .order_by(ChatMessage.created_at.asc())
                    .all()
                )
                if messages:
                    # If the latest record is an unreplied user message (created right before graph_run),
                    # omit it so the restored history contains only completed past turns and avoids prompt duplication
                    if messages[-1].role == "user":
                        messages = messages[:-1]
                    # Keep recent conversation turns to prevent context window saturation
                    for m in messages[-20:]:
                        _conversations[session_id].append({
                            "role": m.role,
                            "content": m.content,
                        })
        except Exception:
            pass
    return _conversations[session_id]

_SYSTEM_PROMPT = (
    "## 1. Role\n"
    "You are a professional, courteous, and efficient restaurant ordering and customer service AI assistant. "
    "You assist customers with menu inquiries, dish recommendations, branch locations, working hours, and taking complete food orders in their preferred language (Arabic or English).\n\n"
    "## 2. Task\n"
    "1. MENU & INFORMATION: Present menu items and restaurant information accurately with exact prices in EGP and itemized inclusions.\n"
    "2. RECOMMENDATIONS: Provide personalized meal recommendations based on customer preferences, tastes, or dietary questions.\n"
    "3. GUIDED UPSELLING: Conduct guided upselling (offering combo upgrades, drinks, and sauces) after items are selected, respecting customer choices immediately without pressure.\n"
    "4. DETAIL COLLECTION: Collect all required fulfillment details (Delivery, Pickup, Dine-in) one missing detail at a time while remembering previously provided information.\n"
    "5. ORDER SUMMARY & CONFIRMATION: Present complete, itemized final order summaries and request explicit customer confirmation before any order can be submitted.\n"
    "6. GENERAL INQUIRIES: Answer questions regarding operating hours, branches, contact details, and policies using verified information.\n\n"
    "## 3. Context\n"
    "You operate within a restaurant management system. Authoritative menu items, prices, branch locations, operating hours, and active order draft details are maintained by backend services and database records.\n"
    "- When runtime context or retrieved knowledge is provided, treat it as the authoritative single source of truth.\n"
    "- If information requested by the customer is not present in the provided context or knowledge base, politely state that you do not have that information instead of guessing.\n"
    "- All draft calculations, combo fees, discounts, and order persistence are handled by backend transaction tools.\n\n"
    "## 4. Constraints\n"
    "- Authoritative Data Only: Use ONLY factual information from the provided context. Never invent products, secret recipes, prices, discounts, or delivery areas.\n"
    "- No Premature or Hallucinated Confirmations: NEVER state that an order has been placed, confirmed, or recorded, and NEVER generate a fake order code (such as ORD-XXXXX) unless the provided context explicitly confirms that the order was committed to the database with that order code.\n"
    "- Required Information Integrity:\n"
    "  * Delivery: Requires Customer Name, Phone Number, Full Delivery Address (area, street, building, apartment/floor), and Payment Method (Cash or Visa).\n"
    "  * Pickup: Requires Customer Name, Phone Number, Selected Pickup Branch, and Payment Method (Cash or Visa). Never ask for a delivery address for pickup.\n"
    "  * Dine-in: Requires Customer Name, Phone Number, Table Number, and Payment Method (Cash or Visa). Never ask for a delivery address or branch for dine-in.\n"
    "- Step-by-Step Questioning: Ask for only ONE missing required detail at a time to keep conversation smooth and natural.\n"
    "- Arithmetic Integrity: Always use prices and totals provided in the context; never calculate or estimate totals independently.\n"
    "- Clean Output Guard: Never output internal reasoning, chain-of-thought, or analysis tags (such as <think>, 'Thinking Process:', or 'Plan:'). Output ONLY the clean, final customer-facing response.\n"
    "- Markdown Formatting: Output clean, standard Markdown with clean line breaks (###, ####, **, *). Never escape Markdown characters with backslashes (never write \\### or \\**).\n\n"
    "## 5. Examples\n\n"
    "### Example 1 — Menu Presentation\n"
    "User: \"Can I see the menu?\"\n"
    "Assistant:\n"
    "### 📋 Our Menu\n\n"
    "#### 🍗 Meals\n\n"
    "**وجبة بريك — 235 EGP**\n"
    "* Includes: Half broasted chicken, fries, bread, garlic dip, coleslaw.\n"
    "* Combo upgrade: +50 EGP for fries and a drink.\n\n"
    "#### ➕ Add-ons\n\n"
    "* **أرز بسمتي** — 35 EGP\n"
    "* **باكيت بطاطس** — 30 EGP\n\n"
    "#### 🥫 Sauces\n\n"
    "* **ثومية** — 15 EGP\n"
    "* **باربكيو** — 15 EGP\n\n"
    "#### 🥤 Drinks\n\n"
    "* **مشروب غازي** — 20 EGP\n"
    "* **مياه** — 10 EGP\n\n"
    "### Example 2 — Guided Upselling\n"
    "User: \"I want 1 وجبة بريك.\"\n"
    "Assistant:\n"
    "I have added **وجبة بريك** (235 EGP) to your order.\n"
    "Would you like to upgrade to a combo (+50 EGP for French fries and a drink), or add any cold drinks or sauces?\n\n"
    "### Example 3 — Detail Collection\n"
    "User: \"No thanks, delivery please.\"\n"
    "Assistant:\n"
    "Certainly! May I please have your name for the delivery order?\n\n"
    "### Example 4 — Order Summary & Confirmation\n"
    "User: \"Cash payment.\"\n"
    "Assistant:\n"
    "### 🧾 Order Summary\n\n"
    "* **Order Type**: 🚀 Delivery (توصيل)\n"
    "* **Customer Name**: زياد الشريف\n"
    "* **Phone Number**: 01011223344\n"
    "* **Delivery Address**: مدينة نصر شارع عباس العقاد\n"
    "* **Payment Method**: Cash\n\n"
    "#### 🛒 Items:\n"
    "* **وجبة بريك** x1 — 235 EGP\n\n"
    "**Total Amount**: 235 EGP\n\n"
    "Would you like to confirm this order? Please reply with **confirm** (or **تأكيد**) to place your order!\n\n"
    "## 6. Notes\n"
    "- Language Matching: Always reply in the customer's language (natural English when addressed in English, fluent Arabic when addressed in Arabic).\n"
    "- Pacing & Hospitality: Maintain a polite, welcoming, and hospitable tone.\n"
    "- Ambiguity Handling: If a customer request is vague, ask a targeted clarifying question rather than guessing.\n"
    "- Lifecycle Sequence: The workflow strictly follows: selecting_items → offering_extras → collecting_details → awaiting_confirmation → confirmed."
)

def get_system_prompt(context: str = "") -> str:
    """Return the structured system prompt, cleanly incorporating dynamic runtime context into Section 3."""
    if not context or not context.strip():
        return _SYSTEM_PROMPT

    context_block = (
        "## 3. Context\n"
        "### Authoritative Runtime Data:\n"
        f"{context.strip()}\n"
    )
    if "## 3. Context\n" in _SYSTEM_PROMPT:
        return _SYSTEM_PROMPT.replace("## 3. Context\n", context_block, 1)

    return f"{_SYSTEM_PROMPT}\n\n## Additional Context\n{context.strip()}"

def _strip_reasoning(text: str) -> str:
    """Remove reasoning/analysis artifacts while preserving all Markdown formatting.

    1. Removes <think>...</think> and <thought>...</thought> tags (including multiline).
    2. Drops explicit thinking preface blocks (e.g., 'Thinking Process:', 'Thought:').
    3. Preserves all line breaks, markdown headers, bold syntax, emojis, and bullet points.
    """
    if not text or not text.strip():
        return "I'm here to help with your restaurant questions."

    import re

    # 1. Remove <think>...</think> and <thought>...</thought> blocks generated by reasoning-capable models
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<thought>.*?</thought>', '', text, flags=re.DOTALL | re.IGNORECASE)

    # 2. Check for explicit final answer marker separating internal reasoning from customer-facing text
    thought_marker_match = re.search(
        r'(?:^|\n)(?:final (?:customer )?response|customer response|final answer|response|answer):\s*\n?',
        text,
        flags=re.IGNORECASE,
    )
    if thought_marker_match:
        text = text[thought_marker_match.end():]

    # 3. Strip leading lines that are purely reasoning metadata headers (e.g. 'Thinking Process:')
    REASONING_HEADERS = [
        "thinking process", "thought process", "thinking:", "thought:",
        "analyze user input", "analyze the request", "determine response strategy",
        "here is a thinking", "here's a thinking", "internal reasoning",
        "system prompt evaluation", "user intent analysis",
    ]

    lines = text.splitlines()
    first_idx = 0
    while first_idx < len(lines):
        line = lines[first_idx].strip()
        if not line:
            first_idx += 1
            continue
        line_clean = re.sub(r'^[#*\s\d.:\-]+', '', line.lower()).strip()
        if any(line_clean.startswith(h) for h in REASONING_HEADERS):
            first_idx += 1
            # Skip subsequent bullet points if they are indented under the reasoning header
            while first_idx < len(lines):
                next_l = lines[first_idx].strip()
                if not next_l:
                    first_idx += 1
                    continue
                next_clean = re.sub(r'^[#*\s\d.:\-]+', '', next_l.lower()).strip()
                if any(next_clean.startswith(h) for h in REASONING_HEADERS) or next_l.startswith(("-", "*", "•", ">")) or re.match(r'^\d+\.', next_l):
                    first_idx += 1
                else:
                    break
        else:
            break

    cleaned_lines = lines[first_idx:]
    result = "\n".join(cleaned_lines).strip()
    if not result:
        return "I'm here to help with your restaurant questions."

    # Remove any backslash escapes on markdown formatting characters that some models output
    result = re.sub(r'\\+([#*_\-\[\]\(\)])', r'\1', result)
    # Ensure headings and product entries have clean linebreaks if model compressed them
    result = re.sub(r'([^\n])\s+(#{2,6}\s+)', r'\1\n\n\2', result)
    result = re.sub(r'(#{2,6}\s+[^\n]+?)\s+(\*\*[^*\n]+?\*\*)', r'\1\n\n\2', result)
    result = re.sub(r'([^\n])\s+(\*\*[^*\n]+?(?:—|-|:)[^*\n]+?\*\*)', r'\1\n\n\2', result)
    result = re.sub(r'([^\n])\s+([*\-]\s+)', r'\1\n\2', result)
    result = re.sub(r'\n{3,}', '\n\n', result)

    return result.strip() or "I'm here to help with your restaurant questions."

def _reply_gemini(session_id: str, user_message: str, system_prompt: str, history: list) -> str:
    """Generate response using official Google Gen AI SDK."""
    model_name = getattr(config, "GEMINI_MODEL", "gemini-2.5-flash") or "gemini-2.5-flash"
    api_key = getattr(config, "GEMINI_API_KEY", "") or ""
    if not api_key:
        return "Gemini API key is not configured. Please add GEMINI_API_KEY to your .env file."

    try:
        from google import genai
        from google.genai import types, errors
    except ImportError:
        return "Google Gen AI package is not installed. Please run: pip install google-genai"

    # Build contents from history capped at 20 turns to prevent context window saturation
    MAX_HISTORY = 20
    contents = []
    for msg in history[-MAX_HISTORY:]:
        role = "model" if msg.get("role") == "assistant" else "user"
        content_text = msg.get("content", "")
        if content_text:
            contents.append(
                types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=content_text)]
                )
            )

    contents.append(
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=user_message)]
        )
    )

    token_limit = max(getattr(config, "AGENT_MAX_TOKENS", 2048) or 2048, 2048)
    # Configure generation with zero thinking budget to eliminate internal reasoning overhead in production
    gen_config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=config.AGENT_TEMPERATURE,
        max_output_tokens=token_limit,
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    )

    # Prepare prioritized fallback models to maintain service availability if primary model is rate-limited
    models_to_try = [model_name]
    for alt in ["gemini-3.5-flash", "gemini-3.5-flash-lite"]:
        if alt not in models_to_try:
            models_to_try.append(alt)

    client = get_gemini_client()
    content = None
    last_err = None

    for m in models_to_try:
        try:
            response = client.models.generate_content(
                model=m,
                contents=contents,
                config=gen_config,
            )
            content = response.text or ""
            break
        except (errors.ClientError, errors.APIError) as exc:
            last_err = exc
            code = getattr(exc, "code", None)
            msg = getattr(exc, "message", str(exc)).lower()
            if code == 400:
                if "key" in msg or "api_key" in msg:
                    content = "Invalid Gemini API key. Please check GEMINI_API_KEY in your .env file."
                    break
                # Guard against API rejections if an endpoint does not support thinking_config
                if getattr(gen_config, "thinking_config", None) is not None:
                    try:
                        no_think_config = types.GenerateContentConfig(
                            system_instruction=system_prompt,
                            temperature=config.AGENT_TEMPERATURE,
                            max_output_tokens=token_limit,
                        )
                        response = client.models.generate_content(
                            model=m,
                            contents=contents,
                            config=no_think_config,
                        )
                        content = response.text or ""
                        break
                    except Exception as inner_exc:
                        last_err = inner_exc
            # Failover to the next candidate model on quota exhaustion (429) or model unavailability (404)
            if code in (429, 404) or "quota" in msg or "not found" in msg or "resource_exhausted" in msg:
                continue
            content = f"Gemini API request error: {getattr(exc, 'message', str(exc))}"
            break
        except Exception as exc:
            last_err = exc
            err_str = str(exc).lower()
            if "api_key" in err_str or "unauthorized" in err_str:
                content = "Invalid Gemini API key. Please check GEMINI_API_KEY in your .env file."
                break
            break

    # Provide graceful human-friendly error messages if all model attempts failed
    if content is None:
        msg = str(last_err).lower() if last_err else ""
        if "quota" in msg or "429" in msg or "resource_exhausted" in msg:
            content = "Sorry, the Gemini AI service has reached its quota limit. Please try again later."
        elif "key" in msg or "api_key" in msg or "unauthorized" in msg:
            content = "Invalid Gemini API key. Please check GEMINI_API_KEY in your .env file."
        else:
            content = "Sorry, I'm having trouble responding right now. Please try again in a moment."

    # Record turn into in-memory conversation history to maintain conversational context
    history.append({"role": "user", "content": user_message})
    history.append({"role": "assistant", "content": content})

    return _strip_reasoning(content)

def reply(session_id: str, user_message: str, context: str = "") -> str:
    history = get_history(session_id)
    system_prompt = get_system_prompt(context)
    return _reply_gemini(session_id, user_message, system_prompt, history)