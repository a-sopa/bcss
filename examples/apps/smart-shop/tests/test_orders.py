import orders


def test_email_is_normalised():
    assert orders.normalise_email("  Ana@Example.EU ") == "ana@example.eu"
