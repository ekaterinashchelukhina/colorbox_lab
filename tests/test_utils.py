from utils import parse_optional_id


def test_parse_optional_id_accepts_zero():
    assert parse_optional_id("0") == 0
    assert parse_optional_id(0) == 0


def test_parse_optional_id_rejects_missing_or_invalid():
    assert parse_optional_id(None) is None
    assert parse_optional_id("") is None
    assert parse_optional_id("abc") is None


def test_parse_optional_id_accepts_positive_ints():
    assert parse_optional_id("42") == 42
    assert parse_optional_id(42) == 42