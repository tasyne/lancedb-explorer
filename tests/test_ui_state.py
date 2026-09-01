import json
from pathlib import Path

import streamlit as st

from lance_explorer.config import AppConfig
from lance_explorer.ui.components.common import (
    _short_table_label,
    _table_reference_label,
    _table_reference_options,
)
from lance_explorer.ui.state import (
    initialize_state,
    select_table,
    selected_table_checkout_reference,
    selected_table_reference_label,
    set_selected_table_reference,
    table_state_file,
)


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig(home_uri=str(tmp_path), template_override_dir=None)


def test_table_selection_persists_to_local_json(tmp_path: Path, monkeypatch) -> None:
    state_file = tmp_path / "state.json"
    monkeypatch.setenv("LANCE_EXPLORER_STATE_FILE", str(state_file))
    st.session_state.clear()
    initialize_state(_config(tmp_path))

    select_table(str(tmp_path / "db" / "items.lance"))

    payload = json.loads(state_file.read_text(encoding="utf-8"))
    assert payload["selected_table_uri"].endswith("items.lance")
    assert payload["selected_table_history"] == [payload["selected_table_uri"]]


def test_initialize_state_loads_persisted_table_history(tmp_path: Path, monkeypatch) -> None:
    selected = str(tmp_path / "db" / "current.lance")
    previous = str(tmp_path / "db" / "previous.lance")
    state_file = tmp_path / "state.json"
    state_file.write_text(
        json.dumps(
            {
                "selected_table_uri": selected,
                "selected_table_history": [selected, previous, selected],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LANCE_EXPLORER_STATE_FILE", str(state_file))
    st.session_state.clear()

    initialize_state(_config(tmp_path))

    assert st.session_state["selected_table_uri"].endswith("current.lance")
    assert len(st.session_state["selected_table_history"]) == 2
    assert st.session_state["selected_table_history"][0].endswith("current.lance")
    assert st.session_state["selected_table_history"][1].endswith("previous.lance")


def test_table_state_file_can_be_overridden(tmp_path: Path, monkeypatch) -> None:
    state_file = tmp_path / "custom-state.json"
    monkeypatch.setenv("LANCE_EXPLORER_STATE_FILE", str(state_file))

    assert table_state_file() == state_file


def test_short_table_label_uses_parent_and_table_name() -> None:
    assert _short_table_label(r"C:\data\actors\movie_stars.lance") == "actors/movie_stars.lance"


def test_selected_table_reference_persists_and_resolves(tmp_path: Path, monkeypatch) -> None:
    state_file = tmp_path / "state.json"
    monkeypatch.setenv("LANCE_EXPLORER_STATE_FILE", str(state_file))
    st.session_state.clear()
    initialize_state(_config(tmp_path))
    select_table(str(tmp_path / "db" / "items.lance"))

    set_selected_table_reference("tag:baseline")

    payload = json.loads(state_file.read_text(encoding="utf-8"))
    assert payload["selected_table_reference"] == "tag:baseline"
    assert selected_table_checkout_reference() == "baseline"
    assert selected_table_reference_label([{"tag": "baseline", "version": 2}]) == (
        "Tag baseline -> version 2"
    )


def test_table_reference_options_show_tags_before_versions() -> None:
    tags = [{"tag": "release", "version": 3}]
    versions = [{"version": 1}, {"version": 3}, {"version": 2}]

    assert _table_reference_options(tags, versions) == [
        "latest",
        "tag:release",
        "version:3",
        "version:2",
        "version:1",
    ]
    assert _table_reference_label("tag:release", tags) == "Tag: release (version 3)"
