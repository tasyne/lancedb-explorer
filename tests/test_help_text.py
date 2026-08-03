import pyarrow as pa

from lance_explorer.index_registry import (
    FTS_BASE_TOKENIZERS,
    FTS_PRESETS,
    INDEX_DEFINITIONS,
    compatible_index_definitions,
    fts_options_for_preset,
    fts_uses_packaged_model,
    get_index_definition,
)
from lance_explorer.ui.help_text import HELP, LANCE_OVERVIEW, LANCE_STRENGTHS, help_text


def test_important_operations_have_succinct_help() -> None:
    required = {
        "uri_bar",
        "database",
        "table_uri",
        "version",
        "fragments",
        "indexes",
        "filter_query",
        "fts_query",
        "hybrid_query",
        "fts_language",
        "fts_tokenizer",
        "raw_vector",
        "metadata_compare",
        "bounded_compare",
        "create_index",
        "drop_index",
        "optimize",
        "cleanup_versions",
        "restore_version",
        "drop_table",
        "code_export",
    }

    assert required <= HELP.keys()
    assert all(help_text(key).strip() for key in required)
    assert max(len(help_text(key)) for key in required) <= 180


def test_lance_overview_is_brief_and_explains_strengths() -> None:
    assert "Arrow-native" in LANCE_OVERVIEW
    assert "versioned" in LANCE_OVERVIEW
    assert "object-store" in LANCE_OVERVIEW
    assert 3 <= len(LANCE_STRENGTHS) <= 5
    assert all(len(item) <= 100 for item in LANCE_STRENGTHS)


def test_every_registered_index_has_user_facing_guidance() -> None:
    expected = {
        "BTREE",
        "BITMAP",
        "LABEL_LIST",
        "FM",
        "FTS",
        "IVF_FLAT",
        "IVF_PQ",
        "IVF_SQ",
        "IVF_RQ",
        "IVF_HNSW_FLAT",
        "IVF_HNSW_PQ",
        "IVF_HNSW_SQ",
        "HNSW_FLAT",
        "HNSW_PQ",
        "HNSW_SQ",
    }
    definitions = {definition.key: definition for definition in INDEX_DEFINITIONS}

    assert expected <= definitions.keys()
    assert all(definition.label for definition in definitions.values())
    assert all("Best for" in definition.description for definition in definitions.values())
    assert all(len(definition.description) <= 100 for definition in definitions.values())


def test_vector_indexes_are_compatible_with_float_vectors_only() -> None:
    vector_keys = {
        definition.key
        for definition in compatible_index_definitions(pa.list_(pa.float32(), 4))
        if definition.category == "vector"
    }
    assert {"IVF_FLAT", "IVF_PQ", "IVF_HNSW_SQ", "HNSW_FLAT"} <= vector_keys

    non_vector_keys = {
        definition.key
        for definition in compatible_index_definitions(pa.string())
        if definition.category == "vector"
    }
    assert non_vector_keys == set()
    assert get_index_definition("IVF_FLAT").class_name == "IvfFlat"


def test_fts_presets_cover_common_tokenizers() -> None:
    assert {
        "ENGLISH",
        "MULTILINGUAL",
        "JIEBA",
        "LINDERA_IPADIC",
        "LINDERA_UNIDIC",
        "LINDERA_KO_DIC",
    } <= FTS_PRESETS.keys()
    assert fts_options_for_preset("ENGLISH")["language"] == "English"
    assert fts_options_for_preset("MULTILINGUAL")["base_tokenizer"] == "icu"
    assert fts_options_for_preset("JIEBA")["base_tokenizer"] == "jieba/default"
    assert "language" not in fts_options_for_preset("JIEBA")
    assert "lindera/ipadic" in FTS_BASE_TOKENIZERS
    assert "lindera/ko-dic" in FTS_BASE_TOKENIZERS
    assert not fts_uses_packaged_model(fts_options_for_preset("LINDERA_IPADIC"))
    assert fts_uses_packaged_model(fts_options_for_preset("JIEBA"))
