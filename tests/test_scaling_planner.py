import pytest

from lance_explorer.scaling_planner import (
    DEFAULT_MAX_BATCH_BYTES,
    DERIVED,
    DOCUMENTED,
    EXPLORER_HEURISTIC,
    LOAD_FREQUENT,
    LOAD_OCCASIONAL,
    LOAD_ONE_TIME,
    LOAD_REGULAR,
    SOURCE_EXISTING_LANCE,
    SOURCE_FILES,
    SOURCE_TRINO,
    TRANSFORM_CUSTOM,
    TRANSFORM_NONE,
    TRANSFORM_SQL,
    GiB,
    PlannerInputs,
    plan_scaling,
)


def _inputs(**overrides) -> PlannerInputs:
    values = {
        "row_count": 10_000_000,
        "source_type": SOURCE_FILES,
        "transformation_type": TRANSFORM_NONE,
        "spark_workers": 4,
        "spark_cores_per_worker": 8,
        "spark_ram_gib_per_worker": 64,
        "has_fts": False,
        "has_vector_index": False,
        "load_pattern": LOAD_ONE_TIME,
    }
    values.update(overrides)
    return PlannerInputs(**values)


def test_10m_rows_without_vectors_uses_default_fragment_range_and_capped_write_tasks() -> None:
    result = plan_scaling(_inputs())

    assert result.fragments.rows_per_fragment.low == 500_000
    assert result.fragments.rows_per_fragment.high == 1_000_000
    assert result.fragments.rows_per_fragment.provenance == EXPLORER_HEURISTIC
    assert result.fragments.count.low == 10
    assert result.fragments.count.high == 20
    assert result.spark.write_tasks.low == 10
    assert result.spark.write_tasks.high == 20
    assert result.vector is None


def test_100m_rows_1536d_float32_vectors_compute_raw_and_pq_storage() -> None:
    result = plan_scaling(
        _inputs(
            row_count=100_000_000,
            has_vector_index=True,
            vector_dimension=1536,
            vector_dtype="float32",
        )
    )

    assert result.vector is not None
    assert result.vector.bytes_per_vector == 1536 * 4
    assert result.vector.raw_vector_bytes == 614_400_000_000
    assert result.vector.pq_subvectors is not None
    assert result.vector.pq_subvectors.low == 96
    assert result.vector.pq_subvectors.high == 192
    assert result.vector.pq_subvectors.provenance == DOCUMENTED
    assert result.vector.pq_index_bytes is not None
    assert result.vector.pq_index_bytes.low == 100_000_000 * (96 + 8)
    assert result.vector.pq_index_bytes.high == 100_000_000 * (192 + 8)


def test_768d_float32_vectors_have_simd_friendly_pq_range() -> None:
    result = plan_scaling(
        _inputs(has_vector_index=True, vector_dimension=768, vector_dtype="float32")
    )

    assert result.vector is not None
    assert result.vector.pq_subvectors is not None
    assert result.vector.pq_subvectors.low == 48
    assert result.vector.pq_subvectors.high == 96


def test_vector_dimension_not_divisible_by_8_warns_and_skips_pq_size() -> None:
    result = plan_scaling(
        _inputs(has_vector_index=True, vector_dimension=770, vector_dtype="float32")
    )

    assert result.vector is not None
    assert result.vector.pq_subvectors is None
    assert result.vector.pq_index_bytes is None
    assert any("not SIMD-friendly" in warning for warning in result.warnings)


def test_wide_known_row_size_reduces_rows_per_fragment_below_1m() -> None:
    result = plan_scaling(_inputs(row_count=100_000_000, average_row_bytes=GiB))

    assert result.fragments.rows_per_fragment.high == 10
    assert result.fragments.rows_per_fragment.low == 5
    assert result.fragments.rows_per_fragment.provenance == EXPLORER_HEURISTIC
    assert result.fragments.count.low == 10_000_000
    assert result.fragments.count.high == 20_000_000


