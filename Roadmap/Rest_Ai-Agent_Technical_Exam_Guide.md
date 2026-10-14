# Rest_Ai-Agent — Technical Exam Preparation & Code Study Guide

## Document Overview
- **Project Name:** Rest_Ai-Agent
- **Business Domain:** Quick-Service & Dine-In Fried Chicken Fast Food Restaurant
- **Authority Reference:** *Technical Assessment — AI Sales & Customer Service Agent* (8-page specification)
- **Target Audience:** Engineering candidate preparing for technical exam, code defense, and architecture interview.

---

# Section 1: Assessment Requirement Audit Table

The following audit compares the 8-page Technical Assessment PDF requirements directly against the current repository:

| Assessment Requirement | Implementation Location | Current Status | What You Need to Know for the Exam |
| :--- | :--- | :--- | :--- |
| **1. Business Domain Selection** | `knowledge/menu.md`, `knowledge/details.md`, `seed.py` | **Implemented and verified** | Fast-food fried chicken restaurant concept with 3 Cairo branches (Nasr City, Dokki, Maadi), dine-in/takeaway/delivery options, combo meals, and add-ons. |
| **2. AI Customer Service Agent** | `app/services/graph.py` (`rag_node`), `app/services/vector_store.py` | **Implemented and verified** | Answers general inquiries, operating hours, delivery fees, branch addresses, and policies grounded via ChromaDB RAG. |
| **3. AI Sales & Upselling Agent** | `app/services/graph.py` (`order_tool_node`), `app/services/order_session.py` (`upgrade_draft_combos`) | **Implemented and verified** | Recommends popular items, asks spicy vs. original preference, suggests combo upgrades (+fries & drink), and offers extra sauces. |
| **4. RAG Implementation** | `knowledge/*.md`, `app/services/chunker.py`, `app/services/embeddings.py`, `app/services/vector_store.py` | **Implemented and verified** | Markdown files chunked by headers and meals, converted to vector embeddings via Gemini (`gemini-embedding-001`), stored in `data/chroma_db`. |
| **5. RAG Management via Dashboard** | `app/routes/admin.py` (`/knowledge`), `app/services/knowledge_sync.py`, `app/templates/knowledge*.html` | **Implemented and verified** | Admin UI allows adding, editing, and deleting knowledge items, modifying raw Markdown source files, and rebuilding vector collections with one click. |
| **6. LangGraph Multi-Node Workflow** | `app/services/graph.py` (`build_graph`, `router_node`, `AgentState`) | **Implemented and verified** | Simplified 2-path StateGraph: `router` -> conditional routing to `rag_node` (informational queries) or `order_tool_node` (orders, tracking, upselling) -> `llm_node` -> `END`. Prevents ungrounded hallucination. |
| **7. Real Business Action / Function Calling** | `app/services/tools.py` (`create_order`, `track_order`), `app/services/order_session.py` (`commit_confirmed_order`) | **Implemented and verified** | Performs real multi-table database transactions (`Customer`, `Order`, `OrderItem`). Rollback occurs on error; orders are never fake strings. |
| **8. Flask Admin Dashboard** | `app/routes/admin.py`, `app/templates/*.html` (`dashboard.html`, `orders.html`, `customers.html`) | **Implemented and verified** | Full dashboard to chat with agent in multi-session tabs, track live orders, transition order statuses, manage customers, and view statistics. |
| **9. Database & ORM** | `app/models/` (`Product`, `Customer`, `Order`, `OrderItem`, `ChatSession`, `ChatMessage`, `KnowledgeItem`) | **Implemented and verified** | SQLAlchemy 2.0 with SQLite database (`instance/restaurant.db`). Relational foreign keys, cascading deletes, and timestamps are strictly enforced. |
| **10. Bonus: Meta Messenger Integration** | Architecture planned in assessment specification | **Optional / Missing** | Assessment explicitly marks Facebook Messenger as an optional bonus. The project prioritized a rich, multi-tab persistent web chat UI. |

---

# Section 2: Overall System Architecture

The application is structured into four decoupled layers:

