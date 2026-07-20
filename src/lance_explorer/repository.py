from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, is_dataclass
from datetime import timedelta
from typing import Any

import lancedb
import pandas as pd
import pyarrow as pa

from lance_explorer.config import lancedb_storage_options_from_env
from lance_explorer.index_registry import get_index_definition
from lance_explorer.paths import TableLocation, split_table_uri
from lance_explorer.schema_diff import schema_to_rows


@dataclass(frozen=True, slots=True)
class QueryResult:
    """Rows returned by a query plus an optional LanceDB execution plan."""

    rows: pd.DataFrame
    plan: str | None = None


def _public_object_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "__dict__"):
        return {
            key: _json_safe(item) for key, item in vars(value).items() if not key.startswith("_")
        }
    result: dict[str, Any] = {}
    for name in dir(value):
        if name.startswith("_"):
            continue
        try:
            item = getattr(value, name)
        except Exception:
            continue
        if callable(item):
            continue
        if isinstance(item, (str, int, float, bool, type(None), list, tuple, dict)):
            result[name] = _json_safe(item)
    return result


def _json_safe(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _json_safe(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, bool, type(None))):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value)


def _index_name(config: Any) -> str:
    for attribute in ("name", "index_name"):
        value = getattr(config, attribute, None)
        if value:
            return str(value)
    data = _public_object_dict(config)
    return str(data.get("name") or data.get("index_name") or "")


def _index_columns(config: Any) -> list[str]:
    for attribute in ("columns", "column", "field_names"):
        value = getattr(config, attribute, None)
        if value:
            return (
                [str(item) for item in value] if isinstance(value, (list, tuple)) else [str(value)]
            )
    data = _public_object_dict(config)
    value = data.get("columns") or data.get("column") or data.get("field_names") or []
    return (
        [str(item) for item in value] if isinstance(value, list) else [str(value)] if value else []
    )


