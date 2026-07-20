from __future__ import annotations

from typing import Any

import streamlit as st

from lance_explorer.paths import PathEntry, list_children
from lance_explorer.repository import LanceRepository
from lance_explorer.schema_diff import schema_to_rows


@st.cache_data(ttl=5, max_entries=256, show_spinner=False)
def cached_local_children(uri: str, generation: int) -> list[PathEntry]:
    """Cache local child listings briefly, keyed by manual generation."""

    del generation
    return list_children(uri)


@st.cache_data(ttl=15, max_entries=256, show_spinner=False)
def cached_remote_children(uri: str, generation: int) -> list[PathEntry]:
    """Cache remote child listings slightly longer than local listings."""

    del generation
    return list_children(uri)


@st.cache_data(ttl=15, max_entries=256, show_spinner=False)
def cached_table_names(database_uri: str, generation: int) -> list[str]:
    """Cache table names for a LanceDB database URI."""

    del generation
    return LanceRepository().list_tables(database_uri)


@st.cache_data(ttl=20, max_entries=512, show_spinner=False)
def cached_snapshot(table_uri: str, version: int | None, generation: int) -> dict[str, Any]:
    """Cache a table metadata snapshot."""

    del generation
    return LanceRepository().snapshot(table_uri, version=version)


@st.cache_data(ttl=20, max_entries=512, show_spinner=False)
def cached_versions(table_uri: str, generation: int) -> list[dict[str, Any]]:
    """Cache table version metadata."""

    del generation
    return LanceRepository().list_versions(table_uri)


@st.cache_data(ttl=20, max_entries=512, show_spinner=False)
def cached_schema_rows(
    table_uri: str,
    version: int | None,
    generation: int,
) -> list[dict[str, Any]]:
    """Cache flattened schema rows for a table/version selection."""

    del generation
    schema = LanceRepository().get_schema(table_uri, version=version)
    return schema_to_rows(schema)


def children_for_uri(uri: str, generation: int) -> list[PathEntry]:
    """Choose the appropriate directory-listing cache for a URI."""

    if uri.lower().startswith(("s3://", "s3a://", "http://", "https://")):
        return cached_remote_children(uri, generation)
    return cached_local_children(uri, generation)
