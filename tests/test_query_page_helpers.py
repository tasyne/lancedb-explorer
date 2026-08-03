from lance_explorer.ui.pages.query import _fts_indexed_columns, _fts_tokenizer_by_column


def test_fts_indexed_columns_uses_index_metadata() -> None:
    indexes = [
        {"name": "bio_idx", "index_type": "FTS", "columns": ["bio"]},
        {"name": "id_idx", "index_type": "BTree", "columns": ["id"]},
        {"name": "legacy_fts", "type_url": "/lance.table.InvertedIndexDetails", "columns": "notes"},
    ]

    assert _fts_indexed_columns(indexes, ["bio", "notes", "title"]) == ["bio", "notes"]


def test_fts_tokenizer_by_column_reads_index_details() -> None:
    indexes = [
        {
            "name": "bio_idx",
            "index_type": "FTS",
            "columns": ["bio"],
            "index_details": {"base_tokenizer": "jieba/default"},
        },
        {
            "name": "title_idx",
            "type_url": "/lance.table.InvertedIndexDetails",
            "columns": "title",
            "index_details": {"base_tokenizer": "icu"},
        },
    ]

    assert _fts_tokenizer_by_column(indexes) == {
        "bio": "jieba/default",
        "title": "icu",
    }
