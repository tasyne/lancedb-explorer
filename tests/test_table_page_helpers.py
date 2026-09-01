from lance_explorer.ui.pages.table import (
    _open_code_reference_label,
    _open_code_reference_options,
    _versions_with_tags,
)


def test_versions_with_tags_adds_tag_names_and_manifest_sizes() -> None:
    rows = _versions_with_tags(
        [{"version": 1, "timestamp": "old"}, {"version": 2, "timestamp": "new"}],
        [
            {"tag": "baseline", "version": 1, "manifest_size": 123},
            {"tag": "release", "version": 2, "manifest_size": 456},
            {"tag": "audit", "version": 2, "manifest_size": 789},
        ],
    )

    assert rows[0]["tags"] == "baseline"
    assert rows[0]["tag_manifest_sizes"] == "123"
    assert rows[1]["tags"] == "release, audit"
    assert rows[1]["tag_manifest_sizes"] == "456, 789"


def test_open_code_reference_options_include_tags_before_versions() -> None:
    options = _open_code_reference_options(
        [{"tag": "baseline", "version": 2}],
        [1, 2],
    )

    assert options == [None, "baseline", 2, 1]
    assert _open_code_reference_label(None) == "Latest"
    assert _open_code_reference_label("baseline") == "Tag baseline"
    assert _open_code_reference_label(2) == "Version 2"
