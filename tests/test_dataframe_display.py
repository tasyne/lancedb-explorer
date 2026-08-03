import pandas as pd

from lance_explorer.ui.components.dataframe import (
    binary_value_for_display,
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


def test_binary_image_values_render_as_data_urls() -> None:
    value = binary_value_for_display(b"\x89PNG\r\n\x1a\nimage", "image/png")

    assert isinstance(value, str)
    assert value.startswith("data:image/png;base64,")


def test_binary_non_image_values_render_as_compact_labels() -> None:
    assert binary_value_for_display(b"not an image", "application/octet-stream") == (
        "<application/octet-stream 12 bytes>"
    )


def test_dataframe_for_display_uses_mime_columns_for_binary_images() -> None:
    dataframe = pd.DataFrame(
        [
            {
                "headshot_mime": "image/png",
                "headshot_thumbnail_bytes": b"\x89PNG\r\n\x1a\nimage",
            }
        ]
    )

    display = dataframe_for_display(dataframe)

    assert display["headshot_thumbnail_bytes"].iloc[0].startswith(
        "data:image/png;base64,"
    )
