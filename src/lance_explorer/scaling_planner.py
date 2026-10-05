from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil, floor, sqrt
from typing import Literal

KiB = 1024
MiB = KiB**2
GiB = KiB**3
TiB = KiB**4

DOCUMENTED = "DOCUMENTED"
DERIVED = "DERIVED"
EXPLORER_HEURISTIC = "EXPLORER HEURISTIC"

SOURCE_EXISTING_LANCE = "existing Lance table"
SOURCE_FILES = "S3 / Parquet / files"
SOURCE_TRINO = "Trino-accessible SQL/table source"
SOURCE_OTHER = "other"

TRANSFORM_NONE = "none / copy"
TRANSFORM_SQL = "SQL-compatible"
TRANSFORM_CUSTOM = "custom / programmatic"

LOAD_ONE_TIME = "one-time bulk load"
LOAD_OCCASIONAL = "occasional large batch"
LOAD_REGULAR = "regular batch"
LOAD_FREQUENT = "frequent small appends"

VECTOR_DTYPES = {
    "float32": 4,
    "float16": 2,
    "bfloat16": 2,
    "int8": 1,
}

DEFAULT_FRAGMENT_ROWS = 1_000_000
UNKNOWN_ROW_FRAGMENT_LOW = 500_000
CONSERVATIVE_FRAGMENT_CEILING_BYTES = 10 * GiB
LARGE_DATASET_FRAGMENT_HIGH = 100_000_000
DEFAULT_MAX_BATCH_BYTES = 256 * MiB
DEFAULT_UPLOAD_CONCURRENCY = 10
DEFAULT_INITIAL_UPLOAD_SIZE_MB = 5
CONCERNING_FRAGMENT_COUNT = 50_000
CONCERNING_SPARK_TASK_COUNT = 10_000
CONCERNING_MEMORY_FRACTION = 0.25
CONCERNING_FTS_FANOUT = 1_000_000


@dataclass(frozen=True)
class Range:
    low: int | float
    high: int | float
    provenance: str = DERIVED


@dataclass(frozen=True)
class PlannerInputs:
    row_count: int
    source_type: str
    transformation_type: str
    spark_workers: int
    spark_cores_per_worker: int
    spark_ram_gib_per_worker: float
    has_fts: bool
    has_vector_index: bool
    load_pattern: str
    vector_dimension: int | None = None
    vector_dtype: str = "float32"
    average_row_bytes: float | None = None
    trino_workers: int | None = None
    trino_cores_per_worker: int | None = None
    executors_per_spark_worker: int | None = None
    spark_task_cpus: int = 1
    s3_region_relationship: Literal["unknown", "same-region", "cross-region"] = "unknown"
    existing_fragment_count: int | None = None
    phrase_search_required: bool = False
    desired_vector_metric: str = "l2"
    preferred_index_type: str = "IVF_PQ"
    override_max_batch_bytes: int | None = None
    use_queued_write_buffer: bool = False
    queue_depth: int = 2


@dataclass(frozen=True)
class EngineRecommendation:
    ingestion_engine: str
    ingestion_reason: str
    source_strategy: str
    transformation_strategy: str
    compute_strategy: str
    fts_engine: str | None
    vector_engine: str | None
    workflow: list[str]


@dataclass(frozen=True)
class LoadPlan:
    pattern: str
    recommended_approach: str
    buffered_append_rows: Range | None
    write_strategy: str
    compaction_strategy: str
    index_strategy: str
    write_amplification_strategy: str
    operational_tips: tuple[str, ...]


@dataclass(frozen=True)
class ConcernIndicators:
    fragments: str | None = None
    spark_write_tasks: str | None = None
    arrow_memory: str | None = None
    queued_memory: str | None = None
    fts_fanout: str | None = None


@dataclass(frozen=True)
class FragmentPlan:
    rows_per_fragment: Range
    count: Range
    target_rows: int
    target_count: int
    row_size_note: str
    beyond_one_billion_note: str | None = None


