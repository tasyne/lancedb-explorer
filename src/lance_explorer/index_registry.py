from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from typing import Any

import pyarrow as pa

Compatibility = Callable[[pa.DataType], bool]


def _scalar(data_type: pa.DataType) -> bool:
    return any(
        predicate(data_type)
        for predicate in (
            pa.types.is_boolean,
            pa.types.is_integer,
            pa.types.is_floating,
            pa.types.is_decimal,
            pa.types.is_temporal,
            pa.types.is_string,
            pa.types.is_large_string,
        )
    )


def _string(data_type: pa.DataType) -> bool:
    return pa.types.is_string(data_type) or pa.types.is_large_string(data_type)


def _list(data_type: pa.DataType) -> bool:
    return (
        pa.types.is_list(data_type)
        or pa.types.is_large_list(data_type)
        or pa.types.is_fixed_size_list(data_type)
    )


@dataclass(frozen=True, slots=True)
class IndexDefinition:
    """UI and construction metadata for one LanceDB non-vector index type."""

    key: str
    class_name: str
    label: str
    description: str
    compatible: Compatibility
    template: str = "create_index"

    def available(self) -> bool:
        """Return whether the installed LanceDB SDK exposes this index class."""

        module = import_module("lancedb.index")
        return hasattr(module, self.class_name)

    def create_config(self, **kwargs: Any) -> Any:
        """Instantiate the LanceDB index configuration for this definition."""

        module = import_module("lancedb.index")
        index_class = getattr(module, self.class_name)
        return index_class(**kwargs)


INDEX_DEFINITIONS: tuple[IndexDefinition, ...] = (
    IndexDefinition(
        "BTREE",
        "BTree",
        "B-tree",
        "Best for selective equality and range filters on mostly unique values.",
        _scalar,
    ),
    IndexDefinition(
        "BITMAP",
        "Bitmap",
        "Bitmap",
        "Best for low-cardinality columns such as statuses or categories.",
        _scalar,
    ),
    IndexDefinition(
        "LABEL_LIST",
        "LabelList",
        "Label list",
        "Best for array membership filters on primitive list columns.",
        _list,
    ),
    IndexDefinition(
        "FM",
        "Fm",
        "FM",
        "Best for raw substring searches in paths, URLs, identifiers, or logs.",
        _string,
    ),
    IndexDefinition(
        "FTS",
        "FTS",
        "Full-text search",
        "Best for BM25-ranked keyword and phrase search over natural language.",
        _string,
    ),
)


def available_index_definitions() -> list[IndexDefinition]:
    """Return registry entries supported by the installed LanceDB SDK."""

    return [definition for definition in INDEX_DEFINITIONS if definition.available()]


def compatible_index_definitions(data_type: pa.DataType) -> list[IndexDefinition]:
    """Return available index definitions compatible with an Arrow data type."""

    return [
        definition
        for definition in available_index_definitions()
        if definition.compatible(data_type)
    ]


def get_index_definition(key: str) -> IndexDefinition:
    """Return an available index definition by stable registry key."""

    for definition in available_index_definitions():
        if definition.key == key:
            return definition
    raise KeyError(f"Index type is unavailable: {key}")
