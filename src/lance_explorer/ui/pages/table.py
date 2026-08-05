from __future__ import annotations

from dataclasses import asdict

import pandas as pd
import streamlit as st

from lance_explorer.config import AppConfig
from lance_explorer.repository import LanceRepository
from lance_explorer.schema_diff import diff_schemas
from lance_explorer.ui.cache import cached_snapshot, cached_tags, cached_versions
from lance_explorer.ui.components.code_export import show_code_export
from lance_explorer.ui.components.common import parse_version, table_uri_control, template_directory
from lance_explorer.ui.components.dataframe import show_dataframe, vector_display_columns
from lance_explorer.ui.help_text import help_text
from lance_explorer.ui.state import generation_for, selected_table_checkout_reference


def _version_numbers(versions: list[dict[str, object]], current_version: object) -> list[int]:
    numbers: set[int] = set()
    for item in versions:
        value = item.get("version")
        if isinstance(value, int):
            numbers.add(value)
    if isinstance(current_version, int):
        numbers.add(current_version)
    return sorted(numbers)


def _sync_schema_diff_defaults(table_uri: str, version_numbers: list[int]) -> None:
    if not version_numbers:
        return
    defaults = (table_uri, version_numbers[0], version_numbers[-1])
    if st.session_state.get("schema_diff_defaults") == defaults:
        return
    st.session_state["schema_diff_defaults"] = defaults
    st.session_state["schema-left-version"] = str(version_numbers[0])
    st.session_state["schema-right-version"] = str(version_numbers[-1])