```
[ Customer / Admin Browser ]
             │ HTTP (JSON / HTML)
             ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. Presentation & Flask Route Layer (app/routes/admin.py)   │
│  - Routes: /dashboard, /agent/chat, /orders, /customers     │
│  - Persistent Sessions: ChatSession & ChatMessage models    │
└─────────────────────────────────────────────────────────────┘
             │ Invokes graph.run(session_id, message)
             ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. LangGraph State Machine (app/services/graph.py)          │
│  - State: AgentState (session_id, message, intent, context) │
│  - Router: Classifies message into 2 distinct paths:        │
│       ┌───────────────────────┴───────────────────────┐     │
│       ▼ (information)                                 ▼     │
│   [ rag_node ]                               [ order_tool_node ]
│   ChromaDB Context Retrieval                 In-Memory Drafts & Tools
│       └───────────────────────┬───────────────────────┘     │
│                               ▼                             │
│                          [ llm_node ]                       │
│                  Gemini (gemini-2.5-flash)                  │
│                               │                             │
│                               ▼                             │
│                             [ END ]                         │
└──────────────┬───────────────────────────────┬──────────────┘
               │                               │
               ▼ RAG Retrieval                 ▼ Order Tools & Drafts
┌───────────────────────────────┐ ┌───────────────────────────┐
│ 3. Knowledge & Vector Engine  │ │ 4. Order & Transaction    │
│  - ChromaDB (data/chroma_db)  │ │    Management Engine      │
│  - Chunker & Embeddings       │ │  - In-Memory Order Drafts │
│  - Markdown Knowledge Sync    │ │  - Atomic DB Operations   │
└───────────────────────────────┘ └─────────────┬─────────────┘
                                                │
                                                ▼ SQLAlchemy ORM
                                  ┌───────────────────────────┐
                                  │ 5. SQLite Database        │
                                  │    (instance/restaurant.db│
                                  │    Products, Customers,   │
                                  │    Orders, OrderItems     │
                                  └───────────────────────────┘
```

---

# Section 3: The 4 Core Workflow Traces

### Workflow 1: Customer Inquires About Products or Menu
1. Customer enters: *"Show me all meals and prices"*
2. Frontend dispatches `POST /agent/chat` with `{ session_id, message }`.
3. `admin.py:agent_chat()` saves user message to SQLite and passes it to `graph.run()`.
4. `graph.py:router_node` checks intent keywords and assigns `intent = "information"`.
5. LangGraph conditional edge routes execution to `rag_node`.
6. `rag_node` calls `vector_store.retrieve(message, top_k=3)`.
7. Retrieved chunks are placed in `state["context"]`.
8. Edge transitions to `llm_node`.
9. `llm_node` invokes `agent.reply()` which combines the system prompt with retrieved context.
10. Execution terminates at `END`; `admin.py` stores agent reply and returns JSON.

### Workflow 2: Customer Builds & Confirms an Order (End-to-End Persistence)
1. **Draft Creation:** Customer requests *"I want 1 وجبة بريك"*.
   - Router selects `intent = "ordering"`, routing execution to `order_tool_node`.
   - `order_session.add_item_to_draft(session_id, product_name, quantity=1)` adds the item to `_drafts[session_id]`.
2. **Upsell Offer:** System identifies item can be made combo and prompts customer for upgrade.
3. **Entity Extraction:** Customer supplies details: *"Delivery - Ahmed - 01012345678 - Dokki - Cash"*.
   - `order_session.parse_user_entities()` parses name, phone, branch/address, fulfillment type, and payment method.
4. **Draft Summary:** Bot renders formatted summary with total and requests confirmation: *"Reply confirm to place order."*
5. **Confirmation & Commit:** Customer replies *"تاكيد"* (or *"confirm"*).
   - `_is_confirmation_intent()` detects affirmative reply.
   - `order_session.get_missing_fields()` verifies all fields are present.
   - `order_session.commit_confirmed_order(session_id)` is executed inside an active Flask application context:
     - Finds or creates `Customer` record by phone.
     - Creates `Order` row with unique code (e.g. `ORD-B4A1F2`), total amount, and delivery address.
     - Creates `OrderItem` rows for every meal in the draft.
     - Commits transaction via `db.session.commit()`.
     - Clears the in-memory draft (`clear_draft(session_id)`).
   - Bot displays confirmed invoice receipt with order tracking code.

