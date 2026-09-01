from __future__ import annotations

from dataclasses import asdict

import pandas as pd
import streamlit as st

from lance_explorer.config import AppConfig
from lance_explorer.repository import LanceRepository
from lance_explorer.schema_diff import diff_schemas
from lance_explorer.table_refs import resolve_table_location, table_parent_resource
from lance_explorer.ui.cache import cached_tags, cached_versions
from lance_explorer.ui.components.code_export import show_code_export
from lance_explorer.ui.components.common import (
    display_result,
    parse_version,
    table_uri_control,
    template_directory,
)
from lance_explorer.ui.help_text import help_text
from lance_explorer.ui.state import bump_generation, generation_for


def _refresh_after_mutation(table_uri: str) -> None:
    bump_generation(table_uri)
    bump_generation(table_parent_resource(table_uri))
    st.session_state.query_results = {}
    st.session_state.comparison_results = {}
    st.session_state.pop("table_preview", None)
    st.session_state.pop("table_schema_diff", None)


def _show_status_once() -> None:
    if message := st.session_state.pop("maintenance_status", None):
        st.success(message)


def _version_numbers(versions: list[dict[str, object]]) -> list[int]:
    return sorted(
        value for item in versions if isinstance(value := item.get("version"), int)
    )


def _version_metadata(versions: list[dict[str, object]], version: int) -> dict[str, object] | None:
    return next((item for item in versions if item.get("version") == version), None)


def _version_selector(
    label: str,
    version_numbers: list[int],
    *,
    key: str,
    default: int | None = None,
) -> int | None:
    if version_numbers:
        index = (
            version_numbers.index(default)
            if default in version_numbers
            else len(version_numbers) - 1
        )
        return st.selectbox(label, version_numbers, index=index, key=key)
    value = st.text_input(label, value=str(default or ""), key=key)
    return parse_version(value)


def _render_version_context(
    repository: LanceRepository,
    table_uri: str,
    versions: list[dict[str, object]],
    version_numbers: list[int],
    selected_version: int | None,
) -> None:
    """Show metadata and schema movement around a version before tagging/restoring."""

    if selected_version is None:
        return
    if metadata := _version_metadata(versions, selected_version):
        st.caption("Selected version metadata")
        st.json(metadata)
    previous_versions = [version for version in version_numbers if version < selected_version]
    if not previous_versions:
        st.caption("No prior version is available for schema-change context.")
        return
    previous_version = previous_versions[-1]
    try:
        changes = [
            asdict(change)
            for change in diff_schemas(
                repository.get_schema(table_uri, previous_version),
                repository.get_schema(table_uri, selected_version),
            )
        ]
    except Exception as exc:
        st.caption(f"Unable to compare schemas around this version: {exc}")
        return
    st.caption(f"Schema changes from version {previous_version} to {selected_version}")
    if changes:
        st.dataframe(pd.DataFrame(changes), width="stretch")
    else:
        st.caption("No schema changes detected. Row/index/maintenance changes may still exist.")


def _render_optimize_tab(config: AppConfig, repository: LanceRepository, table_uri: str) -> None:
    st.subheader("Optimize", help=help_text("optimize"))
    with st.form("optimize-table"):
        cleanup_days = st.number_input(
            "Also clean versions older than this many days (0 disables cleanup)",
            min_value=0,
            value=0,
            help=help_text("optimize"),
        )
        optimize_confirmation = st.checkbox(
            "I understand this will rewrite table/index storage metadata."
        )
        optimize = st.form_submit_button("Optimize table")
    if optimize:
        if not optimize_confirmation:
            st.error("Confirm that you want to optimize this table.")
        else:
            try:
                st.session_state.operation_results["optimize"] = repository.optimize(
                    table_uri,
                    cleanup_days=int(cleanup_days) if cleanup_days else None,
                )
                _refresh_after_mutation(table_uri)
                st.session_state["maintenance_status"] = "Optimization completed"
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    display_result(st.session_state.operation_results.get("optimize"))
    show_code_export(
        "optimize",
        {
            "table_uri": table_uri,
            "cleanup_days": int(cleanup_days) if cleanup_days else None,
        },
        template_directory=template_directory(config),
    )