class LanceRepository:
    """Thin synchronous LanceDB adapter.

    Handles are intentionally opened per operation so checked-out state and mutations are
    not accidentally shared through Streamlit's resource cache.
    """

    def __init__(self, max_query_rows: int = 10_000) -> None:
        self.max_query_rows = max_query_rows

    @staticmethod
    def _connect(database_uri: str):
        return lancedb.connect(
            database_uri,
            storage_options=lancedb_storage_options_from_env() or None,
        )

    def open_table(self, table_uri: str, version: int | None = None):
        """Open a Lance table, optionally checked out at a specific version."""

        location = split_table_uri(table_uri)
        db = self._connect(location.database_uri)
        return db.open_table(location.table_name, version=version)

    def list_tables(self, database_uri: str) -> list[str]:
        """List table names in a LanceDB database URI with a bounded page loop."""

        db = self._connect(database_uri)
        names: list[str] = []
        page_token: str | None = None
        while len(names) < 10_000:
            response = db.list_tables(page_token=page_token, limit=min(1_000, 10_000 - len(names)))
            names.extend(response.tables)
            page_token = response.page_token
            if not page_token:
                break
        return names

    def table_exists(self, table_uri: str) -> bool:
        """Return whether a full `.lance` URI is present in its parent database."""

        location = split_table_uri(table_uri)
        return location.table_name in self.list_tables(location.database_uri)

    def get_schema(self, table_uri: str, version: int | None = None) -> pa.Schema:
        """Return the Arrow schema for a table or version."""

        return self.open_table(table_uri, version=version).schema

    def list_versions(self, table_uri: str) -> list[dict[str, Any]]:
        """Return LanceDB version metadata as JSON-safe dictionaries."""

        table = self.open_table(table_uri)
        return [_json_safe(item) for item in table.list_versions()]

    def list_indexes(self, table_uri: str, version: int | None = None) -> list[dict[str, Any]]:
        """Return index definitions and available statistics for a table."""

        table = self.open_table(table_uri, version=version)
        output: list[dict[str, Any]] = []
        for config in table.list_indices():
            item = _public_object_dict(config)
            name = _index_name(config)
            item.setdefault("name", name)
            item.setdefault("columns", _index_columns(config))
            if name:
                stats = table.index_stats(name)
                if stats is not None:
                    item["statistics"] = _public_object_dict(stats)
            output.append(_json_safe(item))
        return output

    def snapshot(self, table_uri: str, version: int | None = None) -> dict[str, Any]:
        """Collect bounded metadata used by the Table and Compare pages."""

        table = self.open_table(table_uri, version=version)
        stats = table.stats()
        return {
            "table_uri": table_uri,
            "resolved_uri": table.uri,
            "name": table.name,
            "version": table.version,
            "row_count": table.count_rows(),
            "schema": schema_to_rows(table.schema),
            "schema_string": str(table.schema),
            "table_metadata": _json_safe(table.schema.metadata or {}),
            "statistics": _public_object_dict(stats),
            "indexes": self.list_indexes(table_uri, version=version),
        }

    def preview(
        self,
        table_uri: str,
        *,
        columns: list[str] | None = None,
        limit: int = 100,
        version: int | None = None,
    ) -> pd.DataFrame:
        """Return a bounded row preview through the same limit guard as queries."""

        return self.run_filter(
            table_uri,
            where=None,
            columns=columns,
            limit=limit,
            version=version,
            include_plan=False,
        ).rows

    def run_filter(
        self,
        table_uri: str,
        *,
        where: str | None,
        columns: list[str] | None,
        limit: int,
        version: int | None = None,
        include_plan: bool = False,
    ) -> QueryResult:
        """Run a bounded SQL-style filter/projection query."""

        limit = self._validated_limit(limit)
        table = self.open_table(table_uri, version=version)
        query = table.search()
        if where and where.strip():
            query = query.where(where.strip())
        if columns:
            query = query.select(columns)
        query = query.limit(limit)
        plan = query.explain_plan(True) if include_plan else None
        return QueryResult(rows=query.to_pandas(), plan=plan)

    def run_fts(
        self,
        table_uri: str,
        *,
        text: str,
        column: str,
        where: str | None,
        columns: list[str] | None,
        limit: int,
        version: int | None = None,
        include_plan: bool = False,
    ) -> QueryResult:
        """Run a bounded full-text search against a selected string column."""

        if not text.strip():
            raise ValueError("Full-text query cannot be empty")
        limit = self._validated_limit(limit)
        table = self.open_table(table_uri, version=version)
        query = table.search(text.strip(), query_type="fts", fts_columns=column)
        if where and where.strip():
            query = query.where(where.strip())
        if columns:
            query = query.select(columns)
        query = query.limit(limit)
        plan = query.explain_plan(True) if include_plan else None
        return QueryResult(rows=query.to_pandas(), plan=plan)

    def run_vector(
        self,
        table_uri: str,
        *,
        vector: list[float],
        column: str,
        where: str | None,
        columns: list[str] | None,
        limit: int,
        version: int | None = None,
        include_plan: bool = False,
    ) -> QueryResult:
        """Run a bounded raw-vector search without generating embeddings."""

        if not vector or not all(
            isinstance(item, int | float) and math.isfinite(item) for item in vector
        ):
            raise ValueError("Vector must be a non-empty list of finite numbers")
        limit = self._validated_limit(limit)
        table = self.open_table(table_uri, version=version)
        query = table.search(vector, vector_column_name=column, query_type="vector")
        if where and where.strip():
            query = query.where(where.strip())
        if columns:
            query = query.select(columns)
        query = query.limit(limit)
        plan = query.explain_plan(True) if include_plan else None
        return QueryResult(rows=query.to_pandas(), plan=plan)

    def create_index(
        self,
        table_uri: str,
        *,
        column: str,
        index_type: str,
        name: str | None = None,
        replace: bool = False,
        config_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a non-vector index using registry-owned configuration."""

        definition = get_index_definition(index_type)
        config = definition.create_config(**(config_options or {}))
        table = self.open_table(table_uri)
        table.create_index(column, config=config, name=name or None, replace=replace)
        return {"status": "created", "column": column, "index_type": index_type, "name": name}

    def drop_index(self, table_uri: str, name: str) -> dict[str, Any]:
        """Drop an index by name from a Lance table."""

        table = self.open_table(table_uri)
        table.drop_index(name)
        return {"status": "dropped", "name": name}

    def optimize(self, table_uri: str, cleanup_days: int | None = None) -> dict[str, Any]:
        """Run LanceDB optimization, optionally pruning older versions."""

        table = self.open_table(table_uri)
        cleanup = timedelta(days=cleanup_days) if cleanup_days is not None else None
        return _public_object_dict(table.optimize(cleanup_older_than=cleanup))

    def cleanup_versions(
        self,
        table_uri: str,
        *,
        older_than_days: int,
        delete_unverified: bool = False,
    ) -> dict[str, Any]:
        """Optimize while pruning versions older than the requested retention window."""

        if older_than_days < 0:
            raise ValueError("Retention age cannot be negative")
        table = self.open_table(table_uri)
        result = table.optimize(
            cleanup_older_than=timedelta(days=older_than_days),
            delete_unverified=delete_unverified,
        )
        return _public_object_dict(result)

    def restore_version(self, table_uri: str, version: int) -> dict[str, Any]:
        """Restore a table to a prior LanceDB version."""

        table = self.open_table(table_uri)
        result = table.restore(version)
        return {"status": "restored", "version": version, "result": _public_object_dict(result)}

    def drop_table(self, table_uri: str) -> dict[str, Any]:
        """Drop a Lance table from its parent database."""

        location: TableLocation = split_table_uri(table_uri)
        db = self._connect(location.database_uri)
        db.drop_table(location.table_name)
        return {"status": "dropped", "table": location.table_name}

    def _validated_limit(self, limit: int) -> int:
        if limit < 1:
            raise ValueError("Limit must be at least 1")
        return min(limit, self.max_query_rows)


def parse_vector(value: str) -> list[float]:
    """Parse user-entered JSON into a finite numeric vector."""

    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("Vector must be valid JSON, such as [0.1, 0.2]") from exc
    if not isinstance(parsed, list):
        raise ValueError("Vector must be a JSON list")
    vector: list[float] = []
    for item in parsed:
        if not isinstance(item, int | float):
            raise ValueError("Every vector item must be numeric")
        item_float = float(item)
        if not math.isfinite(item_float):
            raise ValueError("Vector values must be finite")
        vector.append(item_float)
    if not vector:
        raise ValueError("Vector cannot be empty")
    return vector
