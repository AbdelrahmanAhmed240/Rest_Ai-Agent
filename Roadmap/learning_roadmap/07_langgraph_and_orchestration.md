# Module 07 — LangGraph and AI Orchestration

## 1. Why LangGraph Instead of a Single Prompt Loop?
If you feed everything into a single prompt loop:
1. Complex conversational branches (ordering vs tracking vs general chat) get tangled.
2. The agent might attempt to confirm an order before asking for the customer's phone number or address.
3. Errors in one branch crash the entire conversation.

**LangGraph** solves this by modeling the agent as a clean **State Machine** with two main paths:
- Clear separation between **Informational/RAG questions** and **Order Management operations**.
- Deterministic guardrails enforce validation rules before any state reaches the LLM.

---

## 2. Graph State Architecture (`AgentState`)

Open [`app/services/graph.py`](file:///c:/Users/Home/Desktop/Rest_Ai-Agent/app/services/graph.py#L29-L38):
```python
class AgentState(TypedDict, total=False):
    session_id: str
    message: str
    intent: str
    history: list[dict[str, Any]]
    response: str
    context: str
    tool_name: str
    tool_result: dict
```
This typed dictionary is passed across nodes. Each node reads fields, updates state, and passes it forward.

---

## 3. The Simplified 2-Path Pipeline Visualized

```
             +-------------+
             |    START    |
             +-------------+
                    |
                    v
             +-------------+
             | router_node | <--- Classifies: "information" vs "ordering"
             +-------------+
              /           \
   [information]         [ordering]
            /               \
           v                 v
     +----------+     +---------------+
     | rag_node |     |order_tool_node|
     | (Path A) |     |   (Path B)    |
     +----------+     +---------------+
           \                 /
            \               /
             v             v
             +-------------+
             |  llm_node   | <--- Generates answer or returns deterministic response
             +-------------+
                    |
                    v
             +-------------+
             |     END     |
             +-------------+
```

---

## 4. The Graph Nodes Explained

### A. The 2-Path Intent Router (`router_node` & `_route_intent`)
Evaluates the incoming message:
- **`ordering`**: Placing an order, providing missing details (delivery address, phone, table number), confirmation (`confirm`, `تأكيد`), or status tracking (`track order`, `حالة الطلب`). Also catches continuation turns when the session has an active unconfirmed draft.
- **`information`**: All customer questions about menu items, prices, cheapest meals, recommendations, branch locations, working hours, delivery policies, and general inquiries.

### B. Path A: The Unified Information Node (`rag_node`)
Consolidates all restaurant inquiries into a single grounded knowledge pipeline:
1. **Deterministic Price Queries**: If user asks for cheapest/expensive dishes or meals under a budget, calls `query_price_info(message)` from `tools.py`.
2. **Preference Recommendations**: If user asks for suggestions or recommendations, calls `recommend_products(message)` from `tools.py`.
3. **Full Menu Catalog**: If user asks for all meals or the menu, calls `search_products("")` to return the complete live SQLite catalog formatted by category.
4. **Semantic Vector Search**: For branch locations, policies, or general details, queries ChromaDB via `retrieve(message, top_k=4)`.
5. Compiles grounded text into `state["context"]`.

### C. Path B: The Order Tool Node (`order_tool_node`)
The core transactional order workflow:
1. **Entity Extraction**: Calls `parse_user_entities(session_id, message)` to capture name, phone, address, branch, table number, and payment method into the draft.
2. **Mixed Message Handling**: If the customer asks an informational question while ordering (*"Do you have Break meal and I want to order one"*), automatically retrieves relevant ChromaDB chunks into the context while updating the draft cart.
3. **Status Tracking**: Dispatches `track_order(order_code)` using `order_code` only and formats authoritative database results. (Order cancellation and editing are not supported once placed).
4. **Order Confirmation**: When confirmation signals are detected:
   - Validates draft completeness (`get_missing_fields(draft)`).
   - If complete, calls `commit_confirmed_order(session_id)` to atomically persist to SQLite!
   - Sets `state["response"]` directly to `_format_confirmed_order_response()`, bypassing LLM hallucination risks.
5. **Upselling Flow**: If items were just selected, enters `offering_extras` stage to suggest combo upgrades (+50 EGP), drinks, or sauces.
6. **Missing Details Collection**: If fields are missing, prompts for them sequentially (one missing detail at a time).

### D. The LLM Node with Hallucination Guard (`llm_node`)
Invokes Google Gemini with the grounded context:
- **Authoritative Bypass**: If `state["response"]` was already generated deterministically by `order_tool_node`, bypasses the API call completely.
- **Hallucination Guardrail**:
  If the LLM generates `ORD-` or claims "your order has been placed" while the database draft was **not** confirmed, `llm_node` intercepts the output, replaces it with the draft summary, and prompts:
  `Please reply confirm (or تأكيد) to place your order!`

---
👉 **Next**: Continue to [**Module 08: Complete End-to-End Workflows**](./08_end_to_end_workflows.md).