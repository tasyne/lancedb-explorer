from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, is_dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse

import lancedb
import pandas as pd
import pyarrow as pa
from lancedb.rerankers import RRFReranker

from lance_explorer.config import lancedb_storage_options_from_env
from lance_explorer.index_compat import create_table_index
from lance_explorer.language_models import (
    ensure_packaged_language_model_home,
)
from lance_explorer.paths import has_uri_scheme, make_upath
from lance_explorer.schema_diff import schema_to_rows
from lance_explorer.table_refs import (
    NamespaceTableLocation,
    format_namespace_table_ref,
    resolve_table_location,
)


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


def _columns_with_scores(
    columns: list[str] | None,
    score_columns: tuple[str, ...],
) -> list[str] | None:
    if columns is None:
        return None
    output = list(columns)
    for column in score_columns:
        if column not in output:
            output.append(column)
    return output


def _trim_query_result(
    rows: pd.DataFrame,
    columns: list[str] | None,
    score_columns: tuple[str, ...],
) -> pd.DataFrame:
    if columns is None:
        return rows
    output_columns = list(columns)
    output_columns.extend(
        column
        for column in score_columns
        if column in rows.columns and column not in output_columns
    )
    return rows.loc[:, [column for column in output_columns if column in rows.columns]]


def _relative_table_location(source_table_uri: str, namespace_root: str) -> str | None:
    """Return source table location relative to a namespace root when possible."""

    source = resolve_table_location(source_table_uri)
    if source.namespace:
        return None
    assert source.direct is not None
    source_uri = source.direct.table_uri
    root = namespace_root.rstrip("/\\")
    source_parsed = urlparse(source_uri)
    root_parsed = urlparse(root)
    if has_uri_scheme(source_uri) or has_uri_scheme(root):
        if (source_parsed.scheme, source_parsed.netloc) != (
            root_parsed.scheme,
            root_parsed.netloc,
        ):
            return None
        root_path = root_parsed.path.rstrip("/")
        source_path = source_parsed.path
        prefix = f"{root_path}/" if root_path else "/"
        if not source_path.startswith(prefix):
            return None
        relative = source_path[len(prefix) :].strip("/")
        return unquote(relative) or None

    try:
        relative_path = Path(source_uri).resolve().relative_to(Path(root).resolve())
    except Exception:
        return None
    return relative_path.as_posix() or None


def _import_relative_location(
    namespace_path: tuple[str, ...],
    table_name: str,
) -> str:
    """Return a catalog-relative physical copy location for imported tables."""

    parts = ["__imports", *namespace_path, table_name]
    encoded = "__".join(quote(part, safe="._-") for part in parts)
    return f"{encoded}.lance"


def _namespace_table_id(location: NamespaceTableLocation) -> list[str]:
    """Return the namespace API identity for a namespace table reference."""

    return [*location.namespace_path, location.table_name]


def _registered_storage_path(root: str, location: str):
    """Resolve a registered namespace location to the path Lance should delete."""

    if has_uri_scheme(location):
        return make_upath(location)
    return make_upath(str(make_upath(root) / location))


