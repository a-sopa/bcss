import pricing


def test_vat_is_added():
    assert pricing.price_with_tax(1.00) == 1.23


def test_pastry_discount():
    assert pricing.discounted(2.00, "pastry") == 1.80


def test_unknown_category_has_no_discount():
    assert pricing.discounted(2.00, "tea") == 2.00
