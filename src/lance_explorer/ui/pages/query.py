from __future__ import annotations

import pyarrow as pa
import streamlit as st

from lance_explorer.config import AppConfig
from lance_explorer.repository import LanceRepository, QueryResult, parse_vector
from lance_explorer.ui.cache import cached_snapshot
from lance_explorer.ui.components.code_export import show_code_export
from lance_explorer.ui.components.common import table_uri_control, template_directory
from lance_explorer.ui.components.dataframe import show_dataframe, vector_display_columns
from lance_explorer.ui.help_text import help_text
from lance_explorer.ui.state import generation_for


def _display_query_result(result: QueryResult | None, *, vector_columns: set[str]) -> None:
    if result is None:
        return
    show_dataframe(result.rows, vector_columns=vector_columns)
    if result.plan:
        st.code(result.plan, language="text")


def _filter_placeholder(fields: list[str]) -> str:
    if "award_count" in fields and "active" in fields:
        return "award_count >= 3 AND active = true"
    if "id" in fields:
        return "id > 10"
    if fields:
        return f"{fields[0]} IS NOT NULL"
    return "id > 10"


def _fts_indexed_columns(indexes: list[dict[str, object]], string_fields: list[str]) -> list[str]:
    fts_columns: set[str] = set()
    for index in indexes:
        index_type = str(index.get("index_type") or index.get("type") or "").lower()
        type_url = str(index.get("type_url") or "").lower()
        if "fts" not in index_type and "inverted" not in type_url:
            continue
        columns = index.get("columns") or []
        if isinstance(columns, str):
            fts_columns.add(columns)
        elif isinstance(columns, list):
            fts_columns.update(str(column) for column in columns)
    return [field for field in string_fields if field in fts_columns]


def render(config: AppConfig) -> None:
    """Render bounded filter, full-text, hybrid, and raw-vector query workflows."""

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
    fts_fields = _fts_indexed_columns(snapshot.get("indexes", []), string_fields)
    vector_fields = [
        name
        for name, data_type in type_by_field.items()
        if pa.types.is_fixed_size_list(data_type)
        or pa.types.is_list(data_type)
        or pa.types.is_large_list(data_type)
    ]
    display_vector_columns = vector_display_columns(snapshot)

    filter_tab, fts_tab, hybrid_tab, vector_tab = st.tabs(
        ["Filter", "Full text", "Hybrid", "Raw vector"]
    )
    repository = LanceRepository(config.max_query_rows)
    where_placeholder = _filter_placeholder(fields)

    with filter_tab:
        st.caption("Bounded structured-data scan", help=help_text("filter_query"))
        with st.form("filter-query"):
            filter_columns = st.multiselect(
                "Return columns", fields, default=fields, key="filter-columns"
            )
            where = st.text_area(
                "SQL-style filter",
                placeholder=where_placeholder,
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
        _display_query_result(
            st.session_state.query_results.get("filter"),
            vector_columns=display_vector_columns,
        )
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
        st.caption(
            "Search text example: words to search across full-text index",
            help=help_text("fts_query"),
        )
        if not fts_fields:
            st.warning("No FTS-indexed string columns are available.")
        else:
            with st.form("fts-query"):
                fts_column = st.selectbox("FTS column", fts_fields)
                text = st.text_input(
                    "Search text",
                    placeholder="words to search across full-text index",
                    help=help_text("fts_query"),
                )
                fts_where = st.text_area(
                    "Optional SQL-style filter",
                    placeholder=where_placeholder,
                    key="fts-where",
                    help=help_text("filter_query"),
                )
                fts_columns = st.multiselect(
                    "Return columns", fields, default=fields, key="fts-columns"
                )
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
            _display_query_result(
                st.session_state.query_results.get("fts"),
                vector_columns=display_vector_columns,
            )
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

    with hybrid_tab:
        st.caption(
            "Hybrid search combines a pasted vector with full-text search.",
            help=help_text("hybrid_query"),
        )
        if not fts_fields or not vector_fields:
            st.warning("Hybrid search needs one FTS-indexed string column and one vector column.")
        else:
            with st.form("hybrid-query"):
                hybrid_fts_column = st.selectbox("FTS column", fts_fields, key="hybrid-fts")
                hybrid_vector_column = st.selectbox(
                    "Vector column", vector_fields, key="hybrid-vector-column"
                )
                hybrid_text = st.text_input(
                    "Search text",
                    placeholder="words to search across full-text index",
                    help=help_text("fts_query"),
                )
                hybrid_vector_text = st.text_area(
                    "Vector", placeholder="[0.1, -0.2, 0.3, 0.5]", help=help_text("raw_vector")
                )
                hybrid_where = st.text_area(
                    "Optional SQL-style filter",
                    placeholder=where_placeholder,
                    key="hybrid-where",
                    help=help_text("filter_query"),
                )
                hybrid_columns = st.multiselect(
                    "Return columns", fields, default=fields, key="hybrid-columns"
                )
                hybrid_limit = st.number_input(
                    "Limit",
                    1,
                    config.max_query_rows,
                    config.default_query_rows,
                    key="hybrid-limit",
                )
                hybrid_rerank = st.checkbox(
                    "Rerank",
                    value=True,
                    key="hybrid-rerank",
                    help=(
                        "Uses LanceDB's model-free RRF reranker. Hybrid search uses RRF fusion "
                        "by default; this applies it explicitly."
                    ),
                )
                hybrid_plan = st.checkbox(
                    "Include query plan", key="hybrid-plan", help=help_text("query_plan")
                )
                run_hybrid = st.form_submit_button("Run hybrid search")
            parsed_hybrid_vector: list[float] = []
            if hybrid_vector_text.strip():
                try:
                    parsed_hybrid_vector = parse_vector(hybrid_vector_text)
                except ValueError:
                    parsed_hybrid_vector = []
            if run_hybrid:
                try:
                    parsed_hybrid_vector = parse_vector(hybrid_vector_text)
                    st.session_state.query_results["hybrid"] = repository.run_hybrid(
                        table_uri,
                        text=hybrid_text,
                        vector=parsed_hybrid_vector,
                        vector_column=hybrid_vector_column,
                        fts_column=hybrid_fts_column,
                        where=hybrid_where,
                        columns=hybrid_columns or None,
                        limit=int(hybrid_limit),
                        rerank=hybrid_rerank,
                        include_plan=hybrid_plan,
                    )
                except Exception as exc:
                    st.error(str(exc))
            _display_query_result(
                st.session_state.query_results.get("hybrid"),
                vector_columns=display_vector_columns,
            )
            show_code_export(
                "hybrid_query",
                {
                    "table_uri": table_uri,
                    "text": hybrid_text,
                    "vector": parsed_hybrid_vector,
                    "vector_column": hybrid_vector_column,
                    "fts_column": hybrid_fts_column,
                    "columns": hybrid_columns,
                    "where": hybrid_where.strip(),
                    "limit": int(hybrid_limit),
                    "rerank": hybrid_rerank,
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
                    "Vector", placeholder="[0.1, -0.2, 0.3, 0.5]", help=help_text("raw_vector")
                )
                vector_where = st.text_area(
                    "Optional SQL-style filter",
                    placeholder=where_placeholder,
                    key="vector-where",
                    help=help_text("filter_query"),
                )
                vector_columns = st.multiselect(
                    "Return columns", fields, default=fields, key="vector-columns"
                )
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
            _display_query_result(
                st.session_state.query_results.get("vector"),
                vector_columns=display_vector_columns,
            )
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
