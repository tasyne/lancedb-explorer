from __future__ import annotations

import streamlit as st

from lance_explorer.config import AppConfig
from lance_explorer.paths import is_lance_table_path, join_uri, normalize_uri
from lance_explorer.ui.cache import cached_table_names, children_for_uri
from lance_explorer.ui.components.code_export import show_code_export
from lance_explorer.ui.components.common import template_directory
from lance_explorer.ui.help_text import help_text
from lance_explorer.ui.state import (
    bump_generation,
    generation_for,
    navigate,
    navigate_back,
    navigate_forward,
    navigate_up,
    select_table,
)


def render(config: AppConfig) -> None:
    st.title("Explorer")

    current_uri = st.session_state.current_uri
    if st.session_state.get("uri_bar_synced") != current_uri:
        st.session_state["uri_bar_value"] = current_uri
        st.session_state["uri_bar_synced"] = current_uri
    st.caption("Location", help=help_text("uri_bar"))
    with st.form("uri_bar"):
        entered_uri = st.text_input("URI", key="uri_bar_value", label_visibility="collapsed")
        go = st.form_submit_button("Go")
    if go:
        try:
            navigate(entered_uri)
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

    controls = st.columns(6)
    if controls[0].button("Back", use_container_width=True) and navigate_back():
        st.rerun()
    if controls[1].button("Forward", use_container_width=True) and navigate_forward():
        st.rerun()
    if controls[2].button("Up", use_container_width=True):
        navigate_up()
        st.rerun()
    if controls[3].button("Home", use_container_width=True):
        navigate(config.home_uri)
        st.rerun()
    if controls[4].button("Refresh", use_container_width=True):
        bump_generation(current_uri)
        st.rerun()
    if controls[5].button(
        "Select table", use_container_width=True, disabled=not is_lance_table_path(current_uri)
    ):
        select_table(current_uri)
        st.success("Selected table")

    current_uri = st.session_state.current_uri
    st.caption(current_uri)

    if is_lance_table_path(current_uri):
        select_table(current_uri)
        st.info("This URI looks like a Lance table and is now the selected table.")
        show_code_export(
            "open_table",
            {"table_uri": current_uri},
            template_directory=template_directory(config),
        )
        return

    generation = generation_for(current_uri)
    try:
        entries = children_for_uri(current_uri, generation)
    except Exception as exc:
        st.error(f"Unable to list this URI: {exc}")
        entries = []

    st.subheader("Children")
    if not entries:
        st.caption("No child paths found.")
    for index, entry in enumerate(entries):
        icon = "📁" if entry.is_dir else "🗂️" if entry.is_table else "📄"
        left, right = st.columns([5, 1])
        left.write(f"{icon} **{entry.name}**")
        action = "Open" if entry.is_dir else "Select" if entry.is_table else "View path"
        if right.button(action, key=f"entry-{index}-{entry.uri}", use_container_width=True):
            if entry.is_dir:
                navigate(entry.uri)
            elif entry.is_table:
                select_table(entry.uri)
            else:
                navigate(entry.uri)
            st.rerun()

    st.subheader("LanceDB database", help=help_text("database"))
    with st.form("probe_database"):
        probe = st.form_submit_button("List tables at this URI", help=help_text("database"))
    if probe:
        try:
            st.session_state["explorer_tables"] = {
                "uri": current_uri,
                "names": cached_table_names(current_uri, generation),
            }
        except Exception as exc:
            st.session_state["explorer_tables"] = {"uri": current_uri, "names": []}
            st.error(f"Unable to open this URI as a LanceDB database: {exc}")

    saved_tables = st.session_state.get("explorer_tables", {})
    table_names = saved_tables.get("names", []) if saved_tables.get("uri") == current_uri else []
    for table_name in table_names:
        table_uri = join_uri(current_uri, f"{table_name}.lance")
        if st.button(f"Select {table_name}", key=f"db-table-{table_name}"):
            select_table(table_uri)
            st.rerun()

    show_code_export(
        "connect",
        {"database_uri": normalize_uri(current_uri)},
        template_directory=template_directory(config),
    )
