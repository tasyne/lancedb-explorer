from __future__ import annotations

import pandas as pd
import streamlit as st

from lance_explorer.config import AppConfig
from lance_explorer.index_registry import (
    available_index_definitions,
    compatible_index_definitions,
)
from lance_explorer.paths import split_table_uri
from lance_explorer.repository import LanceRepository
from lance_explorer.ui.cache import cached_snapshot
from lance_explorer.ui.components.code_export import show_code_export
from lance_explorer.ui.components.common import table_uri_control, template_directory
from lance_explorer.ui.help_text import help_text
from lance_explorer.ui.state import bump_generation, generation_for


def _refresh_after_mutation(table_uri: str) -> None:
    bump_generation(table_uri)
    bump_generation(split_table_uri(table_uri).database_uri)
    st.session_state.query_results = {}
    st.session_state.comparison_results = {}
    st.session_state.pop("table_preview", None)
    st.session_state.pop("table_schema_diff", None)


def _show_status_once() -> None:
    if message := st.session_state.pop("index_status", None):
        st.success(message)


def render(config: AppConfig) -> None:
    st.title("Indexes")
    _show_status_once()
    table_uri = table_uri_control(key="index-table-open")
    if not table_uri:
        return

    generation = generation_for(table_uri)
    repository = LanceRepository(config.max_query_rows)
    try:
        snapshot = cached_snapshot(table_uri, None, generation)
        schema = repository.get_schema(table_uri)
    except Exception as exc:
        st.error(str(exc))
        return

    st.subheader("Existing indexes", help=help_text("existing_indexes"))
    indexes = snapshot.get("indexes", [])
    st.dataframe(pd.DataFrame(indexes), width="stretch")

    st.subheader("Create index", help=help_text("create_index"))
    with st.popover("Index type guide", icon=":material/info:"):
        for index_definition in available_index_definitions():
            st.markdown(f"**{index_definition.label}** - {index_definition.description}")
        st.caption("After writes, Optimize folds new rows into existing indexes.")

    column_names = schema.names
    selected_column = st.selectbox("Column", column_names)
    field = schema.field(selected_column)
    definitions = compatible_index_definitions(field.type)
    if not definitions:
        st.warning(f"No registered non-vector index type supports {field.type}.")
    else:
        labels = {
            definition.key: f"{definition.label} - {definition.description}"
            for definition in definitions
        }
        selected_type = st.selectbox(
            "Index type",
            list(labels),
            format_func=labels.get,
            help=help_text("create_index"),
        )
        index_name = st.text_input("Index name (optional)")
        replace = st.checkbox(
            "Replace an index with the same name",
            help=help_text("replace_index"),
        )
        with_position = st.checkbox(
            "Store token positions (FTS only)",
            value=True,
            disabled=selected_type != "FTS",
            help=help_text("fts_positions"),
        )

        config_options: dict[str, object] = {}
        if selected_type == "FTS":
            config_options["with_position"] = with_position

        definition = next(item for item in definitions if item.key == selected_type)
        show_code_export(
            "create_index",
            {
                "table_uri": table_uri,
                "column": selected_column,
                "config_class": definition.class_name,
                "config_options": config_options,
                "index_name": index_name.strip() or None,
                "replace": replace,
            },
            template_directory=template_directory(config),
        )

        with st.form("create-index"):
            create_confirmation = st.checkbox(
                "I understand this will modify the selected table metadata."
            )
            create = st.form_submit_button("Create index")
        if create:
            if not create_confirmation:
                st.error("Confirm that you want to create this index.")
            else:
                try:
                    st.session_state.operation_results["create_index"] = repository.create_index(
                        table_uri,
                        column=selected_column,
                        index_type=selected_type,
                        name=index_name.strip() or None,
                        replace=replace,
                        config_options=config_options,
                    )
                    _refresh_after_mutation(table_uri)
                    st.session_state["index_status"] = "Index created"
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

    st.subheader("Drop index", help=help_text("drop_index"))
    index_names = [str(item.get("name", "")) for item in indexes if item.get("name")]
    if not index_names:
        st.caption("No named indexes are available.")
    else:
        drop_name = st.selectbox("Index", index_names)
        show_code_export(
            "drop_index",
            {"table_uri": table_uri, "index_name": drop_name},
            template_directory=template_directory(config),
        )
        with st.form("drop-index"):
            st.caption("Type the exact index name to confirm deletion.")
            st.code(drop_name, language="text")
            drop_confirmation = st.text_input("Index name")
            drop = st.form_submit_button("Drop index")
        if drop:
            if drop_confirmation != drop_name:
                st.error("The index name does not match.")
            else:
                try:
                    st.session_state.operation_results["drop_index"] = repository.drop_index(
                        table_uri, drop_name
                    )
                    _refresh_after_mutation(table_uri)
                    st.session_state["index_status"] = (
                        "Index dropped. Optimize later to remove unreferenced files."
                    )
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
