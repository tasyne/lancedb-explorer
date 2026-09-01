import pyarrow as pa
import pytest
import streamlit as st

from lance_explorer.ui.pages.compare import (
    _common_columns_from_schemas,
    _comparison_default_uris,
    _sync_compare_uri_defaults,
    _version_label,
)


@pytest.fixture(autouse=True)
def clear_session_state() -> None:
    st.session_state.clear()


def test_comparison_default_uris_use_selected_table_and_history() -> None:
    st.session_state["selected_table_uri"] = "/tmp/db/current.lance"
    st.session_state["selected_table_history"] = [
        "/tmp/db/current.lance",
        "/tmp/db/previous.lance",
        "/tmp/db/older.lance",
    ]

    assert _comparison_default_uris() == (
        "/tmp/db/current.lance",
        "/tmp/db/previous.lance",
    )


def test_sync_compare_uri_defaults_rehydrates_empty_uri_fields() -> None:
    st.session_state["selected_table_uri"] = "/tmp/db/current.lance"
    st.session_state["selected_table_history"] = ["/tmp/db/previous.lance"]
    st.session_state["compare_uri_defaults"] = (
        "/tmp/db/current.lance",
        "/tmp/db/previous.lance",
    )
    st.session_state["compare-left-uri"] = ""
    st.session_state["compare-right-uri"] = ""

    _sync_compare_uri_defaults()

    assert st.session_state["compare-left-uri"] == "/tmp/db/current.lance"
    assert st.session_state["compare-right-uri"] == "/tmp/db/previous.lance"


def test_common_columns_from_schemas_preserves_left_schema_order() -> None:
    left = pa.schema(
        [
            ("id", pa.int64()),
            ("name", pa.string()),
            ("left_only", pa.bool_()),
            ("score", pa.float64()),
        ]
    )
    right = pa.schema(
        [
            ("score", pa.float64()),
            ("id", pa.int64()),
            ("name", pa.string()),
            ("right_only", pa.string()),
        ]
    )

    assert _common_columns_from_schemas(left, right) == ["id", "name", "score"]


def test_version_label_formats_latest_and_versions() -> None:
    assert _version_label(None) == "Latest"
    assert _version_label(3) == "Version 3"
