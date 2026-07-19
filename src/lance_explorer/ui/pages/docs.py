from __future__ import annotations

from pathlib import Path

import streamlit as st

from lance_explorer.docs_index import (
    DocsIndexEntry,
    load_llms_index,
    local_markdown_path,
)
from lance_explorer.docs_server import (
    DOCS_MIRRORS,
    DocsServer,
    docs_mirror_dir,
    expected_zip_path,
    extract_docs_zip,
    start_docs_server,
)


@st.cache_resource(show_spinner=False)
def _docs_server_for(zip_path: str, slug: str, modified_ns: int) -> DocsServer:
    del modified_ns
    root = extract_docs_zip(Path(zip_path), slug)
    return start_docs_server(root)


@st.cache_data(show_spinner=False)
def _docs_index_for(root: str, modified_ns: int) -> list[DocsIndexEntry]:
    del modified_ns
    return load_llms_index(Path(root))


def render() -> None:
    st.title("Docs")
    st.info(
        "If navigation links inside the mirrored documentation do not work, use the "
        "`Offline Index` view. The embedded docs can reflow and hide navigation in "
        "narrow windows, so maximize your browser window for the best layout."
    )
    selected_slug = st.query_params.get("docs_mirror")
    selected_index = next(
        (index for index, spec in enumerate(DOCS_MIRRORS) if spec.slug == selected_slug),
        0,
    )
    selected = st.selectbox(
        "Documentation",
        DOCS_MIRRORS,
        index=selected_index,
        format_func=lambda spec: spec.title,
    )
    st.query_params["docs_mirror"] = selected.slug
    zip_path = expected_zip_path(selected)

    if not zip_path.exists():
        _show_missing_docs(selected.title, selected.source_url, zip_path)
        return

    try:
        server = _docs_server_for(str(zip_path), selected.slug, zip_path.stat().st_mtime_ns)
    except Exception as exc:
        st.error(f"Unable to load documentation mirror: {exc}")
        return

    view = st.radio(
        "View",
        ["Offline Index", "Mirrored Website"],
        horizontal=True,
        label_visibility="collapsed",
    )
    st.caption(f"Serving `{zip_path}` from `{server.base_url}`")

    if view == "Mirrored Website":
        st.iframe(f"{server.base_url}/index.html", height=900)
        return

    entries = _docs_index_for(str(server.root), zip_path.stat().st_mtime_ns)
    markdown_entries = [
        entry
        for entry in entries
        if entry.markdown_path and local_markdown_path(server.root, entry.markdown_path).exists()
    ]
    if not markdown_entries:
        st.info("This mirror does not include a local markdown index in `llms.txt`.")
        st.iframe(f"{server.base_url}/index.html", height=900)
        return

    _render_indexed_website(
        root=server.root,
        docs_slug=selected.slug,
        docs_title=selected.title,
        static_base_url=server.base_url,
        entries=markdown_entries,
    )


def _show_missing_docs(title: str, source_url: str, zip_path: Path) -> None:
    mirror_dir = docs_mirror_dir()
    st.warning(f"{title} mirror archive was not found.")
    st.write("Expected archive:")
    st.code(str(zip_path), language="text")
    st.write("Create it on an internet-connected machine, then copy it into this folder:")
    st.code(str(mirror_dir), language="text")
    st.write("PowerShell:")
    st.code(".\\scripts\\mirror_docs.ps1", language="powershell")
    st.write("macOS/Linux:")
    st.code("./scripts/mirror_docs.sh", language="bash")
    st.caption(f"Source mirrored by the script: {source_url}")


