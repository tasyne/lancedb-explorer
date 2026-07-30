from pathlib import Path

import lancedb
import pyarrow as pa

from lance_explorer.demo_data import (
    DEMO_EMBEDDING_DIM,
    DEMO_FTS_INDEX_NAME,
    DEMO_VECTOR_INDEX_NAME,
    create_demo_table,
    demo_rows,
    resolve_faker_locale,
)
from lance_explorer.repository import LanceRepository


def test_demo_rows_use_locale_alias_and_expected_shape() -> None:
    rows = demo_rows(row_count=5, locale="usa", seed=123)

    assert len(rows) == 5
    assert rows[0]["locale"] == "en_US"
    assert rows[0]["id"] == 1
    assert "movie star" in rows[0]["bio"]
    assert 1 <= len(rows[0]["genre"]) <= 5
    assert all(isinstance(item, str) for item in rows[0]["genre"])
    assert len(rows[0]["embedding"]) == DEMO_EMBEDDING_DIM
    assert all(-1.0 <= value <= 1.0 for value in rows[0]["embedding"])


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
    assert pa.types.is_list(table.schema.field("genre").type)
    assert "publicity_risk" not in LanceRepository().get_schema(result.table_uri, version=1).names
    assert len(table.list_versions()) >= 3
    indexes = LanceRepository().list_indexes(result.table_uri)
    embedding_indexes = [
        index for index in indexes if index.get("name") == DEMO_VECTOR_INDEX_NAME
    ]
    fts_indexes = [index for index in indexes if index.get("name") == DEMO_FTS_INDEX_NAME]
    assert embedding_indexes
    assert embedding_indexes[0]["columns"] == ["embedding"]
    assert fts_indexes
    assert fts_indexes[0]["columns"] == ["bio"]
    assert fts_indexes[0]["index_details"]["base_tokenizer"] == "icu"
