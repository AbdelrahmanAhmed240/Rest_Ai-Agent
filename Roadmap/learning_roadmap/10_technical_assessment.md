# Module 10 — Technical Assessment Preparation & Code Defense

This final module prepares you to present, explain, and defend the **Rest_Ai-Agent** project in front of an examiner or technical interview panel.

---

## 1. The 2-Minute Project Presentation (Elevator Pitch)

> *"Rest_Ai-Agent is an enterprise-grade conversational AI restaurant ordering and administration system built with Flask, SQLAlchemy, ChromaDB, and LangGraph.*
>
> *Unlike conventional chatbots that hallucinate fake order confirmations or make arithmetic mistakes when calculating prices, our system pairs natural language understanding with a strict deterministic business logic layer.*
>
> *The AI agent uses LangGraph to orchestrate intent classification, RAG retrieval via Google Gemini embeddings in ChromaDB, and multi-turn stateful order drafting with guided upselling. Before any order is placed, the backend enforces complete fulfillment details, validates phone numbers and table/delivery data, and commits the transaction atomically to SQLite.*
>
> *Administrators have full dashboard visibility over orders, customer histories, and menu knowledge, with real-time status synchronization between admin actions and customer chat responses."*

---

## 2. Top 15 Technical Examination Questions & Model Answers

### Q1: Why did you choose SQLite and SQLAlchemy instead of a NoSQL database like MongoDB?
**Answer**: Restaurant ordering requires ACID transactions (Atomicity, Consistency, Isolation, Durability). When committing an order, we write to both the `Order` and `OrderItem` tables simultaneously. If anything fails, `db.session.rollback()` ensures no partial data is saved. Relational foreign keys also ensure customer-to-order integrity.

### Q2: What happens if an administrator deletes a customer who already has existing orders?
**Answer**: We implemented safe historical order preservation in `app/routes/admin.py::delete_customer`. Instead of cascading the deletion, we set `order.customer_id = None` while preserving the customer's name, phone, address, and order totals directly on the `Order` record. This protects sales and accounting records while fulfilling the customer deletion request.

### Q3: How do you prevent the LLM from hallucinating order numbers like `ORD-99999`?
**Answer**: We employ a dual guardrail. First, in `app/services/agent.py`, the system prompt strictly instructs the model never to claim an order is placed or invent order numbers. Second, in `app/services/graph.py::llm_node`, we have a programmatic guard: if the LLM output contains `ORD-` or claims the order is confirmed, but the database draft has not committed an order code, the graph intercepts the response and presents a confirmation prompt instead.

### Q4: How does the application handle state between multiple user chat turns?
**Answer**: Every conversation has a unique `session_id`. In `app/services/order_session.py`, we maintain an in-memory draft store (`_drafts`). To ensure drafts survive server restarts or memory garbage collection, drafts are serialized to JSON and stored in the SQLite `chat_sessions.draft_data` column on every update.

### Q5: What is the purpose of ChromaDB and how does vector search work here?
**Answer**: ChromaDB is our local vector database stored in `data/chroma_db/`. We chunk restaurant policy and branch documents (`knowledge/details.md`) using `app/services/chunker.py`, convert them to dense vectors using Google's `gemini-embedding-001` via `app/services/embeddings.py`, and store them. When a user asks a policy question, `vector_store.retrieve()` embeds the query and finds the nearest chunks using cosine similarity, injecting that factual context into the LLM prompt.

### Q6: Why did you use LangGraph instead of a standard LangChain chain?
**Answer**: Standard chains execute linearly. In a real restaurant ordering conversation, interactions are non-linear state machines. A customer might ask for the menu, switch to placing an order, ask about branch hours, decline an upselling combo, and finally confirm. LangGraph allows explicit state modeling (`AgentState`), intent routing, and cyclical transitions between nodes.

### Q7: How does the system handle Egyptian phone numbers?
**Answer**: Customers provide phone numbers in varying formats (`+2010...`, `010...`, or `10...`). In `app/services/tools.py::_normalize_egyptian_phone`, we strip country codes and leading zeros so all equivalent numbers resolve to the same unique 10-digit customer record.

### Q8: What are the 4 mandatory fields for a dine-in order?
**Answer**: `customer_name`, `customer_phone`, `table_number`, and `payment_method`. If any of these are missing, `order_session.get_missing_fields()` flags them and the agent prompts for the missing detail.

### Q9: What happens if an admin changes an order status from "In Kitchen" to "Ready"?
**Answer**: The admin submits `POST /orders/status/<id>`. Flask updates the SQLite record. If the customer subsequently asks *"What is my order status ORD-XXXXX?"*, the graph calls `tools.track_order()`, queries SQLite directly, and immediately reports the updated status `Ready`.

### Q10: How do you prevent duplicate order creation if a customer says "confirm" twice?
**Answer**: When an order is confirmed, `commit_confirmed_order()` sets `draft["confirmed_order_code"]` and advances the draft stage to `confirmed`. If another confirmation message arrives, the method detects that an order code already exists and returns the previously created order without generating a new database row.

---

## 3. Live Code Defense Checklist

Before entering your exam, be prepared to open these exact files and explain them:

- [ ] [`app/__init__.py`](file:///c:/Users/Home/Desktop/Rest_Ai-Agent/app/__init__.py): Explain `create_app()` and blueprint registration.
- [ ] [`app/routes/admin.py`](file:///c:/Users/Home/Desktop/Rest_Ai-Agent/app/routes/admin.py#L507-L565): Trace `agent_chat()` and how message history is saved in SQLite.
- [ ] [`app/models/order.py`](file:///c:/Users/Home/Desktop/Rest_Ai-Agent/app/models/order.py#L5-L55): Explain the fields of `Order` and its relationship to `OrderItem`.
- [ ] [`app/services/tools.py`](file:///c:/Users/Home/Desktop/Rest_Ai-Agent/app/services/tools.py#L400-L473): Trace `create_order()` and atomic transaction commits.
- [ ] [`app/services/order_session.py`](file:///c:/Users/Home/Desktop/Rest_Ai-Agent/app/services/order_session.py#L478-L600): Trace `parse_user_entities()` regex matching.
- [ ] [`app/services/graph.py`](file:///c:/Users/Home/Desktop/Rest_Ai-Agent/app/services/graph.py#L705-L733): Trace `build_graph()` nodes and conditional edges.
- [ ] [`app/services/vector_store.py`](file:///c:/Users/Home/Desktop/Rest_Ai-Agent/app/services/vector_store.py#L100-L123): Trace `retrieve()` and cosine similarity matching.
- [ ] [`tests/test_order_management.py`](file:///c:/Users/Home/Desktop/Rest_Ai-Agent/tests/test_order_management.py): Show how 64 test scenarios guarantee system stability.

---

## 🎓 Final Readiness Verdict

You now have a complete, progressive understanding of the entire `Rest_Ai-Agent` repository:
1. **Foundations**: Web requests, templates, and Flask routing.
2. **Persistence**: Relational SQLite schemas, relationships, and ACID safety.
3. **Services**: Deterministic calculations, regex entity extraction, and draft state.
4. **AI Architecture**: Structured system prompt, Google GenAI SDK, and output sanitization.
5. **RAG Pipeline**: Semantic chunking, Gemini embeddings, and ChromaDB search.
6. **Orchestration**: LangGraph StateGraph, conditional edges, and hallucination guardrails.
7. **Verification**: 64 comprehensive regression tests.

Good luck with your technical assessment!
