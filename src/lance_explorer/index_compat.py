from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

LEGACY_SCALAR_INDEX_TYPES = {"BTREE", "BITMAP", "LABEL_LIST"}
LEGACY_VECTOR_INDEX_TYPES = {
    "IVF_FLAT",
    "IVF_SQ",
    "IVF_PQ",
    "IVF_RQ",
    "IVF_HNSW_SQ",
    "IVF_HNSW_PQ",
    "IVF_HNSW_FLAT",
}


class UnsupportedIndexError(ValueError):
    """Raised when the installed LanceDB SDK cannot create an index type."""


def create_table_index(
    table: Any,
    *,
    column: str,
    index_type: str,
    config_options: dict[str, Any] | None = None,
    name: str | None = None,
    replace: bool = False,
) -> None:
    """Create an index using the newest public API this LanceDB table supports."""

    from lance_explorer.index_registry import fts_uses_packaged_model
    from lance_explorer.language_models import configure_packaged_language_model

    options = dict(config_options or {})
    if index_type == "FTS" and fts_uses_packaged_model(options):
        configure_packaged_language_model(str(options.get("base_tokenizer", "")))

    if _method_accepts_keyword(table.create_index, "config"):
        from lance_explorer.index_registry import get_index_definition

        definition = get_index_definition(index_type)
        config = definition.create_config(**options)
        table.create_index(column, config=config, name=name or None, replace=replace)
        return

    if index_type in LEGACY_SCALAR_INDEX_TYPES:
        _call_with_supported_kwargs(
            table.create_scalar_index,
            column,
            index_type=index_type,
            name=name or None,
            replace=replace,
        )
        return

    if index_type == "FTS":
        _call_with_supported_kwargs(
            table.create_fts_index,
            column,
            **options,
            name=name or None,
            replace=replace,
        )
        return

    if index_type in LEGACY_VECTOR_INDEX_TYPES:
        _create_legacy_vector_index(
            table,
            column=column,
            index_type=index_type,
            config_options=options,
            name=name,
            replace=replace,
        )
        return

    raise UnsupportedIndexError(
        f"{index_type} requires LanceDB's unified create_index(config=...) API. "
        "Install LanceDB 0.34.0 or newer, or choose a legacy-compatible index type."
    )


def index_type_supported_by_installed_lancedb(index_type: str) -> bool:
    """Return whether the installed sync LanceTable API can create this index type."""

    if _installed_lancetable_accepts_config():
        return True
    return (
        index_type in LEGACY_SCALAR_INDEX_TYPES
        or index_type == "FTS"
        or index_type in LEGACY_VECTOR_INDEX_TYPES
    )


def _installed_lancetable_accepts_config() -> bool:
    try:
        from lancedb.table import LanceTable
    except Exception:
        return True
    return _method_accepts_keyword(LanceTable.create_index, "config")


def _create_legacy_vector_index(
    table: Any,
    *,
    column: str,
    index_type: str,
    config_options: dict[str, Any],
    name: str | None,
    replace: bool,
) -> None:
    legacy_options = {
        "metric": config_options.get("distance_type", "l2"),
        "vector_column_name": column,
        "index_type": index_type,
        "replace": replace,
        "name": name or None,
        "num_partitions": config_options.get("num_partitions"),
        "num_sub_vectors": config_options.get("num_sub_vectors"),
        "num_bits": config_options.get("num_bits", 8),
        "max_iterations": config_options.get("max_iterations", 50),
        "sample_rate": config_options.get("sample_rate", 256),
        "m": config_options.get("m", 20),
        "ef_construction": config_options.get("ef_construction", 300),
        "target_partition_size": config_options.get("target_partition_size"),
        "accelerator": config_options.get("accelerator"),
    }
    _call_with_supported_kwargs(table.create_index, **legacy_options)


def _method_accepts_keyword(method: Callable[..., Any], keyword: str) -> bool:
    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        return True
    return keyword in signature.parameters or any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )


def _call_with_supported_kwargs(
    method: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> Any:
    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        return method(*args, **kwargs)
    if any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    ):
        return method(*args, **kwargs)
    supported = {key: value for key, value in kwargs.items() if key in signature.parameters}
    return method(*args, **supported)
