from ingestion_api.google_sheets import row_to_text


def test_row_to_text_joins_key_value_pairs():
    row = {"Name": "Alice", "Role": "President", "Budget": 500}

    result = row_to_text(row)

    assert result == "Name: Alice | Role: President | Budget: 500"


def test_row_to_text_skips_empty_values():
    row = {"Name": "Alice", "Role": "", "Budget": 500}

    result = row_to_text(row)

    assert result == "Name: Alice | Budget: 500"


def test_row_to_text_all_empty_returns_empty_string():
    row = {"Name": "", "Role": ""}

    result = row_to_text(row)

    assert result == ""
