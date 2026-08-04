from __future__ import annotations

import pandas as pd
import streamlit as st

from lance_explorer.config import AppConfig
from lance_explorer.index_compat import index_type_supported_by_installed_lancedb
from lance_explorer.index_registry import (
    FTS_BASE_TOKENIZERS,
    FTS_LANGUAGES,
    FTS_PRESETS,
    available_index_definitions,
    compatible_index_definitions,
    fts_options_for_preset,
    fts_uses_packaged_model,
)
from lance_explorer.language_models import language_model_archive_bytes, language_model_archive_name
from lance_explorer.paths import split_table_uri
from lance_explorer.repository import LanceRepository
from lance_explorer.ui.cache import cached_snapshot
from lance_explorer.ui.components.code_export import show_code_export
from lance_explorer.ui.components.common import table_uri_control, template_directory
from lance_explorer.ui.components.language_models import show_language_model_downloads
from lance_explorer.ui.help_text import help_text
from lance_explorer.ui.state import bump_generation, generation_for

_PQ_INDEX_TYPES = {"IVF_PQ", "IVF_HNSW_PQ", "HNSW_PQ"}
_RQ_INDEX_TYPES = {"IVF_RQ"}
_HNSW_INDEX_TYPES = {
    "IVF_HNSW_FLAT",
    "IVF_HNSW_PQ",
    "IVF_HNSW_SQ",
    "HNSW_FLAT",
    "HNSW_PQ",
    "HNSW_SQ",
}
_ACCELERATOR_INDEX_TYPES = {
    "IVF_FLAT",
    "IVF_PQ",
    "IVF_SQ",
    "IVF_RQ",
    "IVF_HNSW_PQ",
    "IVF_HNSW_SQ",
    "HNSW_PQ",
    "HNSW_SQ",
}

_VECTOR_HELP = {
    "distance_type": (
        "Metric used to train and query the index. l2 is Euclidean distance and is a "
        "safe default for unnormalized numeric vectors. cosine compares direction and is "
        "common for normalized semantic embeddings; in LanceDB cosine distance runs from 0 "
        "for identical to 2 for maximally dissimilar. dot is best only when the embedding "
        "model was trained for inner-product scoring because vector magnitude affects rank. "
        "The query metric must match the index metric; use flat-scan recall checks when tuning."
    ),
    "partition_mode": (
        "IVF means Inverted File: Lance groups vectors into partitions before searching. "
        "More partitions can reduce scanned vectors but can increase training and tuning cost."
    ),
    "num_partitions": (
        "Number of IVF partitions to train. Start small for HNSW-backed indexes and around "
        "row_count // 4096 for IVF_PQ, IVF_SQ, IVF_RQ, or IVF_FLAT."
    ),
    "target_partition_size": (
        "Alternative to choosing partition count directly. Lance targets this many rows per "
        "partition when training the index."
    ),
    "max_iterations": (
        "Maximum k-means iterations used while training IVF partition centroids from existing "
        "vectors. This is index-build training, not continuous per-row learning. In OSS, new "
        "writes can remain partially unindexed until Optimize updates index coverage."
    ),
    "sample_rate": (
        "Training sample multiplier. Higher values can improve centroid quality but increase "
        "index build time and memory pressure."
    ),
    "num_sub_vectors": (
        "Product Quantization splits each vector into sub-vectors. More sub-vectors usually "
        "improve recall but increase index size and query work."
    ),
    "num_bits": (
        "Bits used by the quantizer. Product Quantization commonly uses 8; RaBitQ often uses "
        "1 for very compact indexes."
    ),
    "m": (
        "HNSW means Hierarchical Navigable Small World. m controls graph degree: larger values "
        "can improve recall but increase memory, disk, and build time."
    ),
    "ef_construction": (
        "HNSW construction beam width. Larger values usually improve recall and index quality "
        "but slow index building."
    ),
    "accelerator": (
        "Optional LanceDB GPU accelerator for supported vector index builds. Use cuda on a "
        "CUDA-enabled NVIDIA setup or mps on Apple Silicon with PyTorch installed. Leave blank "
        "for CPU indexing; Enterprise deployments may manage GPU indexing automatically."
    ),
}