@dataclass(frozen=True)
class SparkPlan:
    total_cores: int
    concurrent_task_slots: int
    stage_task_target: Range
    write_tasks: Range
    tasks_per_worker: int
    max_batch_bytes: int
    batch_memory_upper_bound: int
    batch_ram_fraction: float
    queued_arrow_memory_per_worker: int | None
    queued_ram_fraction: float | None


@dataclass(frozen=True)
class S3Plan:
    upload_concurrency_start: int
    upload_concurrency_benchmark_high: int
    benchmark_scope: str
    basis: str
    initial_upload_size_mb: int = DEFAULT_INITIAL_UPLOAD_SIZE_MB


@dataclass(frozen=True)
class FtsPlan:
    segments: Range
    fanout_indicator: Range


@dataclass(frozen=True)
class VectorPlan:
    bytes_per_vector: int
    raw_vector_bytes: int
    segments: Range
    rows_per_segment: Range
    ivf_partitions_per_segment: Range
    pq_subvectors: Range | None
    pq_index_bytes: Range | None
    training_vectors_per_segment: Range
    pq_note: str


@dataclass(frozen=True)
class PlannerResult:
    engine: EngineRecommendation
    load: LoadPlan
    fragments: FragmentPlan
    spark: SparkPlan
    s3: S3Plan
    fts: FtsPlan | None
    vector: VectorPlan | None
    concerns: ConcernIndicators
    warnings: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)


def plan_scaling(inputs: PlannerInputs) -> PlannerResult:
    """Return Lance distributed ingestion/index planning recommendations.

    Formulas intentionally mirror the reference identifiers in the UI copy, e.g.
    [LANCE-FRAGMENTS], [LANCE-SPARK-PERF], [SPARK-TUNING], and
    [LANCE-DISTRIBUTED-INDEX].
    """

    _validate_inputs(inputs)
    total_cores = inputs.spark_workers * inputs.spark_cores_per_worker
    concurrent_task_slots = max(1, floor(total_cores / inputs.spark_task_cpus))
    fragments = _fragment_plan(inputs)
    spark = _spark_plan(inputs, fragments, total_cores, concurrent_task_slots)
    engine = _engine_recommendation(inputs)
    load = _load_plan(inputs, fragments)
    s3 = _s3_plan(inputs)
    fts = _fts_plan(inputs, fragments.target_count, total_cores) if inputs.has_fts else None
    vector = (
        _vector_plan(inputs, fragments.target_count, total_cores)
        if inputs.has_vector_index
        else None
    )
    concerns = _concern_indicators(
        fragments,
        spark,
        fts,
        spark_ingestion=engine.ingestion_engine == "Spark",
    )
    warnings = _warnings(inputs, concerns, vector)
    assumptions = _assumptions(inputs, fragments)
    return PlannerResult(
        engine=engine,
        load=load,
        fragments=fragments,
        spark=spark,
        s3=s3,
        fts=fts,
        vector=vector,
        concerns=concerns,
        warnings=warnings,
        assumptions=assumptions,
    )


def human_bytes(num_bytes: int | float) -> str:
    value = float(num_bytes)
    for suffix, unit in (("TiB", TiB), ("GiB", GiB), ("MiB", MiB), ("KiB", KiB)):
        if value >= unit:
            amount = value / unit
            return f"{amount:,.1f} {suffix}" if amount < 10 else f"{amount:,.0f} {suffix}"
    return f"{int(value):,} B"


def format_int_range(value: Range, *, approximate: bool = True) -> str:
    prefix = "~" if approximate else ""
    low = int(round(value.low))
    high = int(round(value.high))
    if low == high:
        return f"{prefix}{low:,}"
    return f"{prefix}{low:,}-{high:,}"


