from __future__ import annotations

import pandas as pd
import streamlit as st

from lance_explorer.config import AppConfig
from lance_explorer.healthcheck import HealthFinding, analyze_health
from lance_explorer.scaling_planner import (
    DEFAULT_MAX_BATCH_BYTES,
    DOCUMENTED,
    EXPLORER_HEURISTIC,
    LOAD_FREQUENT,
    LOAD_OCCASIONAL,
    LOAD_ONE_TIME,
    LOAD_REGULAR,
    SOURCE_EXISTING_LANCE,
    SOURCE_FILES,
    SOURCE_OTHER,
    SOURCE_TRINO,
    TRANSFORM_CUSTOM,
    TRANSFORM_NONE,
    TRANSFORM_SQL,
    VECTOR_DTYPES,
    MiB,
    PlannerInputs,
    Range,
    format_int_range,
    human_bytes,
    plan_scaling,
)
from lance_explorer.ui.cache import cached_health_snapshot
from lance_explorer.ui.components.code_export import show_code_export
from lance_explorer.ui.components.common import template_directory

_SOURCE_OPTIONS = (SOURCE_EXISTING_LANCE, SOURCE_FILES, SOURCE_TRINO, SOURCE_OTHER)
_TRANSFORM_OPTIONS = (TRANSFORM_NONE, TRANSFORM_SQL, TRANSFORM_CUSTOM)
_LOAD_OPTIONS = (LOAD_ONE_TIME, LOAD_OCCASIONAL, LOAD_REGULAR, LOAD_FREQUENT)
_REGION_OPTIONS = {
    "unknown": "Unknown / not sure",
    "same-region": "Same AWS region",
    "cross-region": "Cross-region",
}


def _provenance(value: Range | str) -> str:
    provenance = value if isinstance(value, str) else value.provenance
    if provenance == DOCUMENTED:
        return "Documented"
    if provenance == EXPLORER_HEURISTIC:
        return "Explorer heuristic"
    return "Derived"


def _metric(
    label: str,
    value: str,
    provenance: Range | str,
    help_text: str,
    warning: str | None = None,
) -> None:
    displayed_value = f"{value} ⚠" if warning else value
    st.metric(label, displayed_value, help=warning)
    st.caption(f"{_provenance(provenance)}. {help_text}")


def _workflow_text(steps: list[str]) -> str:
    return " -> ".join(steps)


def _render_required_inputs() -> dict[str, object]:
    st.subheader("Dataset")
    row_count = st.number_input(
        "Rows",
        min_value=1,
        value=100_000_000,
        step=1_000_000,
        help="Total rows to ingest or plan around.",
    )
    average_row_known = st.checkbox(
        "I know the average complete row size",
        help=(
            "Include vector, text, scalar metadata, and other record payload bytes. "
            "This materially improves fragment-size and memory estimates."
        ),
    )
    average_row_bytes = None
    if average_row_known:
        average_row_bytes = st.number_input(
            "Average complete row size (bytes)",
            min_value=1,
            value=4096,
            step=128,
        )
    source_type = st.selectbox("Source", _SOURCE_OPTIONS, index=1)
    transformation_type = st.selectbox("Transformation type", _TRANSFORM_OPTIONS)
    load_pattern = st.selectbox("Load pattern", _LOAD_OPTIONS)

    st.subheader("Compute")
    workers_col, cores_col, ram_col = st.columns(3)
    with workers_col:
        spark_workers = st.number_input("Spark workers", min_value=1, value=3, step=1)
    with cores_col:
        spark_cores = st.number_input("Cores / worker", min_value=1, value=16, step=1)
    with ram_col:
        spark_ram = st.number_input("RAM GiB / worker", min_value=0.5, value=64.0, step=1.0)

    st.subheader("Indexes")
    fts_col, vector_col = st.columns(2)
    with fts_col:
        has_fts = st.checkbox("Full-text search")
    with vector_col:
        has_vector = st.checkbox("Vector index", value=True)

    vector_dimension = None
    vector_dtype = "float32"
    if has_vector:
        dim_col, dtype_col = st.columns(2)
        with dim_col:
            vector_dimension = st.number_input("Vector dimension", min_value=1, value=1536, step=1)
        with dtype_col:
            vector_dtype = st.selectbox("Vector datatype", tuple(VECTOR_DTYPES), index=0)

    return {
        "row_count": int(row_count),
        "average_row_bytes": float(average_row_bytes) if average_row_bytes else None,
        "source_type": source_type,
        "transformation_type": transformation_type,
        "spark_workers": int(spark_workers),
        "spark_cores_per_worker": int(spark_cores),
        "spark_ram_gib_per_worker": float(spark_ram),
        "has_fts": has_fts,
        "has_vector_index": has_vector,
        "vector_dimension": int(vector_dimension) if vector_dimension else None,
        "vector_dtype": vector_dtype,
        "load_pattern": load_pattern,
    }