def test_very_small_dataset_caps_fragment_range_to_dataset_size() -> None:
    result = plan_scaling(_inputs(row_count=10_000))

    assert result.fragments.rows_per_fragment.low == 5_000
    assert result.fragments.rows_per_fragment.high == 10_000
    assert result.fragments.count.low == 1
    assert result.fragments.count.high == 2


def test_three_workers_by_16_cores_spark_targets() -> None:
    result = plan_scaling(
        _inputs(row_count=100_000_000, spark_workers=3, spark_cores_per_worker=16)
    )

    assert result.spark.total_cores == 48
    assert result.spark.concurrent_task_slots == 48
    assert result.spark.stage_task_target.low == 96
    assert result.spark.stage_task_target.high == 144
    assert result.spark.stage_task_target.provenance == DOCUMENTED


def test_fts_only_workload_returns_fts_plan_without_vector_plan() -> None:
    result = plan_scaling(_inputs(has_fts=True))

    assert result.fts is not None
    assert result.fts.segments.provenance == EXPLORER_HEURISTIC
    assert result.vector is None
    assert result.engine.fts_engine == "Spark distributed FTS"


def test_vector_only_workload_returns_vector_plan_without_fts_plan() -> None:
    result = plan_scaling(_inputs(has_vector_index=True, vector_dimension=1536))

    assert result.fts is None
    assert result.vector is not None
    assert result.engine.vector_engine == "Spark scheduler + PyLance distributed-index APIs"


def test_both_fts_and_vector_workload_returns_both_index_plans() -> None:
    result = plan_scaling(_inputs(has_fts=True, has_vector_index=True, vector_dimension=1536))

    assert result.fts is not None
    assert result.vector is not None
    assert "build FTS after bulk ingest" in result.engine.workflow
    assert "build vector index after bulk ingest" in result.engine.workflow


def test_sql_compatible_trino_source_prefers_trino_ingestion() -> None:
    result = plan_scaling(
        _inputs(source_type=SOURCE_TRINO, transformation_type=TRANSFORM_SQL, has_fts=True)
    )

    assert result.engine.ingestion_engine == "Trino"
    assert "Trino-accessible" in result.engine.ingestion_reason
    assert "CTAS or INSERT SELECT" in result.engine.source_strategy
    assert "Push SQL" in result.engine.transformation_strategy
    assert "Spark write-task sizing does not apply" in result.engine.compute_strategy
    assert result.s3.benchmark_scope == "Trino worker"
    assert result.engine.fts_engine == "Spark distributed FTS"


def test_trino_worker_cores_size_its_s3_concurrency_range() -> None:
    result = plan_scaling(
        _inputs(
            source_type=SOURCE_TRINO,
            transformation_type=TRANSFORM_SQL,
            trino_workers=5,
            trino_cores_per_worker=24,
            spark_workers=100,
            spark_cores_per_worker=100,
            spark_ram_gib_per_worker=1,
        )
    )

    assert result.s3.upload_concurrency_benchmark_high == 24
    assert result.s3.benchmark_scope == "Trino worker"
    assert result.concerns.spark_write_tasks is None
    assert result.concerns.arrow_memory is None


def test_custom_transformation_forces_spark_ingestion() -> None:
    result = plan_scaling(_inputs(source_type=SOURCE_TRINO, transformation_type=TRANSFORM_CUSTOM))

    assert result.engine.ingestion_engine == "Spark"
    assert "custom/programmatic" in result.engine.ingestion_reason
    assert "custom transform" in result.engine.source_strategy
    assert "retry-safe" in result.engine.transformation_strategy


def test_frequent_small_append_warning_is_emitted() -> None:
    result = plan_scaling(
        _inputs(load_pattern=LOAD_FREQUENT, has_vector_index=True, vector_dimension=768)
    )

    assert any("Frequent small appends" in warning for warning in result.warnings)
    assert result.load.buffered_append_rows is not None
    assert result.load.buffered_append_rows.low == 500_000
    assert result.load.buffered_append_rows.high == 750_000
    assert "queue or staging table" in result.load.write_strategy
    assert "defer_index_remap=True" in result.load.write_amplification_strategy
    assert "Decouple event arrival" in result.load.recommended_approach
    assert any("Never create one Lance append" in tip for tip in result.load.operational_tips)


