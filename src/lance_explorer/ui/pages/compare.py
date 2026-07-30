from __future__ import annotations

import pandas as pd
import streamlit as st

from lance_explorer.comparison import compare_metadata, compare_rows
from lance_explorer.config import AppConfig
from lance_explorer.repository import LanceRepository
from lance_explorer.ui.components.code_export import show_code_export
from lance_explorer.ui.components.common import parse_version, template_directory
from lance_explorer.ui.components.dataframe import (
    json_array_for_display,
    show_dataframe,
    vector_display_columns,
)
from lance_explorer.ui.help_text import help_text


def _comparison_default_uris() -> tuple[str, str]:
    """Return Compare defaults from the current selected table and recent history."""

    selected = str(st.session_state.get("selected_table_uri") or "")
    history = [
        str(item)
        for item in st.session_state.get("selected_table_history", [])
        if item and item != selected
    ]
    left = selected or (history[0] if history else "")
    right = history[0] if selected and history else history[1] if len(history) > 1 else ""
    return left, right


def _sync_compare_uri_defaults() -> None:
    """Rehydrate Compare URI widgets without clobbering active user edits."""

    left, right = _comparison_default_uris()
    defaults = (left, right)
    defaults_changed = st.session_state.get("compare_uri_defaults") != defaults
    st.session_state["compare_uri_defaults"] = defaults

    if left and (defaults_changed or not st.session_state.get("compare-left-uri")):
        st.session_state["compare-left-uri"] = left
    if left and (defaults_changed or not st.session_state.get("row-left-uri")):
        st.session_state["row-left-uri"] = left
    if right and (defaults_changed or not st.session_state.get("compare-right-uri")):
        st.session_state["compare-right-uri"] = right
    if right and (defaults_changed or not st.session_state.get("row-right-uri")):
        st.session_state["row-right-uri"] = right


def _common_columns_from_schemas(left_schema, right_schema) -> list[str]:
    """Return shared top-level columns in left-schema order."""

    right_names = set(right_schema.names)
    return [name for name in left_schema.names if name in right_names]


def _common_columns_for_tables(
    repository: LanceRepository,
    left_uri: str,
    right_uri: str,
) -> tuple[list[str], str | None]:
    """Load common columns for two URIs, returning UI-safe errors instead of raising."""

    if not left_uri.strip() or not right_uri.strip():
        return [], None
    try:
        left_schema = repository.get_schema(left_uri.strip())
        right_schema = repository.get_schema(right_uri.strip())
    except Exception as exc:
        return [], str(exc)
    return _common_columns_from_schemas(left_schema, right_schema), None


