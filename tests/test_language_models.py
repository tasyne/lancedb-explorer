import os
import tarfile
from io import BytesIO

from lance_explorer.language_models import (
    configure_packaged_language_model,
    external_language_models,
    language_model_archive_bytes,
    language_model_for_tokenizer,
    packaged_language_model_home,
    packaged_language_models,
)


def test_packaged_language_model_registry_covers_model_backed_tokenizers() -> None:
    tokenizers = {spec.tokenizer for spec in packaged_language_models()}
    external_tokenizers = {spec.tokenizer for spec in external_language_models()}

    assert tokenizers == {"jieba/default"}
    assert {"lindera/ipadic", "lindera/unidic", "lindera/ko-dic"} <= external_tokenizers
    assert language_model_for_tokenizer("icu") is None
    assert language_model_for_tokenizer("lindera/ipadic") is None


def test_packaged_jieba_configuration_sets_model_home(monkeypatch) -> None:
    monkeypatch.delenv("LANCE_LANGUAGE_MODEL_HOME", raising=False)
    monkeypatch.delenv("LINDERA_CONFIG_PATH", raising=False)

    home = configure_packaged_language_model("jieba/default")

    assert os.environ["LANCE_LANGUAGE_MODEL_HOME"] == str(home)
    assert "LINDERA_CONFIG_PATH" not in os.environ


def test_language_model_archive_contains_lance_model_home_layout() -> None:
    with tarfile.open(fileobj=BytesIO(language_model_archive_bytes("jieba_default"))) as archive:
        names = set(archive.getnames())

    assert "language_models/jieba/default/dict.txt" in names
    assert "language_models/jieba/default/idf.txt" in names
    assert "language_models/jieba/default/stop_words.txt" in names
    assert "README-LANCE-EXPLORER.txt" in names


def test_lindera_placeholders_do_not_bundle_dictionary_binaries() -> None:
    lindera_root = packaged_language_model_home() / "lindera"
    payload_files = [
        path
        for path in lindera_root.rglob("*")
        if path.is_file() and path.name != ".gitkeep"
    ]

    assert payload_files == []
