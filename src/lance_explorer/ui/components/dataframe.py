from __future__ import annotations

import base64
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
_MAX_INLINE_IMAGE_BYTES = 512 * 1024


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
    """Return a copy with vectors and binary values converted for safe display."""

    columns = set(vector_columns) & set(dataframe.columns)
    binary_columns = _binary_columns(dataframe)
    if not columns and not binary_columns:
        return dataframe

    output = dataframe.copy()
    for column in columns:
        output[column] = output[column].map(json_array_for_display)
    for column in binary_columns:
        output[column] = output.apply(
            lambda row, current=column: binary_value_for_display(
                row[current],
                _mime_for_binary_column(row, current),
            ),
            axis=1,
        )
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
    """Display a dataframe with copyable vectors and browser-safe binary previews."""

    binary_columns = _binary_columns(dataframe)
    if binary_columns:
        st.caption(
            "Binary display: Arrow binary columns store bytes directly in the row; Lance Blob "
            "columns store larger payloads as blob data and return lightweight handles. Image "
            "MIME types are previewed when small enough; other binary values are summarized."
        )
    display = dataframe_for_display(dataframe, vector_columns)
    st.dataframe(
        display,
        width="stretch",
        column_config=_image_column_config(display),
    )


def binary_value_for_display(value: Any, mime_type: str | None = None) -> Any:
    """Return an image data URI or compact binary/blob label for one cell value."""

    raw = _binary_bytes(value)
    if raw is None:
        return value

    size = len(raw)
    if (
        mime_type
        and mime_type.startswith("image/")
        and size <= _MAX_INLINE_IMAGE_BYTES
    ):
        encoded = base64.b64encode(raw).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    kind = "blob" if _is_blob_file(value) else "binary"
    return f"<{mime_type or kind} {size:,} bytes>"


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


def _binary_columns(dataframe: pd.DataFrame) -> set[str]:
    columns: set[str] = set()
    for column in dataframe.columns:
        sample = dataframe[column].dropna().head(10)
        if any(_binary_bytes(value) is not None for value in sample):
            columns.add(str(column))
    return columns


def _binary_bytes(value: Any) -> bytes | None:
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray | memoryview):
        return bytes(value)
    if _is_blob_file(value):
        try:
            value.seek(0)
            return value.read()
        except Exception:
            return None
    return None


def _is_blob_file(value: Any) -> bool:
    return type(value).__name__ == "BlobFile" and hasattr(value, "read")


def _mime_for_binary_column(row: pd.Series, column: str) -> str | None:
    candidates = []
    if column.endswith("_bytes"):
        stem = column[: -len("_bytes")]
        candidates.extend(
            [
                f"{stem}_mime",
                f"{stem}_mime_type",
            ]
        )
        if "_" in stem:
            candidates.append(f"{stem.rsplit('_', 1)[0]}_mime")
    candidates.extend(["mime", "mime_type", "content_type"])
    for candidate in candidates:
        value = row.get(candidate)
        if isinstance(value, str) and value:
            return value
    mime_columns = [
        name for name in row.index if isinstance(name, str) and name.endswith("_mime")
    ]
    if len(mime_columns) == 1:
        value = row.get(mime_columns[0])
        if isinstance(value, str) and value:
            return value
    return None


def _image_column_config(dataframe: pd.DataFrame) -> dict[str, Any]:
    config: dict[str, Any] = {}
    for column in dataframe.columns:
        sample = dataframe[column].dropna().head(10)
        if any(isinstance(value, str) and value.startswith("data:image/") for value in sample):
            config[str(column)] = st.column_config.ImageColumn(str(column))
    return config


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
