# Module 04 — Supporting Services Architecture

## 1. Why a Service Layer?
In simple tutorials, developers often put database queries, regex parsing, and pricing calculations directly inside Flask route functions.
In a production-ready application, this causes code bloat and prevents testing the business logic independently from HTTP requests.

The **Service Layer** sits between the presentation layer (Routes/Graph) and the database layer (Models):
```
[HTTP Route / LangGraph Node]
              |
              v
       [Service Layer]   <--- Deterministic calculations, regex parsing, draft tracking
              |
              v
      [Database Models]  <--- SQLite / SQLAlchemy
```

---
## 2. Core Service Modules Breakdown

### A. `app/services/tools.py` — Deterministic Order Tools
Open [`app/services/tools.py`](file:///c:/Users/Home/Desktop/Rest_Ai-Agent/app/services/tools.py#L25-L688).
This module contains stateless, deterministic database tools wrapped in the `@_with_app_context` decorator:
- `search_products(query, limit)`: Performs case-insensitive matching for dishes with synonym expansion (e.g. `drink` -> `مشروب`, `water` -> `مياه`).
- `query_price_info(message)`: Deterministically calculates mathematical queries so the LLM never has to do mental arithmetic:
  - Cheapest meal (`cheapest`, `ارخص`)
  - Most expensive meal (`most expensive`, `اغلى`)
  - Price threshold filters (`under 200 egp`, `اقل من 150 جنيه`)
  - All meal prices table
- `find_or_create_customer(name, phone, address)`: Normalizes Egyptian phone numbers (`+2010...` -> `010...` -> `10...`) so the same customer is matched regardless of country-code formatting.
- `create_order(...)`: Handles the atomic multi-table transaction creating the order and order items.
- `track_order(order_code, phone)`: Looks up real database status (`In Kitchen`, `Ready`, `Delivered`) and verifies customer ownership.
- `tool_result_text(result)`: Converts dictionary outputs into structured markdown strings ready for LLM context injection.

### B. `app/services/order_session.py` — Draft & Entity Management
Open [`app/services/order_session.py`](file:///c:/Users/Home/Desktop/Rest_Ai-Agent/app/services/order_session.py#L40-L678).
This module manages in-flight conversational drafts before they are committed to SQLite:

1. **In-Memory Draft Store (`_drafts`)**:
   Tracks the active draft dictionary per `session_id`:
   ```python
   {
       "session_id": "chat_123",
       "order_type": "delivery",     # "delivery", "pickup", "dine_in"
       "customer_name": "Ahmed",
       "customer_phone": "01094016152",
       "delivery_address": "Maadi, St 9",
       "pickup_branch": None,
       "table_number": None,
       "payment_method": "Cash",     # "Cash", "Visa"
       "items": [...],
       "stage": "awaiting_confirmation",
       "upsell_offered": True,
       "upsell_declined": False,
       "confirmed_order_code": None
   }
   ```
2. **Dual Persistence (`_save_draft_to_db` & `_load_draft_from_db`)**:
   Every time a draft is updated via `update_draft()`, it is serialized to JSON and stored in the SQLite `chat_sessions.draft_data` column. If Python restarts or memory is flushed, the draft is seamlessly restored!
3. **Mandatory Field Enforcement (`get_missing_fields(draft)`)**:
   Strictly enforces the business requirements:
   - **Delivery**: Requires `customer_name`, `customer_phone`, `delivery_address`, `payment_method`.
   - **Pickup**: Requires `customer_name`, `customer_phone`, `pickup_branch`, `payment_method`.
   - **Dine-in**: Requires `customer_name`, `customer_phone`, `table_number`, `payment_method`.
4. **Entity Extraction (`parse_user_entities(session_id, message)`)**:
   Robust bilingual regex parser extracting:
   - Phone numbers: Egyptian mobile prefixes (`010`, `011`, `012`, `015`).
   - Order types: `delivery`, `pickup`, `dine_in`, `توصيل`, `استلام`, `صالة`.
   - Payment methods: `cash`, `visa`, `كاش`, `فيزا`.
   - Table numbers: `table 12`, `ترابيزة 5`, or standalone integers (`12`) when in dine-in stage.
   - Pickup branches: Matches against `AVAILABLE_BRANCHES`.
   - Customer names: Prevents accidental overwrites from food names (e.g. `want to order بسمتيو` is ignored as a name).

---
👉 **Next**: Continue to [**Module 05: AI and LLM Integration**](./05_ai_and_llm.md).