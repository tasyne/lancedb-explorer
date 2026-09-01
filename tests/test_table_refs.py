from lance_explorer.table_refs import (
    format_namespace_path,
    format_namespace_table_ref,
    normalize_table_reference,
    parse_namespace_table_ref,
    table_display_label,
)


def test_namespace_table_reference_round_trips() -> None:
    reference = format_namespace_table_ref(
        "s3://bucket/lance-root",
        ("prod", "search"),
        "movie_stars",
    )

    parsed = parse_namespace_table_ref(reference)

    assert parsed.implementation == "dir"
    assert parsed.root == "s3://bucket/lance-root"
    assert parsed.namespace_path == ("prod", "search")
    assert parsed.table_name == "movie_stars"
    assert normalize_table_reference(reference) == reference
    assert table_display_label(reference) == "ns:prod/search/movie_stars @ lance-root"


def test_format_namespace_path_labels_root() -> None:
    assert format_namespace_path(()) == "(root)"
    assert format_namespace_path(("prod", "search")) == "prod/search"
