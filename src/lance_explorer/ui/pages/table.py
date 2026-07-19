from __future__ import annotations

from dataclasses import asdict

import pandas as pd
import streamlit as st

from lance_explorer.config import AppConfig
from lance_explorer.repository import LanceRepository
from lance_explorer.schema_diff import diff_schemas
from lance_explorer.ui.cache import cached_snapshot, cached_versions
from lance_explorer.ui.components.code_export import show_code_export
from lance_explorer.ui.components.common import parse_version, table_uri_control, template_directory
from lance_explorer.ui.help_text import help_text
from lance_explorer.ui.state import generation_for


def _version_numbers(versions: list[dict[str, object]], current_version: object) -> list[int]:
    numbers: set[int] = set()
    for item in versions:
        value = item.get("version")
        if isinstance(value, int):
            numbers.add(value)
    if isinstance(current_version, int):
        numbers.add(current_version)
    return sorted(numbers)


def _sync_schema_diff_defaults(table_uri: str, version_numbers: list[int]) -> None:
    if not version_numbers:
        return
    defaults = (table_uri, version_numbers[0], version_numbers[-1])
    if st.session_state.get("schema_diff_defaults") == defaults:
        return
    st.session_state["schema_diff_defaults"] = defaults
    st.session_state["schema-left-version"] = str(version_numbers[0])
    st.session_state["schema-right-version"] = str(version_numbers[-1])


def render(config: AppConfig) -> None:
    st.title("Table")
    table_uri = table_uri_control(key="table-open-form")
    if not table_uri:
        st.info("Select a full .lance table URI in Explorer or enter one above.")
        return

    generation = generation_for(table_uri)
    try:
        snapshot = cached_snapshot(table_uri, None, generation)
    except Exception as exc:
        st.error(f"Unable to open table: {exc}")
        return

    try:
        versions = cached_versions(table_uri, generation)
    except Exception as exc:
        versions = []
        st.warning(f"Unable to load table versions: {exc}")
    version_numbers = _version_numbers(versions, snapshot["version"])
    _sync_schema_diff_defaults(table_uri, version_numbers)

    metrics = st.columns(4)
    metrics[0].metric("Rows", snapshot["row_count"], help=help_text("rows"))
    metrics[1].metric("Version", snapshot["version"], help=help_text("version"))
    statistics = snapshot.get("statistics", {})
    fragment_stats = statistics.get("fragment_stats", {})
    metrics[2].metric(
        "Fragments", fragment_stats.get("num_fragments", "-"), help=help_text("fragments")
    )
    metrics[3].metric("Indices", len(snapshot.get("indexes", [])), help=help_text("indexes"))

    tabs = st.tabs(["Schema", "Statistics", "Versions", "Schema changes", "Indexes", "Sample"])
    with tabs[0]:
        st.caption("Arrow schema", help=help_text("schema"))
        st.dataframe(pd.DataFrame(snapshot["schema"]), width="stretch")
        st.code(snapshot["schema_string"], language="text")
    with tabs[1]:
        st.caption("Physical layout", help=help_text("statistics"))
        st.json(statistics)
    with tabs[2]:
        st.caption("Table history", help=help_text("versions"))
        st.dataframe(pd.DataFrame(versions), width="stretch")
    with tabs[3]:
        st.caption("Historical schema comparison", help=help_text("schema_changes"))
        with st.form("version-schema-diff"):
            left_text = st.text_input("Left version", key="schema-left-version")
            right_text = st.text_input("Right version", key="schema-right-version")
            compare = st.form_submit_button("Compare schemas")
        if compare:
            try:
                left_version = parse_version(left_text)
                right_version = parse_version(right_text)
                repository = LanceRepository(config.max_query_rows)
                changes = [
                    asdict(change)
                    for change in diff_schemas(
                        repository.get_schema(table_uri, left_version),
                        repository.get_schema(table_uri, right_version),
                    )
                ]
                st.session_state["table_schema_diff"] = changes
            except Exception as exc:
                st.error(str(exc))
        changes = st.session_state.get("table_schema_diff")
        if changes is not None:
            st.dataframe(pd.DataFrame(changes), width="stretch")
    with tabs[4]:
        st.caption("Secondary indexes", help=help_text("indexes"))
        indexes = snapshot.get("indexes", [])
        st.dataframe(pd.DataFrame(indexes), width="stretch")
    with tabs[5]:
        st.caption("Bounded data preview", help=help_text("sample"))
        fields = [row["path"] for row in snapshot["schema"] if "." not in row["path"]]
        with st.form("table-preview"):
            columns = st.multiselect("Columns", fields, default=fields[: min(8, len(fields))])
            limit = st.number_input(
                "Row limit", 1, config.max_query_rows, config.default_query_rows
            )
            load = st.form_submit_button("Load sample")
        if load:
            try:
                st.session_state["table_preview"] = LanceRepository(config.max_query_rows).preview(
                    table_uri, columns=columns or None, limit=int(limit)
                )
            except Exception as exc:
                st.error(str(exc))
        preview = st.session_state.get("table_preview")
        if preview is not None:
            st.dataframe(preview, width="stretch")

    code_version_options: list[int | None] = [None, *reversed(version_numbers)]
    code_version = st.selectbox(
        "Version for open-table code",
        code_version_options,
        format_func=lambda value: "Latest" if value is None else str(value),
    )
    show_code_export(
        "open_table",
        {"table_uri": table_uri, "open_version": code_version},
        template_directory=template_directory(config),
    )
