from __future__ import annotations

import html
import json
import re
import uuid

import streamlit as st


def browser_copy_button(
    value: str,
    *,
    key_prefix: str,
    label: str = "Copy",
    help_text: str = "Copy to clipboard",
    compact: bool = False,
) -> None:
    """Render a browser-side copy button without touching the server clipboard."""

    safe_prefix = re.sub(r"[^A-Za-z0-9_-]", "-", key_prefix)[:60]
    element_id = f"copy-{safe_prefix}-{uuid.uuid4().hex}"
    escaped_id = html.escape(element_id)
    escaped_value = html.escape(value)
    escaped_label = html.escape(label)
    escaped_help = html.escape(help_text)
    padding = "0.2rem 0.35rem" if compact else "0.35rem 0.8rem"
    font_size = "0.75rem" if compact else "0.875rem"

    height = 30 if compact else 38
    st.iframe(
        f"""
        <!doctype html>
        <html>
        <body style="margin:0;">
        <div style="font-family: sans-serif; display: flex; align-items: center;
          justify-content: flex-end; gap: 0.35rem; width: 100%;">
          <button id="{escaped_id}" type="button" title="{escaped_help}"
            style="border:1px solid #888;border-radius:6px;padding:{padding};
              background:transparent;cursor:pointer;font-size:{font_size};line-height:1.2;
              transition:background-color 120ms ease,border-color 120ms ease,color 120ms ease;">
            {escaped_label}
          </button>
          <span id="{escaped_id}-status" aria-live="polite"
            style="font-size:0.75rem;white-space:nowrap;"></span>
        </div>
        <textarea id="{escaped_id}-source" readonly
          style="position:fixed;left:-1000px;top:0;width:1px;height:1px;">{escaped_value}</textarea>
        <style>
          #{escaped_id}.copy-flash {{
            background:#2563eb !important;
            border-color:#2563eb !important;
            color:#fff !important;
          }}
        </style>
        <script>
          const button = document.getElementById({json.dumps(element_id)});
          const source = document.getElementById({json.dumps(element_id + "-source")});
          const status = document.getElementById({json.dumps(element_id + "-status")});

          function flashCopied() {{
            status.textContent = '';
            button.classList.add('copy-flash');
            window.setTimeout(() => button.classList.remove('copy-flash'), 650);
          }}

          function revealManualCopy() {{
            source.style.position = 'static';
            source.style.width = '100%';
            source.style.height = '4rem';
            source.focus();
            source.select();
            status.textContent = 'Press Ctrl+C';
          }}

          function legacyCopy() {{
            source.style.position = 'fixed';
            source.style.left = '0';
            source.style.top = '0';
            source.style.width = '2px';
            source.style.height = '2px';
            source.focus();
            source.select();
            source.setSelectionRange(0, source.value.length);
            const copied = document.execCommand('copy');
            source.style.position = 'fixed';
            source.style.left = '-1000px';
            source.style.width = '1px';
            source.style.height = '1px';
            return copied;
          }}

          button.addEventListener('click', async () => {{
            try {{
              if (navigator.clipboard && window.isSecureContext) {{
                await navigator.clipboard.writeText(source.value);
              }} else {{
                if (!legacyCopy()) {{
                  throw new Error('copy command failed');
                }}
              }}
              flashCopied();
            }} catch (error) {{
              revealManualCopy();
            }}
          }});
        </script>
        </body>
        </html>
        """,
        height=height,
    )
