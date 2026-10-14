# Module 03 — Database, SQLAlchemy Schemas, Flask Routes & REST APIs

Welcome to **Module 03**. In this integrated module, we bridge the gap between persistent data storage and web endpoints. 

You will learn how **SQLite** stores data, how **SQLAlchemy** models it into Python objects, and how **Flask Routes & REST APIs** query, mutate, and expose those records to the browser and client applications.

---

## 1. Relational Database Concepts (SQLite & SQLAlchemy ORM)

The project stores all operational data in a lightweight, file-based relational database: **SQLite** ([`instance/restaurant.db`](file:///c:/Users/Home/Desktop/Rest_Ai-Agent/instance/restaurant.db)).

### A. Why an ORM (Object-Relational Mapping)?
Without an ORM, you would write raw SQL strings:
```python
cur.execute("SELECT * FROM products WHERE category = ?", ("Meals",))
```
This is prone to SQL syntax errors and security vulnerabilities (SQL Injection). 

With **SQLAlchemy**, tables are represented as Python classes, and table rows are instances of those classes:
```python
meals = Product.query.filter_by(category="Meals").all()
for meal in meals:
    print(meal.name, meal.price)  # Direct object attributes!
```

### B. Base Database Binding: `app/models/base.py`
Open [`app/models/base.py`](file:///c:/Users/Home/Desktop/Rest_Ai-Agent/app/models/base.py#L1-L4):
```python
from flask_sqlalchemy import SQLAlchemy
db = SQLAlchemy()
```
`db` provides the base declarative model `db.Model`, column types (`db.Column`, `db.Integer`, `db.String`), query interfaces, and the active session (`db.session`).

---

## 2. Complete Database Schema & Model Architecture

The database schema is defined across the model files in [`app/models/`](file:///c:/Users/Home/Desktop/Rest_Ai-Agent/app/models/). It consists of **6 model classes** mapping to **6 active SQLite database tables** (plus the automatic SQLite internal sequence table `sqlite_sequence`):

1. **`Product`** &rarr; `products` ([`app/models/product.py`](file:///c:/Users/Home/Desktop/Rest_Ai-Agent/app/models/product.py))
2. **`Customer`** &rarr; `customers` ([`app/models/customer.py`](file:///c:/Users/Home/Desktop/Rest_Ai-Agent/app/models/customer.py))
3. **`Order`** &rarr; `orders` ([`app/models/order.py`](file:///c:/Users/Home/Desktop/Rest_Ai-Agent/app/models/order.py))
4. **`OrderItem`** &rarr; `order_items` ([`app/models/order.py`](file:///c:/Users/Home/Desktop/Rest_Ai-Agent/app/models/order.py))
5. **`KnowledgeItem`** &rarr; `knowledge_items` ([`app/models/knowledge.py`](file:///c:/Users/Home/Desktop/Rest_Ai-Agent/app/models/knowledge.py))
6. **`ChatSession`** &rarr; `chat_sessions` ([`app/models/chat.py`](file:///c:/Users/Home/Desktop/Rest_Ai-Agent/app/models/chat.py))
7. **`ChatMessage`** &rarr; `chat_messages` ([`app/models/chat.py`](file:///c:/Users/Home/Desktop/Rest_Ai-Agent/app/models/chat.py))

*(Note: In `app/models/__init__.py`, `Order` and `OrderItem` share `app/models/order.py`, while `ChatSession` and `ChatMessage` share `app/models/chat.py`).*

---

### Entity-Relationship Diagram (ERD)

The diagram below illustrates the exact foreign keys and SQLAlchemy relationships defined in the source code:

```
+------------------------------------+             +------------------------------------+
|             customers              |             |            chat_sessions           |
+------------------------------------+             +------------------------------------+
| PK: id (Integer)                   |             | PK: id (Integer)                   |
| UQ: phone (String 20)              |             | UQ: session_id (String 100)        |
+------------------------------------+             +------------------------------------+
                  |                                                  |
                  | 1 : N (One Customer has Many Orders)             | 1 : N (One Session has Many Messages)
                  | FK: customer_id (NULLABLE!)                      | FK: session_id -> chat_sessions.session_id
                  v                                                  v
+------------------------------------+             +------------------------------------+
|               orders               |             |            chat_messages           |
+------------------------------------+             +------------------------------------+
| PK: id (Integer)                   |             | PK: id (Integer)                   |
| UQ: order_code (String 30)         |             | FK: session_id (String 100)        |
| FK: customer_id (Integer, Nullable)|             | role (String 20: user | assistant) |
+------------------------------------+             +------------------------------------+
                  |
                  | 1 : N (One Order has Many Items)
                  | FK: order_id -> orders.id
                  | cascade="all, delete-orphan"
                  v
+------------------------------------+             +------------------------------------+
|            order_items             |             |              products              |
+------------------------------------+             +------------------------------------+
| PK: id (Integer)                   |             | PK: id (Integer)                   |
| FK: order_id (Integer)             |             | UQ: name (String 150)              |
| FK: product_id (Integer, Nullable) |<------------| category, price, combo_price       |
+------------------------------------+  N : 1 Ref  +------------------------------------+

+------------------------------------+
|          knowledge_items           |  (Standalone RAG metadata & chunk store)
+------------------------------------+
| PK: id (Integer)                   |
| title, category, content           |
| source_path (Indexed)              |
+------------------------------------+
```

---

### Model Breakdown & Column Specifications

#### 1. `Product` Model (`products` table)
Defined in [`app/models/product.py`](file:///c:/Users/Home/Desktop/Rest_Ai-Agent/app/models/product.py). Represents available food items, sandwiches, meals, drinks, and add-ons.

| Column | Data Type | Constraints & Flags | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `Integer` | Primary Key, Autoincrement | *Auto* | Unique product record identifier. |
| `name` | `String(150)` | `nullable=False`, `unique=True`, `index=True` | — | Unique dish name (e.g. `وجبة بريك`, `بسمتيو`). |
| `category` | `String(50)` | `nullable=False`, `index=True` | — | Grouping category (`Meals`, `Sandwiches`, `Drinks`, `Add-ons`). |
| `description` | `Text` | `nullable=True` | `None` | Detailed ingredients and meal contents. |
| `price` | `Float` | `nullable=False` | — | Base price in Egyptian Pounds (EGP). |
| `combo_price` | `Float` | `nullable=True` | `0.0` | Surcharge for fries + drink combo upgrade (typically 50 EGP). |
| `is_available` | `Boolean` | `nullable=False` | `True` | Stock availability toggle for catalog and ordering. |
| `created_at` | `DateTime` | `nullable=True` | `utcnow` | Creation timestamp. |

---

#### 2. `Customer` Model (`customers` table)
Defined in [`app/models/customer.py`](file:///c:/Users/Home/Desktop/Rest_Ai-Agent/app/models/customer.py). Represents unique restaurant customers identified primarily by normalized mobile phone numbers.

| Column | Data Type | Constraints & Flags | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `Integer` | Primary Key, Autoincrement | *Auto* | Unique customer identifier. |
| `phone` | `String(20)` | `nullable=False`, `unique=True`, `index=True` | — | Egyptian phone number (unique customer identifier). |
| `name` | `String(100)` | `nullable=True` | `None` | Customer full name. |
| `address` | `String(255)` | `nullable=True` | `None` | Default/last-used delivery address. |
| `created_at` | `DateTime` | `nullable=True` | `utcnow` | Customer registration timestamp. |

- **SQLAlchemy Relationship**:
  - `orders = db.relationship("Order", back_populates="customer")`: One-to-many relationship linking a customer to all their historical orders.

---

#### 3. `Order` Model (`orders` table)
Defined in [`app/models/order.py`](file:///c:/Users/Home/Desktop/Rest_Ai-Agent/app/models/order.py). Represents finalized customer transactions across all fulfillment types (Delivery, Pickup, Dine-in).

| Column | Data Type | Constraints & Flags | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `Integer` | Primary Key, Autoincrement | *Auto* | Unique internal order ID. |
| `order_code` | `String(30)` | `nullable=False`, `unique=True`, `index=True` | — | Public tracking code (e.g. `ORD-21231`). |
| `customer_id` | `Integer` | `ForeignKey("customers.id")`, **`nullable=True`** | `None` | Foreign key referencing `customers.id`. Nullable for historical preservation! |
| `customer_name` | `String(100)` | `nullable=True` | `None` | Static snapshot of customer name at order placement. |
| `customer_phone`| `String(20)` | `nullable=True` | `None` | Static snapshot of customer phone at order placement. |
| `order_type` | `String(20)` | `nullable=False` | `"delivery"` | Fulfillment type: `"delivery"`, `"pickup"`, or `"dine_in"`. |
| `payment_method`| `String(20)` | `nullable=False` | `"Cash"` | Payment method: `"Cash"` or `"Visa"`. |
| `delivery_address`| `String(255)`| `nullable=True` | `None` | Delivery destination address (for delivery orders). |
| `pickup_branch` | `String(100)`| `nullable=True` | `None` | Branch name selected for customer pickup. |
| `table_number` | `String(50)` | `nullable=True` | `None` | Table identifier in restaurant (for dine-in orders). |
| `status` | `String(30)` | `nullable=False` | `"In Kitchen"` | Order lifecycle status: `"In Kitchen"`, `"Ready"`, `"Delivered"`, `"Cancelled"`. |
| `total_price` | `Float` | `nullable=False` | `0.0` | Sum of all line items and upgrades in EGP. |
| `created_at` | `DateTime` | `nullable=False` | `utcnow` | Order submission timestamp. |

- **SQLAlchemy Relationships**:
  - `customer = db.relationship("Customer", back_populates="orders")`: Many-to-one relationship back to the customer profile.
  - `items = db.relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")`: One-to-many relationship with order items. If an `Order` row is deleted, all its `OrderItem` rows are deleted automatically (`delete-orphan`).

---

#### 4. `OrderItem` Model (`order_items` table)
Defined in [`app/models/order.py`](file:///c:/Users/Home/Desktop/Rest_Ai-Agent/app/models/order.py). Represents individual line items belonging to an order.

| Column | Data Type | Constraints & Flags | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `Integer` | Primary Key, Autoincrement | *Auto* | Unique order item ID. |
| `order_id` | `Integer` | `ForeignKey("orders.id")`, `nullable=False` | — | Foreign key linking this item to its parent order. |
| `product_id` | `Integer` | `ForeignKey("products.id")`, `nullable=True` | `None` | Foreign key pointing to the catalog product. |
| `product_name` | `String(150)`| `nullable=False` | — | Name of item preserved as text. |
| `quantity` | `Integer` | `nullable=False` | `1` | Quantity ordered. |
| `unit_price` | `Float` | `nullable=False` | — | Final unit price (including combo upgrade fee if selected). |
| `line_total` | `Float` | `nullable=False` | — | Calculated line total (`unit_price * quantity`). |
| `notes` | `String(255)`| `nullable=True` | `None` | Special instructions (e.g. `"Extra garlic dip, Spicy"`). |

- **SQLAlchemy Relationships**:
  - `order = db.relationship("Order", back_populates="items")`: Many-to-one link to parent order.
  - `product = db.relationship("Product")`: Many-to-one reference to the catalog product.

---

#### 5. `KnowledgeItem` Model (`knowledge_items` table)
Defined in [`app/models/knowledge.py`](file:///c:/Users/Home/Desktop/Rest_Ai-Agent/app/models/knowledge.py). Stores raw RAG knowledge chunks in SQL, synchronized to ChromaDB vectors.

| Column | Data Type | Constraints & Flags | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `Integer` | Primary Key, Autoincrement | *Auto* | Unique knowledge chunk ID. |
| `title` | `String(150)` | `nullable=False` | — | Section title (e.g. `"Branches & Hours"`). |
| `category` | `String(50)` | `nullable=False` | `"General"` | Knowledge category (`Menu`, `Branches`, `Hours`, `Policies`, `Offers`). |
| `content` | `Text` | `nullable=False` | — | Full markdown body text indexed for search. |
| `source_path` | `String(255)` | `nullable=True`, `index=True` | `None` | Relative markdown filename (e.g. `"details.md"`). |
| `created_at` | `DateTime` | `nullable=True` | `utcnow` | Initial indexing timestamp. |
| `updated_at` | `DateTime` | `nullable=True`, `onupdate=utcnow` | `utcnow` | Last update/re-sync timestamp. |

---

#### 6. `ChatSession` Model (`chat_sessions` table)
Defined in [`app/models/chat.py`](file:///c:/Users/Home/Desktop/Rest_Ai-Agent/app/models/chat.py). Manages persistent, independent conversation sessions in the chat UI.

| Column | Data Type | Constraints & Flags | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `Integer` | Primary Key, Autoincrement | *Auto* | Unique session record ID. |
| `session_id` | `String(100)` | `nullable=False`, `unique=True`, `index=True` | — | Session token string (e.g. `"chat_1791753145_675af"`). |
| `title` | `String(150)` | `nullable=False` | `"New Chat"`| Sidebar title (e.g. `"Chat 1"`, `"Dinner Order"`). |
| `created_at` | `DateTime` | `nullable=False` | `utcnow` | Session creation time. |
| `updated_at` | `DateTime` | `nullable=False` | `utcnow` | Timestamp of latest message in session. |
| `draft_data` | `Text` | `nullable=True` | `None` | **JSON-serialized order draft**. Ensures in-progress orders survive browser reloads or server restarts! |

- **SQLAlchemy Relationship**:
  - `messages = db.relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan", order_by="ChatMessage.created_at.asc()")`: One-to-many relationship with conversation messages. Deleting a session deletes all its messages.

---

#### 7. `ChatMessage` Model (`chat_messages` table)
Defined in [`app/models/chat.py`](file:///c:/Users/Home/Desktop/Rest_Ai-Agent/app/models/chat.py). Stores individual chat turns for each conversation session.

| Column | Data Type | Constraints & Flags | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `Integer` | Primary Key, Autoincrement | *Auto* | Unique message ID. |
| `session_id` | `String(100)` | `ForeignKey("chat_sessions.session_id")`, `nullable=False`, `index=True` | — | Foreign key referencing `chat_sessions.session_id`. |
| `role` | `String(20)` | `nullable=False` | — | Sender role: `"user"` or `"assistant"`. |
| `content` | `Text` | `nullable=False` | — | Raw message text. |
| `html_content` | `Text` | `nullable=True` | `None` | Sanitized rendered HTML for browser display. |
| `created_at` | `DateTime` | `nullable=False` | `utcnow` | Message timestamp. |

- **SQLAlchemy Relationship**:
  - `session = db.relationship("ChatSession", back_populates="messages")`: Many-to-one link to the owning session.

---

### Architectural Design Decisions Highlighted

1. **Physical FK Constraint vs SQLAlchemy Relationship**:
   - `ForeignKey("table.column")` creates a physical integrity rule in SQLite.
   - `db.relationship(...)` is a pure Python abstraction enabling direct property access (`order.items`, `customer.orders`, `session.messages`) without writing manual SQL joins.
2. **Historical Order Preservation**:
   - In `Order`, `customer_id` is intentionally **nullable** (`nullable=True`), and `customer_name` + `customer_phone` are duplicated directly onto `Order`. When a customer is deleted in the admin dashboard, `customer_id` is set to `None`, preserving sales history and financial records.
3. **Draft Serialization (`draft_data`)**:
   - The conversational agent keeps the draft in memory for fast entity parsing, but serializes it to `ChatSession.draft_data` on every message. This prevents the classic chatbot bug where refreshing the browser drops the pending order.
4. **Cascading Deletions**:
   - `cascade="all, delete-orphan"` is strictly used where child records have no independent meaning without their parent: deleting an `Order` deletes its `order_items`, and deleting a `ChatSession` deletes its `chat_messages`.

---

## 3. Database Transactions: Commit, Rollback, and Data Safety

When confirming an order, we must create 1 `Order` row and multiple `OrderItem` rows.
What happens if the power cuts off or disk fills up while creating item #2?

In [`app/services/tools.py::create_order`](file:///c:/Users/Home/Desktop/Rest_Ai-Agent/app/services/tools.py#L400-L473):
```python
try:
    order = Order(...)
    db.session.add(order)
    db.session.flush()  # Allocates order.id without finalizing the transaction

    for item_data in items:
        item = OrderItem(order_id=order.id, ...)
        db.session.add(item)

    db.session.commit()  # ATOMIC COMMIT: Everything succeeds together!
    return {"ok": True, "order_code": order.order_code}
except Exception as exc:
    db.session.rollback()  # Safely aborts: Zero half-created records left behind!
    return {"ok": False, "error": str(exc)}
```

### The Historical Preservation Pattern
If an administrator deletes a customer who placed 5 orders:
- In [`app/routes/admin.py::delete_customer`](file:///c:/Users/Home/Desktop/Rest_Ai-Agent/app/routes/admin.py#L238-L264):
  1. We detach the customer: `order.customer_id = None`.
  2. We ensure `customer_name` and `customer_phone` remain as static strings on `Order`.
  3. We delete the `Customer` record.
  4. **Result:** Past accounting, sales revenue, and item history are safely preserved!

---

## 4. Flask Routes & Server-Rendered Views

All web endpoints are defined in [`app/routes/admin.py`](file:///c:/Users/Home/Desktop/Rest_Ai-Agent/app/routes/admin.py) using a Flask **Blueprint**:
```python
admin_bp = Blueprint("admin", __name__)
```

### A. Dashboard Overview: `GET /` & `GET /dashboard`
Lines 10–28 of `admin.py`:
- Queries summary counts: `Product.query.count()`, `Customer.query.count()`, `Order.query.count()`.
- Fetches the 5 most recent orders: `Order.query.order_by(Order.created_at.desc()).limit(5).all()`.
- Renders `dashboard.html`.

### B. Product Catalog Management
- **`GET  /products`** (L31–53): Lists menu items with category filtering (`?category=Meals`) and search (`?q=بروستد`).
- **`POST /products/new`** (L56–96): Reads form data, validates required fields, creates `Product`, commits, and redirects.
- **`POST /products/edit/<int:product_id>`** (L99–138): Updates existing dish pricing and availability.
- **`POST /products/delete/<int:product_id>`** (L140–158): Deletes a dish with error handling.

### C. Orders Management: `GET /orders` & `POST /orders/status/<id>`
Lines 160–210 of `admin.py`:
- Filter orders by type (`delivery`, `pickup`, `dine_in`) and status (`In Kitchen`, `Ready`, `Delivered`, `Cancelled`).
- **Status Transition Endpoint**:
  ```python
  @admin_bp.route("/orders/status/<int:order_id>", methods=["POST"])
  def update_order_status(order_id):
      order = db.get_or_404(Order, order_id)
      new_status = request.form.get("status", "").strip()
      if new_status in ["In Kitchen", "Ready", "Delivered", "Cancelled"]:
          order.status = new_status
          db.session.commit()
          flash(f"Order {order.order_code} status updated to {new_status}.", "success")
      return redirect(url_for("admin.orders"))
  ```

---

## 5. REST APIs & Asynchronous Endpoints

Unlike form submissions that trigger a full page reload, the interactive AI chat and session manager use asynchronous **REST APIs** returning **JSON payloads**.

### A. The Core AI Chat API: `POST /agent/chat`
Lines 508–564 of `admin.py`:
1. **Reads JSON request**:
   ```python
   data = request.get_json(silent=True) or {}
   session_id = data.get("session_id", "default")
   message = data.get("message", "")
   ```
2. **Auto-creates session**: If `session_id` does not exist in SQLite, generates a `ChatSession`.
3. **Persists User Message**: Saves a new `ChatMessage(role="user", content=message)`.
4. **Executes AI Pipeline**: Calls `graph_run(session_id=session_id, message=message)`.
5. **Sanitizes Markdown**: Runs `_render_chat_markdown()` to produce safe HTML.
6. **Persists Assistant Message**: Saves `ChatMessage(role="assistant", content=reply, html_content=html)`.
7. **Returns JSON Response (HTTP 200)**:
   ```json
   {
       "session_id": "chat_01",
       "message": "Welcome! Here is our menu...",
       "html": "<p>Welcome! Here is our menu...</p>",
       "intent": "restaurant_product"
   }
   ```

### B. Persistent Chat Sessions REST Endpoints
- **`GET /agent/sessions`** (L566–579): Returns a JSON array of all chat sessions ordered by `updated_at DESC`.
- **`POST /agent/sessions`** (L581–593): Creates a new independent chat session (returns HTTP 201 Created).
- **`GET /agent/sessions/<session_id>/messages`** (L595–603): Fetches all historical messages for the selected session.