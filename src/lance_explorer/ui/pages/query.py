from __future__ import annotations

import pyarrow as pa
import streamlit as st

from lance_explorer.config import AppConfig
from lance_explorer.repository import LanceRepository, QueryResult, parse_vector
from lance_explorer.ui.cache import cached_snapshot
from lance_explorer.ui.components.code_export import show_code_export
from lance_explorer.ui.components.common import table_uri_control, template_directory
from lance_explorer.ui.help_text import help_text
from lance_explorer.ui.state import generation_for


def _display_query_result(result: QueryResult | None) -> None:
    if result is None:
        return
    st.dataframe(result.rows, width="stretch")
    if result.plan:
        st.code(result.plan, language="text")


def render(config: AppConfig) -> None:
    """Render bounded filter, full-text, and raw-vector query workflows."""

    st.title("Query workbench")
    table_uri = table_uri_control(key="query-table-open")
    if not table_uri:
        return

    try:
        snapshot = cached_snapshot(table_uri, None, generation_for(table_uri))
    except Exception as exc:
        st.error(str(exc))
        return

    fields = [row["path"] for row in snapshot["schema"] if "." not in row["path"]]
    type_by_field = {field.name: field.type for field in LanceRepository().get_schema(table_uri)}
    string_fields = [
        name
        for name, data_type in type_by_field.items()
        if pa.types.is_string(data_type) or pa.types.is_large_string(data_type)
    ]
    vector_fields = [
        name
        for name, data_type in type_by_field.items()
        if pa.types.is_fixed_size_list(data_type)
        or pa.types.is_list(data_type)
        or pa.types.is_large_list(data_type)
    ]

    filter_tab, fts_tab, vector_tab = st.tabs(["Filter", "Full text", "Raw vector"])
    repository = LanceRepository(config.max_query_rows)

    with filter_tab:
        st.caption("Bounded structured-data scan", help=help_text("filter_query"))
        with st.form("filter-query"):
            filter_columns = st.multiselect("Return columns", fields, key="filter-columns")
            where = st.text_area(
                "SQL-style filter",
                placeholder="status = 'active'",
                help=help_text("filter_query"),
            )
            limit = st.number_input(
                "Limit", 1, config.max_query_rows, config.default_query_rows, key="filter-limit"
            )
            plan = st.checkbox(
                "Include query plan", key="filter-plan", help=help_text("query_plan")
            )
            run = st.form_submit_button("Run filter query")
        if run:
            try:
                st.session_state.query_results["filter"] = repository.run_filter(
                    table_uri,
                    where=where,
                    columns=filter_columns or None,
                    limit=int(limit),
                    include_plan=plan,
                )
            except Exception as exc:
                st.error(str(exc))
        _display_query_result(st.session_state.query_results.get("filter"))
        show_code_export(
            "filter_query",
            {
                "table_uri": table_uri,
                "columns": filter_columns,
                "where": where.strip(),
                "limit": int(limit),
            },
            template_directory=template_directory(config),
        )

    with fts_tab:
        st.caption("Keyword search with BM25 ranking", help=help_text("fts_query"))
        if not string_fields:
            st.warning("No string columns are available.")
        else:
            with st.form("fts-query"):
                fts_column = st.selectbox("FTS column", string_fields)
                text = st.text_input("Search text", help=help_text("fts_query"))
                fts_where = st.text_area("Optional filter", key="fts-where")
                fts_columns = st.multiselect("Return columns", fields, key="fts-columns")
                fts_limit = st.number_input(
                    "Limit", 1, config.max_query_rows, config.default_query_rows, key="fts-limit"
                )
                fts_plan = st.checkbox(
                    "Include query plan", key="fts-plan", help=help_text("query_plan")
                )
                run_fts = st.form_submit_button("Run full-text search")
            if run_fts:
                try:
                    st.session_state.query_results["fts"] = repository.run_fts(
                        table_uri,
                        text=text,
                        column=fts_column,
                        where=fts_where,
                        columns=fts_columns or None,
                        limit=int(fts_limit),
                        include_plan=fts_plan,
                    )
                except Exception as exc:
                    st.error(str(exc))
            _display_query_result(st.session_state.query_results.get("fts"))
            show_code_export(
                "fts_query",
                {
                    "table_uri": table_uri,
                    "text": text,
                    "column": fts_column,
                    "columns": fts_columns,
                    "where": fts_where.strip(),
                    "limit": int(fts_limit),
                },
                template_directory=template_directory(config),
            )

    with vector_tab:
        st.caption(
            "No embedding generation is performed; paste a numeric JSON vector.",
            help=help_text("raw_vector"),
        )
        if not vector_fields:
            st.warning("No list-like vector columns are available.")
        else:
            with st.form("vector-query"):
                vector_column = st.selectbox("Vector column", vector_fields)
                vector_text = st.text_area(
                    "Vector", placeholder="[0.12, -0.4, 0.8]", help=help_text("raw_vector")
                )
                vector_where = st.text_area("Optional filter", key="vector-where")
                vector_columns = st.multiselect("Return columns", fields, key="vector-columns")
                vector_limit = st.number_input(
                    "Limit", 1, config.max_query_rows, 10, key="vector-limit"
                )
                vector_plan = st.checkbox(
                    "Include query plan", key="vector-plan", help=help_text("query_plan")
                )
                run_vector = st.form_submit_button("Run vector search")
            parsed_vector: list[float] = []
            if run_vector:
                try:
                    parsed_vector = parse_vector(vector_text)
                    st.session_state.query_results["vector"] = repository.run_vector(
                        table_uri,
                        vector=parsed_vector,
                        column=vector_column,
                        where=vector_where,
                        columns=vector_columns or None,
                        limit=int(vector_limit),
                        include_plan=vector_plan,
                    )
                except Exception as exc:
                    st.error(str(exc))
            _display_query_result(st.session_state.query_results.get("vector"))
            if vector_text.strip():
                try:
                    parsed_vector = parse_vector(vector_text)
                except ValueError:
                    parsed_vector = []
            show_code_export(
                "vector_query",
                {
                    "table_uri": table_uri,
                    "vector": parsed_vector,
                    "column": vector_column,
                    "columns": vector_columns,
                    "where": vector_where.strip(),
                    "limit": int(vector_limit),
                },
                template_directory=template_directory(config),
            )
