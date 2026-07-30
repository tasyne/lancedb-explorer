from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd
import streamlit as st

_VECTOR_INDEX_MARKERS = (
    "vector",
    "ivf",
    "hnsw",
    "pq",
    "distance",
    "cosine",
    "l2",
    "dot",
)
_VECTOR_SCHEMA_MARKERS = ("list<item: float", "fixed_size_list<item: float")


def vector_display_columns(snapshot: Mapping[str, Any] | None) -> set[str]:
    """Return columns that should be displayed as JSON vectors."""

    if not snapshot:
        return set()
    indexed = _vector_index_columns(snapshot.get("indexes", []))
    if indexed:
        return indexed
    return _schema_vector_columns(snapshot.get("schema", []))


def dataframe_for_display(
    dataframe: pd.DataFrame,
    vector_columns: Iterable[str] = (),
) -> pd.DataFrame:
    """Return a copy with vector columns serialized as compact JSON arrays."""

    columns = set(vector_columns) & set(dataframe.columns)
    if not columns:
        return dataframe

    output = dataframe.copy()
    for column in columns:
        output[column] = output[column].map(json_array_for_display)
    return output


def json_array_for_display(value: Any) -> Any:
    """Serialize list-like values as compact JSON, otherwise return the value."""

    if value is None:
        return value
    if hasattr(value, "as_py"):
        value = value.as_py()
    elif hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, tuple):
        value = list(value)
    if not isinstance(value, list):
        return value
    return json.dumps(_json_safe(value), separators=(",", ":"))


def show_dataframe(
    dataframe: pd.DataFrame,
    *,
    vector_columns: Iterable[str] = (),
) -> None:
    """Display a dataframe with copyable JSON strings for vector columns."""

    st.dataframe(dataframe_for_display(dataframe, vector_columns), width="stretch")


def _vector_index_columns(indexes: Any) -> set[str]:
    columns: set[str] = set()
    if not isinstance(indexes, list):
        return columns

    for index in indexes:
        if not isinstance(index, Mapping):
            continue
        index_columns = _index_columns(index)
        if index_columns and _contains_vector_marker(index):
            columns.update(index_columns)
    return columns


def _index_columns(index: Mapping[str, Any]) -> set[str]:
    values = index.get("columns") or index.get("column") or index.get("field_names")
    if isinstance(values, str):
        return {values}
    if isinstance(values, list | tuple | set):
        return {str(value) for value in values}
    return set()


def _contains_vector_marker(value: Any) -> bool:
    if isinstance(value, str):
        lower = value.lower()
        return any(marker in lower for marker in _VECTOR_INDEX_MARKERS)
    if isinstance(value, Mapping):
        return any(_contains_vector_marker(item) for item in value.values())
    if isinstance(value, list | tuple | set):
        return any(_contains_vector_marker(item) for item in value)
    return False


def _schema_vector_columns(schema_rows: Any) -> set[str]:
    columns: set[str] = set()
    if not isinstance(schema_rows, list):
        return columns

    for row in schema_rows:
        if not isinstance(row, Mapping):
            continue
        path = str(row.get("path") or "")
        type_text = str(row.get("type") or "").lower()
        if "." not in path and any(marker in type_text for marker in _VECTOR_SCHEMA_MARKERS):
            columns.add(path)
    return columns


def _json_safe(value: Any) -> Any:
    if hasattr(value, "as_py"):
        return _json_safe(value.as_py())
    if hasattr(value, "tolist"):
        return _json_safe(value.tolist())
    if hasattr(value, "item"):
        return _json_safe(value.item())
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value
