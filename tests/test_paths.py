from pathlib import Path

from lance_explorer.paths import join_uri, list_children, normalize_uri, parent_uri, split_table_uri


def test_local_path_navigation(tmp_path: Path) -> None:
    database = tmp_path / "database"
    database.mkdir()
    table = database / "customers.lance"
    table.mkdir()
    (database / "note.txt").write_text("hello", encoding="utf-8")

    normalized = normalize_uri(str(database))
    assert normalized == str(database.absolute())
    assert parent_uri(str(table)) == str(database)
    assert join_uri(str(database), "customers.lance") == str(table)

    entries = list_children(str(database))
    assert [entry.name for entry in entries] == ["customers.lance", "note.txt"]
    assert entries[0].is_table is True


def test_split_table_uri() -> None:
    location = split_table_uri("s3://example-bucket/data/customers.lance")
    assert location.database_uri == "s3://example-bucket/data"
    assert location.table_name == "customers"
