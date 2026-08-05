from pathlib import Path

import lancedb

from lance_explorer.repository import LanceRepository


def test_local_table_inspection_filter_and_versions(tmp_path: Path) -> None:
    db = lancedb.connect(str(tmp_path))
    table = db.create_table(
        "items",
        data=[
            {"id": 1, "category": "a", "text": "red apple"},
            {"id": 2, "category": "b", "text": "green pear"},
        ],
    )
    table.add([{"id": 3, "category": "a", "text": "red berry"}])

    uri = str(tmp_path / "items.lance")
    repository = LanceRepository(max_query_rows=100)

    snapshot = repository.snapshot(uri)
    assert snapshot["row_count"] == 3
    assert snapshot["version"] >= 2
    assert len(repository.list_versions(uri)) >= 2
    assert repository.preview(uri, limit=10, version=1)["id"].tolist() == [1, 2]

    result = repository.run_filter(
        uri,
        where="category = 'a'",
        columns=["id", "category"],
        limit=10,
    )
    assert result.rows["id"].tolist() == [1, 3]


def test_local_scalar_index_lifecycle(tmp_path: Path) -> None:
    db = lancedb.connect(str(tmp_path))
    db.create_table(
        "items",
        data=[{"id": item, "category": str(item % 2)} for item in range(20)],
    )
    uri = str(tmp_path / "items.lance")
    repository = LanceRepository()

    repository.create_index(uri, column="id", index_type="BTREE", name="id_idx")
    names = [index["name"] for index in repository.list_indexes(uri)]
    assert "id_idx" in names

    repository.drop_index(uri, "id_idx")
    remaining = [index["name"] for index in repository.list_indexes(uri)]
    assert "id_idx" not in remaining


def test_local_fts_index_and_search(tmp_path: Path) -> None:
    db = lancedb.connect(str(tmp_path))
    db.create_table(
        "documents",
        data=[
            {"id": 1, "text": "red apple", "embedding": [0.1, 0.2, 0.3, 0.4]},
            {"id": 2, "text": "green pear", "embedding": [0.2, 0.3, 0.4, 0.5]},
            {"id": 3, "text": "red berry", "embedding": [0.3, 0.4, 0.5, 0.6]},
        ],
    )
    uri = str(tmp_path / "documents.lance")
    repository = LanceRepository()

    repository.create_index(
        uri,
        column="text",
        index_type="FTS",
        name="text_idx",
        config_options={"with_position": True},
    )
    result = repository.run_fts(
        uri,
        text="red",
        column="text",
        where=None,
        columns=["id", "text"],
        limit=10,
    )

    assert result.rows["id"].tolist() == [1, 3]
    assert "_score" in result.rows.columns


def test_local_hybrid_search_uses_text_and_vector(tmp_path: Path) -> None:
    db = lancedb.connect(str(tmp_path))
    db.create_table(
        "documents",
        data=[
            {"id": 1, "text": "red apple", "embedding": [0.1, 0.2, 0.3, 0.4]},
            {"id": 2, "text": "green pear", "embedding": [0.2, 0.3, 0.4, 0.5]},
            {"id": 3, "text": "red berry", "embedding": [0.3, 0.4, 0.5, 0.6]},
        ],
    )
    uri = str(tmp_path / "documents.lance")
    repository = LanceRepository()

    repository.create_index(
        uri,
        column="text",
        index_type="FTS",
        name="text_idx",
        config_options={"with_position": True},
    )
    repository.create_index(
        uri,
        column="embedding",
        index_type="IVF_FLAT",
        name="embedding_idx",
        replace=True,
        config_options={"num_partitions": 2},
    )
    result = repository.run_hybrid(
        uri,
        text="red",
        vector=[0.1, 0.2, 0.3, 0.4],
        vector_column="embedding",
        fts_column="text",
        where=None,
        columns=["id", "text"],
        limit=10,
    )

    assert not result.rows.empty
    assert {"id", "text", "_score", "_distance", "_relevance_score"} <= set(
        result.rows.columns
    )


def test_jieba_fts_index_uses_packaged_language_models(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("LANCE_LANGUAGE_MODEL_HOME", raising=False)
    db = lancedb.connect(str(tmp_path))
    db.create_table(
        "documents",
        data=[
            {"id": 1, "text": "南京市长江大桥"},
            {"id": 2, "text": "上海电影节"},
        ],
    )
    uri = str(tmp_path / "documents.lance")
    repository = LanceRepository()

    repository.create_index(
        uri,
        column="text",
        index_type="FTS",
        name="jieba_idx",
        config_options={
            "base_tokenizer": "jieba/default",
            "with_position": True,
            "stem": False,
            "remove_stop_words": False,
            "ascii_folding": False,
        },
    )

    monkeypatch.delenv("LANCE_LANGUAGE_MODEL_HOME", raising=False)
    snapshot = repository.snapshot(uri)
    indexes = snapshot["indexes"]
    jieba = next(index for index in indexes if index.get("name") == "jieba_idx")
    assert jieba["index_details"]["base_tokenizer"] == "jieba/default"


def test_maintenance_restore_and_drop(tmp_path: Path) -> None:
    db = lancedb.connect(str(tmp_path))
    table = db.create_table("maintenance", data=[{"id": 1}])
    table.add([{"id": 2}])
    uri = str(tmp_path / "maintenance.lance")
    repository = LanceRepository()

    repository.optimize(uri)
    repository.cleanup_versions(uri, older_than_days=999)
    repository.restore_version(uri, 1)
    assert repository.snapshot(uri)["row_count"] == 1

    repository.drop_table(uri)
    assert "maintenance" not in repository.list_tables(str(tmp_path))


def test_table_tag_lifecycle(tmp_path: Path) -> None:
    db = lancedb.connect(str(tmp_path))
    table = db.create_table("tagged", data=[{"id": 1}])
    table.add([{"id": 2}])
    uri = str(tmp_path / "tagged.lance")
    repository = LanceRepository()

    created = repository.set_tag(uri, "baseline", 1)
    assert created == {"status": "created", "tag": "baseline", "version": 1}
    tags = repository.list_tags(uri)
    assert tags[0]["tag"] == "baseline"
    assert tags[0]["version"] == 1

    updated = repository.set_tag(uri, "baseline", 2)
    assert updated == {"status": "updated", "tag": "baseline", "version": 2}
    assert repository.list_tags(uri)[0]["version"] == 2

    deleted = repository.delete_tag(uri, "baseline")
    assert deleted == {"status": "deleted", "tag": "baseline"}
    assert repository.list_tags(uri) == []