def _render_indexed_website(
    *,
    root: Path,
    docs_slug: str,
    docs_title: str,
    static_base_url: str,
    entries: list[DocsIndexEntry],
) -> None:
    selected_path = _selected_markdown_path(docs_slug, entries)
    selected_entry = next(entry for entry in entries if entry.markdown_path == selected_path)

    nav_column, content_column = st.columns([0.28, 0.72], gap="large")
    with nav_column:
        st.subheader("Offline Index")
        query = st.text_input("Filter pages", placeholder="Search titles, paths, descriptions")
        filtered_entries = _filter_entries(entries, query)
        st.caption(f"{len(filtered_entries)} of {len(entries)} pages")
        _render_index_buttons(docs_slug, filtered_entries, selected_path, query)

    with content_column:
        markdown_file = local_markdown_path(root, selected_path)
        if not markdown_file.exists():
            st.error(f"Markdown file was listed in `llms.txt` but is missing: `{selected_path}`")
            return

        st.caption(_entry_location(docs_title, selected_entry))
        if selected_entry.description:
            st.info(selected_entry.description)

        mirrored_url = _mirrored_html_url(static_base_url, selected_path)
        st.markdown(f"[Open mirrored HTML page]({mirrored_url})")
        st.iframe(mirrored_url, height=900)


def _render_index_buttons(
    docs_slug: str,
    entries: list[DocsIndexEntry],
    selected_path: str,
    query: str,
) -> None:
    grouped = _group_entries(entries)
    for group_label, group_entries in grouped.items():
        is_selected_group = any(entry.markdown_path == selected_path for entry in group_entries)
        expanded = bool(query.strip()) or is_selected_group
        with st.expander(group_label, expanded=expanded):
            for entry in group_entries:
                if not entry.markdown_path:
                    continue
                label = entry.title
                if entry.markdown_path == selected_path:
                    label = f"-> {label}"
                if st.button(
                    label,
                    key=f"docs-nav-{docs_slug}-{entry.markdown_path}",
                    width="stretch",
                    type="primary" if entry.markdown_path == selected_path else "secondary",
                ):
                    _set_selected_markdown_path(docs_slug, entry.markdown_path)
                    st.rerun()
                if query.strip() and entry.description:
                    st.caption(entry.description)


def _selected_markdown_path(docs_slug: str, entries: list[DocsIndexEntry]) -> str:
    query_slug = st.query_params.get("docs_mirror")
    query_path = st.query_params.get("docs_md") if query_slug == docs_slug else None
    paths = {entry.markdown_path for entry in entries if entry.markdown_path}
    if query_path in paths:
        st.session_state[f"docs_selected_md_{docs_slug}"] = query_path
        return query_path

    session_path = st.session_state.get(f"docs_selected_md_{docs_slug}")
    if session_path in paths:
        return session_path

    for preferred in ("quickstart.md", "index.md"):
        if preferred in paths:
            return preferred
    return next(entry.markdown_path for entry in entries if entry.markdown_path)


def _set_selected_markdown_path(docs_slug: str, markdown_path: str) -> None:
    st.session_state[f"docs_selected_md_{docs_slug}"] = markdown_path
    st.query_params["docs_mirror"] = docs_slug
    st.query_params["docs_md"] = markdown_path


def _filter_entries(entries: list[DocsIndexEntry], query: str) -> list[DocsIndexEntry]:
    terms = [term.casefold() for term in query.split() if term.strip()]
    if not terms:
        return entries
    filtered = []
    for entry in entries:
        haystack = " ".join(
            [
                entry.title,
                entry.description,
                entry.markdown_path or "",
                " ".join(entry.group_path),
                entry.llms_section,
            ]
        ).casefold()
        if all(term in haystack for term in terms):
            filtered.append(entry)
    return filtered


def _group_entries(entries: list[DocsIndexEntry]) -> dict[str, list[DocsIndexEntry]]:
    grouped: dict[str, list[DocsIndexEntry]] = {}
    for entry in entries:
        label = " / ".join(entry.group_path) if entry.group_path else entry.llms_section
        grouped.setdefault(label, []).append(entry)
    return grouped


def _entry_location(docs_title: str, entry: DocsIndexEntry) -> str:
    group = " / ".join(entry.group_path) if entry.group_path else entry.llms_section
    return f"{docs_title} / {group} / {entry.title}"


def _mirrored_html_url(static_base_url: str, markdown_path: str) -> str:
    html_path = markdown_path.removesuffix(".md") + ".html"
    return f"{static_base_url}/{html_path}"
