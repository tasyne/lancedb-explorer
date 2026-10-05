from lancedb.index import FTS, BTree, IvfPq

from lance_explorer.index_registry import create_table_index


class RecordingTable:
    def __init__(self) -> None:
        self.calls = []

    def create_index(self, column, *, config, name=None, replace=False):
        self.calls.append((column, config, name, replace))


def test_scalar_index_uses_unified_config_api() -> None:
    table = RecordingTable()

    create_table_index(table, column="id", index_type="BTREE", name="id_idx", replace=True)

    column, config, name, replace = table.calls[0]
    assert (column, name, replace) == ("id", "id_idx", True)
    assert isinstance(config, BTree)


def test_fts_index_uses_unified_config_api() -> None:
    table = RecordingTable()

    create_table_index(
        table,
        column="bio",
        index_type="FTS",
        config_options={"with_position": True, "base_tokenizer": "simple"},
    )

    _, config, _, _ = table.calls[0]
    assert isinstance(config, FTS)
    assert config.with_position is True
    assert config.base_tokenizer == "simple"


def test_vector_index_uses_unified_config_api() -> None:
    table = RecordingTable()

    create_table_index(
        table,
        column="embedding",
        index_type="IVF_PQ",
        config_options={
            "distance_type": "cosine",
            "num_partitions": 2,
            "num_sub_vectors": 8,
        },
    )

    _, config, _, _ = table.calls[0]
    assert isinstance(config, IvfPq)
    assert config.distance_type == "cosine"
    assert config.num_partitions == 2
