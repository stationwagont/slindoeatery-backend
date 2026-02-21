"""
Slindo's Eatery — Flask Backend
================================
Endpoints:
  GET  /          → health check
  GET  /menu      → full menu as JSON
  POST /order     → place a new order (stored in memory)
  GET  /orders    → retrieve all stored orders

Deploy on Render / Railway:
  1. Push this file + requirements.txt to GitHub
  2. Set start command to:  gunicorn app:app
  3. Set PORT env var if required (Render/Railway inject it automatically)
"""

import os
import uuid
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS

# ── App setup ──────────────────────────────────────────────────────────────────
app = Flask(__name__)
CORS(app)  # Allow cross-origin requests (e.g. from your HTML front-end)

# ── In-memory order store ──────────────────────────────────────────────────────
orders = []

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

# Build a flat item lookup for fast price/name validation at order time
ITEM_LOOKUP = {
    item["id"]: item
    for category in MENU["categories"]
    for item in category["items"]
}

# ── Helper ─────────────────────────────────────────────────────────────────────
def error(message, status=400):
    return jsonify({"success": False, "error": message}), status


# ── Routes ────────────────────────────────────────────────────────────────────
@app.route("/", methods=["GET"])
def health():
    """Health check — useful for Render/Railway uptime pings."""
    return jsonify({
        "status": "online",
        "restaurant": "Slindo's Eatery",
        "message": "It's time for iKota 🍞"
    })


@app.route("/menu", methods=["GET"])
def get_menu():
    """Return the full menu as JSON."""
    return jsonify({"success": True, "menu": MENU})


@app.route("/order", methods=["POST"])
def place_order():
    """
    Accept a new order.

    Expected JSON body:
    {
        "customer_name":   "Thabo Mokoena",          // required
        "contact_number":  "071 234 5678",            // required
        "order_type":      "Pickup" | "Delivery",    // required
        "delivery_address": "123 Main St, eQonce",   // required if Delivery
        "payment_method":  "Cash on Collection",     // required
        "items": [                                   // required, min 1
            { "item_id": "kota_supa",  "quantity": 2 },
            { "item_id": "wings_6",    "quantity": 1 }
        ],
        "special_instructions": "Extra spicy please" // optional
    }

    Returns the saved order with a generated order_id and timestamp.
    """
    data = request.get_json(silent=True)

    if not data:
        return error("Request body must be valid JSON.")

    # ── Required field validation ──
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

    # ── Validate order_type ──
    valid_order_types = ["Pickup", "Delivery"]
    if order_type not in valid_order_types:
        return error(f"'order_type' must be one of: {valid_order_types}.")

    # ── Delivery address required for deliveries ──
    delivery_address = ""
    if order_type == "Delivery":
        delivery_address = str(data.get("delivery_address", "")).strip()
        if not delivery_address:
            return error("'delivery_address' is required when order_type is 'Delivery'.")

    # ── Validate payment method ──
    valid_payments = [m for m in MENU["payment_methods"]]
    if payment_method not in valid_payments:
        return error(f"'payment_method' must be one of: {valid_payments}.")

    # ── Validate items list ──
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

        menu_item   = ITEM_LOOKUP[item_id]
        subtotal    = menu_item["price"] * quantity
        order_total += subtotal

        order_lines.append({
            "item_id":   item_id,
            "name":      menu_item["name"],
            "quantity":  quantity,
            "unit_price": menu_item["price"],
            "subtotal":  subtotal
        })

    # ── Build and store the order ──
    order = {
        "order_id":             str(uuid.uuid4())[:8].upper(),
        "timestamp":            datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "customer_name":        customer_name,
        "contact_number":       contact_number,
        "order_type":           order_type,
        "delivery_address":     delivery_address,
        "payment_method":       payment_method,
        "items":                order_lines,
        "order_total":          order_total,
        "special_instructions": special_note,
        "status":               "Received"
    }

    orders.append(order)

    return jsonify({
        "success": True,
        "message": f"Order received! We'll be in touch on {contact_number} 🍞",
        "order":   order
    }), 201


@app.route("/orders", methods=["GET"])
def get_orders():
    """
    Return all stored orders.
    Optional query params:
      ?status=Received   → filter by status
      ?name=thabo        → filter by customer name (case-insensitive)
    """
    result = list(orders)  # copy so we don't mutate

    # Filter by status
    status_filter = request.args.get("status", "").strip()
    if status_filter:
        result = [o for o in result if o["status"].lower() == status_filter.lower()]

    # Filter by customer name
    name_filter = request.args.get("name", "").strip().lower()
    if name_filter:
        result = [o for o in result if name_filter in o["customer_name"].lower()]

    return jsonify({
        "success":     True,
        "total_orders": len(result),
        "orders":      result
    })


# ── Run ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Render and Railway inject PORT as an environment variable.
    # Locally it defaults to 5000.
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
