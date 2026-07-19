from lance_explorer.docs_index import (
    group_path_for_markdown_path,
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

