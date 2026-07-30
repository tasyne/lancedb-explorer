from __future__ import annotations

import json

import streamlit as st

from lance_explorer.codegen import TemplateRenderer
from lance_explorer.ui.components.clipboard import browser_copy_button
from lance_explorer.ui.help_text import help_text


@st.cache_resource(show_spinner=False)
def get_template_renderer(template_directory: str | None = None) -> TemplateRenderer:
    """Return the cached renderer for the configured template directory."""

    return TemplateRenderer(template_directory)


@st.cache_data(max_entries=512, show_spinner=False)
def render_code(
    template_id: str,
    context_json: str,
    template_directory: str | None,
    template_fingerprint: str,
) -> str:
    """Render code with cache invalidation tied to template fingerprints."""

    del template_fingerprint
    renderer = get_template_renderer(template_directory)
    return renderer.render(template_id, json.loads(context_json))


def show_code_export(
    template_id: str,
    context: dict[str, object],
    *,
    template_directory: str | None = None,
    label: str | None = None,
) -> None:
    """Render a labeled code-export expander with copy support."""

    renderer = get_template_renderer(template_directory)
    spec = renderer.registry.get(template_id)
    expander_label = label or f"Code export: {spec.title}"
    context_json = json.dumps(context, sort_keys=True, default=str)
    code = render_code(
        template_id,
        context_json,
        template_directory,
        renderer.registry.fingerprint(template_id),
    )

    with st.expander(expander_label, expanded=False, icon=":material/code:"):
        st.caption(spec.title, help=help_text("code_export"))
        st.code(code, language=spec.language, line_numbers=False)
        browser_copy_button(code, key_prefix=template_id)
