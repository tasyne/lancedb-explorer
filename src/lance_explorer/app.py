from __future__ import annotations

import streamlit as st

from lance_explorer.config import AppConfig
from lance_explorer.ui.help_text import LANCE_OVERVIEW, LANCE_STRENGTHS
from lance_explorer.ui.pages import compare, explorer, indexes, maintenance, query, table
from lance_explorer.ui.state import initialize_state


def explorer_page() -> None:
    explorer.render(AppConfig.from_env())


def table_page() -> None:
    table.render(AppConfig.from_env())


def query_page() -> None:
    query.render(AppConfig.from_env())


def compare_page() -> None:
    compare.render(AppConfig.from_env())


def indexes_page() -> None:
    indexes.render(AppConfig.from_env())


def maintenance_page() -> None:
    maintenance.render(AppConfig.from_env())


def main() -> None:
    st.set_page_config(page_title="Lance Explorer", page_icon="🗂️", layout="wide")
    config = AppConfig.from_env()
    initialize_state(config)

    with st.sidebar.expander("Why Lance?", icon=":material/info:"):
        st.write(LANCE_OVERVIEW)
        for strength in LANCE_STRENGTHS:
            st.markdown(f"- {strength}")

    selected = st.session_state.get("selected_table_uri")
    if selected:
        st.sidebar.caption("Selected table")
        st.sidebar.code(selected, language="text")

    pages = [
        st.Page(explorer_page, title="Explorer", icon="📁", default=True),
        st.Page(table_page, title="Table", icon="🗂️"),
        st.Page(query_page, title="Query", icon="🔎"),
        st.Page(compare_page, title="Compare", icon="⚖️"),
        st.Page(indexes_page, title="Indexes", icon="🧭"),
        st.Page(maintenance_page, title="Maintenance", icon="🛠️"),
    ]
    st.navigation(pages).run()


if __name__ == "__main__":
    main()
