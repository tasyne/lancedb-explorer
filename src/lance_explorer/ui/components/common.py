from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from lance_explorer.config import AppConfig
from lance_explorer.paths import normalize_uri
from lance_explorer.ui.components.dataframe import show_dataframe
from lance_explorer.ui.help_text import help_text
from lance_explorer.ui.state import select_table


def table_uri_control(*, key: str = "table_uri_control") -> str:
    """Render the shared selected-table input and return the active table URI."""

    current = st.session_state.get("selected_table_uri", "")
    value_key = f"{key}-value"
    sync_key = f"{key}-synced"
    if st.session_state.get(sync_key) != current:
        st.session_state[value_key] = current
        st.session_state[sync_key] = current
    with st.form(key):
        value = st.text_input(
            "Full Lance table URI",
            key=value_key,
            placeholder="/data/db/table.lance",
            help=help_text("table_uri"),
        )
        submitted = st.form_submit_button("Open table")
    if submitted:
        try:
            select_table(normalize_uri(value))
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    return st.session_state.get("selected_table_uri", "")


def display_result(result: Any, *, vector_columns: list[str] | set[str] | None = None) -> None:
    """Display action/query output with special handling for empty LanceDB results."""

    if result is None:
        return
    if isinstance(result, pd.DataFrame):
        show_dataframe(result, vector_columns=vector_columns or ())
        return
    if isinstance(result, dict):
        if not result:
            st.info("Operation completed. LanceDB returned no additional details.")
            return
        st.json(result)
        return
    st.write(result)


def template_directory(config: AppConfig) -> str | None:
    """Return the configured code-template override directory, if any."""

    return str(config.template_override_dir) if config.template_override_dir else None


def parse_version(value: str) -> int | None:
    """Parse an optional positive version number from UI text input."""

    stripped = value.strip()
    if not stripped:
        return None
    version = int(stripped)
    if version < 1:
        raise ValueError("Version must be a positive integer")
    return version


def parse_columns(value: str) -> list[str]:
    """Parse a comma-separated column list from UI text input."""

    return [item.strip() for item in value.split(",") if item.strip()]
