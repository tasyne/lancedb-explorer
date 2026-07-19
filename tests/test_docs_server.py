from pathlib import Path
from zipfile import ZipFile

import pytest

from lance_explorer.docs_server import QuietStaticHandler, extract_docs_zip


def test_extract_docs_zip_requires_root_index(tmp_path: Path) -> None:
    zip_path = tmp_path / "docs.zip"
    with ZipFile(zip_path, "w") as archive:
        archive.writestr("index.html", "<h1>Docs</h1>")
        archive.writestr("assets/site.css", "body { font-family: sans-serif; }")

    root = extract_docs_zip(zip_path, "docs")

    assert (root / "index.html").read_text(encoding="utf-8") == "<h1>Docs</h1>"
    assert (root / "assets" / "site.css").exists()


def test_extract_docs_zip_rejects_archives_without_root_index(tmp_path: Path) -> None:
    zip_path = tmp_path / "docs.zip"
    with ZipFile(zip_path, "w") as archive:
        archive.writestr("nested/index.html", "<h1>Docs</h1>")

    with pytest.raises(FileNotFoundError, match="index.html at the zip root"):
        extract_docs_zip(zip_path, "nested-docs")


def test_extract_docs_zip_rejects_unsafe_paths(tmp_path: Path) -> None:
    zip_path = tmp_path / "docs.zip"
    with ZipFile(zip_path, "w") as archive:
        archive.writestr("index.html", "<h1>Docs</h1>")
        archive.writestr("../escape.txt", "nope")

    with pytest.raises(ValueError, match="Unsafe path"):
        extract_docs_zip(zip_path, "unsafe-docs")


def test_static_handler_serves_mintlify_js_with_javascript_mime_type() -> None:
    assert (
        QuietStaticHandler.guess_type(
            QuietStaticHandler,
            "mintlify-assets/_next/static/chunks/app.js@dpl=abc123",
        )
        == "application/javascript"
    )


def test_static_handler_serves_mintlify_css_with_css_mime_type() -> None:
    assert (
        QuietStaticHandler.guess_type(
            QuietStaticHandler,
            "mintlify-assets/_next/static/chunks/app.css@dpl=abc123",
        )
        == "text/css"
    )