_VECTOR_GUIDANCE_ROWS = (
    {
        "index": "IVF_FLAT",
        "fit": "Raw-vector IVF baseline when storage is acceptable and quantization loss is not.",
        "size": "About raw vector payload plus IVF metadata.",
        "notes": "Float32 payload is roughly dimension x 4 bytes per row before metadata.",
    },
    {
        "index": "IVF_HNSW_FLAT",
        "fit": "Highest-recall IVF+HNSW choice with no quantization.",
        "size": "Around raw vector size plus HNSW graph overhead.",
        "notes": (
            "Graph construction improves search quality/latency but increases build work "
            "and storage."
        ),
    },
    {
        "index": "IVF_HNSW_SQ",
        "fit": "Strong default when recall, latency, and disk size all matter.",
        "size": "Typically a little larger than 1/4 of raw vector size.",
        "notes": "Tune HNSW search ef at query time before changing partitions.",
    },
    {
        "index": "IVF_RQ",
        "fit": "Maximum compression for large, high-dimensional datasets.",
        "size": "Around 1/32 of raw vector size.",
        "notes": "RaBitQ requires dimensions divisible by 8; good candidate for filtered searches.",
    },
    {
        "index": "IVF_PQ",
        "fit": "Often higher accuracy than IVF_RQ for dimensions <= 256.",
        "size": "Usually 1/64 to 1/16 of raw size, depending on sub-vectors.",
        "notes": (
            "Start num_sub_vectors near dimension // 8; increase for recall, decrease "
            "for size/speed."
        ),
    },
    {
        "index": "IVF_HNSW_PQ, IVF_HNSW_SQ, HNSW_PQ, HNSW_SQ",
        "fit": "Graph search plus compressed vectors when raw-vector HNSW is too large.",
        "size": "Compressed vector payload plus graph overhead; benchmark on target data.",
        "notes": (
            "Use when HNSW quality is useful but storage or memory pressure rules out "
            "flat vectors."
        ),
    },
)


def _language_option_applies(base_tokenizer: str) -> bool:
    """Return whether LanceDB's language enum affects this tokenizer setup."""

    return not (
        base_tokenizer.startswith("jieba/") or base_tokenizer.startswith("lindera/")
    )


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
        if _language_option_applies(str(base_tokenizer)):
            language = st.selectbox(
                "Language",
                FTS_LANGUAGES,
                key="fts_language",
                help=help_text("fts_language"),
            )
        else:
            language = None
            st.caption(
                "Language is controlled by the selected tokenizer model files for this preset, "
                "so LanceDB's stemmer language option is hidden."
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
        "max_token_length": int(max_token_length) if max_token_length_enabled else None,
        "lower_case": lower_case,
        "stem": stem,
        "remove_stop_words": remove_stop_words,
        "ascii_folding": ascii_folding,
        "ngram_min_length": int(ngram_min_length),
        "ngram_max_length": int(ngram_max_length),
        "prefix_only": prefix_only,
    }
    if language is not None:
        config_options["language"] = language
    if fts_uses_packaged_model(config_options):
        st.caption(
            "This tokenizer uses packaged model files under "
            "`lance_explorer/language_models`. Generated code sets "
            "`LANCE_LANGUAGE_MODEL_HOME`."
        )
        st.download_button(
            "Download Jieba models (.tar.gz)",
            data=language_model_archive_bytes("jieba_default"),
            file_name=language_model_archive_name("jieba_default"),
            mime="application/gzip",
            icon=":material/download:",
            key="indexes-fts-inline-jieba-download",
            help="Applies only to the Jieba base tokenizer.",
        )
    if str(base_tokenizer).startswith("lindera/"):
        st.warning(
            "Lindera dictionaries are not bundled or downloadable from this app. Supply the "
            "compiled dictionary externally and set `LANCE_LANGUAGE_MODEL_HOME` plus "
            "`LINDERA_CONFIG_PATH` before creating or querying this index.",
            icon=":material/warning:",
        )
    return config_options


