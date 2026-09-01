from __future__ import annotations

import json
import os
from pathlib import Path

import streamlit as st

from lance_explorer.config import AppConfig
from lance_explorer.paths import normalize_uri, parent_uri
from lance_explorer.table_refs import normalize_table_reference

MAX_TABLE_HISTORY = 20
LATEST_TABLE_REFERENCE = "latest"


def initialize_state(config: AppConfig) -> None:
    """Populate Streamlit session defaults without overwriting existing state."""

    persisted = load_persisted_table_state()
    defaults = {
        "current_uri": normalize_uri(config.home_uri),
        "selected_table_uri": persisted.get("selected_table_uri", ""),
        "selected_table_history": persisted.get("selected_table_history", []),
        "selected_table_reference": persisted.get(
            "selected_table_reference", LATEST_TABLE_REFERENCE
        ),
        "namespace_root": "",
        "namespace_root_explicit": False,
        "namespace_path": [],
        "navigation_history": [normalize_uri(config.home_uri)],
        "navigation_index": 0,
        "cache_generations": {},
        "query_results": {},
        "comparison_results": {},
        "operation_results": {},
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def load_persisted_table_state() -> dict[str, object]:
    """Load selected-table state from the small local JSON file, if present."""

    path = table_state_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    selected = _normalized_or_empty(str(data.get("selected_table_uri") or ""))
    history = _normalized_history(data.get("selected_table_history", []))
    if selected and selected not in history:
        history = [selected, *history]
    return {
        "selected_table_uri": selected,
        "selected_table_history": history[:MAX_TABLE_HISTORY],
        "selected_table_reference": _normalized_table_reference(
            str(data.get("selected_table_reference") or LATEST_TABLE_REFERENCE)
        ),
    }


def save_persisted_table_state() -> None:
    """Persist only the table selection/history needed across app restarts."""

    selected = _normalized_or_empty(str(st.session_state.get("selected_table_uri") or ""))
    history = _normalized_history(st.session_state.get("selected_table_history", []))
    payload = {
        "selected_table_uri": selected,
        "selected_table_history": history[:MAX_TABLE_HISTORY],
        "selected_table_reference": _normalized_table_reference(
            str(st.session_state.get("selected_table_reference") or LATEST_TABLE_REFERENCE)
        ),
    }
    path = table_state_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        # Losing persisted UI state should not block the local app.
        return


def table_state_file() -> Path:
    """Return the local JSON file used for table selection persistence."""

    override = os.getenv("LANCE_EXPLORER_STATE_FILE")
    if override:
        return Path(override).expanduser()
    if local_app_data := os.getenv("LOCALAPPDATA"):
        return Path(local_app_data) / "lance-explorer" / "state.json"
    if xdg_state_home := os.getenv("XDG_STATE_HOME"):
        return Path(xdg_state_home) / "lance-explorer" / "state.json"
    return Path.home() / ".lance-explorer" / "state.json"


def navigate(uri: str, *, add_history: bool = True) -> None:
    """Move Explorer to a URI and optionally append browser-style history."""

    normalized = normalize_uri(uri)
    st.session_state.current_uri = normalized
    if not add_history:
        return

    history = list(st.session_state.navigation_history)
    index = int(st.session_state.navigation_index)
    history = history[: index + 1]
    if not history or history[-1] != normalized:
        history.append(normalized)
    st.session_state.navigation_history = history
    st.session_state.navigation_index = len(history) - 1


def navigate_back() -> bool:
    """Move Explorer back in history when possible."""

    index = int(st.session_state.navigation_index)
    if index <= 0:
        return False
    index -= 1
    st.session_state.navigation_index = index
    st.session_state.current_uri = st.session_state.navigation_history[index]
    return True


def navigate_forward() -> bool:
    """Move Explorer forward in history when possible."""

    index = int(st.session_state.navigation_index)
    history = st.session_state.navigation_history
    if index >= len(history) - 1:
        return False
    index += 1
    st.session_state.navigation_index = index
    st.session_state.current_uri = history[index]
    return True


def navigate_up() -> None:
    """Navigate Explorer to the current URI's parent."""

    navigate(parent_uri(st.session_state.current_uri))


def select_table(uri: str) -> None:
    """Select a table, clear stale table outputs, and maintain deduped history."""

    normalized = normalize_table_reference(uri)
    if st.session_state.get("selected_table_uri") != normalized:
        st.session_state.query_results = {}
        st.session_state.pop("table_preview", None)
        st.session_state.pop("table_schema_diff", None)
        st.session_state.selected_table_reference = LATEST_TABLE_REFERENCE
    st.session_state.selected_table_uri = normalized
    history = [
        item
        for item in st.session_state.get("selected_table_history", [])
        if item != normalized
    ]
    st.session_state.selected_table_history = [normalized, *history][:MAX_TABLE_HISTORY]
    save_persisted_table_state()


def set_selected_table_reference(reference: str) -> None:
    """Set the selected table version/tag reference and clear stale read results."""

    normalized = _normalized_table_reference(reference)
    if st.session_state.get("selected_table_reference") == normalized:
        return
    st.session_state.selected_table_reference = normalized
    st.session_state.query_results = {}
    st.session_state.pop("table_preview", None)
    st.session_state.pop("table_schema_diff", None)
    save_persisted_table_state()


def selected_table_checkout_reference() -> int | str | None:
    """Return the current checkout reference as LanceDB expects it."""

    reference = _normalized_table_reference(
        str(st.session_state.get("selected_table_reference") or LATEST_TABLE_REFERENCE)
    )
    if reference == LATEST_TABLE_REFERENCE:
        return None
    kind, value = reference.split(":", 1)
    if kind == "version":
        return int(value)
    return value


def selected_table_reference_label(tags: list[dict[str, object]] | None = None) -> str:
    """Return a compact label for the selected table reference."""

    reference = _normalized_table_reference(
        str(st.session_state.get("selected_table_reference") or LATEST_TABLE_REFERENCE)
    )
    if reference == LATEST_TABLE_REFERENCE:
        return "Latest"
    kind, value = reference.split(":", 1)
    if kind == "version":
        return f"Version {value}"
    tag_version = _tag_version(tags or [], value)
    return f"Tag {value}" + (f" -> version {tag_version}" if tag_version is not None else "")


def _normalized_or_empty(value: str) -> str:
    if not value.strip():
        return ""
    try:
        return normalize_table_reference(value)
    except ValueError:
        return ""


def _normalized_history(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    history: list[str] = []
    for value in values:
        normalized = _normalized_or_empty(str(value or ""))
        if normalized and normalized not in history:
            history.append(normalized)
    return history


def _normalized_table_reference(reference: str) -> str:
    value = reference.strip()
    if not value or value == LATEST_TABLE_REFERENCE:
        return LATEST_TABLE_REFERENCE
    if value.startswith("version:"):
        version_text = value.split(":", 1)[1]
        try:
            version = int(version_text)
        except ValueError:
            return LATEST_TABLE_REFERENCE
        return f"version:{version}" if version > 0 else LATEST_TABLE_REFERENCE
    if value.startswith("tag:") and value.split(":", 1)[1].strip():
        return f"tag:{value.split(':', 1)[1].strip()}"
    return LATEST_TABLE_REFERENCE


def _tag_version(tags: list[dict[str, object]], tag_name: str) -> int | None:
    for tag in tags:
        if tag.get("tag") == tag_name and isinstance(tag.get("version"), int):
            return int(tag["version"])
    return None


def generation_for(resource_uri: str) -> int:
    """Return the current cache generation for a URI."""

    return int(st.session_state.cache_generations.get(resource_uri, 0))


def bump_generation(resource_uri: str) -> int:
    """Increment the cache generation for a URI after refresh or mutation."""

    generations = dict(st.session_state.cache_generations)
    generations[resource_uri] = int(generations.get(resource_uri, 0)) + 1
    st.session_state.cache_generations = generations
    return generations[resource_uri]
