"""
Slindo's Eatery — Flask Backend (Postgres Edition)
===================================================
Endpoints:
  GET  /          → health check (also confirms DB connectivity)
  GET  /status    → store open/closed status
  GET  /menu      → full menu as JSON
  POST /order     → place a new order (persisted to Postgres)
  GET  /orders    → retrieve all stored orders (with optional filters)

Environment variables required:
  DATABASE_URL    → Postgres connection string (Render injects this automatically
                    when you add a Postgres service to your project)
  PORT            → HTTP port (Render/Railway inject this automatically)
  TZ              → Set to "Africa/Johannesburg" in Render dashboard to ensure
                    business hours use South African time (UTC+2)

Deploy on Render:
  1. Push app.py + requirements.txt to GitHub
  2. Create a new Web Service → connect repo
  3. Build command : pip install -r requirements.txt
  4. Start command : gunicorn app:app
  5. Add a Postgres database in Render → it auto-sets DATABASE_URL
  6. Add env var TZ = Africa/Johannesburg
"""

import os
import uuid
from datetime import datetime

from flask import Flask, request, jsonify
from flask_cors import CORS
from sqlalchemy import (
    create_engine, Column, String, Integer, DateTime, Text, text
)
from sqlalchemy.orm import DeclarativeBase, sessionmaker, scoped_session
from sqlalchemy.dialects.postgresql import JSONB


# ── App setup ──────────────────────────────────────────────────────────────────
app = Flask(__name__)
CORS(app)   # Allow cross-origin requests from the HTML front-end


# ── Database setup ─────────────────────────────────────────────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Render provides Postgres URLs starting with "postgres://" but SQLAlchemy 2.x
# requires "postgresql://".  Fix it silently if needed.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL environment variable is not set.\n"
        "Add a Postgres database to your Render project and it will be "
        "injected automatically, or set DATABASE_URL manually for local dev.\n"
        "Local example: postgresql://user:password@localhost:5432/slindos"
    )

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,         # test connections before using (handles Render sleep)
    pool_recycle=300,           # recycle connections every 5 minutes
    pool_size=5,                # keep up to 5 idle connections open
    max_overflow=10,            # allow 10 extra connections under load
    connect_args={
        "connect_timeout": 10   # fail fast if Postgres is unreachable
    }
)

# Scoped session — thread-safe, one session per request
SessionFactory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Session = scoped_session(SessionFactory)


# ── ORM Model ─────────────────────────────────────────────────────────────────
class Base(DeclarativeBase):
    pass


class Order(Base):
    """Represents a single customer order stored in Postgres."""
    __tablename__ = "orders"

    order_id             = Column(String(8),   primary_key=True)
    timestamp            = Column(DateTime,    nullable=False, default=datetime.utcnow)
    customer_name        = Column(String(255), nullable=False)
    contact_number       = Column(String(50),  nullable=False)
    order_type           = Column(String(20),  nullable=False)   # Pickup | Delivery
    delivery_address     = Column(Text,        nullable=True)
    payment_method       = Column(String(50),  nullable=False)
    items                = Column(JSONB,        nullable=False)   # list of order line dicts
    order_total          = Column(Integer,      nullable=False)   # total in Rands (whole number)
    special_instructions = Column(Text,        nullable=True)
    status               = Column(String(30),  nullable=False, default="Received")

    def to_dict(self):
        """Serialise the ORM object to a plain dict for JSON responses."""
        return {
            "order_id":             self.order_id,
            "timestamp":            self.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "customer_name":        self.customer_name,
            "contact_number":       self.contact_number,
            "order_type":           self.order_type,
            "delivery_address":     self.delivery_address or "",
            "payment_method":       self.payment_method,
            "items":                self.items,
            "order_total":          self.order_total,
            "special_instructions": self.special_instructions or "",
            "status":               self.status,
        }


# Create the table if it doesn't exist yet — safe to run on every deploy
with app.app_context():
    Base.metadata.create_all(engine)


# ── Teardown: close DB session after every request ─────────────────────────────
@app.teardown_appcontext
def shutdown_session(exception=None):
    Session.remove()


