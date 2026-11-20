"""Product catalogue."""

PRODUCTS = [
    {"id": 1, "name": "Pastel de nata", "price": 1.20, "category": "pastry", "reviews_total": 46, "reviews_count": 10},
    {"id": 2, "name": "Bica", "price": 0.80, "category": "coffee", "reviews_total": 38, "reviews_count": 9},
    {"id": 3, "name": "Bola de Berlim", "price": 1.50, "category": "pastry", "reviews_total": 21, "reviews_count": 5},
    {"id": 4, "name": "Galão", "price": 1.40, "category": "coffee", "reviews_total": 30, "reviews_count": 7},
    {"id": 5, "name": "Travesseiro de Sintra", "price": 1.90, "category": "pastry", "reviews_total": 0, "reviews_count": 0},
]


def with_rating(product: dict) -> dict:
    count = product["reviews_count"]
    return {**product, "rating": product["reviews_total"] / count if count else 0.0}


def all_products() -> list[dict]:
    return [with_rating(p) for p in PRODUCTS]


def featured() -> list[dict]:
    return all_products()[:3]


def get(product_id: int) -> dict | None:
    return next((with_rating(p) for p in PRODUCTS if p["id"] == product_id), None)