def _render_tags_tab(
    repository: LanceRepository,
    table_uri: str,
    tags: list[dict[str, object]],
    versions: list[dict[str, object]],
    version_numbers: list[int],
) -> None:
    st.subheader("Tags", help=help_text("tags"))
    st.warning(
        "Tagged versions are not removed by regular cleanup/version lifecycle operations. "
        "Delete the tag manually before expecting cleanup to remove that protected version.",
        icon=":material/warning:",
    )
    if tags:
        st.dataframe(pd.DataFrame(tags), width="stretch")
        tag_names = [str(item["tag"]) for item in tags if item.get("tag")]
        selected_tag = st.selectbox("Inspect tag", tag_names)
        selected = next((item for item in tags if item.get("tag") == selected_tag), None)
        if selected:
            st.json(selected)
    else:
        st.info("No tags are defined for this table.")

    st.subheader("Set tag", help=help_text("set_tag"))
    default_version = version_numbers[-1] if version_numbers else None
    selected_version = _version_selector(
        "Version to tag",
        version_numbers,
        key="tag-version",
        default=default_version,
    )
    _render_version_context(repository, table_uri, versions, version_numbers, selected_version)
    with st.form("set-tag"):
        tag_name = st.text_input("Tag name", placeholder="baseline")
        set_confirmation = st.checkbox(
            "I understand this will create or move this tag for the selected version."
        )
        set_tag = st.form_submit_button("Set tag")
    if set_tag:
        if not set_confirmation:
            st.error("Confirm that you want to set this tag.")
        elif selected_version is None:
            st.error("Select a valid version before setting a tag.")
        else:
            try:
                st.session_state.operation_results["set_tag"] = repository.set_tag(
                    table_uri, tag_name, selected_version
                )
                _refresh_after_mutation(table_uri)
                st.session_state["maintenance_status"] = "Tag saved"
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    display_result(st.session_state.operation_results.get("set_tag"))

    st.subheader("Delete tag", help=help_text("delete_tag"))
    tag_names = [str(item["tag"]) for item in tags if item.get("tag")]
    if not tag_names:
        st.caption("No tags are available to delete.")
        return
    delete_tag = st.selectbox("Tag", tag_names, key="delete-tag-name")
    with st.form("delete-tag"):
        st.caption("Type the exact tag name to confirm deletion.")
        st.code(delete_tag, language="text")
        delete_confirmation = st.text_input("Tag name", key="delete-tag-confirmation")
        delete = st.form_submit_button("Delete tag")
    if delete:
        if delete_confirmation != delete_tag:
            st.error("The tag name does not match.")
        else:
            try:
                st.session_state.operation_results["delete_tag"] = repository.delete_tag(
                    table_uri, delete_tag
                )
                _refresh_after_mutation(table_uri)
                st.session_state["maintenance_status"] = "Tag deleted"
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    display_result(st.session_state.operation_results.get("delete_tag"))


