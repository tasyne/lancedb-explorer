from __future__ import annotations

import streamlit as st

from lance_explorer.config import AppConfig
from lance_explorer.paths import split_table_uri
from lance_explorer.repository import LanceRepository
from lance_explorer.ui.components.code_export import show_code_export
from lance_explorer.ui.components.common import (
    display_result,
    table_uri_control,
    template_directory,
)
from lance_explorer.ui.help_text import help_text
from lance_explorer.ui.state import bump_generation


def _refresh_after_mutation(table_uri: str) -> None:
    bump_generation(table_uri)
    bump_generation(split_table_uri(table_uri).database_uri)
    st.session_state.query_results = {}
    st.session_state.comparison_results = {}
    st.session_state.pop("table_preview", None)
    st.session_state.pop("table_schema_diff", None)


def render(config: AppConfig) -> None:
    st.title("Maintenance")
    table_uri = table_uri_control(key="maintenance-table-open")
    if not table_uri:
        return

    repository = LanceRepository(config.max_query_rows)

    st.subheader("Optimize", help=help_text("optimize"))
    with st.form("optimize-table"):
        cleanup_days = st.number_input(
            "Also clean versions older than this many days (0 disables cleanup)",
            min_value=0,
            value=0,
            help=help_text("optimize"),
        )
        optimize = st.form_submit_button("Optimize table")
    if optimize:
        try:
            st.session_state.operation_results["optimize"] = repository.optimize(
                table_uri,
                cleanup_days=int(cleanup_days) if cleanup_days else None,
            )
            _refresh_after_mutation(table_uri)
            st.success("Optimization completed")
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
        cleanup_confirmation = st.text_input("Type CLEANUP to confirm")
        cleanup = st.form_submit_button("Clean up versions")
    if cleanup:
        if cleanup_confirmation != "CLEANUP":
            st.error("Enter CLEANUP exactly to continue")
        else:
            try:
                st.session_state.operation_results["cleanup"] = repository.cleanup_versions(
                    table_uri,
                    older_than_days=int(older_than_days),
                    delete_unverified=delete_unverified,
                )
                _refresh_after_mutation(table_uri)
                st.success("Version cleanup completed")
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
    with st.form("restore-version"):
        version = st.number_input(
            "Version", min_value=1, value=1, help=help_text("restore_version")
        )
        restore_confirmation = st.text_input("Type RESTORE to confirm")
        restore = st.form_submit_button("Restore version")
    if restore:
        if restore_confirmation != "RESTORE":
            st.error("Enter RESTORE exactly to continue")
        else:
            try:
                st.session_state.operation_results["restore"] = repository.restore_version(
                    table_uri, int(version)
                )
                _refresh_after_mutation(table_uri)
                st.success("Version restored")
            except Exception as exc:
                st.error(str(exc))
    display_result(st.session_state.operation_results.get("restore"))
    show_code_export(
        "restore_version",
        {"table_uri": table_uri, "version": int(version)},
        template_directory=template_directory(config),
    )

    st.subheader("Drop table", help=help_text("drop_table"))
    table_name = split_table_uri(table_uri).table_name
    with st.form("drop-table"):
        drop_confirmation = st.text_input(f"Type {table_name} to confirm deletion")
        drop = st.form_submit_button("Drop table")
    if drop:
        if drop_confirmation != table_name:
            st.error("The table name does not match")
        else:
            try:
                st.session_state.operation_results["drop_table"] = repository.drop_table(table_uri)
                _refresh_after_mutation(table_uri)
                st.session_state.selected_table_uri = ""
                st.success("Table dropped")
            except Exception as exc:
                st.error(str(exc))
    display_result(st.session_state.operation_results.get("drop_table"))
    show_code_export(
        "drop_table",
        {"table_uri": table_uri},
        template_directory=template_directory(config),
    )