def _render_advanced_inputs() -> dict[str, object]:
    with st.expander("Advanced", icon=":material/tune:"):
        trino_col, trino_core_col = st.columns(2)
        with trino_col:
            trino_workers_enabled = st.checkbox("Include Trino worker count")
            trino_workers = (
                st.number_input("Trino workers", min_value=1, value=3, step=1)
                if trino_workers_enabled
                else None
            )
        with trino_core_col:
            trino_cores = (
                st.number_input("Trino cores / worker", min_value=1, value=16, step=1)
                if trino_workers_enabled
                else None
            )

        spark_col, batch_col = st.columns(2)
        with spark_col:
            executors_per_worker = st.number_input(
                "Executors / Spark worker",
                min_value=1,
                value=1,
                step=1,
                help="Used only to express the S3 concurrency benchmark range per executor.",
            )
            spark_task_cpus = st.number_input("spark.task.cpus", min_value=1, value=1, step=1)
        with batch_col:
            override_batch = st.checkbox("Override max_batch_bytes")
            max_batch_mib = st.number_input(
                "max_batch_bytes (MiB)",
                min_value=1,
                value=DEFAULT_MAX_BATCH_BYTES // MiB,
                step=16,
                disabled=not override_batch,
            )

        s3_relationship = st.selectbox(
            "S3 region relationship",
            tuple(_REGION_OPTIONS),
            format_func=_REGION_OPTIONS.get,
        )
        existing_fragment_count = st.number_input(
            "Existing Lance fragment count (optional context)",
            min_value=0,
            value=0,
            step=1,
        )

        phrase_search = st.checkbox("Phrase search required")
        metric = st.selectbox("Desired vector metric", ("l2", "cosine", "dot"))
        preferred_index_type = st.selectbox("Preferred vector index type", ("IVF_PQ", "IVF_FLAT"))

        queued = st.checkbox(
            "Enable experimental queued write buffer in this estimate",
            help=(
                "Lance Spark documents this as experimental; this planner never enables "
                "it by default."
            ),
        )
        queue_depth = st.number_input(
            "Queued buffer depth",
            min_value=1,
            value=2,
            step=1,
            disabled=not queued,
        )

    return {
        "trino_workers": int(trino_workers) if trino_workers else None,
        "trino_cores_per_worker": int(trino_cores) if trino_cores else None,
        "executors_per_spark_worker": int(executors_per_worker),
        "spark_task_cpus": int(spark_task_cpus),
        "s3_region_relationship": s3_relationship,
        "existing_fragment_count": int(existing_fragment_count) or None,
        "phrase_search_required": phrase_search,
        "desired_vector_metric": metric,
        "preferred_index_type": preferred_index_type,
        "override_max_batch_bytes": int(max_batch_mib * MiB) if override_batch else None,
        "use_queued_write_buffer": queued,
        "queue_depth": int(queue_depth),
    }


