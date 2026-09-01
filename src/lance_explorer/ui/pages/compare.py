from __future__ import annotations

import pandas as pd
import streamlit as st

from lance_explorer.comparison import compare_metadata, compare_rows
from lance_explorer.config import AppConfig
from lance_explorer.repository import LanceRepository
from lance_explorer.ui.cache import cached_versions
from lance_explorer.ui.components.code_export import show_code_export
from lance_explorer.ui.components.common import template_directory
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
    if right and (defaults_changed or not st.session_state.get("compare-right-uri")):
        st.session_state["compare-right-uri"] = right


def _common_columns_from_schemas(left_schema, right_schema) -> list[str]:
    """Return shared top-level columns in left-schema order."""

    right_names = set(right_schema.names)
    return [name for name in left_schema.names if name in right_names]


def _common_columns_for_tables(
    repository: LanceRepository,
    left_uri: str,
    right_uri: str,
    left_version: int | None = None,
    right_version: int | None = None,
) -> tuple[list[str], str | None]:
    """Load common columns for two URIs, returning UI-safe errors instead of raising."""

    if not left_uri.strip() or not right_uri.strip():
        return [], None
    try:
        left_schema = repository.get_schema(left_uri.strip(), version=left_version)
        right_schema = repository.get_schema(right_uri.strip(), version=right_version)
    except Exception as exc:
        return [], str(exc)
    return _common_columns_from_schemas(left_schema, right_schema), None


def _version_options_for_uri(table_uri: str) -> list[int | None]:
    """Return latest plus table versions in descending order for a URI widget."""

    if not table_uri.strip():
        return [None]
    try:
        versions = cached_versions(table_uri.strip(), 0)
    except Exception:
        return [None]
    version_numbers = sorted(
        {
            int(item["version"])
            for item in versions
            if isinstance(item.get("version"), int)
        },
        reverse=True,
    )
    return [None, *version_numbers]


def _version_label(value: int | None) -> str:
    return "Latest" if value is None else f"Version {value}"


def _render_compare_inputs() -> tuple[str, int | None, str, int | None]:
    """Render side-by-side compare inputs with per-table version dropdowns."""

    left_col, divider_col, right_col = st.columns([0.48, 0.04, 0.48])
    with left_col:
        st.caption("Left")
        left_uri = st.text_input("Table URI", key="compare-left-uri")
        left_version = st.selectbox(
            "Version",
            _version_options_for_uri(left_uri),
            key=f"compare-left-version-{left_uri}",
            format_func=_version_label,
        )
    with divider_col:
        st.markdown(
            "<div style='border-left:1px solid rgba(128,128,128,.35);height:8rem'></div>",
            unsafe_allow_html=True,
        )
    with right_col:
        st.caption("Right")
        right_uri = st.text_input("Table URI", key="compare-right-uri")
        right_version = st.selectbox(
            "Version",
            _version_options_for_uri(right_uri),
            key=f"compare-right-version-{right_uri}",
            format_func=_version_label,
        )
    return left_uri, left_version, right_uri, right_version


def render(config: AppConfig) -> None:
    """Render metadata and bounded row comparison workflows."""

    st.title("Compare tables")
    repository = LanceRepository(config.max_query_rows)
    _sync_compare_uri_defaults()
    left_uri, left_version, right_uri, right_version = _render_compare_inputs()
    schema_tab, data_tab = st.tabs(["Compare Schema/Metadata", "Compare Data"])

    with schema_tab:
        st.caption(
            "Read-only table metadata and schema comparison",
            help=help_text("metadata_compare"),
        )
        run_metadata = st.button("Compare metadata and schemas", width="stretch")

        if run_metadata:
            try:
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

    with data_tab:
        st.subheader("Bounded row comparison", help=help_text("bounded_compare"))
        st.caption(
            "This compares only the explicitly requested bounded result; "
            "it never starts a full scan automatically."
        )

        common_columns, common_column_error = _common_columns_for_tables(
            repository,
            left_uri,
            right_uri,
            left_version=left_version,
            right_version=right_version,
        )
        common_column_signature = (
            left_uri,
            left_version,
            right_uri,
            right_version,
            tuple(common_columns),
        )
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
            key_column = st.text_input(
                "Unique key column (optional)",
                placeholder="id",
                help=help_text("comparison_key"),
            )
            limit = st.number_input("Maximum rows per table", 1, config.max_query_rows, 1_000)
            run_rows = st.form_submit_button("Compare bounded rows")

        if run_rows:
            try:
                if not columns:
                    raise ValueError("Select at least one common comparison column")
                st.session_state.comparison_results["rows"] = compare_rows(
                    repository,
                    left_uri,
                    right_uri,
                    columns=columns,
                    key=key_column.strip() or None,
                    limit=int(limit),
                    left_version=left_version,
                    right_version=right_version,
                )
            except Exception as exc:
                st.error(str(exc))

        row_result = st.session_state.comparison_results.get("rows")
        if row_result:
            left_vector_columns = set()
            right_vector_columns = set()
            try:
                left_vector_columns = vector_display_columns(
                    repository.snapshot(left_uri, left_version)
                )
                right_vector_columns = vector_display_columns(
                    repository.snapshot(right_uri, right_version)
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

        if left_uri and right_uri:
            show_code_export(
                "compare_tables",
                {
                    "left_uri": left_uri,
                    "right_uri": right_uri,
                    "columns": columns,
                    "key": key_column.strip() or None,
                    "limit": int(limit),
                    "left_version": left_version,
                    "right_version": right_version,
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