def test_queued_buffer_memory_calculation_when_enabled() -> None:
    result = plan_scaling(
        _inputs(
            row_count=100_000_000,
            spark_workers=1,
            spark_cores_per_worker=16,
            spark_ram_gib_per_worker=8,
            use_queued_write_buffer=True,
            queue_depth=2,
        )
    )

    assert result.spark.max_batch_bytes == DEFAULT_MAX_BATCH_BYTES
    assert result.spark.write_tasks.high == 48
    assert result.spark.tasks_per_worker == 48
    assert result.spark.queued_arrow_memory_per_worker == 48 * 2 * DEFAULT_MAX_BATCH_BYTES
    assert result.spark.queued_ram_fraction == pytest.approx(3.0)
    assert result.concerns.arrow_memory is not None
    assert "exceeds worker RAM" in result.concerns.queued_memory
    assert any("queued-buffer memory" in warning for warning in result.warnings)


def test_derived_vector_ivf_uses_rows_per_independent_segment() -> None:
    result = plan_scaling(
        _inputs(
            row_count=100_000_000,
            spark_workers=4,
            spark_cores_per_worker=8,
            has_vector_index=True,
            vector_dimension=1536,
        )
    )

    assert result.vector is not None
    assert result.vector.segments.low == 8
    assert result.vector.segments.high == 16
    assert result.vector.ivf_partitions_per_segment.low == 2500
    assert result.vector.ivf_partitions_per_segment.high == 3536
    assert result.vector.ivf_partitions_per_segment.provenance == DERIVED


def test_one_time_load_avoids_unnecessary_recurring_maintenance() -> None:
    result = plan_scaling(_inputs(load_pattern=LOAD_ONE_TIME))

    assert result.load.buffered_append_rows is None
    assert "Skip routine compaction" in result.load.compaction_strategy
    assert "one bounded create or overwrite job" in result.load.recommended_approach
    assert "bulk ingest once" in result.engine.workflow


def test_occasional_batches_get_a_large_append_target() -> None:
    result = plan_scaling(_inputs(load_pattern=LOAD_OCCASIONAL))

    assert result.load.buffered_append_rows is not None
    assert result.load.buffered_append_rows.low == 750_000
    assert result.load.buffered_append_rows.high == 1_000_000
    assert "each delivery" in result.load.compaction_strategy
    assert any("stable batch identifier" in tip for tip in result.load.operational_tips)


def test_regular_batches_use_threshold_maintenance_and_incremental_indexes() -> None:
    result = plan_scaling(
        _inputs(
            load_pattern=LOAD_REGULAR,
            has_fts=True,
            has_vector_index=True,
            vector_dimension=768,
        )
    )

    assert result.load.buffered_append_rows is not None
    assert result.load.buffered_append_rows.low == 500_000
    assert result.load.buffered_append_rows.high == 1_000_000
    assert "not automatically after every batch" in result.load.compaction_strategy
    assert "durable staging boundary" in result.load.recommended_approach
    assert "FTS and vector" in result.load.index_strategy
    assert "optimize_indices" in result.load.index_strategy


def test_existing_lance_source_avoids_staging_rewrites() -> None:
    result = plan_scaling(_inputs(source_type=SOURCE_EXISTING_LANCE))

    assert "existing Lance fragments directly" in result.engine.source_strategy
    assert "rewriting unchanged columns" in result.engine.source_strategy


def test_exceptionally_large_fragment_and_task_counts_have_concern_indicators() -> None:
    fragment_result = plan_scaling(
        _inputs(row_count=100_000_000, average_row_bytes=GiB)
    )
    task_result = plan_scaling(
        _inputs(
            row_count=100_000_000_000,
            spark_workers=4_000,
            spark_cores_per_worker=1,
            average_row_bytes=4096,
        )
    )

    assert fragment_result.concerns.fragments is not None
    assert task_result.spark.write_tasks.high == 12_000
    assert task_result.concerns.spark_write_tasks is not None