def _render_workflow(result) -> None:
    st.subheader("Recommended Workflow")
    ingest_label = result.engine.ingestion_engine
    if result.engine.fts_engine or result.engine.vector_engine:
        ingest_label = f"{ingest_label} ingestion, Spark indexing"
    st.markdown(f"**{ingest_label}**")
    st.caption(result.engine.ingestion_reason)
    st.caption(_workflow_text(result.engine.workflow))
    st.markdown("**Source path**")
    st.caption(result.engine.source_strategy)
    st.markdown("**Transformation placement**")
    st.caption(result.engine.transformation_strategy)
    st.markdown("**Compute effect**")
    st.caption(result.engine.compute_strategy)


def _render_load_strategy(result) -> None:
    st.subheader("Recommended Load Approach")
    st.markdown(f"**Pattern: {result.load.pattern.capitalize()}**")
    st.write(result.load.recommended_approach)
    if result.load.buffered_append_rows:
        _metric(
            "Buffered rows / append",
            format_int_range(result.load.buffered_append_rows),
            result.load.buffered_append_rows,
            "Accumulate enough rows to avoid creating undersized fragments on every commit.",
        )

    st.markdown("**Write cadence**")
    st.write(result.load.write_strategy)
    st.markdown("**Compaction**")
    st.write(result.load.compaction_strategy)
    st.markdown("**Index maintenance**")
    st.write(result.load.index_strategy)
    st.markdown("**Write-amplification control**")
    st.write(result.load.write_amplification_strategy)
    st.markdown("**Operational tips**")
    for tip in result.load.operational_tips:
        st.markdown(f"- {tip}")


def _render_core_results(result) -> None:
    first, second, third = st.columns(3)
    with first:
        _metric(
            "Rows / fragment",
            format_int_range(result.fragments.rows_per_fragment),
            result.fragments.rows_per_fragment,
            result.fragments.row_size_note,
        )
    with second:
        _metric(
            "Fragments",
            format_int_range(result.fragments.count),
            result.fragments.count,
            f"Representative planning value: ~{result.fragments.target_count:,}.",
            result.concerns.fragments,
        )
    with third:
        if result.engine.ingestion_engine == "Spark":
            _metric(
                "Spark write tasks",
                format_int_range(result.spark.write_tasks, approximate=False),
                result.spark.write_tasks,
                "Balances Spark's 2-3 tasks/core guidance against desired Lance fragments.",
                result.concerns.spark_write_tasks,
            )
        else:
            _metric(
                "Ingestion path",
                "Trino SQL",
                DOCUMENTED,
                "Trino schedules CTAS or INSERT SELECT splits; Spark task sizing is not applied.",
            )

    spark_col, s3_col = st.columns(2)
    with spark_col:
        if result.engine.ingestion_engine == "Spark":
            st.markdown("**Spark ingestion**")
            st.caption(f"Total cores: {result.spark.total_cores:,}")
            st.caption(
                f"Approximate concurrent task slots: {result.spark.concurrent_task_slots:,}"
            )
            st.caption(
                "Stage task-count target: "
                f"{format_int_range(result.spark.stage_task_target, approximate=False)}"
            )
            _metric(
                "Arrow memory / worker",
                f"{human_bytes(result.spark.batch_memory_upper_bound)} "
                f"({result.spark.batch_ram_fraction:.0%})",
                EXPLORER_HEURISTIC,
                "Upper-bound estimate from simultaneous tasks and max_batch_bytes.",
                result.concerns.arrow_memory,
            )
            if result.spark.queued_arrow_memory_per_worker is not None:
                _metric(
                    "Queued memory / worker",
                    f"{human_bytes(result.spark.queued_arrow_memory_per_worker)} "
                    f"({result.spark.queued_ram_fraction:.0%})",
                    EXPLORER_HEURISTIC,
                    "Upper-bound queue exposure as a share of worker RAM.",
                    result.concerns.queued_memory,
                )
        else:
            st.markdown("**Trino ingestion**")
            st.caption(result.engine.compute_strategy)
            if result.engine.fts_engine or result.engine.vector_engine:
                st.caption(
                    f"Spark remains reserved for indexing with {result.spark.total_cores:,} "
                    "configured cores."
                )
    with s3_col:
        st.markdown("**S3**")
        st.caption(f"Start upload concurrency: {result.s3.upload_concurrency_start}")
        st.caption(
            f"Benchmark toward: {result.s3.upload_concurrency_benchmark_high} / "
            f"{result.s3.benchmark_scope} based on {result.s3.basis}"
        )
        st.caption(
            f"Initial multipart size default: {result.s3.initial_upload_size_mb} MB. "
            "Larger values can reduce API overhead but consume more memory."
        )


