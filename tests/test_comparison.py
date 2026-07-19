from pathlib import Path

import lancedb

from lance_explorer.comparison import compare_rows
from lance_explorer.repository import LanceRepository


def _table_uri(database: Path, name: str) -> str:
    return str(database / f"{name}.lance")


def test_keyed_row_comparison(tmp_path: Path) -> None:
    db = lancedb.connect(str(tmp_path))
    db.create_table(
        "left",
        data=[{"id": 1, "value": "same"}, {"id": 2, "value": "old"}],
    )
    db.create_table(
        "right",
        data=[{"id": 1, "value": "same"}, {"id": 2, "value": "new"}, {"id": 3, "value": "extra"}],
    )

    result = compare_rows(
        LanceRepository(),
        _table_uri(tmp_path, "left"),
        _table_uri(tmp_path, "right"),
        columns=["value"],
        key="id",
        limit=100,
    )

    assert result["mode"] == "key"
    assert len(result["changed"]) == 1
    assert len(result["only_right"]) == 1
