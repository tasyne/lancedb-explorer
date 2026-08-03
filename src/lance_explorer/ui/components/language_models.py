from __future__ import annotations

import pandas as pd
import streamlit as st

from lance_explorer.language_models import (
    external_language_models,
    language_model_archive_bytes,
    language_model_archive_name,
    packaged_language_models,
)


def show_language_model_downloads(*, expanded: bool = False, key_prefix: str = "fts") -> None:
    """Render FTS tokenizer model downloads and external-model setup notes."""

    packaged = packaged_language_models()
    external = external_language_models()
    with st.expander("FTS language model downloads", expanded=expanded, icon=":material/download:"):
        st.write(
            "Download packaged tokenizer files when another machine needs to reproduce the same "
            "model-backed FTS index or query setup."
        )
        st.caption("The packaged download currently applies only to the Jieba base tokenizer.")
        if packaged:
            st.caption("Packaged and downloadable")
            st.dataframe(
                pd.DataFrame(
                    {
                        "tokenizer": spec.tokenizer,
                        "language": spec.language,
                        "contents": spec.description,
                    }
                    for spec in packaged
                ),
                width="stretch",
                hide_index=True,
            )
            selected = st.selectbox(
                "Downloadable archive",
                [spec.key for spec in packaged],
                format_func={spec.key: spec.label for spec in packaged}.get,
                key=f"{key_prefix}-language-model-download",
            )
            st.download_button(
                "Download Jieba .tar.gz",
                data=language_model_archive_bytes(selected),
                file_name=language_model_archive_name(selected),
                mime="application/gzip",
                icon=":material/download:",
                key=f"{key_prefix}-download-{selected}",
            )
        else:
            st.caption("No packaged tokenizer models are available.")

        if external:
            st.caption("Supported external model-backed tokenizers")
            st.dataframe(
                pd.DataFrame(
                    {
                        "tokenizer": spec.tokenizer,
                        "language": spec.language,
                        "required files": f"$LANCE_LANGUAGE_MODEL_HOME/{spec.relative_path}/main",
                    }
                    for spec in external
                ),
                width="stretch",
                hide_index=True,
            )
            st.caption(
                "Lindera dictionaries are intentionally not bundled. Supply compiled "
                "dictionaries externally, set `LANCE_LANGUAGE_MODEL_HOME`, and set "
                "`LINDERA_CONFIG_PATH` to a config.yml whose `segmenter.dictionary` value points "
                "at the compiled `main` directory."
            )

        st.caption(
            "Multiple language-specific FTS indexes can exist on one table. When querying, use "
            "`fts_columns` to select the intended indexed column."
        )
