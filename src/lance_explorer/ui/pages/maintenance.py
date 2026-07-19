from __future__ import annotations

import streamlit as st

from lance_explorer.config import AppConfig
from lance_explorer.paths import split_table_uri
from lance_explorer.repository import LanceRepository
from lance_explorer.ui.cache import cached_versions
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
    bump_generation(split_table_uri(table_uri).database_uri)
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


def render(config: AppConfig) -> None:
    st.title("Maintenance")
    _show_status_once()
    table_uri = table_uri_control(key="maintenance-table-open")
    if not table_uri:
        return

    repository = LanceRepository(config.max_query_rows)
    table_name = split_table_uri(table_uri).table_name
    try:
        versions = cached_versions(table_uri, generation_for(table_uri))
    except Exception as exc:
        versions = []
        st.warning(f"Unable to load table versions: {exc}")
    version_numbers = _version_numbers(versions)

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
    if version_numbers:
        st.caption(f"Available versions: {version_numbers[0]} to {version_numbers[-1]}")
        default_restore = str(version_numbers[-1])
    else:
        st.caption("Available versions could not be loaded.")
        default_restore = "1"
    restore_sync = (table_uri, default_restore)
    if st.session_state.get("restore_version_default") != restore_sync:
        st.session_state["restore_version_default"] = restore_sync
        st.session_state["restore-version-text"] = default_restore
    version_text = st.text_input("Version", key="restore-version-text")
    selected_restore_version: int | None = None
    try:
        selected_restore_version = parse_version(version_text)
        if selected_restore_version is None:
            raise ValueError("Version is required")
        if version_numbers and selected_restore_version not in version_numbers:
            st.warning("This version is outside the currently loaded version list.")
        elif metadata := _version_metadata(versions, selected_restore_version):
            st.caption("Selected version metadata")
            st.json(metadata)
    except Exception as exc:
        st.error(str(exc))

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
