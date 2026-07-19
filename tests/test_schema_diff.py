import pyarrow as pa

from lance_explorer.schema_diff import diff_schemas, flatten_schema


def test_schema_diff_detects_nested_and_top_level_changes() -> None:
    left = pa.schema(
        [
            pa.field("id", pa.int64(), nullable=False),
            pa.field("profile", pa.struct([pa.field("name", pa.string())])),
        ]
    )
    right = pa.schema(
        [
            pa.field("id", pa.int32(), nullable=False),
            pa.field(
                "profile",
                pa.struct([pa.field("name", pa.string()), pa.field("active", pa.bool_())]),
            ),
            pa.field("created_at", pa.timestamp("us")),
        ]
    )

    paths = {field.path for field in flatten_schema(right)}
    assert "profile.active" in paths

    changes = diff_schemas(left, right)
    observed = {(change.path, change.change) for change in changes}
    assert ("id", "type") in observed
    assert ("profile.active", "added") in observed
    assert ("created_at", "added") in observed
