from __future__ import annotations

import streamlit as st

from lance_explorer.config import AppConfig
from lance_explorer.paths import normalize_uri, parent_uri


def initialize_state(config: AppConfig) -> None:
    """Populate Streamlit session defaults without overwriting existing state."""

    defaults = {
        "current_uri": normalize_uri(config.home_uri),
        "selected_table_uri": "",
        "selected_table_history": [],
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

    normalized = normalize_uri(uri)
    if st.session_state.get("selected_table_uri") != normalized:
        st.session_state.query_results = {}
        st.session_state.pop("table_preview", None)
        st.session_state.pop("table_schema_diff", None)
    st.session_state.selected_table_uri = normalized
    history = [
        item
        for item in st.session_state.get("selected_table_history", [])
        if item != normalized
    ]
    st.session_state.selected_table_history = [normalized, *history][:20]


def generation_for(resource_uri: str) -> int:
    """Return the current cache generation for a URI."""

    return int(st.session_state.cache_generations.get(resource_uri, 0))


def bump_generation(resource_uri: str) -> int:
    """Increment the cache generation for a URI after refresh or mutation."""

    generations = dict(st.session_state.cache_generations)
    generations[resource_uri] = int(generations.get(resource_uri, 0)) + 1
    st.session_state.cache_generations = generations
    return generations[resource_uri]