### Workflow 3: Customer Tracks Live Order Status
1. Customer asks: *"What is the status of my order ORD-B4A1F2?"*
2. Router assigns `intent = "ordering"`, routing execution to `order_tool_node`.
3. `order_tool_node` invokes `tools.track_order(order_code="ORD-B4A1F2")`.
4. `track_order` executes `Order.query.filter(Order.code.ilike(...)).first()`.
5. Retrieves live status directly from the database (`Pending`, `Preparing`, `Out for Delivery`, `Delivered`, etc.).
6. Agent returns the official status to the user.

### Workflow 4: Administrator Manages Orders in Dashboard
1. Admin navigates to `/orders`.
2. `admin.py:orders` queries `Order.query.order_by(Order.created_at.desc()).all()`.
3. Admin selects a new status from the dropdown (e.g. changes `Pending` to `Preparing`).
4. JavaScript sends `POST /orders/status/<order_id>` with `{ status: "Preparing" }`.
5. `admin.py:update_order_status` validates status against `Order.ALLOWED_STATUSES`, sets `order.status = new_status`, and commits transaction.
6. The change is saved immediately in SQLite and appears in future tracking inquiries.

---

# Section 4: The Exact Code You Must Study (Repository Map)

| Priority | File Path | Code Location / Functions | What It Does | Key Concept to Understand |
| :--- | :--- | :--- | :--- | :--- |
| **MUST STUDY** | `app/services/graph.py` | L40-L120: `router_node`, `build_graph` | Directs messages into 2 paths (`information` vs `ordering`) before calling LLM | StateGraph compilation, conditional edges, deterministic routing before LLM |
| **MUST STUDY** | `app/services/graph.py` | L180-L310: `order_tool_node`, `_is_confirmation_intent` | Manages ordering conversation, drafts, and triggers database commit | Guardrails preventing LLM hallucination of order persistence |
| **MUST STUDY** | `app/services/order_session.py` | L240-L380: `commit_confirmed_order`, `parse_user_entities` | Extracts customer/fulfillment entities & commits atomic DB transaction | Multi-table relational insert (`Customer` -> `Order` -> `OrderItem`) & rollback |
| **MUST STUDY** | `app/services/tools.py` | L40-L160: `create_order`, `track_order`, `recommend_products` | Business tool definitions callable by graph or tests | ORM queries, Egyptian phone normalization, relational joins |
| **MUST STUDY** | `app/models/` | `customer.py`, `order.py`, `product.py`, `chat.py` | SQLAlchemy database schema | Foreign keys, `backref`, cascading deletes (`cascade="all, delete-orphan"`) |
| **MUST STUDY** | `app/services/agent.py` | L20-L110: `reply`, `get_system_prompt`, `_reply_gemini` | Prepares prompt with RAG context, invokes Gemini 2.5 Flash, sanitizes output | System prompt architecture (Role, Task, Context, Constraints), Google GenAI SDK |
| **MUST STUDY** | `app/services/vector_store.py` | L30-L120: `retrieve`, `upsert_chunks`, `get_collection` | ChromaDB vector search and chunk storage | Vector similarity search, cosine distance, top-k retrieval |
| **SHOULD STUDY**| `app/routes/admin.py` | L50-L140: `agent_chat`, `/orders`, `/customers` | HTTP endpoints connecting frontend UI with backend services | Request validation, session persistence, JSON API responses |
| **SHOULD STUDY**| `app/services/knowledge_sync.py` | L50-L180: `sync_all`, `rebuild_vector_index` | Synchronizes Markdown files (`knowledge/*.md`) with ChromaDB | Document parsing, chunking, indexing, and vector DB maintenance |
| **SHOULD STUDY**| `tests/test_order_management.py` | 64 test scenarios | Validates full system from products to chat deletion | Pytest fixtures, test client, assertions, regression protection |

---

# Section 5: Technical Exam Questions & Answers