def _validate_inputs(inputs: PlannerInputs) -> None:
    if inputs.row_count <= 0:
        raise ValueError("Row count must be greater than zero.")
    if inputs.spark_workers <= 0:
        raise ValueError("Spark worker nodes must be greater than zero.")
    if inputs.spark_cores_per_worker <= 0:
        raise ValueError("CPU cores per Spark worker must be greater than zero.")
    if inputs.spark_ram_gib_per_worker <= 0:
        raise ValueError("RAM per Spark worker must be greater than zero.")
    if inputs.spark_task_cpus <= 0:
        raise ValueError("spark.task.cpus must be greater than zero.")
    if inputs.average_row_bytes is not None and inputs.average_row_bytes <= 0:
        raise ValueError("Average row size must be greater than zero when supplied.")
    if inputs.has_vector_index:
        if not inputs.vector_dimension or inputs.vector_dimension <= 0:
            raise ValueError("Vector dimension is required when vector indexing is enabled.")
        if inputs.vector_dtype not in VECTOR_DTYPES:
            raise ValueError(f"Unsupported vector datatype: {inputs.vector_dtype}.")
    if inputs.queue_depth <= 0:
        raise ValueError("Queue depth must be greater than zero.")


def _fragment_plan(inputs: PlannerInputs) -> FragmentPlan:
    note: str
    beyond_note = None
    if inputs.average_row_bytes is not None:
        rows_at_10_gib = max(
            1,
            floor(CONSERVATIVE_FRAGMENT_CEILING_BYTES / inputs.average_row_bytes),
        )
        high = max(1, min(inputs.row_count, DEFAULT_FRAGMENT_ROWS, rows_at_10_gib))
        low = max(1, round(high * 0.5))
        note = (
            "Uses supplied complete row size and a conservative 10 GiB ceiling inside "
            "Lance's documented 10-100 GB upper fragment range."
        )
    elif inputs.row_count <= 1_000_000_000:
        high = min(inputs.row_count, DEFAULT_FRAGMENT_ROWS)
        low = max(1, min(UNKNOWN_ROW_FRAGMENT_LOW, round(high * 0.5)))
        note = (
            "Fragment-size estimates use row-count guidance because the full byte width of "
            "each record is unknown."
        )
    else:
        high = min(inputs.row_count, LARGE_DATASET_FRAGMENT_HIGH)
        low = max(DEFAULT_FRAGMENT_ROWS, round(high * 0.5))
        note = (
            "Fragment-size estimates use row-count guidance because the full byte width of "
            "each record is unknown."
        )
        beyond_note = (
            "For datasets larger than about 1B rows, Lance documentation says substantially "
            "larger fragments, potentially toward 100M rows depending on row width, can be "
            "reasonable; verify with real row sizes before committing to this range."
        )

    count_min = ceil(inputs.row_count / high)
    count_max = ceil(inputs.row_count / low)
    target_rows = max(1, round((low + high) / 2))
    target_count = ceil(inputs.row_count / target_rows)
    return FragmentPlan(
        rows_per_fragment=Range(low, high, EXPLORER_HEURISTIC),
        count=Range(count_min, count_max, DERIVED),
        target_rows=target_rows,
        target_count=target_count,
        row_size_note=note,
        beyond_one_billion_note=beyond_note,
    )


def _spark_plan(
    inputs: PlannerInputs,
    fragments: FragmentPlan,
    total_cores: int,
    concurrent_task_slots: int,
) -> SparkPlan:
    write_low = max(1, min(2 * total_cores, int(fragments.count.low)))
    write_high = max(write_low, min(3 * total_cores, int(fragments.count.high)))
    tasks_per_worker = ceil(write_high / inputs.spark_workers)
    max_batch_bytes = inputs.override_max_batch_bytes or DEFAULT_MAX_BATCH_BYTES
    batch_memory_upper_bound = tasks_per_worker * max_batch_bytes
    worker_ram_bytes = inputs.spark_ram_gib_per_worker * GiB
    queued_memory = None
    queued_fraction = None
    if inputs.use_queued_write_buffer:
        queued_memory = tasks_per_worker * inputs.queue_depth * max_batch_bytes
        queued_fraction = queued_memory / worker_ram_bytes
    return SparkPlan(
        total_cores=total_cores,
        concurrent_task_slots=concurrent_task_slots,
        stage_task_target=Range(2 * total_cores, 3 * total_cores, DOCUMENTED),
        write_tasks=Range(write_low, write_high, EXPLORER_HEURISTIC),
        tasks_per_worker=tasks_per_worker,
        max_batch_bytes=max_batch_bytes,
        batch_memory_upper_bound=batch_memory_upper_bound,
        batch_ram_fraction=batch_memory_upper_bound / worker_ram_bytes,
        queued_arrow_memory_per_worker=queued_memory,
        queued_ram_fraction=queued_fraction,
    )


