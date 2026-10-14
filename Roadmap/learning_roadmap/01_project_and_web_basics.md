# Module 01 — Project Overview and Web Basics

## 1. What Problem Does This Project Solve?
In real-world food and beverage businesses, customer service channels (WhatsApp, web chat, phone calls) often suffer from:
1. High human labor costs during peak ordering hours.
2. Inconsistent pricing information or human error in calculating meal upgrades and delivery fees.
3. Chatbots that hallucinate non-existent items, promise fake delivery times, or invent fake order confirmation codes without actually persisting anything to the database.

**Rest_Ai-Agent** solves this by combining:
- A responsive web dashboard for customers and administrators.
- A deterministic database layer (SQLAlchemy + SQLite) that guarantees ACID transaction safety.
- A semantic knowledge base (ChromaDB + Gemini embeddings) to answer branch and menu policy questions.
- A stateful conversational AI graph (LangGraph + Gemini) that conducts guided upselling, collects fulfillment details step-by-step, and strictly refuses to confirm an order until all mandatory information is verified and committed to disk.

---

## 2. Client-Server Architecture & The HTTP Model
When you run the project and open `http://localhost:5000` in your browser:

```
+------------------+         HTTP GET /dashboard         +------------------------+
|  Browser Client  |  --------------------------------->  |   Flask Server (run.py)|
| (HTML, CSS, JS)  |  <---------------------------------  |   WSGI App             |
+------------------+        HTML Response (200 OK)       +------------------------+
```

1. **Client (Frontend)**: The browser parses HTML, applies Bootstrap CSS styling, and executes JavaScript to handle button clicks and chat interactions.
2. **Server (Backend)**: Flask listens on port `5000` (configurable), intercepts incoming HTTP requests, matches them against registered routes, executes Python logic, queries SQLite, and renders HTML templates or returns JSON.
3. **Stateless HTTP**: HTTP itself is stateless. Every request is independent. To maintain context across chat turns, the application tracks a unique `session_id` string sent with every request.

---

## 3. Entry Points and Configuration

### A. The Server Runner: `run.py`
Open [`run.py`](file:///c:/Users/Home/Desktop/Rest_Ai-Agent/run.py#L1-L14). This is the executable entry point:

```python
# run.py
from app import create_app
from config import config

app = create_app()

if __name__ == "__main__":
    app.run(
        host=config.FLASK_HOST,
        port=config.FLASK_PORT,
        debug=config.FLASK_DEBUG,
    )
```
- **What it does**: It calls `create_app()` to construct the Flask application instance, then boots the local development server on host `0.0.0.0` (or `127.0.0.1`) and port `5000`.

### B. Environment & Configuration: `config.py`
Open [`config.py`](file:///c:/Users/Home/Desktop/Rest_Ai-Agent/config.py#L1-L98).
- **Responsibility**: It loads environment variables from `.env` using `python-dotenv`.
- **Key attributes**:
  - `SQLALCHEMY_DATABASE_URI`: Path to the SQLite database file (`sqlite:///instance/restaurant.db`).
  - `GEMINI_API_KEY`: API key for Google Gemini model calls.
  - `GEMINI_MODEL`: Model name (`gemini-2.5-flash` or fallback).
  - `GEMINI_EMBEDDING_MODEL`: Official Google embedding model (`gemini-embedding-001`).
  - `CHROMA_PERSIST_DIR`: Directory where vector embeddings are saved (`data/chroma_db`).

### C. The Application Factory: `app/__init__.py`
Open [`app/__init__.py`](file:///c:/Users/Home/Desktop/Rest_Ai-Agent/app/__init__.py#L1-L26).
- **Pattern**: Uses Flask's standard **Application Factory Pattern** (`create_app()`).
- **Why this pattern?** Rather than creating a single global `app` object, the factory function lets tests or scripts instantiate separate app instances with custom configurations (e.g., `app.config["TESTING"] = True` in pytest).
```python
def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = config.SECRET_KEY
    app.config["SQLALCHEMY_DATABASE_URI"] = config.SQLALCHEMY_DATABASE_URI
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    from app.routes.admin import admin_bp
    app.register_blueprint(admin_bp)

    with app.app_context():
        db.create_all()

    return app
```
- **Blueprint Registration**: Routes are organized modularly in `app/routes/admin.py` and mounted to the main app via `app.register_blueprint(admin_bp)`.
- **Database Initialization**: `db.init_app(app)` binds SQLAlchemy to the Flask app, and `db.create_all()` ensures all database tables exist before handling incoming requests.

---
👉 **Next**: Continue to [**Module 02: Frontend and Flask Request Lifecycle**](./02_frontend_and_flask.md).