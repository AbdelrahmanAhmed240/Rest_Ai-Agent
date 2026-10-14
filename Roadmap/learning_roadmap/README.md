# Rest_Ai-Agent — Complete Step-by-Step Learning Roadmap

Welcome to the comprehensive, progressive learning guide for the **Rest_Ai-Agent** repository.

This roadmap is designed for computer engineering and software engineering students who already know fundamental Python and web development concepts, and want to master every layer of this conversational AI restaurant ordering and administration system.

---

## 🗺️ Learning Path Structure (Easiest to Hardest)

The roadmap is divided into structured modules, arranged in strict prerequisite order so you never encounter advanced AI concepts before understanding basic web flows, database transactions, and API endpoints:

1. [**01_project_and_web_basics.md**](./01_project_and_web_basics.md)
   - What the project is and why it exists.
   - Client-Server architecture and the HTTP Request/Response model.
   - The role of Flask, `run.py`, and `config.py`.
   - Application Factory pattern in `app/__init__.py`.

2. [**02_frontend_and_flask.md**](./02_frontend_and_flask.md)
   - Jinja2 template inheritance (`base.html`, `dashboard.html`, `orders.html`).
   - The frontend chat UI: Chat switching, creation, deletion, and local storage.
   - Event listeners and `fetch()` POST requests to the Flask API.
   - Admin management forms and modal workflows.

3. [**03_database_and_business_logic.md**](./03_database_and_business_logic.md) *(Integrated Module)*
   - **Database & SQLAlchemy**: SQLite file storage, declarative base, and the ORM concept.
   - **Database Schemas & Models**: Complete breakdown of all 7 tables (`products`, `customers`, `orders`, `order_items`, `knowledge_items`, `chat_sessions`, `chat_messages`).
   - **Relationships & Data Integrity**: Primary keys, foreign keys, 1-to-many relationships, and historical order preservation.
   - **ACID Transactions**: Session management, `db.session.flush()`, `commit()`, and error `rollback()`.
   - **Flask Routes & Views**: Blueprint routing in `admin.py`, dashboard metrics, and admin CRUD handlers.
   - **REST APIs & JSON**: Asynchronous `/agent/chat` pipeline, markdown sanitization, and persistent chat session endpoints.

4. [**04_supporting_services.md**](./04_supporting_services.md)
   - The Service Layer architecture: Separating routes from business logic.
   - `app/services/tools.py`: Deterministic catalog queries, price calculations, and atomic order creation.
   - `app/services/order_session.py`: In-memory draft management, DB persistence synchronization, and Arabic/English regex entity extraction.

5. [**05_ai_and_llm.md**](./05_ai_and_llm.md)
   - What Large Language Models (LLMs) do in conversational commerce.
   - Official Google GenAI SDK integration in `app/services/agent.py`.
   - The 6-part structured system prompt (Role, Task, Context, Constraints, Examples, Notes).
   - Rate limiting, fallback models, and output sanitization (`_strip_reasoning`).

6. [**06_rag_and_vector_search.md**](./06_rag_and_vector_search.md)
   - Retrieval-Augmented Generation (RAG): Why the LLM cannot memorize live prices and branch policies.
   - Markdown knowledge documents (`knowledge/menu.md`, `details.md`).
   - Chunking documents into semantic units (`app/services/chunker.py`).
   - Text embeddings via `gemini-embedding-001` (`app/services/embeddings.py`).
   - Persistent vector storage and semantic querying via ChromaDB (`app/services/vector_store.py`).
   - Automated bi-directional synchronization (`app/services/knowledge_sync.py`).

7. [**07_langgraph_and_orchestration.md**](./07_langgraph_and_orchestration.md)
   - Why simple chat loops fail for complex transaction flows.
   - StateGraph architecture, `AgentState` typed dictionary, nodes, and edges.
   - Intent classification router (`router_node` and `_route_intent`).
   - Dedicated 2-path workflow nodes: `rag_node` (informational Q&A), `order_tool_node` (drafting & order operations), and `llm_node`.
   - Strict hallucination prevention guardrails.

8. [**08_end_to_end_workflows.md**](./08_end_to_end_workflows.md)
   - Scenario 1: Menu catalog inquiry and price comparisons.
   - Scenario 2: Semantic question answered via ChromaDB RAG.
   - Scenario 3: Complete conversational food order with guided upselling, fulfillment details extraction, and database confirmation.
   - Scenario 4: Admin order status update and live chatbot status synchronization.
   - Scenario 5: Safe customer deletion with historical order preservation.

9. [**09_testing_and_debugging.md**](./09_testing_and_debugging.md)
   - Pytest test architecture and Flask test client fixture (`tests/test_order_management.py`).
   - The 10 functional test categories covering 64 regression scenarios.
   - Tracing failed assertions and debugging state leakage across test runs.
   - Verifying transaction rollbacks on disk failures.

10. [**10_technical_assessment.md**](./10_technical_assessment.md)
    - 2-Minute project elevator pitch for examiners.
    - System architecture walk-through and architectural trade-offs defense.
    - 25 Anticipated technical examination questions with model answers.
    - Live code-tracing defense checklist.

---

## ⏱️ Recommended Study Schedule

| Mastery Level | Goal | Recommended Timeline | Modules to Focus On |
| :--- | :--- | :--- | :--- |
| **Level 1: Foundations** | Understand & explain the full web app, models, database schemas, and REST APIs | 2 to 3 days (6–8 hours) | Modules 01, 02, 03, 04 |
| **Level 2: AI & RAG** | Trace the AI pipeline, embeddings, ChromaDB, and LangGraph | 3 to 4 days (8–10 hours) | Modules 05, 06, 07, 08 |
| **Level 3: Defense Mastery**| Debug edge cases, understand tests, and defend architectural decisions | 2 days (4–6 hours) | Modules 09, 10 |

**Total Estimated Study Time:** ~18 to 24 focused hours.

---

## 📌 Getting Started

Continue your journey with the integrated [**Module 03: Database, SQLAlchemy Schemas, Flask Routes & REST APIs**](./03_database_and_business_logic.md)!
