from pathlib import Path

import lancedb
import pyarrow as pa

from lance_explorer.demo_data import (
    DEMO_EMBEDDING_DIM,
    DEMO_FTS_INDEX_NAME,
    DEMO_HEADSHOT_MIME,
    DEMO_VECTOR_INDEX_NAME,
    create_demo_table,
    demo_fts_index_options,
    demo_rows,
    demo_schema,
    resolve_faker_locale,
    supports_blob_v2,
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
    assert rows[0]["headshot_filename"].endswith(".png")
    assert rows[0]["headshot_mime"] == DEMO_HEADSHOT_MIME
    assert rows[0]["headshot_thumbnail_bytes"].startswith(b"\x89PNG")
    assert rows[0]["headshot_full_bytes"].startswith(b"\x89PNG")


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
    assert result.fts_preset in {"MULTILINGUAL", "ENGLISH"}
    assert "id" in field_names
    assert "bio" in field_names
    assert "embedding" in field_names
    assert "headshot_thumbnail_bytes" in field_names
    assert "headshot_full_bytes" in field_names
    assert "publicity_risk" in field_names
    assert pa.types.is_list(table.schema.field("genre").type)
    assert pa.types.is_binary(table.schema.field("headshot_thumbnail_bytes").type)
    full_field_type = table.schema.field("headshot_full_bytes").type
    if supports_blob_v2():
        assert result.blob_v2_enabled
        assert str(full_field_type).startswith("extension<lance.blob")
    else:
        assert not result.blob_v2_enabled
        assert pa.types.is_binary(full_field_type)
    sample = table.search().limit(1).to_pandas().iloc[0]
    assert sample["headshot_thumbnail_bytes"].startswith(b"\x89PNG")
    full_value = sample["headshot_full_bytes"]
    full_bytes = full_value.read() if hasattr(full_value, "read") else full_value
    assert full_bytes.startswith(b"\x89PNG")
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
    assert fts_indexes[0]["index_details"]["base_tokenizer"] == result.fts_base_tokenizer


def test_demo_schema_can_fallback_to_arrow_binary_for_full_headshot() -> None:
    schema = demo_schema(use_blob_v2=False)

    assert pa.types.is_binary(schema.field("headshot_thumbnail_bytes").type)
    assert pa.types.is_binary(schema.field("headshot_full_bytes").type)


def test_demo_fts_options_fallback_for_lancedb_033(monkeypatch) -> None:
    monkeypatch.setattr("lance_explorer.demo_data.lancedb_supports_fts_icu", lambda: False)

    preset, options = demo_fts_index_options()

    assert preset == "ENGLISH"
    assert options["base_tokenizer"] == "simple"
