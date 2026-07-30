import pandas as pd

from lance_explorer.ui.components.dataframe import (
    dataframe_for_display,
    json_array_for_display,
    vector_display_columns,
)


def test_vector_display_columns_prefers_vector_index_metadata() -> None:
    snapshot = {
        "indexes": [
            {
                "name": "embedding_idx",
                "columns": ["embedding"],
                "index_type": "IVF_PQ",
            }
        ],
        "schema": [
            {"path": "tags", "type": "list<item: string>"},
            {"path": "embedding", "type": "fixed_size_list<item: float>[8]"},
        ],
    }

    assert vector_display_columns(snapshot) == {"embedding"}


def test_vector_display_columns_falls_back_to_float_list_schema() -> None:
    snapshot = {
        "indexes": [],
        "schema": [
            {"path": "tags", "type": "list<item: string>"},
            {"path": "embedding", "type": "fixed_size_list<item: float>[8]"},
        ],
    }

    assert vector_display_columns(snapshot) == {"embedding"}


def test_dataframe_for_display_serializes_only_vector_columns() -> None:
    dataframe = pd.DataFrame(
        {
            "id": [1],
            "tags": [["red", "blue"]],
            "embedding": [[0.1, 0.2, 0.3]],
        }
    )

    display = dataframe_for_display(dataframe, {"embedding"})

    assert display.loc[0, "embedding"] == "[0.1,0.2,0.3]"
    assert display.loc[0, "tags"] == ["red", "blue"]


def test_json_array_for_display_handles_tuple_values() -> None:
    assert json_array_for_display((0.1, 0.2)) == "[0.1,0.2]"
