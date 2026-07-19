from pathlib import Path

import lancedb

from lance_explorer.demo_data import create_demo_table, demo_rows, resolve_faker_locale


def test_demo_rows_use_locale_alias_and_expected_shape() -> None:
    rows = demo_rows(row_count=5, locale="usa", seed=123)

    assert len(rows) == 5
    assert rows[0]["locale"] == "en_US"
    assert rows[0]["id"] == 1
    assert "movie star" in rows[0]["bio"]
    assert len(rows[0]["embedding"]) == 8


def test_create_demo_table(tmp_path: Path) -> None:
    result = create_demo_table(
        str(tmp_path / "stars.lance"),
        row_count=7,
        locale="spanish",
        seed=123,
    )

    db = lancedb.connect(str(tmp_path))
    table = db.open_table("stars")
    field_names = table.schema.names
    assert result.locale == resolve_faker_locale("spanish")
    assert result.version_count == 3
    assert table.count_rows() == 7
    assert "id" in field_names
    assert "bio" in field_names
    assert "embedding" in field_names
    assert "publicity_risk" in field_names
    assert "publicity_risk" not in db.open_table("stars", version=1).schema.names
    assert len(table.list_versions()) >= 3
