from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from lance_explorer.config import AppConfig
from lance_explorer.paths import normalize_uri, split_table_uri
from lance_explorer.ui.cache import cached_tags, cached_versions
from lance_explorer.ui.components.dataframe import show_dataframe
from lance_explorer.ui.help_text import help_text
from lance_explorer.ui.state import (
    LATEST_TABLE_REFERENCE,
    generation_for,
    select_table,
    selected_table_reference_label,
    set_selected_table_reference,
)


def table_uri_control(*, key: str = "table_uri_control") -> str:
    """Render the shared selected-table input and return the active table URI."""

    current = st.session_state.get("selected_table_uri", "")
    value_key = f"{key}-value"
    sync_key = f"{key}-synced"
    if st.session_state.get(sync_key) != current:
        st.session_state[value_key] = current
        st.session_state[sync_key] = current
    tags: list[dict[str, object]] = []
    versions: list[dict[str, object]] = []
    if current:
        tags, versions = _table_tags_and_versions(current)
        st.caption(
            f"Current table: `{_short_table_label(current)}` "
            f"({selected_table_reference_label(tags)})"
        )
        st.caption(current)
    else:
        st.caption("No table is currently selected.")
    with st.form(key):
        uri_col, reference_col, button_col = st.columns(
            [0.62, 0.24, 0.14], vertical_alignment="bottom"
        )
        with uri_col:
            value = st.text_input(
                "Full Lance table URI",
                key=value_key,
                placeholder="/data/db/table.lance",
                help=help_text("table_uri"),
            )
        with reference_col:
            selected_reference = st.selectbox(
                "Open table at",
                _table_reference_options(tags, versions),
                index=_table_reference_index(tags, versions),
                format_func=lambda option: _table_reference_label(option, tags),
                key=f"{key}-reference-select",
                help=help_text("table_reference"),
            )
        with button_col:
            submitted = st.form_submit_button("Open table", width="stretch")
    if submitted:
        try:
            normalized = normalize_uri(value)
            select_table(normalized)
            if normalized == current:
                set_selected_table_reference(selected_reference)
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    return st.session_state.get("selected_table_uri", "")


def _short_table_label(table_uri: str) -> str:
    try:
        location = split_table_uri(table_uri)
    except Exception:
        return table_uri
    parent = location.database_uri.rstrip("/\\").replace("\\", "/").split("/")[-1]
    if parent:
        return f"{parent}/{location.table_name}.lance"
    return f"{location.table_name}.lance"


def _table_tags_and_versions(
    table_uri: str,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    try:
        generation = generation_for(table_uri)
        return cached_tags(table_uri, generation), cached_versions(table_uri, generation)
    except Exception:
        return [], []


def _table_reference_options(
    tags: list[dict[str, object]],
    versions: list[dict[str, object]],
) -> list[str]:
    options = [LATEST_TABLE_REFERENCE]
    options.extend(f"tag:{tag['tag']}" for tag in tags if tag.get("tag"))
    version_numbers = sorted(
        {
            int(version["version"])
            for version in versions
            if isinstance(version.get("version"), int)
        },
        reverse=True,
    )
    options.extend(f"version:{version}" for version in version_numbers)
    return options


def _table_reference_index(
    tags: list[dict[str, object]],
    versions: list[dict[str, object]],
) -> int:
    options = _table_reference_options(tags, versions)
    selected = st.session_state.get("selected_table_reference", LATEST_TABLE_REFERENCE)
    return options.index(selected) if selected in options else 0


def _table_reference_label(reference: str, tags: list[dict[str, object]]) -> str:
    if reference == LATEST_TABLE_REFERENCE:
        return "Latest"
    kind, value = reference.split(":", 1)
    if kind == "version":
        return f"Version {value}"
    for tag in tags:
        if tag.get("tag") == value:
            version = tag.get("version")
            return f"Tag: {value}" + (f" (version {version})" if version else "")
    return f"Tag: {value}"


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
