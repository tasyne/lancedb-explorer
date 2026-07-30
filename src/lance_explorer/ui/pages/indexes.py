from __future__ import annotations

import pandas as pd
import streamlit as st

from lance_explorer.config import AppConfig
from lance_explorer.index_registry import (
    FTS_BASE_TOKENIZERS,
    FTS_LANGUAGES,
    FTS_PRESETS,
    available_index_definitions,
    compatible_index_definitions,
    fts_options_for_preset,
    fts_uses_packaged_jieba,
)
from lance_explorer.paths import split_table_uri
from lance_explorer.repository import LanceRepository
from lance_explorer.ui.cache import cached_snapshot
from lance_explorer.ui.components.code_export import show_code_export
from lance_explorer.ui.components.common import table_uri_control, template_directory
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
    if message := st.session_state.pop("index_status", None):
        st.success(message)


def _apply_fts_preset_to_state(preset_key: str) -> None:
    if st.session_state.get("fts_preset_applied") == preset_key:
        return
    options = fts_options_for_preset(preset_key)
    for key, value in options.items():
        st.session_state[f"fts_{key}"] = value
    st.session_state["fts_max_token_length_enabled"] = (
        options.get("max_token_length") is not None
    )
    st.session_state["fts_preset_applied"] = preset_key


def _fts_config_controls() -> dict[str, object]:
    preset_labels = {
        key: f"{preset.label} - {preset.description}" for key, preset in FTS_PRESETS.items()
    }
    preset_key = st.selectbox("FTS preset", list(FTS_PRESETS), format_func=preset_labels.get)
    _apply_fts_preset_to_state(preset_key)

    first, second = st.columns(2)
    with first:
        with_position = st.checkbox(
            "Store token positions",
            key="fts_with_position",
            help=help_text("fts_positions"),
        )
        base_tokenizer = st.selectbox(
            "Base tokenizer",
            FTS_BASE_TOKENIZERS,
            key="fts_base_tokenizer",
            help=help_text("fts_tokenizer"),
        )
        language = st.selectbox(
            "Language",
            FTS_LANGUAGES,
            key="fts_language",
            help=help_text("fts_language"),
        )
        max_token_length_enabled = st.checkbox(
            "Limit max token length",
            key="fts_max_token_length_enabled",
        )
        max_token_length = st.number_input(
            "Max token length",
            min_value=1,
            max_value=100,
            disabled=not max_token_length_enabled,
            key="fts_max_token_length",
        )
    with second:
        lower_case = st.checkbox("Lowercase tokens", key="fts_lower_case")
        stem = st.checkbox("Stem tokens", key="fts_stem")
        remove_stop_words = st.checkbox("Remove stop words", key="fts_remove_stop_words")
        ascii_folding = st.checkbox("ASCII folding", key="fts_ascii_folding")
        ngram_min_length = st.number_input(
            "N-gram min length",
            min_value=1,
            max_value=20,
            disabled=base_tokenizer != "ngram",
            key="fts_ngram_min_length",
        )
        ngram_max_length = st.number_input(
            "N-gram max length",
            min_value=1,
            max_value=20,
            disabled=base_tokenizer != "ngram",
            key="fts_ngram_max_length",
        )
        prefix_only = st.checkbox(
            "Prefix-only n-grams",
            disabled=base_tokenizer != "ngram",
            key="fts_prefix_only",
        )

    config_options: dict[str, object] = {
        "with_position": with_position,
        "base_tokenizer": base_tokenizer,
        "language": language,
        "max_token_length": int(max_token_length) if max_token_length_enabled else None,
        "lower_case": lower_case,
        "stem": stem,
        "remove_stop_words": remove_stop_words,
        "ascii_folding": ascii_folding,
        "ngram_min_length": int(ngram_min_length),
        "ngram_max_length": int(ngram_max_length),
        "prefix_only": prefix_only,
    }
    if fts_uses_packaged_jieba(config_options):
        st.caption(
            "Jieba uses packaged dictionary files under "
            "`lance_explorer/language_models/jieba/default`."
        )
    return config_options