### Question 1: What is the high-level architecture of your project?
- **Model Answer:** Rest_Ai-Agent is a full-stack Flask application integrated with LangGraph, ChromaDB, and SQLite. When a user sends a message, a simplified 2-path LangGraph state machine routes the input: informational queries retrieve grounded chunks from ChromaDB via `rag_node`; ordering operations update an in-memory draft and commit atomic transactions via `order_tool_node`. Both paths pass context to `llm_node` powered by Google Gemini (gemini-2.5-flash). Administrators manage orders, customers, and RAG knowledge via a web dashboard.
- **Simpler Explanation:** It is a restaurant ordering and customer service system where LangGraph decides whether to look up information from a vector database or write a real order to SQLite, all visible in an admin dashboard.
- **Relevant Code:** `app/services/graph.py` (`build_graph`), `app/routes/admin.py`.

### Question 2: Why did you use LangGraph instead of calling an LLM directly?
- **Model Answer:** Calling an LLM directly leads to hallucinations—such as telling a user their order is confirmed when no database write occurred. LangGraph allows us to define deterministic nodes and conditional edges. The router deterministically separates informational RAG queries from ordering operations, enforces required customer fields, and only calls `commit_confirmed_order` upon explicit affirmative confirmation.
- **Simpler Explanation:** LangGraph separates conversation reasoning from business actions so the AI can never fake database operations.
- **Relevant Code:** `app/services/graph.py` (lines 50-110).

### Question 3: How does RAG work in your project from file to prompt?
- **Model Answer:** Knowledge is stored in Markdown files under `knowledge/` (`menu.md` and `details.md`). `chunker.py` segments the text by headers and menu items. `embeddings.py` converts text into numerical vector embeddings via `gemini-embedding-001`. `vector_store.py` indexes the vectors in ChromaDB. When a customer asks a question, `retrieve(query, top_k=3)` performs a similarity search. The resulting text is injected into the LLM system prompt under the `Context:` section.
- **Simpler Explanation:** Markdown files are split into small pieces, converted to vectors, and stored in ChromaDB. When a user asks a question, the most similar pieces are fetched and given to the LLM to ground its answer.
- **Relevant Code:** `app/services/vector_store.py`, `app/services/chunker.py`, `app/services/agent.py`.

### Question 4: How do you guarantee that an order is actually saved in the database?
- **Model Answer:** The AI agent never creates database rows directly. When items are added, they reside in an in-memory draft dictionary (`order_session._drafts[session_id]`). When the customer confirms, `order_tool_node` checks for affirmative intent (`_is_confirmation_intent`), validates that required fields are present (`get_missing_fields`), and calls `commit_confirmed_order()`. This function executes an atomic SQLAlchemy transaction inserting records into `Customer`, `Order`, and `OrderItem`, followed by `db.session.commit()`. If an exception occurs, `db.session.rollback()` is executed.
- **Simpler Explanation:** The order stays in memory as a draft until all fields are collected and the customer says confirm. Then a Python function commits the real rows to SQLite using SQLAlchemy.
- **Relevant Code:** `app/services/order_session.py` (`commit_confirmed_order`), `app/services/graph.py` (`order_tool_node`).

### Question 5: What happens if the LLM provider fails or experiences rate limits?
- **Model Answer:** In `app/services/agent.py`, the `reply()` function wraps the Google GenAI SDK call in try-except blocks handling API and network errors. If an error occurs, it returns a polite localized error message without crashing the Flask web server.
- **Simpler Explanation:** The system catches API errors and displays a friendly error message to the user rather than crashing.
- **Relevant Code:** `app/services/agent.py` (`reply`).

---

# Section 6: Honest Study-Time Estimates & Preparation Plan

Based on the actual codebase complexity (4,500 lines of Python, 12 backend modules, 11 templates, 64 automated tests):

### Preparation Levels
1. **Level 1: Minimum Exam Readiness (6 – 8 Focused Hours / 2 – 4 Calendar Days)**
   - *Scope:* Understand overall architecture, explain the 2-minute overview, describe database models, explain RAG conceptually, and explain how an order is saved.
   - *Risk:* Vulnerable to detailed code-tracing questions or edge-case debugging.
2. **Level 2: Strong Technical Understanding (14 – 18 Focused Hours / 4 – 7 Calendar Days) [RECOMMENDED]**
   - *Scope:* Trace all 4 workflows line-by-line through the actual source files, explain LangGraph routing logic, describe SQLAlchemy transaction commits/rollbacks, explain ChromaDB retrieval, and answer intermediate follow-up questions confidently.
