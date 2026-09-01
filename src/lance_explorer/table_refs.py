from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, quote, unquote, urlparse

from lance_explorer.paths import TableLocation, normalize_uri, split_table_uri

NAMESPACE_TABLE_SCHEME = "lance-ns"


@dataclass(frozen=True, slots=True)
class NamespaceTableLocation:
    """A namespace-backed Lance table reference."""

    table_ref: str
    implementation: str
    root: str
    namespace_path: tuple[str, ...]
    table_name: str


@dataclass(frozen=True, slots=True)
class ResolvedTableLocation:
    """A selected table resolved to either a path URI or namespace table."""

    original: str
    direct: TableLocation | None = None
    namespace: NamespaceTableLocation | None = None

    @property
    def is_namespace(self) -> bool:
        return self.namespace is not None


def namespace_path_from_text(value: str) -> tuple[str, ...]:
    """Parse slash-delimited namespace text into validated path components."""

    parts = tuple(part.strip() for part in value.replace("\\", "/").split("/") if part.strip())
    invalid = [part for part in parts if "/" in part or "\\" in part]
    if invalid:
        raise ValueError("Namespace path components cannot contain path separators")
    return parts


def format_namespace_path(namespace_path: tuple[str, ...] | list[str]) -> str:
    """Return a compact slash-delimited namespace path label."""

    return "/".join(namespace_path) if namespace_path else "(root)"


def format_namespace_table_ref(
    root: str,
    namespace_path: tuple[str, ...] | list[str],
    table_name: str,
    *,
    implementation: str = "dir",
) -> str:
    """Encode a namespace table reference as a URI-like string for app state."""

    normalized_root = normalize_uri(root)
    components = [*namespace_path, table_name]
    if not table_name.strip():
        raise ValueError("Namespace table name cannot be empty")
    encoded_path = "/".join(quote(str(component).strip(), safe="._-") for component in components)
    return (
        f"{NAMESPACE_TABLE_SCHEME}://{quote(implementation, safe='._-')}/{encoded_path}"
        f"?root={quote(normalized_root, safe='')}"
    )


def is_namespace_table_ref(value: str) -> bool:
    """Return whether a selected table string uses Lance Explorer namespace syntax."""

    return urlparse(value).scheme == NAMESPACE_TABLE_SCHEME


def parse_namespace_table_ref(value: str) -> NamespaceTableLocation:
    """Decode a namespace table reference created by `format_namespace_table_ref`."""

    parsed = urlparse(value)
    if parsed.scheme != NAMESPACE_TABLE_SCHEME:
        raise ValueError("Not a Lance namespace table reference")
    implementation = unquote(parsed.netloc or "")
    if not implementation:
        raise ValueError("Namespace implementation is missing")
    root_values = parse_qs(parsed.query).get("root", [])
    if not root_values:
        raise ValueError("Namespace root is missing")
    components = tuple(
        unquote(part) for part in parsed.path.strip("/").split("/") if part.strip()
    )
    if not components:
        raise ValueError("Namespace table reference does not include a table name")
    namespace_path = components[:-1]
    table_name = components[-1]
    return NamespaceTableLocation(
        table_ref=value,
        implementation=implementation,
        root=normalize_uri(root_values[0]),
        namespace_path=namespace_path,
        table_name=table_name,
    )


def resolve_table_location(value: str) -> ResolvedTableLocation:
    """Resolve a selected table string to direct-path or namespace details."""

    normalized = normalize_uri(value)
    if is_namespace_table_ref(normalized):
        namespace = parse_namespace_table_ref(normalized)
        return ResolvedTableLocation(original=namespace.table_ref, namespace=namespace)
    direct = split_table_uri(normalized)
    return ResolvedTableLocation(original=direct.table_uri, direct=direct)


def normalize_table_reference(value: str) -> str:
    """Normalize either a direct `.lance` URI or a namespace table reference."""

    return resolve_table_location(value).original


def table_parent_resource(value: str) -> str:
    """Return a cache parent resource for a selected table reference."""

    resolved = resolve_table_location(value)
    if resolved.namespace:
        return resolved.namespace.root
    assert resolved.direct is not None
    return resolved.direct.database_uri


def table_display_label(value: str) -> str:
    """Return a concise label for direct and namespace table references."""

    resolved = resolve_table_location(value)
    if resolved.namespace:
        namespace = format_namespace_path(resolved.namespace.namespace_path)
        root_tail = resolved.namespace.root.rstrip("/\\").replace("\\", "/").split("/")[-1]
        suffix = f" @ {root_tail}" if root_tail else ""
        return f"ns:{namespace}/{resolved.namespace.table_name}{suffix}"
    assert resolved.direct is not None
    parent = resolved.direct.database_uri.rstrip("/\\").replace("\\", "/").split("/")[-1]
    if parent:
        return f"{parent}/{resolved.direct.table_name}.lance"
    return f"{resolved.direct.table_name}.lance"
