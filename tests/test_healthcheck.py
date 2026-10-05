from lance_explorer.healthcheck import analyze_health


def test_healthy_scalar_table_has_no_findings() -> None:
    report = analyze_health(
        {
            "row_count": 100_000,
            "fragments": [
                {
                    "fragment_id": 0,
                    "physical_rows": 100_000,
                    "deleted_rows": 0,
                    "live_rows": 100_000,
                    "data_bytes": 100_000_000,
                }
            ],
            "indexes": [],
            "schema_fields": [{"name": "id", "type": "int64"}],
            "versions": [],
        }
    )

    assert report.status == "Healthy"
    assert report.score == 100
    assert report.findings == ()


def test_healthcheck_prioritizes_layout_deletions_and_stale_indexes() -> None:
    report = analyze_health(
        {
            "row_count": 2_400_000,
            "fragments": [
                {
                    "fragment_id": fragment_id,
                    "physical_rows": 1_000_000,
                    "deleted_rows": 400_000,
                    "live_rows": 600_000,
                    "data_bytes": 1_000_000_000,
                }
                for fragment_id in range(4)
            ],
            "indexes": [
                {
                    "name": "vector_idx",
                    "columns": ["vector"],
                    "index_type": "IVF_PQ",
                    "num_segments": 128,
                    "statistics": {
                        "num_indexed_rows": 1_000_000,
                        "num_unindexed_rows": 1_400_000,
                    },
                }
            ],
            "schema_fields": [
                {
                    "name": "vector",
                    "type": "fixed_size_list<item: float>[770]",
                    "vector_storage": "fixed",
                    "vector_dimension": 770,
                }
            ],
            "versions": [],
        }
    )

    titles = [finding.title for finding in report.findings]
    assert report.status == "Critical"
    assert titles[0] in {
        "Deletion tombstones are a large share of the table",
        "vector_idx does not cover the current table",
    }
    assert "vector_idx does not cover the current table" in titles
    assert "vector_idx has high segment fan-out" in titles
    assert "vector is not SIMD-aligned" in titles


def test_vector_workload_checks_are_advisory_when_usage_is_unknown() -> None:
    report = analyze_health(
        {
            "row_count": 20_000,
            "fragments": [],
            "indexes": [],
            "schema_fields": [
                {
                    "name": "embedding",
                    "type": "fixed_size_list<item: float>[384]",
                    "vector_storage": "fixed",
                    "vector_dimension": 384,
                }
            ],
            "versions": [],
        }
    )

    assert report.status == "Review advised"
    assert report.findings[0].severity == "advisory"
    assert report.findings[0].title == "embedding has no ANN index"
