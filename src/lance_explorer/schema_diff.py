from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pyarrow as pa


@dataclass(frozen=True, slots=True)
class FieldSnapshot:
    path: str
    type: str
    nullable: bool
    metadata: dict[str, str]
    ordinal: int


@dataclass(frozen=True, slots=True)
class FieldChange:
    path: str
    change: str
    left: Any
    right: Any


def _decode_metadata(metadata: dict[bytes, bytes] | None) -> dict[str, str]:
    if not metadata:
        return {}
    return {
        key.decode("utf-8", errors="replace"): value.decode("utf-8", errors="replace")
        for key, value in metadata.items()
    }


def _children(field: pa.Field) -> list[pa.Field]:
    data_type = field.type
    if pa.types.is_struct(data_type):
        return list(data_type)
    if (
        pa.types.is_list(data_type)
        or pa.types.is_large_list(data_type)
        or pa.types.is_fixed_size_list(data_type)
    ):
        return [pa.field("item", data_type.value_type, nullable=data_type.value_field.nullable)]
    if pa.types.is_map(data_type):
        return [
            pa.field("key", data_type.key_type, nullable=False),
            pa.field("value", data_type.item_type, nullable=True),
        ]
    return []


def flatten_schema(schema: pa.Schema) -> list[FieldSnapshot]:
    snapshots: list[FieldSnapshot] = []

    def visit(field: pa.Field, prefix: str, ordinal: int) -> None:
        path = f"{prefix}.{field.name}" if prefix else field.name
        snapshots.append(
            FieldSnapshot(
                path=path,
                type=str(field.type),
                nullable=field.nullable,
                metadata=_decode_metadata(field.metadata),
                ordinal=ordinal,
            )
        )
        for child_ordinal, child in enumerate(_children(field)):
            visit(child, path, child_ordinal)

    for ordinal, field in enumerate(schema):
        visit(field, "", ordinal)
    return snapshots


def schema_to_rows(schema: pa.Schema) -> list[dict[str, Any]]:
    return [asdict(field) for field in flatten_schema(schema)]


def diff_schemas(left: pa.Schema, right: pa.Schema) -> list[FieldChange]:
    left_fields = {field.path: field for field in flatten_schema(left)}
    right_fields = {field.path: field for field in flatten_schema(right)}
    changes: list[FieldChange] = []

    for path in sorted(left_fields.keys() - right_fields.keys()):
        changes.append(FieldChange(path, "removed", asdict(left_fields[path]), None))
    for path in sorted(right_fields.keys() - left_fields.keys()):
        changes.append(FieldChange(path, "added", None, asdict(right_fields[path])))

    for path in sorted(left_fields.keys() & right_fields.keys()):
        left_field = left_fields[path]
        right_field = right_fields[path]
        for attribute in ("type", "nullable", "metadata", "ordinal"):
            left_value = getattr(left_field, attribute)
            right_value = getattr(right_field, attribute)
            if left_value != right_value:
                changes.append(
                    FieldChange(
                        path=path,
                        change=attribute,
                        left=left_value,
                        right=right_value,
                    )
                )

    if _decode_metadata(left.metadata) != _decode_metadata(right.metadata):
        changes.append(
            FieldChange(
                path="<schema>",
                change="metadata",
                left=_decode_metadata(left.metadata),
                right=_decode_metadata(right.metadata),
            )
        )
    return changes
