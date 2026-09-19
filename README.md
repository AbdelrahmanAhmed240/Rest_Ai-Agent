# Restaurant AI Agent

## What It Does

This project is a restaurant-facing AI agent built with Flask.
It answers customer questions, recommends products, and performs real order operations using a relational database.
Administrators can manage menu items, orders, customers, and the RAG knowledge base from a dashboard.

## Main Features

- Customer service conversations
- Product and menu questions
- AI recommendations based on real product data
- RAG knowledge base with Markdown sources
- Order creation, editing, and cancellation
- Conversation context during a session
- Admin dashboard

## Architecture

Customer
→ Flask
→ LangGraph
→ RAG / Tools
→ SQLAlchemy + SQLite
→ Response

## RAG

- Knowledge is stored in Markdown files and `KnowledgeItem` records.
- Documents are split into semantic chunks.
- Embeddings are generated and stored in ChromaDB.
- Retrieval is used when answering restaurant and product questions.
- Admin can add, edit, and delete knowledge from the dashboard.
- Changes are reindexed and immediately available to the agent.

## LangGraph

The agent uses a small LangGraph workflow:

- Router
- Recommendation
- RAG
- Tools
- LLM
- Output

This keeps the flow explicit and prevents the model from acting without the right context.

## Business Actions

The agent can perform real database actions:

- Create order
- Edit order
- Cancel order

Cancellation updates the order status in SQLite; historical records are preserved.

It uses the existing SQLAlchemy models and validation rules.
The database is the source of truth.

## Admin Dashboard

Admin pages manage:

- Products
- Orders
- Customers
- Knowledge/RAG data

## Project Structure

```
app/
  models/
  routes/
  services/
  templates/
knowledge/
config.py
run.py
seed.py
requirements.txt
README.md
```

## Setup

1. Create a virtual environment.
2. Install dependencies.
3. Copy `.env.example` to `.env` and set required variables.
4. Run the server.
5. Visit `http://127.0.0.1:5000`.

## Environment Variables

- `SECRET_KEY`
- `DEBUG`
- `PORT`
- `DATABASE_URI`
- `OPENROUTER_API_KEY`
- `OPENROUTER_BASE_URL`
- `OPENROUTER_MODEL`
- `OPENROUTER_FALLBACK_MODELS`
- `EMBEDDING_MODEL`
- `CHROMA_PERSIST_DIR`
- `AGENT_TEMPERATURE`
- `AGENT_MAX_TOKENS`

Never commit real secret values.

## Demo

1. Customer asks a question.
2. Agent retrieves knowledge.
3. Customer asks for a recommendation.
4. Customer places an order.
5. Order is stored in SQLite.
6. Admin sees the order.
7. Admin updates knowledge.
8. Agent uses the updated knowledge.

## Limitations

- OpenRouter free-tier rate limits may affect live AI calls.
- Conversation history is kept in memory only.
- Order management is basic; no payment gateway.
- Admin forms do not include CSRF protection.
- No Alembic/migration system.
- Meta Messenger integration is not included in this submission.