def _recommended_partitions(index_type: str, row_count: int) -> int:
    divisor = 1_048_576 if index_type in _HNSW_INDEX_TYPES else 4_096
    return max(1, row_count // divisor)


def _vector_dimension(data_type) -> int | None:
    return int(data_type.list_size) if hasattr(data_type, "list_size") else None


def _raw_vector_size_text(dimension: int | None) -> str:
    if not dimension:
        return "Raw float32 vector payload is approximately dimension x 4 bytes per row."
    bytes_per_vector = dimension * 4
    return (
        f"This field appears to be {dimension}-dimensional, so the raw float32 vector payload "
        f"is roughly {bytes_per_vector:,} bytes per row before index metadata."
    )


def _vector_config_controls(index_type: str, row_count: int, data_type) -> dict[str, object]:
    dimension = _vector_dimension(data_type)
    with st.expander("Vector index concepts", expanded=True, icon=":material/info:"):
        st.markdown(
            "IVF is **Inverted File** partitioning: vectors are grouped before search so "
            "queries probe likely partitions instead of scanning every row."
        )
        st.markdown(
            "HNSW is **Hierarchical Navigable Small World** graph search. In LanceDB, the "
            "IVF+HNSW variants partition first, then search an HNSW graph inside selected "
            "partitions."
        )
        st.markdown(
            "PQ is **Product Quantization**, SQ is **Scalar Quantization**, and RQ is "
            "**RaBitQ Quantization**. Quantization shrinks indexes and can speed search, but "
            "it trades away some recall."
        )
        st.caption(_raw_vector_size_text(dimension))
        st.dataframe(pd.DataFrame(_VECTOR_GUIDANCE_ROWS), width="stretch", hide_index=True)
        st.caption(
            "Filtered vector searches often favor IVF_RQ or IVF_PQ because HNSW-backed IVF "
            "indexes can show higher latency variance under selective metadata filters. For "
            "recall testing, compare indexed results against a sampled flat scan before choosing "
            "final nprobes, ef, or refine_factor values."
        )
        st.caption(
            "Operational note: in LanceDB OSS, index creation and updates are manual. After "
            "writes, index statistics can show unindexed rows until you run Optimize. Queries "
            "can temporarily fall back to brute-force search for unindexed rows; fast_search "
            "can skip those rows when latency matters more than completeness."
        )

    first, second = st.columns(2)
    with first:
        distance_type = st.selectbox(
            "Distance type",
            ("l2", "cosine", "dot"),
            key=f"vector_{index_type}_distance_type",
            help=_VECTOR_HELP["distance_type"],
        )
        partition_mode = st.selectbox(
            "Partitioning",
            ("Set number of partitions", "Let Lance choose", "Target partition size"),
            key=f"vector_{index_type}_partition_mode",
            help=_VECTOR_HELP["partition_mode"],
        )
        config_options: dict[str, object] = {"distance_type": distance_type}
        if partition_mode == "Set number of partitions":
            num_partitions = st.number_input(
                "Number of partitions",
                min_value=1,
                max_value=1_000_000,
                value=_recommended_partitions(index_type, row_count),
                key=f"vector_{index_type}_num_partitions",
                help=_VECTOR_HELP["num_partitions"],
            )
            config_options["num_partitions"] = int(num_partitions)
        elif partition_mode == "Target partition size":
            target_partition_size = st.number_input(
                "Target partition size",
                min_value=1,
                max_value=10_000_000,
                value=4_096,
                key=f"vector_{index_type}_target_partition_size",
                help=_VECTOR_HELP["target_partition_size"],
            )
            config_options["target_partition_size"] = int(target_partition_size)

        max_iterations = st.number_input(
            "Max training iterations",
            min_value=1,
            max_value=1_000,
            value=50,
            key=f"vector_{index_type}_max_iterations",
            help=_VECTOR_HELP["max_iterations"],
        )
        sample_rate = st.number_input(
            "Training sample rate",
            min_value=1,
            max_value=10_000,
            value=256,
            key=f"vector_{index_type}_sample_rate",
            help=_VECTOR_HELP["sample_rate"],
        )
        config_options["max_iterations"] = int(max_iterations)
        config_options["sample_rate"] = int(sample_rate)
        st.caption(
            "Training iterations apply while Lance trains IVF centroids/quantizers from a "
            "sample of existing vectors. Inserts do not continually retrain centroids; run "
            "Optimize in OSS to fold newly written rows into existing indexes."
        )

    with second:
        if index_type in _PQ_INDEX_TYPES:
            recommended_sub_vectors = max(1, dimension // 8) if dimension else 8
            num_sub_vectors = st.number_input(
                "Product-quantization sub-vectors",
                min_value=1,
                max_value=4_096,
                value=recommended_sub_vectors,
                key=f"vector_{index_type}_num_sub_vectors",
                help=_VECTOR_HELP["num_sub_vectors"],
            )
            pq_bits = st.number_input(
                "Product-quantization bits",
                min_value=1,
                max_value=16,
                value=8,
                key=f"vector_{index_type}_num_bits",
                help=_VECTOR_HELP["num_bits"],
            )
            config_options["num_sub_vectors"] = int(num_sub_vectors)
            config_options["num_bits"] = int(pq_bits)

        if index_type in _RQ_INDEX_TYPES:
            rq_bits = st.number_input(
                "RaBitQ bits",
                min_value=1,
                max_value=8,
                value=1,
                key=f"vector_{index_type}_rq_num_bits",
                help=_VECTOR_HELP["num_bits"],
            )
            config_options["num_bits"] = int(rq_bits)

        if index_type in _HNSW_INDEX_TYPES:
            hnsw_m = st.number_input(
                "HNSW graph degree",
                min_value=2,
                max_value=256,
                value=20,
                key=f"vector_{index_type}_m",
                help=_VECTOR_HELP["m"],
            )
            ef_construction = st.number_input(
                "HNSW construction candidates",
                min_value=10,
                max_value=10_000,
                value=300,
                key=f"vector_{index_type}_ef_construction",
                help=_VECTOR_HELP["ef_construction"],
            )
            config_options["m"] = int(hnsw_m)
            config_options["ef_construction"] = int(ef_construction)

        if index_type in _ACCELERATOR_INDEX_TYPES:
            st.caption(
                "GPU accelerator setup: install a PyTorch build that can see your device, then "
                "enter `cuda` for NVIDIA CUDA on Linux/Windows or `mps` for Apple Silicon. "
                "If LanceDB raises a Torch/CUDA error, the Python environment does not have a "
                "matching GPU-enabled PyTorch build. CPU indexing is used when this is blank."
            )
            accelerator = st.text_input(
                "Accelerator (optional)",
                placeholder="cuda or mps",
                key=f"vector_{index_type}_accelerator",
                help=_VECTOR_HELP["accelerator"],
            )
            if accelerator.strip():
                config_options["accelerator"] = accelerator.strip()

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

    st.subheader("FTS language models")
    show_language_model_downloads(expanded=True, key_prefix="indexes-fts")

    st.subheader("Create index", help=help_text("create_index"))
    with st.popover("Index type guide", icon=":material/info:"):
        for index_definition in available_index_definitions():
            st.markdown(f"**{index_definition.label}** - {index_definition.description}")
        st.caption(
            "After writes, Optimize folds new rows into existing indexes. Vector index "
            "build/update cost depends heavily on partitioning, quantization, and HNSW graph "
            "settings."
        )

    column_names = schema.names
    selected_column = st.selectbox("Column", column_names)
    field = schema.field(selected_column)
    st.caption(
        f"Detected Arrow type: `{field.type}`. Available index types are filtered by this type."
    )
    definitions = [
        definition
        for definition in compatible_index_definitions(field.type)
        if index_type_supported_by_installed_lancedb(definition.key)
    ]
    if not definitions:
        st.warning(f"No registered index type supports {field.type}.")
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
        definition = next(item for item in definitions if item.key == selected_type)
        config_options: dict[str, object] = {}
        if selected_type == "FTS":
            config_options = _fts_config_controls()
        elif definition.category == "vector":
            config_options = _vector_config_controls(
                selected_type,
                int(snapshot.get("row_count") or 0),
                field.type,
            )

        show_code_export(
            "create_index",
            {
                "table_uri": table_uri,
                "column": selected_column,
                "index_type": selected_type,
                "config_class": definition.class_name,
                "config_options": config_options,
                "needs_language_model_home": fts_uses_packaged_model(config_options),
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
