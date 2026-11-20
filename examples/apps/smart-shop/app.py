"""Smart Shop: demo app for OwnCloud's AI features (pipeline, canary, edge cache, database tuning, load tests)."""

import os

from flask import Flask, abort, jsonify, request

import catalog
import orders
import pricing

app = Flask(__name__)


def page(title: str, body: str, max_age: int = 30):
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>{title} · Smart Shop</title>
<link rel="stylesheet" href="/static/style.css"></head><body><header><a href="/">Smart Shop</a> · <a href="/products">Products</a></header>
<main>{body}</main><script src="/static/app.js"></script></body></html>"""
    return html, 200, {"Cache-Control": f"public, max-age={max_age}", "Content-Type": "text/html; charset=utf-8"}


@app.get("/")
def home():
    featured = "".join(f'<li><a href="/products/{p["id"]}">{p["name"]}</a></li>' for p in catalog.featured())
    return page("Home", f"<h1>Welcome</h1><ul>{featured}</ul>")


@app.get("/products")
def products():
    items = "".join(f'<li><a href="/products/{p["id"]}">{p["name"]}</a> — €{pricing.price_with_tax(p["price"]):.2f}</li>'
                    for p in catalog.all_products())
    return page("Products", f"<h1>Products</h1><ul>{items}</ul>")


@app.get("/products/<int:product_id>")
def product(product_id: int):
    item = catalog.get(product_id)
    if item is None:
        abort(404)
    price = pricing.price_with_tax(pricing.discounted(item["price"], item["category"]))
    return page(item["name"], f"<h1>{item['name']}</h1><p>€{price:.2f} · rated {item['rating']:.1f}/5</p>")


@app.get("/api/price/<int:product_id>")
def api_price(product_id: int):
    item = catalog.get(product_id)
    if item is None:
        abort(404)
    return jsonify({"id": product_id, "price": pricing.price_with_tax(pricing.discounted(item["price"], item["category"]))})


@app.get("/orders")
def find_orders():
    if not orders.available():
        return jsonify({"error": "no database configured"}), 503
    return jsonify(orders.for_customer(request.args.get("email", "")))


@app.get("/orders/recent")
def recent_orders():
    if not orders.available():
        return jsonify({"error": "no database configured"}), 503
    return jsonify(orders.recent(int(request.args.get("page", "0"))))


if __name__ == "__main__":
    orders.prepare()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), threaded=True)
