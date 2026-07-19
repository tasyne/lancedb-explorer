from __future__ import annotations

import html
import json
import uuid

import streamlit as st

from lance_explorer.codegen import TemplateRenderer
from lance_explorer.ui.help_text import help_text


@st.cache_resource(show_spinner=False)
def get_template_renderer(template_directory: str | None = None) -> TemplateRenderer:
    return TemplateRenderer(template_directory)


@st.cache_data(max_entries=512, show_spinner=False)
def render_code(
    template_id: str,
    context_json: str,
    template_directory: str | None,
    template_fingerprint: str,
) -> str:
    del template_fingerprint
    renderer = get_template_renderer(template_directory)
    return renderer.render(template_id, json.loads(context_json))


def show_code_export(
    template_id: str,
    context: dict[str, object],
    *,
    template_directory: str | None = None,
    label: str = "Code export",
) -> None:
    renderer = get_template_renderer(template_directory)
    spec = renderer.registry.get(template_id)
    context_json = json.dumps(context, sort_keys=True, default=str)
    code = render_code(
        template_id,
        context_json,
        template_directory,
        renderer.registry.fingerprint(template_id),
    )

    with st.expander(label, expanded=False, icon=":material/code:"):
        st.caption(spec.title, help=help_text("code_export"))
        st.code(code, language=spec.language, line_numbers=False)
        _copy_button(code, key_prefix=template_id)


def _copy_button(code: str, *, key_prefix: str) -> None:
    element_id = f"copy-{key_prefix}-{uuid.uuid4().hex}"
    escaped_code = html.escape(code)
    escaped_id = html.escape(element_id)
    st.html(
        f"""
        <div style="font-family: sans-serif; display: flex; justify-content: flex-end;">
          <textarea id="{escaped_id}-source"
            style="position:absolute;left:-9999px;">{escaped_code}</textarea>
          <button id="{escaped_id}" type="button"
            style="border:1px solid #888;border-radius:8px;padding:0.35rem 0.8rem;
              background:transparent;cursor:pointer;">
            Copy
          </button>
          <span id="{escaped_id}-status" aria-live="polite"
            style="margin-left:0.5rem;padding-top:0.35rem;"></span>
        </div>
        <script>
          const button = document.getElementById({json.dumps(element_id)});
          const source = document.getElementById({json.dumps(element_id + "-source")});
          const status = document.getElementById({json.dumps(element_id + "-status")});
          button.addEventListener('click', async () => {{
            try {{
              await navigator.clipboard.writeText(source.value);
              status.textContent = 'Copied';
            }} catch (error) {{
              source.style.position = 'static';
              source.select();
              document.execCommand('copy');
              source.style.position = 'absolute';
              status.textContent = 'Copied';
            }}
          }});
        </script>
        """,
        width="content",
        unsafe_allow_javascript=True,
    )
