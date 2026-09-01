from __future__ import annotations

import streamlit as st

from lance_explorer.compat import lancedb_compatibility_warning
from lance_explorer.config import AppConfig
from lance_explorer.language_models import ensure_packaged_language_model_home
from lance_explorer.table_refs import is_namespace_table_ref, table_display_label
from lance_explorer.ui.cache import cached_tags
from lance_explorer.ui.components.clipboard import browser_copy_button
from lance_explorer.ui.help_text import LANCE_OVERVIEW, LANCE_STRENGTHS
from lance_explorer.ui.state import (
    generation_for,
    initialize_state,
    select_table,
    selected_table_reference_label,
)

ensure_packaged_language_model_home()


def explorer_page() -> None:
    """Render the storage/table explorer page."""

    from lance_explorer.ui.pages import explorer

    explorer.render(AppConfig.from_env())


def table_page() -> None:
    """Render table metadata, schema, version, and preview tools."""

    from lance_explorer.ui.pages import table

    table.render(AppConfig.from_env())


def query_page() -> None:
    """Render bounded filter, FTS, and raw-vector query tools."""

    from lance_explorer.ui.pages import query

    query.render(AppConfig.from_env())


def compare_page() -> None:
    """Render table metadata and bounded row comparison tools."""

    from lance_explorer.ui.pages import compare

    compare.render(AppConfig.from_env())


def indexes_page() -> None:
    """Render non-vector index inspection and management tools."""

    from lance_explorer.ui.pages import indexes

    indexes.render(AppConfig.from_env())


def maintenance_page() -> None:
    """Render table optimization, cleanup, restore, and drop tools."""

    from lance_explorer.ui.pages import maintenance

    maintenance.render(AppConfig.from_env())


def docs_page() -> None:
    """Render offline documentation mirrors and the local docs index."""

    from lance_explorer.ui.pages import docs

    docs.render()


def _install_global_css() -> None:
    """Install small rendering fixes that Streamlit does not expose as options."""

    st.markdown(
        """
        <style>
        code,
        pre,
        textarea,
        input,
        [data-testid="stCodeBlock"] *,
        [data-testid="stTextArea"] *,
        [data-testid="stTextInput"] * {
            font-variant-ligatures: none;
            font-feature-settings: "liga" 0, "calt" 0;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _short_table_label(table_uri: str) -> str:
    try:
        return table_display_label(table_uri)
    except Exception:
        return table_uri


def _copy_table_uri_button(table_uri: str, *, key: str) -> None:
    browser_copy_button(
        table_uri,
        key_prefix=key,
        label="Copy",
        help_text="Copy full table URI",
        compact=True,
    )


def _table_uri_row(
    table_uri: str,
    *,
    key: str,
    icon: str,
    disabled: bool = False,
) -> bool:
    label_col, copy_col = st.sidebar.columns([0.76, 0.24], vertical_alignment="center")
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
        selected_icon = (
            ":material/account_tree:" if is_namespace_table_ref(selected) else ":material/database:"
        )
        _table_uri_row(
            selected,
            key="selected-table-current",
            icon=selected_icon,
            disabled=True,
        )
        try:
            tags = cached_tags(selected, generation_for(selected))
        except Exception:
            tags = []
        st.sidebar.caption(f"Open at: {selected_table_reference_label(tags)}")
    else:
        st.sidebar.caption("No table selected")

    st.sidebar.caption("Table history")
    if not history:
        st.sidebar.caption("No prior table selections")
        return
    for index, table_uri in enumerate(history[:10]):
        history_icon = (
            ":material/account_tree:"
            if is_namespace_table_ref(table_uri)
            else ":material/history:"
        )
        if _table_uri_row(
            table_uri,
            key=f"selected-table-history-{index}-{table_uri}",
            icon=history_icon,
        ):
            select_table(table_uri)
            st.rerun()


def main() -> None:
    """Initialize shared Streamlit state and run multipage navigation."""

    st.set_option("client.toolbarMode", "viewer")
    st.set_page_config(page_title="Lance Explorer", page_icon="🗂️", layout="wide")
    _install_global_css()
    if warning := lancedb_compatibility_warning():
        st.warning(warning, icon=":material/warning:")
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
        st.Page(indexes_page, title="Indexes", icon="🔖"),
        st.Page(maintenance_page, title="Maintenance", icon="🛠️"),
        st.Page(docs_page, title="Docs", icon="📚"),
    ]
    st.navigation(pages).run()


if __name__ == "__main__":
    main()