class LanceRepository:
    """Thin synchronous LanceDB adapter.

    Handles are intentionally opened per operation so checked-out state and mutations are
    not accidentally shared through Streamlit's resource cache.
    """

    def __init__(self, max_query_rows: int = 10_000) -> None:
        self.max_query_rows = max_query_rows

    @staticmethod
    def _connect(database_uri: str):
        # Lance may initialize FTS tokenizers while reading index metadata. Set the
        # bundled model root before every SDK operation while preserving user overrides.
        ensure_packaged_language_model_home()
        return lancedb.connect(
            database_uri,
            storage_options=lancedb_storage_options_from_env() or None,
        )

    @staticmethod
    def _connect_namespace(implementation: str, properties: dict[str, str]):
        """Open a namespace-backed LanceDB connection when the SDK supports it."""

        ensure_packaged_language_model_home()
        if not hasattr(lancedb, "connect_namespace"):
            raise RuntimeError(
                "This LanceDB version does not expose namespace lifecycle APIs. "
                "Install lancedb>=0.34.0 to browse and manage namespaces."
            )
        return lancedb.connect_namespace(
            implementation,
            properties,
            storage_options=lancedb_storage_options_from_env() or None,
        )

    def _connect_namespace_location(self, location: NamespaceTableLocation):
        return self._connect_namespace(location.implementation, {"root": location.root})

    def open_table(self, table_uri: str, version: int | str | None = None):
        """Open a Lance table, optionally checked out at a specific version."""

        resolved = resolve_table_location(table_uri)
        if resolved.namespace:
            # Namespace references must be resolved through LanceDB's catalog API.
            db = self._connect_namespace_location(resolved.namespace)
            table = db.open_table(
                resolved.namespace.table_name,
                namespace_path=list(resolved.namespace.namespace_path),
            )
        else:
            # Direct table URIs open from local disk, S3, or another object-store path.
            assert resolved.direct is not None
            db = self._connect(resolved.direct.database_uri)
            table = db.open_table(resolved.direct.table_name)
        if version is not None:
            # `open_table(version=...)` exists in newer LanceDB releases, but `checkout`
            # has been the stable time-travel path across more SDK versions.
            table.checkout(version)
        return table

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

        resolved = resolve_table_location(table_uri)
        if resolved.namespace:
            tables = self.list_namespace_tables(
                resolved.namespace.root,
                resolved.namespace.namespace_path,
                implementation=resolved.namespace.implementation,
            )
            return resolved.namespace.table_name in tables
        assert resolved.direct is not None
        return resolved.direct.table_name in self.list_tables(resolved.direct.database_uri)

    def list_namespaces(
        self,
        root: str,
        namespace_path: list[str] | tuple[str, ...] | None = None,
        *,
        implementation: str = "dir",
    ) -> list[str]:
        """List immediate child namespaces for a namespace catalog root."""

        db = self._connect_namespace(implementation, {"root": root})
        names: list[str] = []
        page_token: str | None = None
        while len(names) < 10_000:
            response = db.list_namespaces(
                namespace_path=list(namespace_path or []),
                page_token=page_token,
                limit=min(1_000, 10_000 - len(names)),
            )
            names.extend(str(item) for item in getattr(response, "namespaces", []))
            page_token = getattr(response, "page_token", None)
            if not page_token:
                break
        return names

    def list_namespace_tables(
        self,
        root: str,
        namespace_path: list[str] | tuple[str, ...] | None = None,
        *,
        implementation: str = "dir",
    ) -> list[str]:
        """List tables inside a namespace path."""

        db = self._connect_namespace(implementation, {"root": root})
        names: list[str] = []
        page_token: str | None = None
        while len(names) < 10_000:
            response = db.list_tables(
                namespace_path=list(namespace_path or []),
                page_token=page_token,
                limit=min(1_000, 10_000 - len(names)),
            )
            names.extend(str(item) for item in getattr(response, "tables", []))
            page_token = getattr(response, "page_token", None)
            if not page_token:
                break
        return names

    def namespace_tree(
        self,
        root: str,
        namespace_path: list[str] | tuple[str, ...] | None = None,
        *,
        implementation: str = "dir",
        max_depth: int = 8,
    ) -> dict[str, Any]:
        """Return a recursive namespace/table tree for compact UI browsing."""

        path = tuple(namespace_path or ())
        children = []
        if max_depth > 0:
            for name in sorted(
                self.list_namespaces(root, path, implementation=implementation),
                key=str.lower,
            ):
                children.append(
                    self.namespace_tree(
                        root,
                        (*path, name),
                        implementation=implementation,
                        max_depth=max_depth - 1,
                    )
                )
        return {
            "name": path[-1] if path else "(root)",
            "path": path,
            "namespaces": children,
            "tables": sorted(
                self.list_namespace_tables(root, path, implementation=implementation),
                key=str.lower,
            ),
        }

    def describe_namespace(
        self,
        root: str,
        namespace_path: list[str] | tuple[str, ...],
        *,
        implementation: str = "dir",
    ) -> dict[str, Any]:
        """Return namespace metadata/properties from the catalog."""

        db = self._connect_namespace(implementation, {"root": root})
        response = db.describe_namespace(list(namespace_path))
        return _public_object_dict(response)

    def create_namespace(
        self,
        root: str,
        namespace_path: list[str] | tuple[str, ...],
        *,
        implementation: str = "dir",
        mode: str = "exist_ok",
        properties: dict[str, str] | None = None,
        create_parents: bool = True,
    ) -> dict[str, Any]:
        """Create a namespace and optionally ensure parent namespaces first."""

        path = list(namespace_path)
        if not path:
            raise ValueError("Cannot create the root namespace")
        if mode == "exist_ok" and self.namespace_exists(
            root, path, implementation=implementation
        ):
            return {"status": "exists", "namespace": "/".join(path), "responses": []}
        db = self._connect_namespace(implementation, {"root": root})
        responses: list[dict[str, Any]] = []
        if create_parents and len(path) > 1:
            responses.extend(
                self.ensure_namespace_path(root, path[:-1], implementation=implementation)
            )
        response = db.create_namespace(path, mode=mode, properties=properties or None)
        responses.append(_public_object_dict(response))
        return {"status": "created", "namespace": "/".join(path), "responses": responses}

    def namespace_exists(
        self,
        root: str,
        namespace_path: list[str] | tuple[str, ...],
        *,
        implementation: str = "dir",
    ) -> bool:
        """Return whether a namespace path exists without creating it."""

        path = tuple(namespace_path)
        if not path:
            return True
        parent = path[:-1]
        try:
            return path[-1] in self.list_namespaces(
                root, parent, implementation=implementation
            )
        except Exception:
            try:
                self.describe_namespace(root, path, implementation=implementation)
                return True
            except Exception:
                return False

    def ensure_namespace_path(
        self,
        root: str,
        namespace_path: list[str] | tuple[str, ...],
        *,
        implementation: str = "dir",
    ) -> list[dict[str, Any]]:
        """Create missing namespace components while leaving existing nodes intact."""

        path = tuple(namespace_path)
        responses: list[dict[str, Any]] = []
        for index in range(1, len(path) + 1):
            partial = path[:index]
            if self.namespace_exists(root, partial, implementation=implementation):
                continue
            response = self.create_namespace(
                root,
                partial,
                implementation=implementation,
                mode="create",
                create_parents=False,
            )
            responses.append(response)
        return responses

    def drop_namespace(
        self,
        root: str,
        namespace_path: list[str] | tuple[str, ...],
        *,
        implementation: str = "dir",
        mode: str = "FAIL",
        behavior: str = "RESTRICT",
    ) -> dict[str, Any]:
        """Drop a namespace using LanceDB's restrict/cascade behavior."""

        path = list(namespace_path)
        if not path:
            raise ValueError("Cannot drop the root namespace")
        db = self._connect_namespace(implementation, {"root": root})
        response = db.drop_namespace(path, mode=mode, behavior=behavior)
        return {
            "status": "dropped",
            "namespace": "/".join(path),
            "result": _public_object_dict(response),
        }

    def namespace_table_reference(
        self,
        root: str,
        namespace_path: list[str] | tuple[str, ...],
        table_name: str,
        *,
        implementation: str = "dir",
    ) -> str:
        """Return the app's canonical reference for a namespace table."""

        return format_namespace_table_ref(
            root,
            tuple(namespace_path),
            table_name,
            implementation=implementation,
        )

    def import_table_to_namespace(
        self,
        source_table_uri: str,
        root: str,
        namespace_path: list[str] | tuple[str, ...],
        table_name: str,
        *,
        implementation: str = "dir",
        mode: str = "create",
        prefer_registration: bool = True,
        batch_size: int = 8192,
    ) -> dict[str, Any]:
        """Import a selected table into a namespace, preferring metadata registration."""

        target_name = table_name.strip()
        if not target_name:
            raise ValueError("Target table name cannot be empty")
        path = tuple(namespace_path)
        if path:
            self.ensure_namespace_path(root, path, implementation=implementation)
        db = self._connect_namespace(implementation, {"root": root})
        target_ref = format_namespace_table_ref(
            root, path, target_name, implementation=implementation
        )

        if prefer_registration:
            registered = self._try_register_table_location(
                db,
                source_table_uri,
                root,
                path,
                target_name,
                mode=mode,
            )
            if registered is not None:
                return {
                    "status": "registered",
                    "target": target_ref,
                    "method": "namespace metadata registration",
                    "result": registered,
                }

        copied = self._try_copy_table_location_into_catalog(
            db,
            source_table_uri,
            root,
            path,
            target_name,
            mode=mode,
        )
        if copied is not None:
            return {
                "status": "registered",
                "target": target_ref,
                "method": "physical table copy + namespace registration",
                "result": copied,
                "note": (
                    "Copied the Lance table directory before registering it. Versions, indexes, "
                    "and blob files are preserved by copying the physical table storage."
                ),
            }

        source_table = self.open_table(source_table_uri)
        row_count = int(source_table.count_rows())
        reader = (
            None
            if row_count == 0
            else source_table.search().limit(row_count).to_batches(batch_size=batch_size)
        )
        db.create_table(
            target_name,
            data=reader,
            schema=source_table.schema,
            mode=mode,
            namespace_path=list(path),
        )
        return {
            "status": "copied",
            "target": target_ref,
            "method": "Arrow batch copy",
            "row_count": row_count,
            "note": (
                "Copied the current logical rows only; source history, tags, indexes, "
                "and physical blob layout are not preserved."
            ),
        }

    def _try_register_table_location(
        self,
        namespace_db: Any,
        source_table_uri: str,
        root: str,
        namespace_path: tuple[str, ...],
        table_name: str,
        *,
        mode: str,
    ) -> dict[str, Any] | None:
        """Register an existing table location when it is already under the catalog root."""

        location = _relative_table_location(source_table_uri, root)
        if location is None:
            return None
        return self._register_table_location(
            namespace_db,
            location,
            namespace_path,
            table_name,
            mode=mode,
        )

    def _try_copy_table_location_into_catalog(
        self,
        namespace_db: Any,
        source_table_uri: str,
        root: str,
        namespace_path: tuple[str, ...],
        table_name: str,
        *,
        mode: str,
    ) -> dict[str, Any] | None:
        """Copy a direct `.lance` table directory into the catalog and register it."""

        resolved = resolve_table_location(source_table_uri)
        if resolved.namespace:
            return None
        assert resolved.direct is not None

        relative_location = _import_relative_location(namespace_path, table_name)
        source = make_upath(resolved.direct.table_uri)
        target = make_upath(str(make_upath(root) / relative_location))
        if target.exists():
            if mode != "overwrite":
                raise ValueError(
                    f"Import target storage already exists: {target}. "
                    "Use overwrite only if replacing it is intended."
                )
            target.fs.rm(str(target), recursive=True)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            source.copy(str(target), recursive=True)
        except Exception:
            return None
        registered = self._register_table_location(
            namespace_db,
            relative_location,
            namespace_path,
            table_name,
            mode=mode,
        )
        return {
            "location": relative_location,
            "copied_from": resolved.direct.table_uri,
            "registration": registered,
        }

    def _register_table_location(
        self,
        namespace_db: Any,
        location: str,
        namespace_path: tuple[str, ...],
        table_name: str,
        *,
        mode: str,
    ) -> dict[str, Any] | None:
        """Register a catalog-relative physical table location."""

        try:
            from lance_namespace_urllib3_client.models.register_table_request import (
                RegisterTableRequest,
            )
        except Exception:
            return None
        try:
            response = namespace_db.namespace_client().register_table(
                RegisterTableRequest(
                    id=[*namespace_path, table_name],
                    location=location,
                    mode="Overwrite" if mode == "overwrite" else "Create",
                )
            )
        except Exception:
            return None
        return {"location": location, "response": _public_object_dict(response)}

    def get_schema(self, table_uri: str, version: int | str | None = None) -> pa.Schema:
        """Return the Arrow schema for a table or version."""

        return self.open_table(table_uri, version=version).schema

    def list_versions(self, table_uri: str) -> list[dict[str, Any]]:
        """Return LanceDB version metadata as JSON-safe dictionaries."""

        table = self.open_table(table_uri)
        return [_json_safe(item) for item in table.list_versions()]

    def list_tags(self, table_uri: str) -> list[dict[str, Any]]:
        """Return table version tags as rows suitable for display."""

        table = self.open_table(table_uri)
        tags = getattr(table, "tags", None)
        if tags is None:
            return []
        rows: list[dict[str, Any]] = []
        for name, metadata in tags.list().items():
            item = _public_object_dict(metadata)
            item["tag"] = str(name)
            rows.append(_json_safe(item))
        return sorted(rows, key=lambda item: str(item.get("tag", "")))

    def list_indexes(
        self, table_uri: str, version: int | str | None = None
    ) -> list[dict[str, Any]]:
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

    def snapshot(self, table_uri: str, version: int | str | None = None) -> dict[str, Any]:
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
        version: int | str | None = None,
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
        version: int | str | None = None,
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
        version: int | str | None = None,
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
        query = query.limit(limit)
        plan = query.explain_plan(True) if include_plan else None
        rows = query.to_pandas()
        return QueryResult(rows=_trim_query_result(rows, columns, ("_score",)), plan=plan)

    def run_vector(
        self,
        table_uri: str,
        *,
        vector: list[float],
        column: str,
        where: str | None,
        columns: list[str] | None,
        limit: int,
        version: int | str | None = None,
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
            query = query.select(_columns_with_scores(columns, ("_distance",)))
        query = query.limit(limit)
        plan = query.explain_plan(True) if include_plan else None
        rows = query.to_pandas()
        return QueryResult(rows=_trim_query_result(rows, columns, ("_distance",)), plan=plan)

    def run_hybrid(
        self,
        table_uri: str,
        *,
        text: str,
        vector: list[float],
        vector_column: str,
        fts_column: str,
        where: str | None,
        columns: list[str] | None,
        limit: int,
        rerank: bool = True,
        version: int | str | None = None,
        include_plan: bool = False,
    ) -> QueryResult:
        """Run LanceDB hybrid search from separate text and raw-vector inputs."""

        if not text.strip():
            raise ValueError("Hybrid search text cannot be empty")
        if not vector or not all(
            isinstance(item, int | float) and math.isfinite(item) for item in vector
        ):
            raise ValueError("Vector must be a non-empty list of finite numbers")
        limit = self._validated_limit(limit)
        table = self.open_table(table_uri, version=version)
        query = (
            table.search(
                query_type="hybrid",
                vector_column_name=vector_column,
                fts_columns=fts_column,
            )
            .vector(vector)
            .text(text.strip())
        )
        if rerank:
            query = query.rerank(RRFReranker(return_score="all"))
        if where and where.strip():
            query = query.where(where.strip())
        query = query.limit(limit)
        plan = query.explain_plan(True) if include_plan else None
        rows = query.to_pandas()
        return QueryResult(
            rows=_trim_query_result(rows, columns, ("_score", "_distance", "_relevance_score")),
            plan=plan,
        )

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
        """Create an index using registry-owned LanceDB configuration classes."""

        table = self.open_table(table_uri)
        create_table_index(
            table,
            column=column,
            index_type=index_type,
            name=name,
            replace=replace,
            config_options=config_options,
        )
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

    def set_tag(self, table_uri: str, tag: str, version: int) -> dict[str, Any]:
        """Create or move a table version tag."""

        tag_name = tag.strip()
        if not tag_name:
            raise ValueError("Tag name cannot be empty")
        table = self.open_table(table_uri)
        tags = getattr(table, "tags", None)
        if tags is None:
            raise ValueError("This LanceDB version does not expose table tags.")
        existing = tags.list()
        action = "updated" if tag_name in existing else "created"
        if action == "updated":
            tags.update(tag_name, version)
        else:
            tags.create(tag_name, version)
        return {"status": action, "tag": tag_name, "version": version}

    def delete_tag(self, table_uri: str, tag: str) -> dict[str, Any]:
        """Delete a table version tag without deleting the underlying version."""

        tag_name = tag.strip()
        if not tag_name:
            raise ValueError("Tag name cannot be empty")
        table = self.open_table(table_uri)
        tags = getattr(table, "tags", None)
        if tags is None:
            raise ValueError("This LanceDB version does not expose table tags.")
        tags.delete(tag_name)
        return {"status": "deleted", "tag": tag_name}

    def _describe_namespace_table_location(
        self,
        namespace_db: Any,
        location: NamespaceTableLocation,
    ) -> str | None:
        """Return the storage location registered for a namespace table."""

        try:
            from lance_namespace_urllib3_client.models.describe_table_request import (
                DescribeTableRequest,
            )
        except Exception:
            return None
        try:
            response = namespace_db.namespace_client().describe_table(
                DescribeTableRequest(
                    id=_namespace_table_id(location),
                    with_table_uri=True,
                )
            )
        except Exception:
            return None
        return str(getattr(response, "location", "") or getattr(response, "table_uri", "") or "")

    def _deregister_namespace_table(
        self,
        namespace_db: Any,
        location: NamespaceTableLocation,
    ) -> dict[str, Any] | None:
        """Remove a namespace catalog entry without touching table storage."""

        try:
            from lance_namespace_urllib3_client.models.deregister_table_request import (
                DeregisterTableRequest,
            )
        except Exception:
            return None
        try:
            response = namespace_db.namespace_client().deregister_table(
                DeregisterTableRequest(id=_namespace_table_id(location))
            )
        except Exception as exc:
            if "Table not found" in str(exc):
                return {"status": "already_absent"}
            raise
        return _public_object_dict(response)

    def _repair_namespace_drop_after_location_error(
        self,
        namespace_db: Any,
        location: NamespaceTableLocation,
        registered_location: str | None,
        original_error: Exception,
    ) -> dict[str, Any] | None:
        """Work around LanceDB 0.34 slash-encoding failures during namespace drops."""

        error_text = str(original_error)
        if (
            not registered_location
            or "Failed to delete table directory" not in error_text
            or "%2F" not in error_text
        ):
            return None

        storage_path = _registered_storage_path(location.root, registered_location)
        removed_storage = False
        if storage_path.exists():
            storage_path.fs.rm(str(storage_path), recursive=True)
            removed_storage = True
        deregistered = self._deregister_namespace_table(namespace_db, location)
        return {
            "status": "dropped",
            "table": location.table_name,
            "method": "manual namespace deregistration after SDK drop fallback",
            "removed_storage": removed_storage,
            "registered_location": registered_location,
            "deregistered": deregistered,
            "sdk_error": error_text,
        }

    def drop_table(self, table_uri: str) -> dict[str, Any]:
        """Drop a Lance table from its parent database."""

        resolved = resolve_table_location(table_uri)
        if resolved.namespace:
            db = self._connect_namespace_location(resolved.namespace)
            registered_location = self._describe_namespace_table_location(
                db,
                resolved.namespace,
            )
            try:
                db.drop_table(
                    resolved.namespace.table_name,
                    namespace_path=list(resolved.namespace.namespace_path),
                )
            except Exception as exc:
                repaired = self._repair_namespace_drop_after_location_error(
                    db,
                    resolved.namespace,
                    registered_location,
                    exc,
                )
                if repaired is not None:
                    return repaired
                raise
            return {"status": "dropped", "table": resolved.namespace.table_name}
        assert resolved.direct is not None
        db = self._connect(resolved.direct.database_uri)
        db.drop_table(resolved.direct.table_name)
        return {"status": "dropped", "table": resolved.direct.table_name}

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
