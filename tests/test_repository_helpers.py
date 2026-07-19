import pytest

from lance_explorer.repository import LanceRepository, parse_vector


def test_parse_vector() -> None:
    assert parse_vector("[0.1, 2, -3]") == [0.1, 2.0, -3.0]


@pytest.mark.parametrize("value", ["", "{}", "[]", "[1, null]", "[NaN]"])
def test_parse_vector_rejects_invalid_input(value: str) -> None:
    with pytest.raises(ValueError):
        parse_vector(value)


def test_query_limit_is_bounded() -> None:
    repository = LanceRepository(max_query_rows=50)
    assert repository._validated_limit(100) == 50
    with pytest.raises(ValueError):
        repository._validated_limit(0)
