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


def _icon_button(container: st.delta_generator.DeltaGenerator, label: str, icon: str) -> bool:
    return container.button(
        "",
        key=f"explorer-{label.lower().replace(' ', '-')}",
        help=label,
        icon=icon,
        use_container_width=True,
    )


def _entry_type(is_dir: bool, is_table: bool) -> str:
    if is_dir:
        return "directory"
    if is_table:
        return "table"
    return "file"


def _entry_icon(entry_type: str) -> str:
    return {
        "directory": ":material/folder:",
        "table": ":material/table:",
        "file": ":material/draft:",
    }[entry_type]


def _entry_label(name: str, entry_type: str) -> str:
    if entry_type == "directory":
        return f"{name}/"
    return name


def _inject_explorer_styles() -> None:
    st.markdown(
        """
        <style>
        div[data-testid="stVerticalBlock"] div[data-testid="stButton"] {
            margin-bottom: -0.45rem;
        }
        div[data-testid="stButton"] button[kind="tertiary"] {
            justify-content: flex-start;
            min-height: 1.7rem;
            padding: 0.08rem 0.15rem;
            text-align: left;
        }
        div[data-testid="stButton"] button[kind="tertiary"] p {
            color: #1f6feb;
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
            font-size: 0.92rem;
            line-height: 1.2;
            overflow: hidden;
            text-decoration: underline;
            text-overflow: ellipsis;
            text-underline-offset: 0.15rem;
            white-space: nowrap;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render(config: AppConfig) -> None:
    st.title("Explorer")
    _inject_explorer_styles()

    current_uri = st.session_state.current_uri
    if st.session_state.get("uri_bar_synced") != current_uri:
        st.session_state["uri_bar_value"] = current_uri
        st.session_state["uri_bar_synced"] = current_uri
    st.caption("Location", help=help_text("uri_bar"))
    with st.form("uri_bar"):
        uri_col, go_col = st.columns([7, 1], vertical_alignment="bottom")
        entered_uri = uri_col.text_input("URI", key="uri_bar_value", label_visibility="collapsed")
        go = go_col.form_submit_button("Go", use_container_width=True)
    if go:
        try:
            navigate(entered_uri)
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

    controls = st.columns([1, 1, 1, 1, 1, 1, 8])
    if _icon_button(controls[0], "Back", ":material/arrow_back:") and navigate_back():
        st.rerun()
    if _icon_button(controls[1], "Forward", ":material/arrow_forward:") and navigate_forward():
        st.rerun()
    if _icon_button(controls[2], "Up", ":material/arrow_upward:"):
        navigate_up()
        st.rerun()
    if _icon_button(controls[3], "Home", ":material/home:"):
        navigate(config.home_uri)
        st.rerun()
    if _icon_button(controls[4], "Refresh", ":material/refresh:"):
        bump_generation(current_uri)
        st.rerun()
    if controls[5].button(
        "",
        key="explorer-select-current-table",
        help="Select table",
        icon=":material/check:",
        use_container_width=True,
        disabled=not is_lance_table_path(current_uri),
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
        entry_type = _entry_type(entry.is_dir, entry.is_table)
        help_label = (
            "Open folder" if entry.is_dir else "Select table" if entry.is_table else "View path"
        )
        if st.button(
            _entry_label(entry.name, entry_type),
            key=f"entry-{index}-{entry.uri}",
            help=f"{help_label}: {entry.uri}",
            icon=_entry_icon(entry_type),
            type="tertiary",
            use_container_width=True,
        ):
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
        if st.button(
            f"{table_name}.lance",
            key=f"db-table-{table_name}",
            help=f"Select table: {table_uri}",
            icon=":material/table:",
            type="tertiary",
        ):
            select_table(table_uri)
            st.rerun()

    show_code_export(
        "connect",
        {"database_uri": normalize_uri(current_uri)},
        template_directory=template_directory(config),
    )