# ── Menu data ─────────────────────────────────────────────────────────────────
MENU = {
    "restaurant": "Slindo's Eatery",
    "slogan": "It's time for iKota",
    "location": "King William's Town / eQonce",
    "contact": "068 116 1511",
    "hours": "Monday – Sunday, 09:00 – 20:00",
    "categories": [
        {
            "name": "Wings & Chips",
            "items": [
                {
                    "id": "wings_4",
                    "name": "4 Wings & Chips",
                    "description": "Crispy chicken wings served with golden chips",
                    "price": 40
                },
                {
                    "id": "wings_6",
                    "name": "6 Wings & Chips",
                    "description": "Crispy chicken wings served with golden chips",
                    "price": 60
                },
                {
                    "id": "wings_10",
                    "name": "10 Wings & Chips",
                    "description": "Feast mode — wings & chips for the whole squad",
                    "price": 90
                }
            ]
        },
        {
            "name": "The Kota",
            "items": [
                {
                    "id": "kota_supa",
                    "name": "Supa Kota",
                    "description": "White toasted bread, chips, polony, burger patty, cheese, vienna, Russian sausage, egg",
                    "price": 45
                },
                {
                    "id": "kota_mega",
                    "name": "Mega Kota",
                    "description": "White toasted bread, chips, burger patty, cheese, Russian sausage",
                    "price": 40
                },
                {
                    "id": "kota_regular",
                    "name": "Regular Kota",
                    "description": "White toasted bread, chips, polony, cheese, vienna",
                    "price": 35
                },
                {
                    "id": "kota_budget",
                    "name": "Budget Kota",
                    "description": "White toasted bread, chips, burger patty, egg",
                    "price": 30
                }
            ]
        }
    ],
    "payment_methods": ["Cash on Collection", "EFT / Bank Transfer", "Capitec Pay"],
    "banking_details": {
        "bank":           "ABSA",
        "account_name":   "Slindo's Eatery",
        "account_number": "4121776528",
        "reference":      "Your name + order ID"
    },
    "delivery_note": "Pick-up available. Delivery around King William's Town / eQonce at extra cost."
}

# Flat lookup: item_id → menu item dict (for validation + pricing)
ITEM_LOOKUP = {
    item["id"]: item
    for category in MENU["categories"]
    for item in category["items"]
}


# ── Helpers ───────────────────────────────────────────────────────────────────
def error(message, status=400):
    """Return a consistent error JSON response."""
    return jsonify({"success": False, "error": message}), status


# ── Business hours ─────────────────────────────────────────────────────────────
OPEN_HOUR  = 9    # 09:00
CLOSE_HOUR = 20   # 20:00

def is_open():
    """
    Return True if the current server time is within business hours.
    Set TZ=Africa/Johannesburg on Render so datetime.now() reflects SAST (UTC+2).
    """
    now = datetime.now()
    return OPEN_HOUR <= now.hour < CLOSE_HOUR


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def health():
    """
    Health check — confirms the app is running and Postgres is reachable.
    Render uses this endpoint for uptime monitoring.
    """
    db_ok = False
    try:
        Session.execute(text("SELECT 1"))
        db_ok = True
    except Exception as e:
        app.logger.error(f"DB health check failed: {e}")

    return jsonify({
        "status":     "online",
        "database":   "connected" if db_ok else "unreachable",
        "restaurant": "Slindo's Eatery",
        "message":    "It's time for iKota 🍞"
    }), 200 if db_ok else 503


@app.route("/status", methods=["GET"])
def store_status():
    """Returns whether the store is currently open or closed."""
    now   = datetime.now()
    open_ = is_open()
    return jsonify({
        "open":           open_,
        "status":         "open" if open_ else "closed",
        "server_time":    now.strftime("%H:%M"),
        "business_hours": f"{OPEN_HOUR:02d}:00 – {CLOSE_HOUR:02d}:00",
        "message":        "We're open, come order! 🍞" if open_
                          else "Ordering is closed. Please come back during business hours."
    })


@app.route("/menu", methods=["GET"])
def get_menu():
    """Return the full menu as JSON."""
    return jsonify({"success": True, "menu": MENU})