3. **Level 3: Deep Technical Mastery (26 – 32 Focused Hours / 7 – 14 Calendar Days)**
   - *Scope:* Capable of modifying graph nodes on the whiteboard, writing new tools live, debugging ChromaDB chunking edge cases, explaining cascade deletions, and discussing architectural trade-offs.

### Conversion to Calendar Days
| Daily Study Commitment | Level 1 (Min Readiness: ~8h) | Level 2 (Strong Understanding: ~16h) | Level 3 (Deep Mastery: ~30h) |
| :--- | :--- | :--- | :--- |
| **2 Focused Hours/Day** | 4 Calendar Days | 8 Calendar Days | 15 Calendar Days |
| **4 Focused Hours/Day** | 2 Calendar Days | 4 Calendar Days | 7.5 Calendar Days |
| **6 Focused Hours/Day** | 1.5 Calendar Days | 3 Calendar Days | 5 Calendar Days |

### Day-by-Day Study Plan (Recommended Level 2: 16 Focused Hours across 4 Days)
- **Day 1: Architecture, Flask & Database Layer (4 Hours)**
  - Study `config.py`, `app/__init__.py`, `app/routes/admin.py`, and `app/models/`.
  - Checkpoint: Draw the database schema from memory and explain the Flask route lifecycle.
- **Day 2: LangGraph & Agent Layer (4 Hours)**
  - Study `app/services/graph.py` and `app/services/agent.py`.
  - Checkpoint: Trace a user message from `router_node` to `llm_node` and explain conditional edges.
- **Day 3: RAG Pipeline & Order Persistence (4 Hours)**
  - Study `app/services/vector_store.py`, `chunker.py`, `knowledge_sync.py`, and `order_session.py`.
  - Checkpoint: Explain how Markdown becomes vector chunks in ChromaDB and trace `commit_confirmed_order()`.
- **Day 4: Tests, Mock Exam & Readiness Practice (4 Hours)**
  - Review `tests/test_order_management.py` and practice the 2-Minute Explanation and Q&A bank aloud.
  - Checkpoint: Score 85%+ on the Readiness Self-Test without looking at notes.

---

# Section 7: "Explain the Project in 2 Minutes" (Practice Script)

"Rest_Ai-Agent is an automated sales and customer service web platform built for a fast-food restaurant. It combines a Flask administrative backend with an agentic AI system powered by LangGraph, ChromaDB, and SQLAlchemy on SQLite.

When a customer chats with the restaurant, their message enters a LangGraph state machine. The router node determines the intent—directing informational queries to a RAG retrieval node that queries ChromaDB for accurate items and policies, and ordering requests to a dedicated order tool node that manages drafts, upsells combos, and tracks existing orders.

What makes this architecture robust is that the AI never makes fake promises about orders. The system collects items, delivery address, and phone number in a validated draft session. Only upon explicit customer confirmation does the application trigger an atomic SQLAlchemy transaction that persists the customer, order, and order-item records into SQLite.

Finally, the administrator has a live Flask dashboard to manage orders, update preparation statuses, review customer metrics, edit the menu, and even modify and re-index the RAG knowledge base dynamically without redeploying the code. All 64 unit and integration tests are verified and passing."

---

# Section 8: Readiness Self-Test & Evaluation Rubric

Before heading into the interview, test yourself against these 8 core tasks without looking at the guide:
1.  **Can you explain the high-level architecture in 2 minutes?**
2.  **Can you draw the LangGraph state machine (nodes and conditional edges)?**
3.  **Can you explain how a Markdown document in `knowledge/` reaches the LLM prompt?**
4.  **Can you name the 4 primary database tables and explain their foreign key relationships?**
5.  **Can you point to the exact function where an order is committed to the database?**
6.  **Can you explain what happens if the LLM provider fails during a chat request?**
7.  **Can you describe how an administrator updates an order's status from the dashboard?**
8.  **Can you explain the difference between an in-memory draft and a persisted order?**

**Scoring Rubric:**
- **7-8 Correct:** Ready for the examination with high confidence.
- **5-6 Correct:** Review Days 2 and 3 of the study plan before interviewing.
- **Under 5:** Spend an additional 4-6 focused hours tracing source code before taking the exam.
