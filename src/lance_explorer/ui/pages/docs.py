from __future__ import annotations

from pathlib import Path

import streamlit as st

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


def render() -> None:
    st.title("Docs")
    selected = st.selectbox(
        "Documentation",
        DOCS_MIRRORS,
        format_func=lambda spec: spec.title,
    )
    zip_path = expected_zip_path(selected)

    if not zip_path.exists():
        _show_missing_docs(selected.title, selected.source_url, zip_path)
        return

    try:
        server = _docs_server_for(str(zip_path), selected.slug, zip_path.stat().st_mtime_ns)
    except Exception as exc:
        st.error(f"Unable to load documentation mirror: {exc}")
        return

    st.caption(f"Serving `{zip_path}` from `{server.base_url}`")
    st.iframe(f"{server.base_url}/index.html", height=900)


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