def _s3_plan(inputs: PlannerInputs) -> S3Plan:
    trino_ingestion = (
        inputs.source_type == SOURCE_TRINO
        and inputs.transformation_type in {TRANSFORM_NONE, TRANSFORM_SQL}
    )
    if trino_ingestion:
        high = max(DEFAULT_UPLOAD_CONCURRENCY, inputs.trino_cores_per_worker or 0)
        scope = "Trino worker"
        basis = (
            "supplied Trino cores per worker"
            if inputs.trino_cores_per_worker
            else "default baseline because Trino cores were not supplied"
        )
    elif inputs.executors_per_spark_worker and inputs.executors_per_spark_worker > 0:
        cores_per_executor = max(
            1,
            inputs.spark_cores_per_worker // inputs.executors_per_spark_worker,
        )
        high = max(DEFAULT_UPLOAD_CONCURRENCY, cores_per_executor)
        scope = "Spark executor"
        basis = "cores per executor"
    else:
        high = max(DEFAULT_UPLOAD_CONCURRENCY, inputs.spark_cores_per_worker)
        scope = "Spark worker"
        basis = "cores per worker"
    return S3Plan(DEFAULT_UPLOAD_CONCURRENCY, high, scope, basis)


def _engine_recommendation(inputs: PlannerInputs) -> EngineRecommendation:
    trino_natural = (
        inputs.source_type == SOURCE_TRINO
        and inputs.transformation_type in {TRANSFORM_NONE, TRANSFORM_SQL}
    )
    if trino_natural:
        ingestion = "Trino"
        reason = "The source is already Trino-accessible and the ingestion transform is SQL-shaped."
    else:
        ingestion = "Spark"
        reason = (
            "Spark is the safer ingestion default for custom/programmatic transforms, "
            "file-oriented sources, or workflows dominated by distributed post-processing."
        )

    if inputs.source_type == SOURCE_TRINO and trino_natural:
        source_strategy = (
            "Use Trino CTAS or INSERT SELECT so its workers read the source and write Lance "
            "without an intermediate export."
        )
    elif inputs.source_type == SOURCE_TRINO:
        source_strategy = (
            "Read the Trino-accessible source into Spark for the custom transform, then let "
            "Spark own partitioning and the Lance write."
        )
    elif inputs.source_type == SOURCE_FILES:
        source_strategy = (
            "Use Spark's distributed file scan, prune unused columns early, and keep the "
            "compute and destination object storage in the same region."
        )
    elif inputs.source_type == SOURCE_EXISTING_LANCE:
        source_strategy = (
            "Read the existing Lance fragments directly; avoid staging through Parquet or "
            "rewriting unchanged columns."
        )
    else:
        source_strategy = (
            "Partition the source before the Lance writer and validate its Arrow schema and "
            "batch sizes on a representative slice."
        )

    if inputs.transformation_type == TRANSFORM_NONE:
        transformation_strategy = (
            "Keep the path pass-through: project only required columns and avoid a shuffle or "
            "row rewrite that does not change the result."
        )
    elif inputs.transformation_type == TRANSFORM_SQL and trino_natural:
        transformation_strategy = (
            "Push SQL filters, projections, joins, and aggregations into the Trino CTAS or "
            "INSERT SELECT before Lance files are written."
        )
    elif inputs.transformation_type == TRANSFORM_SQL:
        transformation_strategy = (
            "Run the SQL-shaped transform in Spark, then repartition the final result for the "
            "Lance write rather than preserving upstream tiny partitions."
        )
    else:
        transformation_strategy = (
            "Run the custom transform in Spark with deterministic, retry-safe partition work; "
            "repartition its output before writing if the transform creates skew."
        )

    if ingestion == "Trino":
        if inputs.trino_workers and inputs.trino_cores_per_worker:
            compute_strategy = (
                f"Trino ingestion uses the supplied {inputs.trino_workers} workers x "
                f"{inputs.trino_cores_per_worker} cores. Trino schedules its own splits, so "
                "Spark write-task sizing does not apply to ingestion."
            )
        else:
            compute_strategy = (
                "Trino schedules its own distributed splits. Add Trino worker/core counts under "
                "Advanced to tune the per-worker S3 concurrency range. Spark write-task sizing "
                "does not apply to ingestion; Spark compute is used only for requested indexing "
                "work."
            )
    else:
        compute_strategy = (
            "The Spark worker, core, task-CPU, and RAM inputs directly size the write-task range "
            "and Arrow memory estimate below."
        )

    fts_engine = "Spark distributed FTS" if inputs.has_fts else None
    vector_engine = (
        "Spark scheduler + PyLance distributed-index APIs"
        if inputs.has_vector_index
        else None
    )
    load_step = {
        LOAD_ONE_TIME: "bulk ingest once",
        LOAD_OCCASIONAL: "append each large delivery",
        LOAD_REGULAR: "buffer and append each scheduled batch",
        LOAD_FREQUENT: "buffer small arrivals into fragment-sized appends",
    }[inputs.load_pattern]
    workflow = [load_step, "verify fragment sizes and count"]
    if inputs.has_fts:
        workflow.append("build FTS after bulk ingest")
    if inputs.has_vector_index:
        workflow.append("build vector index after bulk ingest")
    if trino_natural and (inputs.has_fts or inputs.has_vector_index):
        workflow.insert(1, "use Spark for indexing/specialized post-processing")
    return EngineRecommendation(
        ingestion,
        reason,
        source_strategy,
        transformation_strategy,
        compute_strategy,
        fts_engine,
        vector_engine,
        workflow,
    )


