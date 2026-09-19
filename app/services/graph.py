from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from app.services.agent import get_history
from app.services.vector_store import retrieve
from app.services.tools import search_products, find_or_create_customer, create_order, edit_order, cancel_order, tool_result_text, recommend_products


class AgentState(TypedDict, total=False):
    session_id: str
    message: str
    intent: str
    history: list[dict[str, Any]]
    response: str
    context: str
    tool_name: str
    tool_result: dict


def _route_intent(message: str) -> str:
    text = message.strip().lower()

    cancel_signals = ["cancel", "cancel my order", "cancel order"]
    if any(signal in text for signal in cancel_signals):
        return "future_tool_request"

    edit_signals = ["edit", "change", "remove", "add ", "update"]
    if any(signal in text for signal in edit_signals):
        return "future_tool_request"

    tool_signals = ["place an order", "create order", "create a", "find ", "show me "]
    if any(signal in text for signal in tool_signals):
        return "future_tool_request"

    recommendation_signals = ["recommend", "suggest", "best", "cheaper", "cheap", "hungry", "what should i get", "spicy"]
    if any(signal in text for signal in recommendation_signals):
        return "recommendation"

    restaurant_signals = ["menu", "food", "dish", "price", "order ", "shawarma", "egyptian", "pasta", "drink", "hours"]
    if any(signal in text for signal in restaurant_signals):
        return "restaurant_product"
    return "general"


def router_node(state: AgentState) -> AgentState:
    state["intent"] = _route_intent(state.get("message", ""))
    return state


def recommendation_node(state: AgentState) -> AgentState:
    message = state.get("message", "")
    rec_result = recommend_products(message, limit=3)
    product_results = search_products(message, limit=5)
    # Skip RAG embedding — use product data only to reduce OpenRouter API calls.

    pieces = []
    if rec_result.get("ok") and rec_result.get("items"):
        lines = ["Recommended products:"]
        for item in rec_result["items"]:
            price = item.get("combo_price") or item.get("price")
            lines.append(f"- {item['name']} ({item['category']}): {price} EGP")
        pieces.append("\n".join(lines))

    if product_results.get("ok") and product_results.get("items"):
        product_lines = ["Available products:"]
        for item in product_results["items"]:
            price = item.get("combo_price") or item.get("price")
            product_lines.append(f"- {item['name']} ({item['category']}): {price} EGP")
        pieces.append("\n".join(product_lines))

    if not pieces:
        pieces.append("I couldn't find a suitable recommendation right now.")

    state["context"] = "\n\n".join(pieces)
    state["tool_name"] = "recommend_products"
    state["tool_result"] = rec_result
    return state


def rag_node(state: AgentState) -> AgentState:
    message = state.get("message", "")
    text_lower = message.lower()
    # Menu/listing queries: return ALL products, skip RAG embedding.
    is_menu_query = any(kw in text_lower for kw in (
        "menu", "can i see", "what do you have", "what's on",
        "show me", "i want to see", "list", "available",
    ))
    # Restaurant knowledge queries: use RAG retrieval (hours, branches,
    # policies, delivery, payment, etc.).
    is_knowledge_query = any(kw in text_lower for kw in (
        "hour", "open", "close", "branch", "location", "address",
        "policy", "delivery", "payment", "visa", "cash",
        "area", "region", "where", "find", "Contact", "contact",
        "phone", "social", "facebook", "media",
    ))
    pieces = []
    product_results = None
    if is_knowledge_query:
        hits = retrieve(message, top_k=3)
        for hit in hits:
            content = hit.get("content") or ""
            if content.strip():
                pieces.append(content.strip())
    if is_menu_query:
        product_results = search_products("", limit=50)
    elif not is_knowledge_query:
        product_results = search_products(message, limit=5)
    if product_results and product_results.get("ok") and product_results.get("items"):
        product_lines = ["Available products:"]
        for item in product_results["items"]:
            price = item.get("combo_price") or item.get("price")
            product_lines.append(f"- {item['name']} ({item['category']}): {price} EGP")
        pieces.append("\n".join(product_lines))
    elif not pieces:
        pieces.append("I don't have specific information for that request.")

    state["context"] = "\n\n".join(pieces)
    return state


def _decide_tool(message: str) -> str:
    text = message.strip().lower()
    if "cancel" in text or "cancel order" in text:
        return "cancel_order"
    if "edit" in text or "change" in text or "remove" in text or "add " in text or "update" in text:
        return "edit_order"
    if "order" in text:
        return "create_order"
    if "customer" in text or "phone" in text or "name" in text:
        return "customer"
    return "product_search"


def tool_node(state: AgentState) -> AgentState:
    message = state.get("message", "")
    tool_name = _decide_tool(message)
    state["tool_name"] = tool_name

    result: dict = {"ok": False, "error": "Unsupported tool request."}
    if tool_name == "product_search":
        result = search_products(query=message)
    elif tool_name == "customer":
        # Extremely minimal extraction; LLM will see exact result.
        result = find_or_create_customer(name="", phone="", address="")
        if not result.get("ok") and "phone is required" in result.get("error", "").lower():
            result = {
                "ok": False,
                "error": "To create or find a customer, I need the customer's phone number.",
            }
    elif tool_name == "create_order":
        result = {
            "ok": False,
            "error": "To create an order, I need the customer phone and at least one product with quantity.",
        }
    elif tool_name == "edit_order":
        result = {
            "ok": False,
            "error": "To edit an order, I need the order code and phone number.",
        }
    elif tool_name == "cancel_order":
        result = {
            "ok": False,
            "error": "To cancel an order, I need the order code and phone number.",
        }

    state["tool_result"] = result
    state["context"] = tool_result_text(result)
    return state


def llm_node(state: AgentState) -> AgentState:
    from app.services.agent import reply

    session_id = state.get("session_id", "default")
    message = state.get("message", "")
    context = state.get("context", "")
    response = reply(session_id=session_id, user_message=message, context=context)
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
    workflow.add_node("tool", tool_node)
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
            "future_tool_request": "tool",
        },
    )
    workflow.add_edge("recommendation", "llm")
    workflow.add_edge("rag", "llm")
    workflow.add_edge("tool", "llm")
    workflow.add_edge("llm", "output")
    workflow.add_edge("output", END)
    return workflow.compile()


_graph = build_graph()


def run(session_id: str, message: str) -> dict:
    return _graph.invoke({
        "session_id": session_id,
        "message": message,
    })
