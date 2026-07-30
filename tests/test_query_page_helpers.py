from lance_explorer.ui.pages.query import _fts_indexed_columns


def test_fts_indexed_columns_uses_index_metadata() -> None:
    indexes = [
        {"name": "bio_idx", "index_type": "FTS", "columns": ["bio"]},
        {"name": "id_idx", "index_type": "BTree", "columns": ["id"]},
        {"name": "legacy_fts", "type_url": "/lance.table.InvertedIndexDetails", "columns": "notes"},
    ]

    assert _fts_indexed_columns(indexes, ["bio", "notes", "title"]) == ["bio", "notes"]
