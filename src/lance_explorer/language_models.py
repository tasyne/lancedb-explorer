from __future__ import annotations

import os
from pathlib import Path


def packaged_language_model_home() -> Path:
    """Return the bundled Lance language-model root."""

    return Path(__file__).with_name("language_models")


def ensure_packaged_language_model_home() -> Path:
    """Point Lance at bundled tokenizer files unless the caller already configured a home."""

    home = packaged_language_model_home()
    os.environ.setdefault("LANCE_LANGUAGE_MODEL_HOME", str(home))
    return Path(os.environ["LANCE_LANGUAGE_MODEL_HOME"])
