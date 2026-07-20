from __future__ import annotations

import pandas as pd
import streamlit as st

from lance_explorer.comparison import compare_metadata, compare_rows
from lance_explorer.config import AppConfig
from lance_explorer.repository import LanceRepository
from lance_explorer.ui.components.code_export import show_code_export
from lance_explorer.ui.components.common import parse_columns, parse_version, template_directory
from lance_explorer.ui.help_text import help_text


def render(config: AppConfig) -> None:
    """Render metadata and bounded row comparison workflows."""

    st.title("Compare tables")
    repository = LanceRepository(config.max_query_rows)

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
    with st.form("row-compare"):
        row_left_uri = st.text_input("Left table URI", value=left_uri, key="row-left-uri")
        row_right_uri = st.text_input("Right table URI", value=right_uri, key="row-right-uri")
        columns_text = st.text_input("Columns (comma-separated)", placeholder="id,name,status")
        key_column = st.text_input(
            "Unique key column (optional)",
            placeholder="id",
            help=help_text("comparison_key"),
        )
        limit = st.number_input("Maximum rows per table", 1, config.max_query_rows, 1_000)
        run_rows = st.form_submit_button("Compare bounded rows")

    columns = parse_columns(columns_text)
    if run_rows:
        try:
            if not columns:
                raise ValueError("Select at least one comparison column")
            st.session_state.comparison_results["rows"] = compare_rows(
                repository,
                row_left_uri,
                row_right_uri,
                columns=columns,
                key=key_column.strip() or None,
                limit=int(limit),
            )
        except Exception as exc:
            st.error(str(exc))

    row_result = st.session_state.comparison_results.get("rows")
    if row_result:
        st.write(f"Mode: `{row_result['mode']}`")
        for name, value in row_result.items():
            if name in {"mode", "left_rows", "right_rows"}:
                continue
            st.subheader(name.replace("_", " ").title())
            if isinstance(value, pd.DataFrame):
                st.dataframe(value, width="stretch")
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
            },
            template_directory=template_directory(config),
        )
