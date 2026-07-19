from __future__ import annotations

import streamlit as st

from lance_explorer.config import AppConfig
from lance_explorer.paths import is_lance_table_path, make_upath
from lance_explorer.ui.cache import children_for_uri
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
        width="stretch",
    )


def _entry_type(is_dir: bool, is_table: bool) -> str:
    if is_table:
        return "table"
    if is_dir:
        return "directory"
    return "file"


def _entry_icon(entry_type: str, *, selected: bool = False) -> str:
    if selected:
        return "\u2b50"
    return {
        "directory": "\U0001f4c1",
        "table": "\u2733\ufe0f",
        "file": ":material/draft:",
    }[entry_type]


def _entry_label(name: str, entry_type: str) -> str:
    if entry_type == "directory":
        return f"{name}/"
    return name


def _selected_entry_label(name: str, entry_type: str, *, selected: bool) -> str:
    label = _entry_label(name, entry_type)
    if selected:
        return f"-> {label}"
    return label


def _entry_sort_key(entry) -> tuple[int, str]:
    entry_type = _entry_type(entry.is_dir, entry.is_table)
    rank = {"table": 0, "directory": 1, "file": 2}[entry_type]
    return rank, entry.name.lower()


def _breadcrumb_items(uri: str) -> list[tuple[str, str]]:
    path = make_upath(uri)
    items: list[tuple[str, str]] = []
    seen: set[str] = set()
    while True:
        path_uri = str(path)
        if path_uri in seen:
            break
        seen.add(path_uri)
        items.append((path.name or path_uri, path_uri))
        parent = path.parent
        if str(parent) == path_uri:
            break
        path = parent
    return list(reversed(items))


def _render_breadcrumbs(current_uri: str) -> None:
    with st.container(key="explorer-breadcrumbs", horizontal=True, gap="small"):
        for index, (label, uri) in enumerate(_breadcrumb_items(current_uri)):
            if index:
                st.markdown("/")
            if st.button(label, key=f"breadcrumb-{index}-{uri}", help=uri, type="tertiary"):
                navigate(uri)
                st.rerun()


def _inject_explorer_styles() -> None:
    st.markdown(
        """
        <style>
        .st-key-directory-listing div[data-testid="stButton"] {
            margin-bottom: 0;
            min-height: 1.75rem;
        }
        .st-key-directory-listing div[data-testid="stButton"] button[kind="tertiary"] {
            justify-content: flex-start;
            min-height: 1.75rem;
            padding: 0 0.1rem;
            text-align: left;
        }
        .st-key-directory-listing div[data-testid="stButton"] button[kind="tertiary"] p,
        .st-key-explorer-breadcrumbs div[data-testid="stButton"] button[kind="tertiary"] p {
            color: #1f6feb;
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
            font-size: 0.86rem;
            line-height: 2;
            overflow: hidden;
            text-decoration: underline;
            text-overflow: ellipsis;
            text-underline-offset: 0.15rem;
            white-space: nowrap;
        }
        .st-key-explorer-breadcrumbs {
            align-items: center;
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
        go = go_col.form_submit_button("Go", width="stretch")
    if go:
        try:
            navigate(entered_uri)
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

    controls = st.columns([1, 1, 1, 1, 1, 9])
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

    current_uri = st.session_state.current_uri
    st.caption(current_uri)
    _render_breadcrumbs(current_uri)

    if is_lance_table_path(current_uri):
        select_table(current_uri)
        st.info("This URI looks like a Lance table and is now the selected table.")
        show_code_export(
            "open_table",
            {"table_uri": current_uri, "open_version": None},
            template_directory=template_directory(config),
        )
        return

    generation = generation_for(current_uri)
    try:
        entries = children_for_uri(current_uri, generation)
    except Exception as exc:
        st.error(f"Unable to list this URI: {exc}")
        entries = []

    st.subheader("Directory Listing")
    if "explorer_lance_only" not in st.session_state:
        st.session_state["explorer_lance_only"] = True
    lance_only = st.checkbox(
        "Hide non-Lance files",
        key="explorer_lance_only",
        help="Show folders and .lance tables only.",
    )
    if lance_only:
        entries = [entry for entry in entries if entry.is_dir or entry.is_table]
    entries = sorted(entries, key=_entry_sort_key)
    if not entries:
        st.caption("No child paths found.")
    with st.container(key="directory-listing", gap=None):
        selected_table = st.session_state.get("selected_table_uri", "")
        for index, entry in enumerate(entries):
            entry_type = _entry_type(entry.is_dir, entry.is_table)
            is_selected = entry.is_table and entry.uri == selected_table
            help_label = (
                "Select table" if entry.is_table else "Open folder" if entry.is_dir else "View path"
            )
            if st.button(
                _selected_entry_label(entry.name, entry_type, selected=is_selected),
                key=f"entry-{index}-{entry.uri}",
                help=f"{help_label}: {entry.uri}",
                icon=_entry_icon(entry_type, selected=is_selected),
                type="tertiary",
            ):
                if entry.is_table:
                    select_table(entry.uri)
                elif entry.is_dir:
                    navigate(entry.uri)
                else:
                    navigate(entry.uri)
                st.rerun()
