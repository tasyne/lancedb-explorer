from lance_explorer.docs_index import (
    discover_markdown_entries,
    group_path_for_markdown_path,
    load_llms_index,
    local_markdown_path,
    markdown_path_from_url,
    parse_llms_index,
)


def test_parse_llms_index_preserves_sections_and_descriptions() -> None:
    entries = parse_llms_index(
        """# LanceDB

## Docs

- [Understanding Transforms](https://docs.lancedb.com/geneva/udfs/index.md): Learn transforms.
- [openapi](https://docs.lancedb.com/api-reference/openapi.json)

## OpenAPI Specs

- [spec](https://docs.lancedb.com/spec.json)
"""
    )

    assert entries[0].llms_section == "Docs"
    assert entries[0].title == "Understanding Transforms"
    assert entries[0].description == "Learn transforms."
    assert entries[0].markdown_path == "geneva/udfs/index.md"
    assert entries[0].group_path == ("Geneva", "UDFs")
    assert entries[2].llms_section == "OpenAPI Specs"
    assert entries[2].markdown_path is None


def test_markdown_path_from_url_only_accepts_markdown() -> None:
    assert (
        markdown_path_from_url("https://docs.lancedb.com/geneva/udfs/index.md")
        == "geneva/udfs/index.md"
    )
    assert markdown_path_from_url("https://docs.lancedb.com/api-reference/openapi.json") is None


def test_group_path_for_markdown_path_humanizes_path_parts() -> None:
    assert group_path_for_markdown_path("api-reference/rest/table/query-a-table.md") == (
        "API Reference",
        "REST",
        "Table",
    )


def test_load_llms_index_discovers_markdown_not_listed_in_llms(tmp_path) -> None:
    (tmp_path / "llms.txt").write_text(
        "# Docs\n\n## Docs\n\n- [Home](https://docs.lancedb.com/index.md)\n",
        encoding="utf-8",
    )
    (tmp_path / "index.md").write_text("# Home\n", encoding="utf-8")
    (tmp_path / "datasets").mkdir()
    (tmp_path / "datasets" / "index.md").write_text("# Datasets\n", encoding="utf-8")
    (tmp_path / "enterprise").mkdir()
    (tmp_path / "enterprise" / "auth.md").write_text("# Auth\n", encoding="utf-8")

    entries = load_llms_index(tmp_path)
    paths = {entry.markdown_path for entry in entries}

    assert {"index.md", "datasets/index.md", "enterprise/auth.md"} <= paths
    assert any(entry.group_path == ("Datasets",) for entry in entries)
    assert any(entry.group_path == ("Enterprise",) for entry in entries)


def test_discover_markdown_entries_uses_path_titles(tmp_path) -> None:
    (tmp_path / "embedding").mkdir()
    (tmp_path / "embedding" / "index.md").write_text("# Embedding\n", encoding="utf-8")

    entries = discover_markdown_entries(tmp_path)

    assert entries[0].title == "Embedding"
    assert entries[0].group_path == ("Embedding",)


def test_local_markdown_path_resolves_case_insensitively(tmp_path) -> None:
    (tmp_path / "Enterprise").mkdir()
    expected = tmp_path / "Enterprise" / "Auth.md"
    expected.write_text("# Auth\n", encoding="utf-8")

    assert local_markdown_path(tmp_path, "enterprise/auth.md") == expected
