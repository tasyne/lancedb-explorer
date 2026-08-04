from lance_explorer.compat import (
    is_lancedb_below_recommended,
    lance_blob_v2_available,
    lancedb_compatibility_warning,
    lancedb_supports_fts_icu,
    lancedb_version_tuple,
)


def test_lancedb_version_tuple_parses_stable_versions() -> None:
    assert lancedb_version_tuple("0.33.0") == (0, 33, 0)
    assert lancedb_version_tuple("0.34.0") == (0, 34, 0)
    assert lancedb_version_tuple("0.34.0.post1") == (0, 34, 0)
    assert lancedb_version_tuple("unknown") is None


def test_lancedb_compatibility_warning_for_older_versions() -> None:
    assert is_lancedb_below_recommended("0.33.0")
    assert lancedb_compatibility_warning("0.33.0")
    assert lancedb_compatibility_warning("0.34.0") is None


def test_blob_v2_requires_minimum_lancedb_version() -> None:
    assert not lance_blob_v2_available("0.33.0")


def test_icu_fts_tokenizer_requires_recommended_lancedb_version() -> None:
    assert not lancedb_supports_fts_icu("0.33.0")
    assert lancedb_supports_fts_icu("0.34.0")