def _render_versions_tab(
    config: AppConfig,
    repository: LanceRepository,
    table_uri: str,
    table_name: str,
    versions: list[dict[str, object]],
    version_numbers: list[int],
) -> None:
    st.subheader("Clean up old versions", help=help_text("cleanup_versions"))
    with st.form("cleanup-versions"):
        older_than_days = st.number_input(
            "Remove versions older than days",
            min_value=0,
            value=7,
            help=help_text("cleanup_versions"),
        )
        delete_unverified = st.checkbox(
            "Also delete unverified files", help=help_text("delete_unverified")
        )
        st.caption("Type the exact table name to confirm version cleanup.")
        st.code(table_name, language="text")
        cleanup_confirmation = st.text_input("Table name", key="cleanup-table-confirmation")
        cleanup = st.form_submit_button("Clean up versions")
    if cleanup:
        if cleanup_confirmation != table_name:
            st.error("The table name does not match.")
        else:
            try:
                st.session_state.operation_results["cleanup"] = repository.cleanup_versions(
                    table_uri,
                    older_than_days=int(older_than_days),
                    delete_unverified=delete_unverified,
                )
                _refresh_after_mutation(table_uri)
                st.session_state["maintenance_status"] = "Version cleanup completed"
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    display_result(st.session_state.operation_results.get("cleanup"))
    show_code_export(
        "cleanup_versions",
        {
            "table_uri": table_uri,
            "older_than_days": int(older_than_days),
            "delete_unverified": delete_unverified,
        },
        template_directory=template_directory(config),
    )

    st.subheader("Restore a version", help=help_text("restore_version"))
    st.info(
        "Restore is an append-only table operation: it commits a new latest version whose "
        "contents match the selected historical version. For example, restoring version 18 "
        "while the table is at version 19 creates version 20, and version 20 has the same "
        "logical contents as version 18. Versions 18 and 19 remain in the history unless "
        "they are later cleaned up.",
        icon=":material/history:",
    )
    if version_numbers:
        st.caption(f"Available versions: {version_numbers[0]} to {version_numbers[-1]}")
        default_restore = version_numbers[-1]
    else:
        st.caption("Available versions could not be loaded.")
        default_restore = 1
    selected_restore_version = _version_selector(
        "Version",
        version_numbers,
        key="restore-version-text",
        default=default_restore,
    )
    if version_numbers and selected_restore_version not in version_numbers:
        st.warning("This version is outside the currently loaded version list.")
    _render_version_context(
        repository, table_uri, versions, version_numbers, selected_restore_version
    )

    with st.form("restore-version"):
        restore_confirmation = st.checkbox(
            "I understand this will change the current table contents."
        )
        restore = st.form_submit_button("Restore version")
    if restore:
        if not restore_confirmation:
            st.error("Confirm that you want to restore this version.")
        elif selected_restore_version is None:
            st.error("Enter a valid version before restoring.")
        else:
            try:
                st.session_state.operation_results["restore"] = repository.restore_version(
                    table_uri, selected_restore_version
                )
                _refresh_after_mutation(table_uri)
                st.session_state["maintenance_status"] = "Version restored"
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    display_result(st.session_state.operation_results.get("restore"))
    show_code_export(
        "restore_version",
        {"table_uri": table_uri, "version": selected_restore_version or int(default_restore)},
        template_directory=template_directory(config),
    )


def _render_table_management_tab(
    config: AppConfig,
    repository: LanceRepository,
    table_uri: str,
    table_name: str,
) -> None:
    st.subheader("Drop table", help=help_text("drop_table"))
    with st.form("drop-table"):
        st.caption("Type the exact table name to confirm deletion.")
        st.code(table_name, language="text")
        drop_confirmation = st.text_input("Table name", key="drop-table-confirmation")
        drop = st.form_submit_button("Drop table")
    if drop:
        if drop_confirmation != table_name:
            st.error("The table name does not match.")
        else:
            try:
                st.session_state.operation_results["drop_table"] = repository.drop_table(table_uri)
                _refresh_after_mutation(table_uri)
                st.session_state.selected_table_uri = ""
                st.session_state["maintenance_status"] = "Table dropped"
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    display_result(st.session_state.operation_results.get("drop_table"))
    show_code_export(
        "drop_table",
        {"table_uri": table_uri},
        template_directory=template_directory(config),
    )


def render(config: AppConfig) -> None:
    """Render table optimization, version cleanup, restore, and drop workflows."""

    st.title("Maintenance")
    _show_status_once()
    table_uri = table_uri_control(key="maintenance-table-open")
    if not table_uri:
        return

    repository = LanceRepository(config.max_query_rows)
    resolved_location = resolve_table_location(table_uri)
    table_name = (
        resolved_location.namespace.table_name
        if resolved_location.namespace
        else resolved_location.direct.table_name
    )
    try:
        versions = cached_versions(table_uri, generation_for(table_uri))
    except Exception as exc:
        versions = []
        st.warning(f"Unable to load table versions: {exc}")
    try:
        tags = cached_tags(table_uri, generation_for(table_uri))
    except Exception as exc:
        tags = []
        st.warning(f"Unable to load table tags: {exc}")
    version_numbers = _version_numbers(versions)

    optimize_tab, tags_tab, versions_tab, table_management_tab = st.tabs(
        ["Optimize", "Tags", "Versions", "Table Management"]
    )
    with optimize_tab:
        _render_optimize_tab(config, repository, table_uri)
    with tags_tab:
        _render_tags_tab(repository, table_uri, tags, versions, version_numbers)
    with versions_tab:
        _render_versions_tab(config, repository, table_uri, table_name, versions, version_numbers)
    with table_management_tab:
        _render_table_management_tab(config, repository, table_uri, table_name)