def _load_plan(inputs: PlannerInputs, fragments: FragmentPlan) -> LoadPlan:
    index_targets = []
    if inputs.has_fts:
        index_targets.append("FTS")
    if inputs.has_vector_index:
        index_targets.append("vector")
    index_label = " and ".join(index_targets) if index_targets else "any later"

    if inputs.load_pattern == LOAD_ONE_TIME:
        return LoadPlan(
            pattern=inputs.load_pattern,
            recommended_approach=(
                "Use one bounded create or overwrite job. Complete the final transform before "
                "the write, repartition once for the recommended output parallelism, and let "
                "each task produce target-sized fragments. Verify fragment sizes and row counts "
                "before building indexes, and keep writers paused until the final index commit."
            ),
            buffered_append_rows=None,
            write_strategy=(
                "Run one distributed create or overwrite and let each output task produce "
                "fragment-sized files. Quiesce ingestion before final indexing."
            ),
            compaction_strategy=(
                "Skip routine compaction when the initial files land in the target range. "
                "Compact undersized retry or tail fragments once, before index construction."
            ),
            index_strategy=(
                f"Build {index_label} indexes after the bulk write and fragment check."
                if index_targets
                else "No index-maintenance cycle is needed for this plan."
            ),
            write_amplification_strategy=(
                "Getting fragment sizing right in the initial write avoids rewriting the "
                "dataset through an immediate compaction pass."
            ),
            operational_tips=(
                "Use overwrite only for the initial dataset or an intentional full replacement.",
                "Keep the transform and write in one distributed job so intermediate tiny files "
                "do not become the next ingestion source.",
                "Treat post-load compaction as an exception for undersized tails, not a required "
                "second write of the entire dataset.",
            ),
        )

    if inputs.load_pattern == LOAD_OCCASIONAL:
        buffered_rows = Range(
            fragments.target_rows,
            int(fragments.rows_per_fragment.high),
            EXPLORER_HEURISTIC,
        )
        write_strategy = (
            "Treat each delivery as a bulk append and coalesce small tail partitions before "
            "the write."
        )
        compaction_strategy = (
            "Inspect fragment sizes after each delivery; compact only when undersized tails "
            "have accumulated, preferably before index maintenance."
        )
        recommended_approach = (
            "Treat every delivery as a self-contained bulk append. Finish validation and "
            "transformation first, coalesce small source partitions, then commit the delivery "
            "once. A large delivery may use the full recommended write parallelism; its final "
            "partial partition can wait for the next delivery when your staging design allows it."
        )
        operational_tips = (
            "Make retries idempotent by assigning each delivery a stable batch identifier.",
            "Measure new fragment count and file sizes after each delivery before deciding to "
            "compact.",
            "Update index coverage after the append rather than rebuilding every index from "
            "scratch.",
        )
    elif inputs.load_pattern == LOAD_REGULAR:
        buffered_rows = Range(
            int(fragments.rows_per_fragment.low),
            int(fragments.rows_per_fragment.high),
            EXPLORER_HEURISTIC,
        )
        write_strategy = (
            "Buffer each scheduled batch until it can fill at least one target fragment, and "
            "coalesce upstream partitions that would create tiny files."
        )
        compaction_strategy = (
            "Compact on a fragment-count or small-fragment threshold, not automatically after "
            "every batch; do not overlap compaction with index builds."
        )
        recommended_approach = (
            "Use scheduled micro-batches with a durable staging boundary. Accumulate at least "
            "one fragment-sized batch, make the batch retry-safe, then append it in a small "
            "number of well-filled writer partitions. Track fragment growth and unindexed rows "
            "across batches so maintenance runs only when a threshold is crossed."
        )
        operational_tips = (
            "Choose a batch interval long enough to reach the buffered-row target under normal "
            "traffic.",
            "Checkpoint source offsets or batch IDs before acknowledging a successful append.",
            "Separate ingestion, compaction, and index-maintenance windows to avoid repeated work "
            "from transaction retries.",
        )
    else:
        buffered_rows = Range(
            int(fragments.rows_per_fragment.low),
            fragments.target_rows,
            EXPLORER_HEURISTIC,
        )
        write_strategy = (
            "Land arrivals in a queue or staging table and flush fragment-sized micro-batches. "
            "A commit per event creates versions and undersized fragments too quickly."
        )
        compaction_strategy = (
            "Use threshold-based compaction outside peak ingestion. Keep appends flowing, but "
            "avoid concurrent compaction and index construction because retries repeat work."
        )
        recommended_approach = (
            "Decouple event arrival from Lance commits with a queue, stream checkpoint, or "
            "staging table. A consumer should aggregate arrivals into the recommended buffered "
            "range, write one idempotent micro-batch, and advance its checkpoint only after the "
            "Lance commit succeeds. This keeps commit and fragment growth proportional to batches "
            "instead of individual events."
        )
        operational_tips = (
            "Never create one Lance append per message or request; backpressure is preferable to "
            "a growing population of tiny fragments.",
            "Use deterministic batch or window IDs so a failed commit can be retried safely.",
            "Run compaction off-peak and use deferred index remapping on indexed tables to avoid "
            "rewriting index row addresses during every compaction cycle.",
        )

    if index_targets:
        index_strategy = (
            f"Run incremental optimize_indices for {index_label} on a coverage or time cadence; "
            "new rows remain searchable through fallback scans until they are indexed."
        )
        amplification_strategy = (
            "When compacting an indexed table, use defer_index_remap=True so the Fragment "
            "Reuse Index can avoid immediately rewriting index row addresses."
        )
    else:
        index_strategy = "No incremental index-maintenance cycle is needed for this plan."
        amplification_strategy = (
            "Avoid compaction on every append. Rewrite only after enough small fragments have "
            "accumulated to justify the I/O."
        )

    return LoadPlan(
        pattern=inputs.load_pattern,
        recommended_approach=recommended_approach,
        buffered_append_rows=buffered_rows,
        write_strategy=write_strategy,
        compaction_strategy=compaction_strategy,
        index_strategy=index_strategy,
        write_amplification_strategy=amplification_strategy,
        operational_tips=operational_tips,
    )