def render(config: AppConfig) -> None:
    """Render index inspection, creation, and removal workflows."""

    st.title("Indexes")
    _show_status_once()
    table_uri = table_uri_control(key="index-table-open")
    if not table_uri:
        return

    generation = generation_for(table_uri)
    repository = LanceRepository(config.max_query_rows)
    try:
        snapshot = cached_snapshot(table_uri, None, generation)
        schema = repository.get_schema(table_uri)
    except Exception as exc:
        st.error(str(exc))
        return

    st.subheader("Existing indexes", help=help_text("existing_indexes"))
    indexes = snapshot.get("indexes", [])
    st.dataframe(pd.DataFrame(indexes), width="stretch")

    st.subheader("Create index", help=help_text("create_index"))
    with st.popover("Index type guide", icon=":material/info:"):
        for index_definition in available_index_definitions():
            st.markdown(f"**{index_definition.label}** - {index_definition.description}")
        st.caption("After writes, Optimize folds new rows into existing indexes.")

    column_names = schema.names
    selected_column = st.selectbox("Column", column_names)
    field = schema.field(selected_column)
    definitions = compatible_index_definitions(field.type)
    if not definitions:
        st.warning(f"No registered non-vector index type supports {field.type}.")
    else:
        labels = {
            definition.key: f"{definition.label} - {definition.description}"
            for definition in definitions
        }
        selected_type = st.selectbox(
            "Index type",
            list(labels),
            format_func=labels.get,
            help=help_text("create_index"),
        )
        index_name = st.text_input("Index name (optional)")
        replace = st.checkbox(
            "Replace an index with the same name",
            help=help_text("replace_index"),
        )
        config_options: dict[str, object] = {}
        if selected_type == "FTS":
            config_options = _fts_config_controls()

        definition = next(item for item in definitions if item.key == selected_type)
        show_code_export(
            "create_index",
            {
                "table_uri": table_uri,
                "column": selected_column,
                "config_class": definition.class_name,
                "config_options": config_options,
                "needs_language_model_home": fts_uses_packaged_jieba(config_options),
                "index_name": index_name.strip() or None,
                "replace": replace,
            },
            template_directory=template_directory(config),
        )

        with st.form("create-index"):
            create_confirmation = st.checkbox(
                "I understand this will modify the selected table metadata."
            )
            create = st.form_submit_button("Create index")
        if create:
            if not create_confirmation:
                st.error("Confirm that you want to create this index.")
            else:
                try:
                    st.session_state.operation_results["create_index"] = repository.create_index(
                        table_uri,
                        column=selected_column,
                        index_type=selected_type,
                        name=index_name.strip() or None,
                        replace=replace,
                        config_options=config_options,
                    )
                    _refresh_after_mutation(table_uri)
                    st.session_state["index_status"] = "Index created"
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

    st.subheader("Drop index", help=help_text("drop_index"))
    index_names = [str(item.get("name", "")) for item in indexes if item.get("name")]
    if not index_names:
        st.caption("No named indexes are available.")
    else:
        drop_name = st.selectbox("Index", index_names)
        show_code_export(
            "drop_index",
            {"table_uri": table_uri, "index_name": drop_name},
            template_directory=template_directory(config),
        )
        with st.form("drop-index"):
            st.caption("Type the exact index name to confirm deletion.")
            st.code(drop_name, language="text")
            drop_confirmation = st.text_input("Index name")
            drop = st.form_submit_button("Drop index")
        if drop:
            if drop_confirmation != drop_name:
                st.error("The index name does not match.")
            else:
                try:
                    st.session_state.operation_results["drop_index"] = repository.drop_index(
                        table_uri, drop_name
                    )
                    _refresh_after_mutation(table_uri)
                    st.session_state["index_status"] = (
                        "Index dropped. Optimize later to remove unreferenced files."
                    )
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
