# ruff: noqa: E501 - Finding copy is kept as complete sentences for UI readability.

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

Severity = Literal["critical", "warning", "advisory"]


@dataclass(frozen=True, slots=True)
class HealthFinding:
    """A table-health signal with evidence and an actionable next step."""

    severity: Severity
    category: str
    title: str
    evidence: str
    impact: str
    next_step: str
    basis: str


@dataclass(frozen=True, slots=True)
class HealthReport:
    """Prioritized findings derived from a bounded table metadata snapshot."""

    score: int
    status: str
    findings: tuple[HealthFinding, ...]
    inspection_errors: tuple[str, ...]


_SEVERITY_ORDER = {"critical": 0, "warning": 1, "advisory": 2}
_SEVERITY_PENALTY = {"critical": 30, "warning": 15, "advisory": 5}


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _version_span_days(versions: list[dict[str, Any]]) -> float | None:
    timestamps: list[datetime] = []
    for version in versions:
        value = version.get("timestamp")
        if not value:
            continue
        try:
            timestamps.append(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
        except ValueError:
            continue
    if len(timestamps) < 2:
        return None
    return (max(timestamps) - min(timestamps)).total_seconds() / 86_400


def _fragment_findings(snapshot: dict[str, Any]) -> list[HealthFinding]:
    fragments = list(snapshot.get("fragments") or [])
    row_count = _integer(snapshot.get("row_count"))
    fragment_count = len(fragments) or _integer(
        (snapshot.get("statistics") or {}).get("fragment_stats", {}).get("num_fragments")
    )
    findings: list[HealthFinding] = []

    if fragment_count >= 100_000:
        findings.append(
            HealthFinding(
                "critical",
                "Layout",
                "Fragment count is exceptionally high",
                f"{fragment_count:,} fragments are recorded for {row_count:,} live rows.",
                "Manifest-level reads, writes, planning, and conflict checks all walk the fragment list.",
                "Compact small fragments during a quiet write window, then revisit writer task counts and append batching so the layout stays compact.",
                "Lance says tens of thousands of fragments are generally fine; 100,000 is an Explorer critical threshold.",
            )
        )
    elif fragment_count >= 50_000:
        findings.append(
            HealthFinding(
                "warning",
                "Layout",
                "Fragment count deserves attention",
                f"{fragment_count:,} fragments are recorded for {row_count:,} live rows.",
                "Large manifests add fixed work to dataset opens, scan planning, mutations, and conflict resolution.",
                "Inspect fragment-size distribution and compact undersized fragments; reduce write-task fan-out or buffer small appends at ingestion.",
                "Lance says tens of thousands of fragments are generally fine; 50,000 is an Explorer review threshold.",
            )
        )

    if not fragments:
        return findings

    live_rows = [_integer(fragment.get("live_rows")) for fragment in fragments]
    small_count = sum(0 < rows < 250_000 for rows in live_rows)
    small_share = _ratio(small_count, fragment_count)
    if row_count >= 1_000_000 and fragment_count >= 4 and small_share >= 0.5:
        findings.append(
            HealthFinding(
                "warning",
                "Layout",
                "Most fragments are undersized",
                f"{small_count:,} of {fragment_count:,} fragments ({small_share:.0%}) contain fewer than 250,000 live rows.",
                "Many small fragments increase manifest and scan-planning overhead and are a common result of small appends.",
                "Compact toward roughly 1,000,000 rows per fragment. For recurring loads, buffer appends and schedule compaction by threshold instead of after every write.",
                "Lance defaults to 1M rows per fragment through roughly 1B rows; 250,000 is an Explorer undersized-fragment threshold.",
            )
        )
    elif row_count >= 1_000_000 and fragment_count >= 4 and small_share >= 0.2:
        findings.append(
            HealthFinding(
                "advisory",
                "Layout",
                "Small fragments are accumulating",
                f"{small_count:,} of {fragment_count:,} fragments ({small_share:.0%}) contain fewer than 250,000 live rows.",
                "The layout is beginning to trade useful scan units for extra metadata work.",
                "Watch the trend and compact once the small-fragment share or write latency becomes material; batch future appends more coarsely.",
                "Lance defaults to 1M rows per fragment; the 20% share is an Explorer heuristic.",
            )
        )

    max_bytes = max((_integer(fragment.get("data_bytes")) for fragment in fragments), default=0)
    max_fragment = max(fragments, key=lambda fragment: _integer(fragment.get("data_bytes")))
    if max_bytes >= 1_000_000_000_000:
        findings.append(
            HealthFinding(
                "critical",
                "Layout",
                "A fragment has reached the hard size ceiling",
                f"Fragment {max_fragment.get('fragment_id', '?')} contains about {max_bytes / 1_000_000_000_000:.2f} TB of data files.",
                "Very large fragments make fragment-level scans, updates, deletes, and compaction expensive.",
                "Rewrite into smaller fragments well below 1 TB; target 10-100 GB at most when byte size is the controlling constraint.",
                "Lance documents 10-100 GB as a reasonable upper range and 1 TB as a hard ceiling.",
            )
        )
    elif max_bytes >= 100_000_000_000:
        findings.append(
            HealthFinding(
                "warning",
                "Layout",
                "A fragment is unusually large",
                f"Fragment {max_fragment.get('fragment_id', '?')} contains about {max_bytes / 1_000_000_000:.1f} GB of data files.",
                "Large fragments increase the cost and conflict surface of fragment-level maintenance.",
                "Use a lower row target for wide records so new and compacted fragments remain in the 10-100 GB range.",
                "Lance documents 10-100 GB as a reasonable upper fragment-size range.",
            )
        )

    physical_rows = sum(_integer(fragment.get("physical_rows")) for fragment in fragments)
    deleted_rows = sum(_integer(fragment.get("deleted_rows")) for fragment in fragments)
    deletion_ratio = _ratio(deleted_rows, physical_rows)
    if physical_rows >= 100_000 and deletion_ratio >= 0.25:
        findings.append(
            HealthFinding(
                "critical",
                "Deletions",
                "Deletion tombstones are a large share of the table",
                f"{deleted_rows:,} of {physical_rows:,} physical rows ({deletion_ratio:.1%}) are deleted.",
                "Scans still encounter deletion metadata and skip tombstoned rows, wasting I/O and decode work.",
                "Compact files to materialize deletions before rebuilding or consolidating indexes. With active indexing, consider deferred index remapping during compaction.",
                "Lance documents that compaction removes deletion files and improves scans; 25% is an Explorer critical threshold.",
            )
        )
    elif physical_rows >= 100_000 and deletion_ratio >= 0.10:
        findings.append(
            HealthFinding(
                "warning",
                "Deletions",
                "Deletion tombstones are accumulating",
                f"{deleted_rows:,} of {physical_rows:,} physical rows ({deletion_ratio:.1%}) are deleted.",
                "Deleted rows add avoidable work to scans until affected fragments are rewritten.",
                "Schedule compaction to materialize deletions, preferably before a full index rebuild.",
                "Lance documents the scan cost of deleted rows; 10% is an Explorer warning threshold.",
            )
        )
    elif physical_rows >= 100_000 and deletion_ratio >= 0.05:
        findings.append(
            HealthFinding(
                "advisory",
                "Deletions",
                "Deletion overhead is becoming measurable",
                f"{deleted_rows:,} of {physical_rows:,} physical rows ({deletion_ratio:.1%}) are deleted.",
                "The table is still usable, but tombstone cost will grow if delete-heavy traffic continues.",
                "Track the ratio and include deletion materialization in the next scheduled compaction.",
                "The 5% observation threshold is an Explorer heuristic.",
            )
        )
    return findings


def _index_findings(snapshot: dict[str, Any]) -> list[HealthFinding]:
    findings: list[HealthFinding] = []
    for index in snapshot.get("indexes") or []:
        stats = index.get("statistics") or {}
        indexed = _integer(stats.get("num_indexed_rows", index.get("num_indexed_rows")))
        unindexed = _integer(stats.get("num_unindexed_rows", index.get("num_unindexed_rows")))
        total = indexed + unindexed
        coverage = _ratio(indexed, total)
        name = str(index.get("name") or "Unnamed index")
        if unindexed:
            if total >= 100_000 and coverage < 0.80:
                severity: Severity = "critical"
            elif unindexed >= 10_000 or coverage < 0.95:
                severity = "warning"
            else:
                severity = "advisory"
            findings.append(
                HealthFinding(
                    severity,
                    "Indexes",
                    f"{name} does not cover the current table",
                    f"Coverage is {coverage:.1%}: {indexed:,} indexed and {unindexed:,} unindexed rows.",
                    "Queries must fall back to scanning uncovered rows, which can erase much of the index benefit.",
                    "Run incremental index optimization after the current write batch. If coverage stays incomplete after compaction, rebuild the index.",
                    "Lance reports coverage as approximate and recommends rebuilding or optimizing indexes below 100% coverage.",
                )
            )

        segments = _integer(index.get("num_segments"))
        if not segments:
            segments = _integer(stats.get("num_indices"))
        if segments >= 128:
            findings.append(
                HealthFinding(
                    "warning",
                    "Indexes",
                    f"{name} has high segment fan-out",
                    f"The logical index is split across {segments:,} physical segments.",
                    "Every segment is searched, and segment boundaries restrict how far data compaction can coalesce fragments.",
                    "Rebuild or consolidate the index with fewer, contiguous segments after pending writes and compaction settle.",
                    "Lance documents the query and compaction cost; 128 segments is an Explorer warning threshold.",
                )
            )
        elif segments >= 32:
            findings.append(
                HealthFinding(
                    "advisory",
                    "Indexes",
                    f"{name} has substantial segment fan-out",
                    f"The logical index is split across {segments:,} physical segments.",
                    "Additional segments add search fan-out and impose more compaction boundaries.",
                    "Watch query latency and consolidate segments when incremental index maintenance next runs.",
                    "Lance documents the cost of high segment counts; 32 segments is an Explorer observation threshold.",
                )
            )
    return findings


def _schema_findings(snapshot: dict[str, Any]) -> list[HealthFinding]:
    findings: list[HealthFinding] = []
    fields = list(snapshot.get("schema_fields") or [])
    row_count = _integer(snapshot.get("row_count"))
    indexed_columns = {
        str(column)
        for index in snapshot.get("indexes") or []
        for column in index.get("columns") or []
        if any(
            marker in str(index.get("index_type") or index.get("statistics", {}).get("index_type", "")).upper()
            for marker in ("IVF", "HNSW")
        )
    }

    for field in fields:
        name = str(field.get("name") or "vector column")
        if field.get("vector_storage") == "variable":
            findings.append(
                HealthFinding(
                    "warning" if row_count >= 10_000 else "advisory",
                    "Schema",
                    f"{name} uses a variable-length vector type",
                    f"The field type is {field.get('type', 'a variable-length list of numbers')}.",
                    "Variable-length lists lose the storage and compute efficiencies Lance provides for fixed-dimension embeddings.",
                    "If this field contains embeddings, migrate it to an Arrow FixedSizeList with the model's exact dimension.",
                    "Lance recommends FixedSizeList, rather than List, for vector data.",
                )
            )
        dimension = _integer(field.get("vector_dimension"))
        if dimension and dimension % 8:
            findings.append(
                HealthFinding(
                    "advisory",
                    "Schema",
                    f"{name} is not SIMD-aligned",
                    f"The fixed vector dimension is {dimension:,}, which is not divisible by 8.",
                    "Vector indexing and distance calculations cannot use the optimal SIMD alignment.",
                    "When model choice permits, use an embedding dimension divisible by 8. Do not reshape existing embeddings merely to silence this check.",
                    "Lance recommends vector dimensions divisible by 8 for SIMD acceleration.",
                )
            )
        if (
            row_count > 10_000
            and field.get("vector_storage") == "fixed"
            and name not in indexed_columns
        ):
            findings.append(
                HealthFinding(
                    "advisory",
                    "Workload fit",
                    f"{name} has no ANN index",
                    f"The table has {row_count:,} rows and a fixed-size numeric vector column, but no vector index is registered on it.",
                    "This is only a concern when the column serves approximate nearest-neighbor searches; exact scans may be intentional.",
                    "If this is a search embedding, benchmark an ANN index and validate recall. Otherwise, treat this as an informational workload check.",
                    "Lance recommends an ANN index for vector-search datasets above roughly 10,000 vectors.",
                )
            )
    return findings


def _retention_findings(snapshot: dict[str, Any]) -> list[HealthFinding]:
    versions = list(snapshot.get("versions") or [])
    span_days = _version_span_days(versions)
    if len(versions) < 100 or span_days is None or span_days < 7:
        return []
    return [
        HealthFinding(
            "advisory",
            "Storage",
            "Version retention may be accumulating storage",
            f"{len(versions):,} versions span about {span_days:.0f} days; tagged versions are retained separately.",
            "Old versions keep superseded data and deletion files reachable. This affects storage more directly than current-version query speed.",
            "Confirm time-travel requirements, preserve required versions with tags, and clean versions older than the approved retention window.",
            "Lance keeps old-version files until cleanup and exempts tagged versions from cleanup.",
        )
    ]


def analyze_health(snapshot: dict[str, Any]) -> HealthReport:
    """Analyze bounded Lance metadata without scanning user data."""

    findings = [
        *_fragment_findings(snapshot),
        *_index_findings(snapshot),
        *_schema_findings(snapshot),
        *_retention_findings(snapshot),
    ]
    findings.sort(key=lambda finding: (_SEVERITY_ORDER[finding.severity], finding.category))
    score = max(0, 100 - sum(_SEVERITY_PENALTY[item.severity] for item in findings))
    errors = tuple(str(error) for error in snapshot.get("inspection_errors") or [])
    if any(item.severity == "critical" for item in findings):
        status = "Critical"
    elif any(item.severity == "warning" for item in findings):
        status = "Needs attention"
    elif findings:
        status = "Review advised"
    else:
        status = "Healthy"
    if errors and not findings:
        status = "Incomplete"
    return HealthReport(score, status, tuple(findings), errors)
