from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

import pandas as pd

from lance_explorer.repository import LanceRepository
from lance_explorer.schema_diff import diff_schemas


def compare_metadata(
    repository: LanceRepository,
    left_uri: str,
    right_uri: str,
    *,
    left_version: int | None = None,
    right_version: int | None = None,
) -> dict[str, Any]:
    left = repository.snapshot(left_uri, version=left_version)
    right = repository.snapshot(right_uri, version=right_version)
    schema_changes = [
        asdict(change)
        for change in diff_schemas(
            repository.get_schema(left_uri, left_version),
            repository.get_schema(right_uri, right_version),
        )
    ]
    return {
        "left": left,
        "right": right,
        "summary": {
            "row_count_delta": right["row_count"] - left["row_count"],
            "same_schema": not schema_changes,
            "same_indexes": left["indexes"] == right["indexes"],
        },
        "schema_changes": schema_changes,
    }


def _canonical(value: Any) -> str:
    if pd.isna(value) if not isinstance(value, (list, dict, tuple)) else False:
        return "<NULL>"
    return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))


def compare_rows(
    repository: LanceRepository,
    left_uri: str,
    right_uri: str,
    *,
    columns: list[str],
    limit: int,
    key: str | None = None,
    left_version: int | None = None,
    right_version: int | None = None,
) -> dict[str, pd.DataFrame | int | str]:
    selected = list(dict.fromkeys(([key] if key else []) + columns))
    left = repository.preview(left_uri, columns=selected or None, limit=limit, version=left_version)
    right = repository.preview(
        right_uri, columns=selected or None, limit=limit, version=right_version
    )

    if not key:
        max_length = max(len(left), len(right))
        left_aligned = left.reindex(range(max_length)).add_prefix("left.")
        right_aligned = right.reindex(range(max_length)).add_prefix("right.")
        combined = pd.concat([left_aligned, right_aligned], axis=1)
        return {
            "mode": "positional_sample",
            "left_rows": len(left),
            "right_rows": len(right),
            "comparison": combined,
        }

    if key not in left.columns or key not in right.columns:
        raise ValueError(f"Comparison key '{key}' must exist in both tables")
    if left[key].duplicated().any() or right[key].duplicated().any():
        raise ValueError("Key-based comparison requires unique keys within the bounded result")

    left_indexed = left.set_index(key, drop=False)
    right_indexed = right.set_index(key, drop=False)
    left_keys = set(left_indexed.index)
    right_keys = set(right_indexed.index)

    only_left = (
        left_indexed.loc[list(left_keys - right_keys)] if left_keys - right_keys else left.iloc[0:0]
    )
    only_right = (
        right_indexed.loc[list(right_keys - left_keys)]
        if right_keys - left_keys
        else right.iloc[0:0]
    )

    changed_records: list[dict[str, Any]] = []
    compare_columns = columns or [
        column for column in left.columns if column != key and column in right.columns
    ]
    for current_key in sorted(left_keys & right_keys, key=str):
        for column in compare_columns:
            if column not in left.columns or column not in right.columns:
                continue
            left_value = left_indexed.at[current_key, column]
            right_value = right_indexed.at[current_key, column]
            if _canonical(left_value) != _canonical(right_value):
                changed_records.append(
                    {
                        key: current_key,
                        "column": column,
                        "left": left_value,
                        "right": right_value,
                    }
                )

    return {
        "mode": "key",
        "left_rows": len(left),
        "right_rows": len(right),
        "only_left": only_left.reset_index(drop=True),
        "only_right": only_right.reset_index(drop=True),
        "changed": pd.DataFrame(changed_records),
    }