def _render_index_results(result) -> None:
    fts_col, vector_col = st.columns(2)
    with fts_col:
        st.markdown("**FTS**")
        if not result.fts:
            st.caption("Not requested.")
        else:
            _metric(
                "FTS segments",
                format_int_range(result.fts.segments, approximate=False),
                result.fts.segments,
                "Uses an Explorer heuristic of roughly 2-4 segments per Spark worker, "
                "clamped by fragments and cores.",
            )
            _metric(
                "Relative FTS fan-out",
                format_int_range(result.fts.fanout_indicator),
                result.fts.fanout_indicator,
                "Fragment count multiplied by physical FTS segments; useful for comparison only.",
                result.concerns.fts_fanout,
            )
            st.caption(
                "Build after bulk ingest. More segments can improve build parallelism "
                "but increase query fan-out."
            )

    with vector_col:
        st.markdown("**Vector Index**")
        if not result.vector:
            st.caption("Not requested.")
        else:
            _metric(
                "Vector segments",
                format_int_range(result.vector.segments, approximate=False),
                result.vector.segments,
                "Spark schedules work while PyLance builds uncommitted physical segments.",
            )
            st.caption(
                "Rows / vector segment: "
                f"{format_int_range(result.vector.rows_per_segment)}"
            )
            st.caption(
                "IVF partitions / segment: "
                f"{format_int_range(result.vector.ivf_partitions_per_segment)}"
            )
            if result.vector.pq_subvectors:
                st.caption(
                    "PQ subvectors: "
                    f"{format_int_range(result.vector.pq_subvectors, approximate=False)}"
                )
            else:
                st.caption("PQ subvectors: lower-confidence recommendation")
            st.caption(f"Raw vector payload only: {human_bytes(result.vector.raw_vector_bytes)}")
            if result.vector.pq_index_bytes:
                st.caption(
                    "Approximate PQ index payload: "
                    f"{human_bytes(result.vector.pq_index_bytes.low)}-"
                    f"{human_bytes(result.vector.pq_index_bytes.high)}"
                )


def _range_midpoint(value: Range) -> int:
    return int(round((value.low + value.high) / 2))


