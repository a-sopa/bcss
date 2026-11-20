"""Prices, discounts and VAT."""

VAT = 0.23
DISCOUNTS = {"pastry": 0.10, "coffee": 0.0}


def discounted(price: float, category: str) -> float:
    return round(price * (1 - DISCOUNTS.get(category, 0.0)), 2)


def price_with_tax(price: float) -> float:
    return round(price * (1 + VAT), 2)
