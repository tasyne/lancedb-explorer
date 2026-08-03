from __future__ import annotations

import io
import os
import tarfile
from dataclasses import dataclass
from functools import cache
from pathlib import Path


@dataclass(frozen=True, slots=True)
class LanguageModelSpec:
    """Packaged tokenizer model metadata used by FTS UI and generated code."""

    key: str
    label: str
    tokenizer: str
    language: str
    description: str
    relative_path: Path
    archive_name: str


_PACKAGED_MODEL_SPECS: tuple[LanguageModelSpec, ...] = (
    LanguageModelSpec(
        "jieba_default",
        "Jieba default - Mandarin Chinese",
        "jieba/default",
        "Mandarin Chinese",
        "Jieba dictionary, IDF, stop words, and alternate dictionary size files.",
        Path("jieba/default"),
        "lance-language-model-jieba-default.tar.gz",
    ),
)

_EXTERNAL_MODEL_SPECS: tuple[LanguageModelSpec, ...] = (
    LanguageModelSpec(
        "lindera_ipadic",
        "Lindera IPADIC - Japanese",
        "lindera/ipadic",
        "Japanese",
        "Externally supplied Japanese IPADIC dictionary compiled for Lindera tokenization.",
        Path("lindera/ipadic"),
        "",
    ),
    LanguageModelSpec(
        "lindera_unidic",
        "Lindera UniDic - Japanese",
        "lindera/unidic",
        "Japanese",
        "Externally supplied Japanese UniDic dictionary compiled for Lindera tokenization.",
        Path("lindera/unidic"),
        "",
    ),
    LanguageModelSpec(
        "lindera_ko_dic",
        "Lindera ko-dic - Korean",
        "lindera/ko-dic",
        "Korean",
        "Externally supplied Korean ko-dic dictionary compiled for Lindera tokenization.",
        Path("lindera/ko-dic"),
        "",
    ),
)

_JIEBA_REQUIRED_FILES = ("dict.txt", "idf.txt", "stop_words.txt")


def packaged_language_model_home() -> Path:
    """Return the bundled Lance language-model root."""

    return Path(__file__).with_name("language_models")


def packaged_language_models() -> tuple[LanguageModelSpec, ...]:
    """Return metadata for tokenizer models bundled with the application."""

    return _PACKAGED_MODEL_SPECS


def external_language_models() -> tuple[LanguageModelSpec, ...]:
    """Return model-backed tokenizers supported when users supply files themselves."""

    return _EXTERNAL_MODEL_SPECS


def model_backed_tokenizers() -> tuple[str, ...]:
    """Return base_tokenizer values that require external model files."""

    return tuple(spec.tokenizer for spec in (*_PACKAGED_MODEL_SPECS, *_EXTERNAL_MODEL_SPECS))


def language_model_for_tokenizer(base_tokenizer: str) -> LanguageModelSpec | None:
    """Return packaged model metadata for a Lance FTS base_tokenizer value."""

    for spec in _PACKAGED_MODEL_SPECS:
        if spec.tokenizer == base_tokenizer:
            return spec
    return None


def fts_uses_packaged_language_model(config_options: dict[str, object]) -> bool:
    """Return whether FTS options require bundled tokenizer model files."""

    return language_model_for_tokenizer(str(config_options.get("base_tokenizer", ""))) is not None


def ensure_packaged_language_model_home(base_tokenizer: str | None = None) -> Path:
    """Point Lance at bundled tokenizer files unless the caller already configured a home."""

    del base_tokenizer
    home = packaged_language_model_home()
    current = os.environ.get("LANCE_LANGUAGE_MODEL_HOME")
    if current:
        current_path = Path(current)
        if _has_packaged_jieba_files(current_path):
            return current_path
        if not _looks_like_lance_default_home(current_path):
            return current_path
    os.environ["LANCE_LANGUAGE_MODEL_HOME"] = str(home)
    return Path(os.environ["LANCE_LANGUAGE_MODEL_HOME"])


def configure_packaged_language_model(base_tokenizer: str) -> Path:
    """Configure environment variables required by a packaged model-backed tokenizer."""

    if language_model_for_tokenizer(base_tokenizer) is None:
        raise ValueError(f"No packaged language model is registered for {base_tokenizer!r}")
    return ensure_packaged_language_model_home(base_tokenizer)


def language_model_archive_name(model_key: str) -> str:
    """Return the downloadable archive filename for a packaged language model."""

    return _model_spec(model_key).archive_name


@cache
def language_model_archive_bytes(model_key: str) -> bytes:
    """Build a gzipped tar archive for one packaged tokenizer model."""

    spec = _model_spec(model_key)
    root = packaged_language_model_home()
    model_root = root / spec.relative_path
    if not model_root.exists():
        raise FileNotFoundError(f"Packaged language model is missing: {spec.tokenizer}")

    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for path in sorted(item for item in model_root.rglob("*") if item.is_file()):
            archive.add(path, arcname=Path("language_models") / path.relative_to(root))
        _add_archive_readme(archive, spec)
    return output.getvalue()


def _model_spec(model_key: str) -> LanguageModelSpec:
    for spec in _PACKAGED_MODEL_SPECS:
        if spec.key == model_key:
            return spec
    raise KeyError(f"Unknown packaged language model: {model_key}")


def _has_packaged_jieba_files(home: Path) -> bool:
    model_path = home / "jieba" / "default"
    return all((model_path / filename).exists() for filename in _JIEBA_REQUIRED_FILES)


def _looks_like_lance_default_home(path: Path) -> bool:
    normalized = path.as_posix().lower()
    return normalized.endswith("/lance/language_models") and (
        "/appdata/local/" in normalized
        or "/.local/share/" in normalized
        or "/library/application support/" in normalized
    )


def _add_archive_readme(archive: tarfile.TarFile, spec: LanguageModelSpec) -> None:
    readme = (
        f"{spec.label}\n\n"
        f"LanceDB base_tokenizer: {spec.tokenizer}\n"
        f"Language: {spec.language}\n\n"
        "Extract the language_models/ directory from this archive and point "
        "LANCE_LANGUAGE_MODEL_HOME at the extracted language_models directory. Jieba can be "
        "used directly. "
        "For Lindera, create a config.yml or set LINDERA_CONFIG_PATH so segmenter.dictionary "
        "points at the extracted main dictionary directory.\n\n"
        "Review the upstream dictionary license before redistributing this archive.\n"
    ).encode()
    info = tarfile.TarInfo("README-LANCE-EXPLORER.txt")
    info.size = len(readme)
    archive.addfile(info, io.BytesIO(readme))