def _render_code_templates(config: AppConfig, inputs: PlannerInputs, result) -> None:
    st.subheader("Starter Code")
    recommended_engine = result.engine.ingestion_engine
    common_context = {
        "target_rows_per_fragment": result.fragments.target_rows,
        "transformation_type": inputs.transformation_type,
    }
    buffered_rows = result.load.buffered_append_rows
    buffered_low = int(buffered_rows.low) if buffered_rows else result.fragments.target_rows
    buffered_high = int(buffered_rows.high) if buffered_rows else result.fragments.target_rows
    write_tasks = int(result.spark.write_tasks.high)
    if inputs.load_pattern in {LOAD_REGULAR, LOAD_FREQUENT}:
        write_tasks = max(
            1,
            min(
                write_tasks,
                (buffered_high + result.fragments.target_rows - 1)
                // result.fragments.target_rows,
            ),
        )

    vector = result.vector
    pq_subvectors = None
    if (
        vector
        and inputs.preferred_index_type == "IVF_PQ"
        and vector.pq_subvectors is not None
    ):
        pq_subvectors = int(vector.pq_subvectors.low)

    show_code_export(
        "scaling_spark",
        {
            **common_context,
            "source_type": inputs.source_type,
            "load_pattern": inputs.load_pattern,
            "buffered_append_low": buffered_low,
            "buffered_append_high": buffered_high,
            "write_tasks": write_tasks,
            "include_max_batch_bytes": inputs.override_max_batch_bytes is not None,
            "max_batch_bytes": result.spark.max_batch_bytes,
            "write_mode": "overwrite" if inputs.load_pattern == LOAD_ONE_TIME else "append",
            "queued_write_buffer": inputs.use_queued_write_buffer,
            "queue_depth": inputs.queue_depth,
            "has_fts": inputs.has_fts,
            "fts_segments": int(result.fts.segments.high) if result.fts else 1,
            "phrase_search_required": inputs.phrase_search_required,
            "has_vector_index": inputs.has_vector_index,
            "vector_index_type": inputs.preferred_index_type,
            "vector_segments": int(vector.segments.high) if vector else 1,
            "vector_partitions": (
                _range_midpoint(vector.ivf_partitions_per_segment) if vector else 1
            ),
            "pq_subvectors": pq_subvectors,
            "vector_metric": inputs.desired_vector_metric,
        },
        template_directory=template_directory(config),
        label=(
            "Spark ingestion (recommended)"
            if recommended_engine == "Spark"
            else "Spark ingestion alternative"
        ),
    )
    show_code_export(
        "scaling_trino",
        {
            **common_context,
            "append_mode": inputs.load_pattern != LOAD_ONE_TIME,
            "load_pattern": inputs.load_pattern,
            "buffered_append_low": buffered_low,
            "buffered_append_high": buffered_high,
            "include_target_rows_setting": (
                result.fragments.target_rows != 1_000_000
            ),
        },
        template_directory=template_directory(config),
        label=(
            "Trino SQL ingestion (recommended)"
            if recommended_engine == "Trino"
            else "Trino SQL ingestion alternative"
        ),
    )

    show_code_export(
        "scaling_python",
        {
            **common_context,
            "recurring_load": inputs.load_pattern != LOAD_ONE_TIME,
            "load_pattern": inputs.load_pattern,
            "has_indexes": inputs.has_fts or inputs.has_vector_index,
        },
        template_directory=template_directory(config),
        label="Python maintenance",
    )


def _render_details(result) -> None:
    with st.expander("Explanation and provenance", icon=":material/info:"):
        st.markdown(
            "This planner gives a sensible first configuration, not a benchmark result. "
            "Runtime depends on data distribution, object-store behavior, network, executor "
            "layout, schema width, and index quality targets."
        )
        rows = [
            {
                "Recommendation": "Lance fragment sizing",
                "Provenance": "Documented + Explorer heuristic",
                "Basis": "[LANCE-FRAGMENTS]: 1M rows/fragment default, 10-100 GB upper range.",
            },
            {
                "Recommendation": "Spark write tasks",
                "Provenance": "Documented + Explorer heuristic",
                "Basis": "[SPARK-TUNING] 2-3 tasks/core, capped by target fragment count.",
            },
            {
                "Recommendation": "Arrow batch memory",
                "Provenance": "Documented + Explorer heuristic",
                "Basis": (
                    "[LANCE-SPARK-PERF] max_batch_bytes default is 256 MiB; "
                    "25% RAM warning is Explorer-specific."
                ),
            },
            {
                "Recommendation": "Distributed FTS",
                "Provenance": "Documented + Explorer heuristic",
                "Basis": (
                    "[LANCE-SPARK-INDEX] supports num_segments; 2-4 segments/node "
                    "is Explorer-specific."
                ),
            },
            {
                "Recommendation": "Distributed vector indexing",
                "Provenance": "Documented + Derived",
                "Basis": (
                    "[LANCE-DISTRIBUTED-INDEX] external schedulers build uncommitted "
                    "segments and commit them together."
                ),
            },
            {
                "Recommendation": "IVF/PQ sizing",
                "Provenance": "Documented + Derived",
                "Basis": "[LANCEDB-IVFPQ], [LANCE-VECTOR-QUICKSTART], [LANCE-PERF-INDEX].",
            },
            {
                "Recommendation": "S3 concurrency",
                "Provenance": "Documented",
                "Basis": (
                    "[LANCE-SPARK-PERF] default upload concurrency 10; "
                    "[AWS-S3-PERF] parallel connections and same-region compute/storage."
                ),
            },
            {
                "Recommendation": "Recurring append maintenance",
                "Provenance": "Documented + Explorer heuristic",
                "Basis": (
                    "[LANCE-PERFORMANCE]: appends create fragments; compact by threshold, "
                    "defer index remap with FRI, and incrementally optimize index coverage."
                ),
            },
        ]
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        if result.vector:
            st.markdown("**Independent vector-index models**")
            st.caption(
                "Each physical segment can train its own IVF/PQ model. This keeps orchestration "
                "simple and is valid because Lance searches each segment with that "
                "segment's model. "
                "Physical merging later is easier when segments share compatible models."
            )
            st.caption(
                "Estimated training vectors / segment: "
                f"{format_int_range(result.vector.training_vectors_per_segment)}"
            )