def _fts_plan(inputs: PlannerInputs, target_fragment_count: int, total_cores: int) -> FtsPlan:
    low = min(target_fragment_count, max(1, min(total_cores, 2 * inputs.spark_workers)))
    high = min(target_fragment_count, max(low, min(total_cores, 4 * inputs.spark_workers)))
    return FtsPlan(
        segments=Range(low, high, EXPLORER_HEURISTIC),
        fanout_indicator=Range(target_fragment_count * low, target_fragment_count * high, DERIVED),
    )


def _vector_plan(inputs: PlannerInputs, target_fragment_count: int, total_cores: int) -> VectorPlan:
    assert inputs.vector_dimension is not None
    bytes_per_vector = inputs.vector_dimension * VECTOR_DTYPES[inputs.vector_dtype]
    raw_vector_bytes = inputs.row_count * bytes_per_vector
    low = min(target_fragment_count, max(1, min(total_cores, 2 * inputs.spark_workers)))
    high = min(target_fragment_count, max(low, min(total_cores, 4 * inputs.spark_workers)))
    rows_per_segment_low = inputs.row_count / high
    rows_per_segment_high = inputs.row_count / low
    ivf_low = max(1, round(sqrt(rows_per_segment_low)))
    ivf_high = max(ivf_low, round(sqrt(rows_per_segment_high)))
    training_low = min(rows_per_segment_low, 256 * ivf_low)
    training_high = min(rows_per_segment_high, 256 * ivf_high)
    pq_subvectors, pq_note = _pq_subvectors(inputs.vector_dimension)
    pq_index_bytes = None
    if pq_subvectors is not None:
        pq_index_bytes = Range(
            inputs.row_count * (int(pq_subvectors.low) + 8),
            inputs.row_count * (int(pq_subvectors.high) + 8),
            DERIVED,
        )
    return VectorPlan(
        bytes_per_vector=bytes_per_vector,
        raw_vector_bytes=raw_vector_bytes,
        segments=Range(low, high, EXPLORER_HEURISTIC),
        rows_per_segment=Range(rows_per_segment_low, rows_per_segment_high, DERIVED),
        ivf_partitions_per_segment=Range(ivf_low, ivf_high, DERIVED),
        pq_subvectors=pq_subvectors,
        pq_index_bytes=pq_index_bytes,
        training_vectors_per_segment=Range(training_low, training_high, DERIVED),
        pq_note=pq_note,
    )


