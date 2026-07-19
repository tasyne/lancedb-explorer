from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from upath import UPath

from lance_explorer.config import upath_storage_options_from_env


@dataclass(frozen=True, slots=True)
class PathEntry:
    uri: str
    name: str
    is_dir: bool
    is_table: bool
    size: int | None = None


@dataclass(frozen=True, slots=True)
class TableLocation:
    table_uri: str
    database_uri: str
    table_name: str


def has_uri_scheme(value: str) -> bool:
    parsed = urlparse(value)
    return bool(parsed.scheme and len(parsed.scheme) > 1)


def normalize_uri(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("URI cannot be empty")
    if has_uri_scheme(value):
        return value.rstrip("/") if value not in {"file://", "memory://"} else value
    return str(Path(value).expanduser().absolute())


def make_upath(uri: str) -> UPath:
    normalized = normalize_uri(uri)
    return UPath(normalized, **upath_storage_options_from_env(normalized))


def is_lance_table_path(path: UPath | str) -> bool:
    return str(path).rstrip("/").lower().endswith(".lance")


def split_table_uri(table_uri: str) -> TableLocation:
    normalized = normalize_uri(table_uri)
    if not is_lance_table_path(normalized):
        raise ValueError("A full Lance table URI must end with '.lance'")

    path = make_upath(normalized)
    table_name = path.name[: -len(".lance")]
    if not table_name:
        raise ValueError("Table URI does not include a table name")
    return TableLocation(
        table_uri=str(path),
        database_uri=str(path.parent),
        table_name=table_name,
    )


def parent_uri(uri: str) -> str:
    return str(make_upath(uri).parent)


def join_uri(parent: str, child: str) -> str:
    return str(make_upath(parent) / child)


def list_children(uri: str) -> list[PathEntry]:
    path = make_upath(uri)
    entries: list[PathEntry] = []
    for child in path.iterdir():
        try:
            is_dir = child.is_dir()
        except OSError:
            is_dir = False
        size: int | None = None
        if not is_dir:
            try:
                size = child.stat().st_size
            except (OSError, AttributeError):
                size = None
        entries.append(
            PathEntry(
                uri=str(child),
                name=child.name,
                is_dir=is_dir,
                is_table=is_lance_table_path(child),
                size=size,
            )
        )
    return sorted(entries, key=lambda item: (not item.is_dir, item.name.lower()))