def _render_warnings(result) -> None:
    if result.warnings:
        st.subheader("Warnings")
        for warning in result.warnings:
            st.warning(warning, icon=":material/warning:")
    st.subheader("Assumptions")
    for assumption in result.assumptions:
        st.caption(f"- {assumption}")


def _render_recommendations(config: AppConfig) -> None:
    input_col, result_col = st.columns([0.38, 0.62], gap="large")
    with input_col:
        required = _render_required_inputs()
        advanced = _render_advanced_inputs()
        inputs = PlannerInputs(**required, **advanced)

    with result_col:
        try:
            result = plan_scaling(inputs)
        except ValueError as exc:
            st.error(str(exc))
            return
        _render_workflow(result)
        _render_core_results(result)
        _render_load_strategy(result)
        _render_index_results(result)
        _render_code_templates(config, inputs, result)
        _render_details(result)
        _render_warnings(result)


def _health_fragment_metrics(snapshot: dict[str, object]) -> dict[str, int | float]:
    fragments = list(snapshot.get("fragments") or [])
    statistics = snapshot.get("statistics") or {}
    fragment_statistics = statistics.get("fragment_stats") or {}
    physical_rows = sum(int(fragment.get("physical_rows") or 0) for fragment in fragments)
    deleted_rows = sum(int(fragment.get("deleted_rows") or 0) for fragment in fragments)
    live_rows = int(snapshot.get("row_count") or 0)
    fragment_count = len(fragments) or int(fragment_statistics.get("num_fragments") or 0)
    small_fragments = sum(
        0 < int(fragment.get("live_rows") or 0) < 250_000 for fragment in fragments
    )
    return {
        "physical_rows": physical_rows,
        "deleted_rows": deleted_rows,
        "deletion_ratio": deleted_rows / physical_rows if physical_rows else 0.0,
        "fragment_count": fragment_count,
        "average_live_rows": live_rows / fragment_count if fragment_count else 0.0,
        "small_fragments": small_fragments,
        "reported_small_fragments": int(fragment_statistics.get("num_small_fragments") or 0),
        "max_fragment_bytes": max(
            (int(fragment.get("data_bytes") or 0) for fragment in fragments), default=0
        ),
    }


