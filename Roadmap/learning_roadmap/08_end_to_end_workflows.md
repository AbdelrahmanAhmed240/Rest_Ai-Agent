# Module 08 — Complete End-to-End Workflows

This module traces the 5 most critical workflows in the application from the user's initial input to the final database record and UI response.

---

## 1. Scenario 1: Customer Asks for Menu and Prices

### Flow:
1. **User Sends**: `"Show me all meals and prices"`
2. **`dashboard.html`**: Sends `POST /agent/chat` with `{ session_id: "chat_01", message: "Show me all meals and prices" }`.
3. **`admin.py::agent_chat`**:
   - Saves user message in `ChatMessage` SQLite table.
   - Invokes `graph_run(session_id="chat_01", message=...)`.
4. **`graph.py::router_node`**:
   - Matches menu intent signals. Returns `intent = "information"`.
5. **`graph.py::rag_node`**:
   - Detects all-meals request (`"all meals"`).
   - Calls `search_products(query="")` to get every item from SQLite `Product` table.
   - Formats complete catalog grouped by category (`Meals`, `Add-ons`, `Sauces`, `Drinks`, `Extras`).
   - Sets `state["context"]`.
6. **`graph.py::llm_node`**:
   - Passes context to `agent.reply()`.
   - LLM responds with a beautifully formatted menu in EGP.
7. **`admin.py::agent_chat`**:
   - Stores assistant reply in `ChatMessage`.
   - Returns JSON with rendered HTML to `dashboard.html`.

---

## 2. Scenario 2: Customer Creates a Dine-In Order

### Step 1: Selecting Item
- **User**: `"I want 1 وجبة بريك"`
- **Router**: Detects product name `وجبة بريك` -> routes to `order_tool_node` (`intent = "ordering"`).
- **Order Tool**:
  - `add_item_to_draft(session_id, "وجبة بريك", quantity=1)` adds item (235 EGP).
  - Enters `offering_extras` stage.
  - Suggests combo upgrade (+50 EGP for fries and drink), cold drinks, and sauces.

### Step 2: Customer Declines Upselling
- **User**: `"لا شكراً"` (or `"no"`)
- **Router**: Detects decline signal in `offering_extras` stage -> routes to `order_tool_node` (`intent = "ordering"`).
- **Order Tool**:
  - Sets `upsell_declined = True`.
  - Advances stage to `collecting_details`.
  - Identifies missing fields: `order_type`, `customer_name`, `customer_phone`, `payment_method`.
  - Prompts: *"Would you like Delivery (توصيل), Pickup (استلام من الفرع), or Dine-in (صالة المطعم)?"*

### Step 3: Providing Dine-In & Customer Info
- **User**: `"صالة، اسمي عبد الرحمن، تليفون 01094016152، كاش"`
- **Order Tool**:
  - `parse_user_entities` extracts:
    - `order_type = "dine_in"`
    - `customer_name = "عبد الرحمن"`
    - `customer_phone = "01094016152"`
    - `payment_method = "Cash"`
  - Checks missing fields: `table_number` is still missing!
  - Prompts: *"Please provide your table number in the restaurant (رقم الترابيزة)."*

### Step 4: Providing Table Number
- **User**: `"ترابيزة 12"` (or simply `"12"`)
- **Order Tool**:
  - `parse_user_entities` extracts `table_number = "12"`.
  - All mandatory fields present!
  - Calculates total: 235 EGP.
  - Formats order summary and prompts customer to reply `confirm` (أو `تأكيد`).

### Step 5: Confirmation and Database Commit
- **User**: `"تأكيد"` (or `"confirm"`, `"اه تمام"`)
- **Order Tool**:
  - Detects confirmation intent.
  - Calls `commit_confirmed_order(session_id)`:
    1. `find_or_create_customer`: Inserts or retrieves `Customer` row with phone `01094016152`.
    2. Generates unique order code: `ORD-XXXXX`.
    3. Inserts `Order` row: `customer_id`, `dine_in`, `table_number = 12`, `total = 235.0`, `status = In Kitchen`.
    4. Inserts `OrderItem` row: `وجبة بريك x1`.
    5. Executes `db.session.commit()`.
  - Returns `_format_confirmed_order_response` directly to the user with the real order code!

---

## 3. Scenario 3: Customer Checks Order Status

### Flow:
1. **User**: `"حالة الطلب ORD-21231"` (or `"where is my order ORD-21231"`)
2. **Router**: Detects tracking signal -> routes to `order_tool_node` (`intent = "ordering"`).
3. **Order Tool**:
   - Extracts order code `ORD-21231`.
   - Calls `track_order("ORD-21231")` in `tools.py`.
   - Queries `Order` table in SQLite: returns `status = "In Kitchen"` (or `"Ready"` / `"Delivered"`).
   - Formats clear confirmation of current status.
4. **LLM Node**: Presents the live database status directly to the customer.

---

## 4. Scenario 4: Administrator Updates Order Status

### Flow:
1. Admin visits `/orders` in the browser.
2. Locates `ORD-21231`, clicks "Manage", selects status `Ready`, and clicks Save.
3. Form submits `POST /orders/status/<id>` with `status=Ready`.
4. Flask route executes `db.session.commit()`.
5. If the customer immediately sends `"what is my order status ORD-21231"` in chat, the bot queries SQLite and instantly answers that the order is now **Ready**!

---

## 5. Hands-On Practical Exercise
1. Run the test verifying live order status synchronization:
   ```powershell
   python -m pytest tests/test_order_management.py -k "test_51" -v
   ```
2. Examine how `test_51_live_order_status_reflects_admin_changes` simulates an admin status change and verifies the chatbot's immediate response.

---
👉 **Next**: Continue to [**Module 09: Testing, Debugging, and Reliability**](./09_testing_and_debugging.md).
