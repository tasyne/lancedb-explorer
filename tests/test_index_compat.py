import pytest

import lance_explorer.index_compat as index_compat
from lance_explorer.index_compat import UnsupportedIndexError, create_table_index


class UnifiedTable:
    def __init__(self) -> None:
        self.calls = []

    def create_index(self, column, *, config=None, name=None, replace=False):
        self.calls.append(("create_index", column, config.__class__.__name__, name, replace))


class LegacyScalarTable:
    def __init__(self) -> None:
        self.calls = []

    def create_index(self, metric="l2", vector_column_name="vector", replace=True):
        raise AssertionError("legacy scalar indexes should use create_scalar_index")

    def create_scalar_index(self, column, *, replace=True, index_type="BTREE", name=None):
        self.calls.append(("create_scalar_index", column, index_type, name, replace))


class LegacyFtsTable:
    def __init__(self) -> None:
        self.calls = []

    def create_index(self, metric="l2", vector_column_name="vector", replace=True):
        raise AssertionError("legacy FTS indexes should use create_fts_index")

    def create_fts_index(
        self,
        field_names,
        *,
        replace=False,
        with_position=False,
        base_tokenizer="simple",
        name=None,
    ):
        self.calls.append(
            ("create_fts_index", field_names, replace, with_position, base_tokenizer, name)
        )


class LegacyVectorTable:
    def __init__(self) -> None:
        self.calls = []

    def create_index(
        self,
        metric="l2",
        num_partitions=None,
        num_sub_vectors=None,
        vector_column_name="vector",
        replace=True,
        *,
        index_type="IVF_PQ",
        max_iterations=50,
        sample_rate=256,
        name=None,
    ):
        self.calls.append(
            {
                "metric": metric,
                "num_partitions": num_partitions,
                "num_sub_vectors": num_sub_vectors,
                "vector_column_name": vector_column_name,
                "replace": replace,
                "index_type": index_type,
                "max_iterations": max_iterations,
                "sample_rate": sample_rate,
                "name": name,
            }
        )


class LegacyUnsupportedTable:
    def create_index(self, metric="l2", vector_column_name="vector", replace=True):
        raise AssertionError("unsupported index types should fail before calling create_index")


def test_unified_index_api_uses_config_object() -> None:
    table = UnifiedTable()

    create_table_index(
        table,
        column="id",
        index_type="BTREE",
        name="id_idx",
        replace=True,
    )

    assert table.calls == [("create_index", "id", "BTree", "id_idx", True)]


def test_legacy_scalar_index_uses_public_scalar_helper() -> None:
    table = LegacyScalarTable()

    create_table_index(
        table,
        column="id",
        index_type="BITMAP",
        name="id_bitmap_idx",
        replace=True,
    )

    assert table.calls == [
        ("create_scalar_index", "id", "BITMAP", "id_bitmap_idx", True)
    ]


def test_legacy_fts_index_filters_options_into_public_fts_helper() -> None:
    table = LegacyFtsTable()

    create_table_index(
        table,
        column="bio",
        index_type="FTS",
        name="bio_idx",
        replace=True,
        config_options={
            "with_position": True,
            "base_tokenizer": "simple",
            "lower_case": True,
        },
    )

    assert table.calls == [
        ("create_fts_index", "bio", True, True, "simple", "bio_idx")
    ]


def test_legacy_vector_index_maps_config_options_to_vector_kwargs() -> None:
    table = LegacyVectorTable()

    create_table_index(
        table,
        column="embedding",
        index_type="IVF_PQ",
        name="embedding_idx",
        replace=True,
        config_options={
            "distance_type": "cosine",
            "num_partitions": 2,
            "num_sub_vectors": 8,
            "max_iterations": 77,
            "sample_rate": 123,
            "accelerator": "cuda",
        },
    )

    assert table.calls == [
        {
            "metric": "cosine",
            "num_partitions": 2,
            "num_sub_vectors": 8,
            "vector_column_name": "embedding",
            "replace": True,
            "index_type": "IVF_PQ",
            "max_iterations": 77,
            "sample_rate": 123,
            "name": "embedding_idx",
        }
    ]


def test_legacy_api_rejects_unified_only_index_types() -> None:
    with pytest.raises(UnsupportedIndexError, match="unified create_index"):
        create_table_index(
            LegacyUnsupportedTable(),
            column="embedding",
            index_type="HNSW_FLAT",
        )


def test_installed_support_filter_hides_unified_only_types_on_legacy(monkeypatch) -> None:
    monkeypatch.setattr(index_compat, "_installed_lancetable_accepts_config", lambda: False)

    assert index_compat.index_type_supported_by_installed_lancedb("IVF_HNSW_SQ")
    assert not index_compat.index_type_supported_by_installed_lancedb("HNSW_FLAT")
