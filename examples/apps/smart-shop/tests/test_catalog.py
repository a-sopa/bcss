import catalog


def test_first_product():
    assert catalog.get(1)["name"] == "Pastel de nata"


def test_rating_of_first_product():
    assert round(catalog.get(1)["rating"], 1) == 4.6


def test_missing_product():
    assert catalog.get(999) is None