@app.route("/order", methods=["POST"])
def place_order():
    """
    Validate, price, and persist a new order to Postgres.

    Expected JSON body:
    {
        "customer_name":        "Thabo Mokoena",
        "contact_number":       "071 234 5678",
        "order_type":           "Pickup" | "Delivery",
        "delivery_address":     "123 Main St, eQonce",   // required if Delivery
        "payment_method":       "Cash on Collection",
        "items": [
            { "item_id": "kota_supa", "quantity": 2 },
            { "item_id": "wings_6",   "quantity": 1 }
        ],
        "special_instructions": "Extra spicy please"     // optional
    }
    """
    # ── 1. Business hours gate ────────────────────────────────────────────────
    if not is_open():
        return jsonify({
            "success":        False,
            "message":        "Ordering is closed. Please come back during business hours.",
            "business_hours": f"{OPEN_HOUR:02d}:00 – {CLOSE_HOUR:02d}:00",
            "server_time":    datetime.now().strftime("%H:%M")
        }), 503

    # ── 2. Parse JSON body ────────────────────────────────────────────────────
    data = request.get_json(silent=True)
    if not data:
        return error("Request body must be valid JSON.")

    # ── 3. Required field presence check ─────────────────────────────────────
    required = ["customer_name", "contact_number", "order_type", "payment_method", "items"]
    for field in required:
        if not data.get(field):
            return error(f"Missing required field: '{field}'.")

    customer_name   = str(data["customer_name"]).strip()
    contact_number  = str(data["contact_number"]).strip()
    order_type      = str(data["order_type"]).strip()
    payment_method  = str(data["payment_method"]).strip()
    items_requested = data["items"]
    special_note    = str(data.get("special_instructions", "")).strip()

    # ── 4. Validate order_type ────────────────────────────────────────────────
    valid_order_types = ["Pickup", "Delivery"]
    if order_type not in valid_order_types:
        return error(f"'order_type' must be one of: {valid_order_types}.")

    # ── 5. Delivery address required for deliveries ───────────────────────────
    delivery_address = ""
    if order_type == "Delivery":
        delivery_address = str(data.get("delivery_address", "")).strip()
        if not delivery_address:
            return error("'delivery_address' is required when order_type is 'Delivery'.")

    # ── 6. Validate payment method ────────────────────────────────────────────
    if payment_method not in MENU["payment_methods"]:
        return error(f"'payment_method' must be one of: {MENU['payment_methods']}.")

    # ── 7. Validate and price each requested item ─────────────────────────────
    if not isinstance(items_requested, list) or len(items_requested) == 0:
        return error("'items' must be a non-empty list.")

    order_lines = []
    order_total = 0

    for i, entry in enumerate(items_requested):
        if not isinstance(entry, dict):
            return error(f"Item at index {i} must be an object with 'item_id' and 'quantity'.")

        item_id  = str(entry.get("item_id", "")).strip()
        quantity = entry.get("quantity", 1)

        if not item_id:
            return error(f"Item at index {i} is missing 'item_id'.")

        if item_id not in ITEM_LOOKUP:
            return error(f"Unknown item_id '{item_id}'. Check GET /menu for valid IDs.")

        try:
            quantity = int(quantity)
        except (TypeError, ValueError):
            return error(f"'quantity' for item '{item_id}' must be an integer.")

        if quantity < 1 or quantity > 50:
            return error(f"'quantity' for item '{item_id}' must be between 1 and 50.")

        menu_item    = ITEM_LOOKUP[item_id]
        subtotal     = menu_item["price"] * quantity
        order_total += subtotal

        order_lines.append({
            "item_id":    item_id,
            "name":       menu_item["name"],
            "quantity":   quantity,
            "unit_price": menu_item["price"],
            "subtotal":   subtotal
        })

    # ── 8. Build ORM object and persist to Postgres ───────────────────────────
    new_order = Order(
        order_id             = str(uuid.uuid4())[:8].upper(),
        timestamp            = datetime.utcnow(),
        customer_name        = customer_name,
        contact_number       = contact_number,
        order_type           = order_type,
        delivery_address     = delivery_address or None,
        payment_method       = payment_method,
        items                = order_lines,      # JSONB column accepts a Python list directly
        order_total          = order_total,
        special_instructions = special_note or None,
        status               = "Received"
    )

    try:
        Session.add(new_order)
        Session.commit()
    except Exception as e:
        Session.rollback()
        app.logger.error(f"DB insert failed: {e}")
        return error("Database error — could not save the order. Please try again.", 500)

    return jsonify({
        "success": True,
        "message": f"Order received! We'll be in touch on {contact_number} 🍞",
        "order":   new_order.to_dict()
    }), 201


@app.route("/orders", methods=["GET"])
def get_orders():
    """
    Return all stored orders from Postgres.

    Optional query params:
      ?status=Received   → filter by order status (case-insensitive)
      ?name=thabo        → filter by customer name (case-insensitive, partial match)
      ?limit=50          → max records to return (default 100, capped at 500)
      ?offset=0          → pagination offset (default 0)

    Orders are returned newest-first.
    """
    try:
        query = Session.query(Order)

        # Filter by status — case-insensitive exact match
        status_filter = request.args.get("status", "").strip()
        if status_filter:
            query = query.filter(Order.status.ilike(status_filter))

        # Filter by customer name — case-insensitive partial match
        name_filter = request.args.get("name", "").strip()
        if name_filter:
            query = query.filter(Order.customer_name.ilike(f"%{name_filter}%"))

        # Pagination
        try:
            limit  = min(int(request.args.get("limit",  100)), 500)
            offset = max(int(request.args.get("offset", 0)),   0)
        except ValueError:
            return error("'limit' and 'offset' must be integers.")

        total  = query.count()
        orders = (
            query
            .order_by(Order.timestamp.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

        return jsonify({
            "success":      True,
            "total_orders": total,
            "returned":     len(orders),
            "offset":       offset,
            "limit":        limit,
            "orders":       [o.to_dict() for o in orders]
        })

    except Exception as e:
        app.logger.error(f"DB query failed: {e}")
        return error("Database error — could not fetch orders.", 500)


# ── Run ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Render and Railway inject PORT as an environment variable.
    # Locally it defaults to 5000.
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