def render(config: AppConfig) -> None:
    """Render metadata and bounded row comparison workflows."""

    st.title("Compare tables")
    repository = LanceRepository(config.max_query_rows)
    _sync_compare_uri_defaults()

    st.caption("Read-only table metadata and schema comparison", help=help_text("metadata_compare"))
    with st.form("metadata-compare"):
        left_uri = st.text_input("Left table URI", key="compare-left-uri")
        right_uri = st.text_input("Right table URI", key="compare-right-uri")
        left_version_text = st.text_input("Left version (optional)")
        right_version_text = st.text_input("Right version (optional)")
        run_metadata = st.form_submit_button("Compare metadata and schemas")

    if run_metadata:
        try:
            left_version = parse_version(left_version_text)
            right_version = parse_version(right_version_text)
            st.session_state.comparison_results["metadata"] = compare_metadata(
                repository,
                left_uri,
                right_uri,
                left_version=left_version,
                right_version=right_version,
            )
        except Exception as exc:
            st.error(str(exc))

    metadata = st.session_state.comparison_results.get("metadata")
    if metadata:
        summary = metadata["summary"]
        metrics = st.columns(3)
        metrics[0].metric("Row-count delta", summary["row_count_delta"])
        metrics[1].metric("Same schema", "Yes" if summary["same_schema"] else "No")
        metrics[2].metric("Same indexes", "Yes" if summary["same_indexes"] else "No")
        st.subheader("Schema changes")
        st.dataframe(pd.DataFrame(metadata["schema_changes"]), width="stretch")
        with st.expander("Left snapshot"):
            st.json(metadata["left"])
        with st.expander("Right snapshot"):
            st.json(metadata["right"])

    st.subheader("Bounded row comparison", help=help_text("bounded_compare"))
    st.caption(
        "This compares only the explicitly requested bounded result; "
        "it never starts a full scan automatically."
    )
    row_left_uri = st.text_input("Left table URI", key="row-left-uri")
    row_right_uri = st.text_input("Right table URI", key="row-right-uri")

    common_columns, common_column_error = _common_columns_for_tables(
        repository,
        row_left_uri,
        row_right_uri,
    )
    common_column_signature = (row_left_uri, row_right_uri, tuple(common_columns))
    if st.session_state.get("row-common-columns-signature") != common_column_signature:
        st.session_state["row-columns"] = common_columns
        st.session_state["row-common-columns-signature"] = common_column_signature

    column_placeholder = (
        "Fields will populate when Left and Right table URIs are present. "
        "Only common fields are displayed."
    )
    columns = st.multiselect(
        "Columns",
        common_columns,
        key="row-columns",
        disabled=not common_columns,
        placeholder=column_placeholder if not common_columns else "Select common columns",
    )
    if common_column_error:
        st.warning(f"Could not load common columns: {common_column_error}")

    with st.form("row-compare"):
        row_left_version_text = st.text_input("Left version (optional)", key="row-left-version")
        row_right_version_text = st.text_input("Right version (optional)", key="row-right-version")
        key_column = st.text_input(
            "Unique key column (optional)",
            placeholder="id",
            help=help_text("comparison_key"),
        )
        limit = st.number_input("Maximum rows per table", 1, config.max_query_rows, 1_000)
        run_rows = st.form_submit_button("Compare bounded rows")

    try:
        row_left_version = parse_version(row_left_version_text)
        row_right_version = parse_version(row_right_version_text)
    except ValueError:
        row_left_version = None
        row_right_version = None
    if run_rows:
        try:
            row_left_version = parse_version(row_left_version_text)
            row_right_version = parse_version(row_right_version_text)
            if not columns:
                raise ValueError("Select at least one common comparison column")
            st.session_state.comparison_results["rows"] = compare_rows(
                repository,
                row_left_uri,
                row_right_uri,
                columns=columns,
                key=key_column.strip() or None,
                limit=int(limit),
                left_version=row_left_version,
                right_version=row_right_version,
            )
        except Exception as exc:
            st.error(str(exc))

    row_result = st.session_state.comparison_results.get("rows")
    if row_result:
        left_vector_columns = set()
        right_vector_columns = set()
        try:
            left_vector_columns = vector_display_columns(
                repository.snapshot(row_left_uri, row_left_version)
            )
            right_vector_columns = vector_display_columns(
                repository.snapshot(row_right_uri, row_right_version)
            )
        except Exception:
            pass
        st.write(f"Mode: `{row_result['mode']}`")
        for name, value in row_result.items():
            if name in {"mode", "left_rows", "right_rows"}:
                continue
            st.subheader(name.replace("_", " ").title())
            if isinstance(value, pd.DataFrame):
                if name == "comparison":
                    vectors = {
                        *(f"left.{column}" for column in left_vector_columns),
                        *(f"right.{column}" for column in right_vector_columns),
                    }
                elif name == "only_left":
                    vectors = left_vector_columns
                elif name == "only_right":
                    vectors = right_vector_columns
                elif name == "changed":
                    vectors = set()
                    value = _stringify_changed_vector_values(
                        value,
                        left_vector_columns | right_vector_columns,
                    )
                else:
                    vectors = left_vector_columns | right_vector_columns
                show_dataframe(value, vector_columns=vectors)
            else:
                st.write(value)

    if row_left_uri and row_right_uri:
        show_code_export(
            "compare_tables",
            {
                "left_uri": row_left_uri,
                "right_uri": row_right_uri,
                "columns": columns,
                "key": key_column.strip() or None,
                "limit": int(limit),
                "left_version": row_left_version,
                "right_version": row_right_version,
            },
            template_directory=template_directory(config),
        )


def _stringify_changed_vector_values(
    dataframe: pd.DataFrame,
    vector_columns: set[str],
) -> pd.DataFrame:
    if not vector_columns or not {"column", "left", "right"}.issubset(dataframe.columns):
        return dataframe
    output = dataframe.copy()
    mask = output["column"].isin(vector_columns)
    output.loc[mask, "left"] = output.loc[mask, "left"].map(json_array_for_display)
    output.loc[mask, "right"] = output.loc[mask, "right"].map(json_array_for_display)
    return output
