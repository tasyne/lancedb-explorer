from lance_explorer.index_registry import INDEX_DEFINITIONS
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
    expected = {"BTREE", "BITMAP", "LABEL_LIST", "FM", "FTS"}
    definitions = {definition.key: definition for definition in INDEX_DEFINITIONS}

    assert expected <= definitions.keys()
    assert all(definition.label for definition in definitions.values())
    assert all("Best for" in definition.description for definition in definitions.values())
    assert all(len(definition.description) <= 100 for definition in definitions.values())