def _health_index_rows(snapshot: dict[str, object]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index in snapshot.get("indexes") or []:
        statistics = index.get("statistics") or {}
        indexed = int(statistics.get("num_indexed_rows", index.get("num_indexed_rows", 0)) or 0)
        unindexed = int(
            statistics.get("num_unindexed_rows", index.get("num_unindexed_rows", 0)) or 0
        )
        total = indexed + unindexed
        segments = index.get("num_segments") or statistics.get("num_indices")
        rows.append(
            {
                "Index": str(index.get("name") or "(unnamed)"),
                "Type": str(index.get("index_type") or statistics.get("index_type") or "-"),
                "Columns": ", ".join(str(column) for column in index.get("columns") or []),
                "Coverage": f"{indexed / total:.1%}" if total else "-",
                "Unindexed rows": unindexed,
                "Segments": str(segments) if segments is not None else "-",
                "Size": human_bytes(int(index.get("size_bytes") or 0))
                if index.get("size_bytes")
                else "-",
            }
        )
    return rows


def _health_schema_rows(snapshot: dict[str, object]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for field in snapshot.get("schema_fields") or []:
        dimension = field.get("vector_dimension")
        rows.append(
            {
                "Column": str(field.get("name") or "-"),
                "Type": str(field.get("type") or "-"),
                "Vector storage": str(field.get("vector_storage") or "-"),
                "Dimension": str(dimension) if dimension is not None else "-",
                "Blob": "yes" if field.get("is_blob") else "no",
            }
        )
    return rows


def _render_health_finding(finding: HealthFinding) -> None:
    message = f"**{finding.title}**\n\n{finding.evidence}"
    if finding.severity == "critical":
        st.error(message, icon=":material/error:")
    elif finding.severity == "warning":
        st.warning(message, icon=":material/warning:")
    else:
        st.info(message, icon=":material/info:")
    st.markdown(f"**Why it matters:** {finding.impact}")
    st.markdown(f"**Next step:** {finding.next_step}")
    st.caption(f"Basis: {finding.basis}")


def _render_health_details(snapshot: dict[str, object]) -> None:
    fragment_metrics = _health_fragment_metrics(snapshot)
    statistics = snapshot.get("statistics") or {}
    st.subheader("Measured Signals")
    layout_rows = [
        {
            "Signal": "Table data size",
            "Value": human_bytes(int(statistics.get("total_bytes") or 0)),
        },
        {"Signal": "Physical rows", "Value": f"{fragment_metrics['physical_rows']:,.0f}"},
        {"Signal": "Deleted rows", "Value": f"{fragment_metrics['deleted_rows']:,.0f}"},
        {
            "Signal": "Deletion ratio",
            "Value": f"{fragment_metrics['deletion_ratio']:.1%}",
        },
        {
            "Signal": "Fragments below 250K live rows",
            "Value": f"{fragment_metrics['small_fragments']:,.0f}",
        },
        {
            "Signal": "Lance-reported small fragments",
            "Value": f"{fragment_metrics['reported_small_fragments']:,.0f}",
        },
        {
            "Signal": "Largest fragment data files",
            "Value": human_bytes(int(fragment_metrics["max_fragment_bytes"])),
        },
        {"Signal": "Versions", "Value": f"{len(snapshot.get('versions') or []):,}"},
        {"Signal": "Tags", "Value": f"{len(snapshot.get('tags') or []):,}"},
        {
            "Signal": "Manifest paths",
            "Value": "V2"
            if snapshot.get("uses_v2_manifest_paths") is True
            else "Legacy"
            if snapshot.get("uses_v2_manifest_paths") is False
            else "Unavailable",
        },
    ]
    st.dataframe(pd.DataFrame(layout_rows), width="stretch", hide_index=True)

    index_rows = _health_index_rows(snapshot)
    st.markdown("**Index coverage and fan-out**")
    if index_rows:
        st.dataframe(pd.DataFrame(index_rows), width="stretch", hide_index=True)
    else:
        st.caption("No user indexes are registered on this table.")

    schema_rows = _health_schema_rows(snapshot)
    st.markdown("**Schema signals**")
    st.dataframe(pd.DataFrame(schema_rows), width="stretch", hide_index=True)


def _render_healthcheck() -> None:
    st.subheader("Healthcheck")
    st.caption(
        "Read-only analysis of the selected table's latest version. The healthcheck reads "
        "metadata, fragment manifests, and index statistics; it does not scan table rows."
    )
    table_uri = str(st.session_state.get("selected_table_uri") or "")
    if not table_uri:
        st.info("Select a Lance table in Explorer to run its healthcheck.")
        return

    st.markdown(f"**Selected table:** `{table_uri}`")
    generations = dict(st.session_state.get("cache_generations") or {})
    if st.button("Refresh healthcheck", icon=":material/refresh:"):
        generations[table_uri] = int(generations.get(table_uri, 0)) + 1
        st.session_state.cache_generations = generations
    generation = int(generations.get(table_uri, 0))

    try:
        with st.spinner("Inspecting table metadata..."):
            snapshot = cached_health_snapshot(table_uri, generation)
    except Exception as exc:
        st.error(f"Unable to inspect table: {exc}")
        return

    report = analyze_health(snapshot)
    fragment_metrics = _health_fragment_metrics(snapshot)
    index_rows = _health_index_rows(snapshot)
    coverages = [
        float(row["Coverage"].rstrip("%")) / 100
        for row in index_rows
        if isinstance(row["Coverage"], str) and row["Coverage"].endswith("%")
    ]

    metric_columns = st.columns(6)
    metric_columns[0].metric(
        "Health score", "Incomplete" if report.inspection_errors else f"{report.score}/100"
    )
    metric_columns[1].metric("Rows", f"{int(snapshot.get('row_count') or 0):,}")
    metric_columns[2].metric("Fragments", f"{fragment_metrics['fragment_count']:,.0f}")
    metric_columns[3].metric(
        "Rows / fragment", f"{fragment_metrics['average_live_rows']:,.0f}"
    )
    metric_columns[4].metric("Deleted", f"{fragment_metrics['deletion_ratio']:.1%}")
    metric_columns[5].metric(
        "Lowest index coverage", f"{min(coverages):.1%}" if coverages else "-"
    )

    status_message = f"**{report.status}**"
    if report.status == "Critical":
        st.error(status_message, icon=":material/error:")
    elif report.status in {"Needs attention", "Incomplete"}:
        st.warning(status_message, icon=":material/warning:")
    elif report.status == "Healthy":
        st.success(status_message, icon=":material/check_circle:")
    else:
        st.info(status_message, icon=":material/info:")

    if report.inspection_errors:
        with st.expander("Incomplete inspection details", icon=":material/warning:"):
            for error in report.inspection_errors:
                st.write(f"- {error}")

    st.subheader("Prioritized Findings")
    if report.findings:
        for finding in report.findings:
            _render_health_finding(finding)
    else:
        st.success(
            "No material layout, deletion, index coverage, or vector-schema issues were "
            "identified from the available metadata.",
            icon=":material/check_circle:",
        )

    _render_health_details(snapshot)
    with st.expander("Method and thresholds", icon=":material/info:"):
        st.markdown(
            "The check combines documented Lance behavior with conservative Explorer "
            "thresholds. Workload-dependent observations are advisory; absence of an index "
            "is not treated as a failure unless the schema strongly resembles a vector-search "
            "table."
        )
        st.markdown(
            "References: [Lance performance guide](https://lance.org/guide/performance/), "
            "[table maintenance](https://lance.org/guide/read_and_write/#table-maintenance), "
            "[vector data types](https://lance.org/guide/data_types/"
            "#best-practices-for-vector-data), and [index diagnostics](https://lance.org/"
            "integrations/spark/operations/ddl/show-indexes/)."
        )


def render(config: AppConfig | None = None) -> None:
    """Render the distributed Lance ingestion and indexing planner."""

    config = config or AppConfig.from_env()

    st.title("Scaling Recommendations")
    st.caption(
        "Plan large-scale Lance ingestion and indexing with Spark, Trino, PyLance, and S3. "
        "The output is a starting range, not a performance prediction."
    )

    recommendations_tab, healthcheck_tab = st.tabs(
        ["Recommendations", "Healthcheck"],
        key="scaling-page-tabs",
        on_change="rerun",
    )
    if recommendations_tab.open:
        with recommendations_tab:
            _render_recommendations(config)
    if healthcheck_tab.open:
        with healthcheck_tab:
            _render_healthcheck()