def _versions_with_tags(
    versions: list[dict[str, object]],
    tags: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Join tag names and tag manifest sizes onto version rows."""

    tags_by_version: dict[int, list[dict[str, object]]] = {}
    for tag in tags:
        version = tag.get("version")
        if isinstance(version, int):
            tags_by_version.setdefault(version, []).append(tag)
    rows: list[dict[str, object]] = []
    for version in versions:
        row = dict(version)
        version_number = row.get("version")
        version_tags = (
            tags_by_version.get(version_number, [])
            if isinstance(version_number, int)
            else []
        )
        row["tags"] = ", ".join(str(tag.get("tag", "")) for tag in version_tags if tag.get("tag"))
        row["tag_manifest_sizes"] = ", ".join(
            str(tag.get("manifest_size", ""))
            for tag in version_tags
            if tag.get("manifest_size") is not None
        )
        rows.append(row)
    return rows


def _open_code_reference_options(
    tags: list[dict[str, object]],
    version_numbers: list[int],
) -> list[int | str | None]:
    options: list[int | str | None] = [None]
    options.extend(str(tag["tag"]) for tag in tags if tag.get("tag"))
    options.extend(reversed(version_numbers))
    return options


def _open_code_reference_label(value: int | str | None) -> str:
    if value is None:
        return "Latest"
    if isinstance(value, int):
        return f"Version {value}"
    return f"Tag {value}"


def _render_insert_guidance(config: AppConfig, table_uri: str) -> None:
    """Render read-only insertion and update guidance for the selected table."""

    template_dir = template_directory(config)
    context = {"table_uri": table_uri, "open_version": None}

    st.caption("Read-only insertion and update guide", help=help_text("insert_data"))
    st.info(
        "This tab only generates reference code. It does not provide forms that write to the "
        "selected table."
    )

    st.markdown(
        """
        Before inserting production data:

        - Use `table.add(...)` to append to an existing table. `create_table(..., exist_ok=True)`
          opens an existing table and validates schema, but it does not append the provided rows.
        - Batch writes when possible. LanceDB can parallelize large materialized writes, while many
          tiny appends create fragments that later need compaction.
        - Prefer pandas for familiar scalar/text/vector appends, PyArrow for exact Arrow types, and
          `LanceModel` when you want Pydantic validation before writing.
        - Use inline Arrow `binary` for small payloads such as thumbnails. Use Lance Blob v2
          columns for larger images or file-like/partial-read workflows; Blob v2 requires tables
          written with `data_storage_version="2.2"` or newer.
        - Writes create new table versions. After many small appends, deletes, or index-backed
          updates, run `table.optimize()` during a maintenance window to compact fragments, prune
          old data when configured, and incorporate newly written rows into existing indexes.
        - For updates, prefer `merge_insert(...)` when matching incoming rows by key. Use direct
          `update(...)` only when a SQL predicate unambiguously identifies the target rows.
        """
    )

    arrow_tab, pandas_tab, pydantic_tab, merge_tab, update_tab = st.tabs(
        ["Arrow + blobs", "Pandas", "Pydantic", "Merge/upsert", "Update"]
    )
    with arrow_tab:
        st.write(
            "Use this pattern when you need explicit Arrow types or Blob v2 image payloads. "
            "The incoming schema must be compatible with the table schema."
        )
        show_code_export(
            "insert_arrow_blobs",
            context,
            template_directory=template_dir,
            label="Code export: Append Arrow rows with image blobs",
        )
    with pandas_tab:
        st.write(
            "Pandas is the simplest path for teams that already build DataFrames. Use Arrow when "
            "you need precise binary/blob storage controls."
        )
        show_code_export(
            "insert_pandas",
            context,
            template_directory=template_dir,
            label="Code export: Append a pandas DataFrame",
        )
    with pydantic_tab:
        st.write(
            "`LanceModel` adds Pydantic validation and LanceDB-aware vector fields. "
            "Pydantic-AI can produce or validate these model instances before they are "
            "converted to rows."
        )
        show_code_export(
            "insert_pydantic",
            context,
            template_directory=template_dir,
            label="Code export: Validate rows with Pydantic",
        )
    with merge_tab:
        st.write(
            "Use merge/upsert when incoming rows should update matching keys and insert missing "
            "keys in one committed write."
        )
        show_code_export(
            "merge_upsert",
            context,
            template_directory=template_dir,
            label="Code export: Merge or upsert rows by key",
        )
    with update_tab:
        st.write(
            "Use direct updates for small, well-scoped changes where a SQL predicate identifies "
            "the target rows clearly."
        )
        show_code_export(
            "update_rows",
            context,
            template_directory=template_dir,
            label="Code export: Update rows with a SQL predicate",
        )


def render(config: AppConfig) -> None:
    """Render selected-table metadata, versions, schema diff, and preview."""

    st.title("Table")
    table_uri = table_uri_control(key="table-open-form")
    if not table_uri:
        st.info("Select a full .lance table URI in Explorer or enter one above.")
        return

    generation = generation_for(table_uri)
    table_reference = selected_table_checkout_reference()
    try:
        snapshot = cached_snapshot(table_uri, table_reference, generation)
    except Exception as exc:
        st.error(f"Unable to open table: {exc}")
        return

    try:
        versions = cached_versions(table_uri, generation)
    except Exception as exc:
        versions = []
        st.warning(f"Unable to load table versions: {exc}")
    try:
        tags = cached_tags(table_uri, generation)
    except Exception as exc:
        tags = []
        st.warning(f"Unable to load table tags: {exc}")
    version_numbers = _version_numbers(versions, snapshot["version"])
    _sync_schema_diff_defaults(table_uri, version_numbers)
    display_vector_columns = vector_display_columns(snapshot)

    metrics = st.columns(4)
    metrics[0].metric("Rows", snapshot["row_count"], help=help_text("rows"))
    metrics[1].metric("Version", snapshot["version"], help=help_text("version"))
    statistics = snapshot.get("statistics", {})
    fragment_stats = statistics.get("fragment_stats", {})
    metrics[2].metric(
        "Fragments", fragment_stats.get("num_fragments", "-"), help=help_text("fragments")
    )
    metrics[3].metric("Indices", len(snapshot.get("indexes", [])), help=help_text("indexes"))

    (
        sample_tab,
        insert_tab,
        schema_tab,
        versions_tab,
        schema_changes_tab,
        indexes_tab,
        statistics_tab,
    ) = st.tabs(
        [
            "Sample",
            "Insert data",
            "Schema",
            "Versions",
            "Schema changes",
            "Indexes",
            "Statistics",
        ]
    )
    with sample_tab:
        st.caption("Bounded data preview", help=help_text("sample"))
        fields = [row["path"] for row in snapshot["schema"] if "." not in row["path"]]
        with st.form("table-preview"):
            columns = st.multiselect("Columns", fields, default=fields)
            limit = st.number_input(
                "Row limit", 1, config.max_query_rows, config.default_query_rows
            )
            load = st.form_submit_button("Load sample")
        if load:
            try:
                st.session_state["table_preview"] = LanceRepository(config.max_query_rows).preview(
                    table_uri,
                    columns=columns or None,
                    limit=int(limit),
                    version=table_reference,
                )
            except Exception as exc:
                st.error(str(exc))
        preview = st.session_state.get("table_preview")
        if preview is not None:
            show_dataframe(preview, vector_columns=display_vector_columns)
    with insert_tab:
        _render_insert_guidance(config, table_uri)
    with schema_tab:
        st.caption("Arrow schema", help=help_text("schema"))
        st.dataframe(pd.DataFrame(snapshot["schema"]), width="stretch")
        st.code(snapshot["schema_string"], language="text")
    with versions_tab:
        st.caption("Table history and tags", help=help_text("versions"))
        st.info(
            "Tags protect their target versions from regular cleanup. Delete a tag manually "
            "before expecting version cleanup to remove that tagged version."
        )
        st.dataframe(pd.DataFrame(_versions_with_tags(versions, tags)), width="stretch")
    with schema_changes_tab:
        st.caption("Historical schema comparison", help=help_text("schema_changes"))
        with st.form("version-schema-diff"):
            left_text = st.text_input("Left version", key="schema-left-version")
            right_text = st.text_input("Right version", key="schema-right-version")
            compare = st.form_submit_button("Compare schemas")
        if compare:
            try:
                left_version = parse_version(left_text)
                right_version = parse_version(right_text)
                repository = LanceRepository(config.max_query_rows)
                changes = [
                    asdict(change)
                    for change in diff_schemas(
                        repository.get_schema(table_uri, left_version),
                        repository.get_schema(table_uri, right_version),
                    )
                ]
                st.session_state["table_schema_diff"] = changes
            except Exception as exc:
                st.error(str(exc))
        changes = st.session_state.get("table_schema_diff")
        if changes is not None:
            st.dataframe(pd.DataFrame(changes), width="stretch")
    with indexes_tab:
        st.caption("Secondary indexes", help=help_text("indexes"))
        indexes = snapshot.get("indexes", [])
        st.dataframe(pd.DataFrame(indexes), width="stretch")
    with statistics_tab:
        st.caption("Physical layout", help=help_text("statistics"))
        st.json(statistics)

    code_version_options = _open_code_reference_options(tags, version_numbers)
    code_version = st.selectbox(
        "Version or tag for open-table code",
        code_version_options,
        format_func=_open_code_reference_label,
    )
    show_code_export(
        "open_table",
        {"table_uri": table_uri, "open_version": code_version},
        template_directory=template_directory(config),
    )
