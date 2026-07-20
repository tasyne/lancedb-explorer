from __future__ import annotations

import shutil
import subprocess
import sys

import streamlit as st

from lance_explorer.config import AppConfig
from lance_explorer.paths import split_table_uri
from lance_explorer.ui.help_text import LANCE_OVERVIEW, LANCE_STRENGTHS
from lance_explorer.ui.pages import compare, docs, explorer, indexes, maintenance, query, table
from lance_explorer.ui.state import initialize_state, select_table


def explorer_page() -> None:
    """Render the storage/table explorer page."""

    explorer.render(AppConfig.from_env())


def table_page() -> None:
    """Render table metadata, schema, version, and preview tools."""

    table.render(AppConfig.from_env())


def query_page() -> None:
    """Render bounded filter, FTS, and raw-vector query tools."""

    query.render(AppConfig.from_env())


def compare_page() -> None:
    """Render table metadata and bounded row comparison tools."""

    compare.render(AppConfig.from_env())


def indexes_page() -> None:
    """Render non-vector index inspection and management tools."""

    indexes.render(AppConfig.from_env())


def maintenance_page() -> None:
    """Render table optimization, cleanup, restore, and drop tools."""

    maintenance.render(AppConfig.from_env())


def docs_page() -> None:
    """Render offline documentation mirrors and the local docs index."""

    docs.render()


def _short_table_label(table_uri: str) -> str:
    try:
        location = split_table_uri(table_uri)
        parent_name = location.database_uri.rstrip("/\\").replace("\\", "/").split("/")[-1]
        if parent_name:
            return f"{parent_name}/{location.table_name}.lance"
        return f"{location.table_name}.lance"
    except Exception:
        return table_uri


def _copy_to_local_clipboard(value: str) -> None:
    if sys.platform == "win32":
        subprocess.run(["clip"], input=value, text=True, check=True)
        return
    if sys.platform == "darwin" and shutil.which("pbcopy"):
        subprocess.run(["pbcopy"], input=value, text=True, check=True)
        return
    for command in ("wl-copy", "xclip"):
        if shutil.which(command):
            args = [command] if command == "wl-copy" else [command, "-selection", "clipboard"]
            subprocess.run(args, input=value, text=True, check=True)
            return
    raise RuntimeError("No local clipboard command is available.")


def _copy_table_uri_button(table_uri: str, *, key: str) -> None:
    if st.button(
        "",
        key=key,
        help="Copy full table URI",
        icon=":material/content_copy:",
        width="stretch",
    ):
        try:
            _copy_to_local_clipboard(table_uri)
            st.toast("Copied table URI")
        except Exception as exc:
            st.sidebar.error(f"Unable to copy table URI: {exc}")


def _table_uri_row(
    table_uri: str,
    *,
    key: str,
    icon: str,
    disabled: bool = False,
) -> bool:
    label_col, copy_col = st.sidebar.columns([0.82, 0.18], vertical_alignment="center")
    selected = label_col.button(
        _short_table_label(table_uri),
        key=key,
        help=table_uri,
        icon=icon,
        width="stretch",
        disabled=disabled,
    )
    with copy_col:
        _copy_table_uri_button(table_uri, key=f"{key}-copy")
    return selected


def _render_table_selection_sidebar() -> None:
    selected = st.session_state.get("selected_table_uri")
    history = [
        item
        for item in st.session_state.get("selected_table_history", [])
        if item and item != selected
    ]

    st.sidebar.divider()
    st.sidebar.caption("Selected table")
    if selected:
        _table_uri_row(
            selected,
            key="selected-table-current",
            icon=":material/database:",
            disabled=True,
        )
    else:
        st.sidebar.caption("No table selected")

    st.sidebar.caption("Table history")
    if not history:
        st.sidebar.caption("No prior table selections")
        return
    for index, table_uri in enumerate(history[:10]):
        if _table_uri_row(
            table_uri,
            key=f"selected-table-history-{index}-{table_uri}",
            icon=":material/history:",
        ):
            select_table(table_uri)
            st.rerun()


def main() -> None:
    """Initialize shared Streamlit state and run multipage navigation."""

    st.set_option("client.toolbarMode", "viewer")
    st.set_page_config(page_title="Lance Explorer", page_icon="🗂️", layout="wide")
    config = AppConfig.from_env()
    initialize_state(config)

    with st.sidebar.expander("Why Lance?", icon=":material/info:"):
        st.write(LANCE_OVERVIEW)
        for strength in LANCE_STRENGTHS:
            st.markdown(f"- {strength}")

    _render_table_selection_sidebar()

    pages = [
        st.Page(explorer_page, title="Explorer", icon="📁", default=True),
        st.Page(table_page, title="Table", icon="🗂️"),
        st.Page(query_page, title="Query", icon="🔎"),
        st.Page(compare_page, title="Compare", icon="⚖️"),
        st.Page(indexes_page, title="Indexes", icon="🧭"),
        st.Page(maintenance_page, title="Maintenance", icon="🛠️"),
        st.Page(docs_page, title="Docs", icon="📚"),
    ]
    st.navigation(pages).run()


if __name__ == "__main__":
    main()