def _pq_subvectors(dimension: int) -> tuple[Range | None, str]:
    if dimension % 16 == 0:
        return (
            Range(dimension // 16, dimension // 8, DOCUMENTED),
            "D/16 favors compression; D/8 retains more information and both keep "
            "SIMD-friendly widths.",
        )
    if dimension % 8 == 0:
        return (
            Range(dimension // 8, dimension // 8, DOCUMENTED),
            "Dimension is divisible by 8 but not 16, so D/8 is the compatible PQ starting point.",
        )
    return (
        None,
        "This vector dimension is not SIMD-friendly for Lance PQ. Automatic PQ "
        "recommendations have lower confidence.",
    )


def _concern_indicators(
    fragments: FragmentPlan,
    spark: SparkPlan,
    fts: FtsPlan | None,
    *,
    spark_ingestion: bool,
) -> ConcernIndicators:
    fragment_warning = None
    task_warning = None
    arrow_warning = None
    queued_warning = None
    fanout_warning = None
    if int(fragments.count.high) > CONCERNING_FRAGMENT_COUNT:
        fragment_warning = (
            "Expected fragment count is very high. Lance can tolerate tens of thousands of "
            "fragments, but query planning and maintenance work should be monitored."
        )
    if spark_ingestion and int(spark.write_tasks.high) > CONCERNING_SPARK_TASK_COUNT:
        task_warning = (
            "The write stage contains more than 10,000 tasks. Validate scheduler overhead and "
            "avoid carrying tiny upstream partitions into the Lance write."
        )
    if spark_ingestion and spark.batch_ram_fraction > CONCERNING_MEMORY_FRACTION:
        arrow_warning = (
            "Arrow batch memory could exceed 25% of worker RAM. Reduce max_batch_bytes or the "
            "number of simultaneous tasks per worker."
        )
        if spark.batch_ram_fraction > 1:
            arrow_warning = (
                "Estimated Arrow batch memory exceeds worker RAM. Reduce max_batch_bytes or "
                "simultaneous tasks before running this write."
            )
    if (
        spark_ingestion
        and spark.queued_ram_fraction is not None
        and spark.queued_ram_fraction > CONCERNING_MEMORY_FRACTION
    ):
        queued_warning = (
            "The experimental queued write buffer could reserve a large fraction of worker RAM; "
            "benchmark carefully before enabling it."
        )
        if spark.queued_ram_fraction > 1:
            queued_warning = (
                "Estimated queued-buffer memory exceeds worker RAM. Reduce queue depth, "
                "max_batch_bytes, or simultaneous tasks before enabling it."
            )
    if fts and int(fts.fanout_indicator.high) > CONCERNING_FTS_FANOUT:
        fanout_warning = (
            "Relative FTS fan-out is high because fragment count and segment count multiply. "
            "Opening and searching FTS segments may require more coordination work."
        )
    return ConcernIndicators(
        fragments=fragment_warning,
        spark_write_tasks=task_warning,
        arrow_memory=arrow_warning,
        queued_memory=queued_warning,
        fts_fanout=fanout_warning,
    )


def _warnings(
    inputs: PlannerInputs,
    concerns: ConcernIndicators,
    vector: VectorPlan | None,
) -> list[str]:
    warnings: list[str] = []
    if inputs.average_row_bytes is None:
        warnings.append(
            "Average complete row size is unknown, so fragment-byte estimates are lower confidence."
        )
    warnings.extend(
        warning
        for warning in (
            concerns.fragments,
            concerns.spark_write_tasks,
            concerns.arrow_memory,
            concerns.queued_memory,
            concerns.fts_fanout,
        )
        if warning
    )
    if inputs.s3_region_relationship == "cross-region":
        warnings.append(
            "Compute and S3 storage are cross-region. Expect avoidable latency and transfer-cost "
            "pressure; same-region placement is recommended where practical."
        )
    if inputs.load_pattern == LOAD_FREQUENT:
        warnings.append(
            "Frequent small appends need buffering and maintenance: monitor fragment count, "
            "unindexed rows, and physical index segment count."
        )
    if vector:
        if vector.bytes_per_vector > 8 * KiB:
            warnings.append(
                "Vectors are unusually wide, so raw payload and index training memory can dominate "
                "the workload. Validate on a representative subset."
            )
        if vector.pq_subvectors is None:
            warnings.append(vector.pq_note)
    return warnings


def _assumptions(inputs: PlannerInputs, fragments: FragmentPlan) -> list[str]:
    assumptions = [
        "Calculated values are planning ranges, not exact runtime or throughput predictions.",
        "Spark write-task guidance balances Spark stage parallelism with Lance "
        "output-fragment sizing.",
        "S3 concurrency should be benchmarked while watching network, CPU, RAM, and S3 "
        "throttling/503s.",
        "Trino is not treated as the default distributed indexing engine; current "
        "lance-trino worker-distributed index construction remains open.",
    ]
    if fragments.beyond_one_billion_note:
        assumptions.append(fragments.beyond_one_billion_note)
    if inputs.has_vector_index:
        assumptions.append(
            "Vector planning assumes independently trained IVF/PQ models per physical "
            "index segment."
        )
    return assumptions
