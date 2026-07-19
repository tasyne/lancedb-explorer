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
            {"id": 1, "text": "red apple"},
            {"id": 2, "text": "green pear"},
            {"id": 3, "text": "red berry"},
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
