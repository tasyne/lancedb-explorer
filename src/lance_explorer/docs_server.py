from __future__ import annotations

import hashlib
import os
import socket
import tempfile
import zipfile
from dataclasses import dataclass
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread


@dataclass(frozen=True, slots=True)
class DocsMirrorSpec:
    slug: str
    title: str
    zip_name: str
    source_url: str


@dataclass(frozen=True, slots=True)
class DocsServer:
    base_url: str
    root: Path
    server: ThreadingHTTPServer
    thread: Thread


DOCS_MIRRORS = [
    DocsMirrorSpec(
        slug="lancedb-docs",
        title="LanceDB Docs",
        zip_name="lancedb-docs.zip",
        source_url="https://docs.lancedb.com/",
    ),
    DocsMirrorSpec(
        slug="lancedb-python-api",
        title="LanceDB Python API",
        zip_name="lancedb-python-api.zip",
        source_url="https://lancedb.github.io/lancedb/python/python/",
    ),
]


class QuietStaticHandler(SimpleHTTPRequestHandler):
    def guess_type(self, path: str) -> str:
        if ".js@" in path:
            return "application/javascript"
        if ".css@" in path:
            return "text/css"
        return super().guess_type(path)

    def log_message(self, format: str, *args: object) -> None:
        return


def docs_mirror_dir() -> Path:
    configured = os.getenv("LANCE_EXPLORER_DOCS_MIRROR_DIR")
    return Path(configured).expanduser() if configured else Path.cwd() / "docs_mirrors"


def expected_zip_path(spec: DocsMirrorSpec) -> Path:
    return docs_mirror_dir() / spec.zip_name


def extract_docs_zip(zip_path: Path, slug: str) -> Path:
    digest = _file_digest(zip_path)
    target = Path(tempfile.gettempdir()) / "lance_explorer_docs" / slug / digest
    index_path = target / "index.html"
    if index_path.exists():
        return target

    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            destination = target / member.filename
            if not _is_relative_to(destination.resolve(), target.resolve()):
                raise ValueError(f"Unsafe path in docs archive: {member.filename}")
        archive.extractall(target)

    if not index_path.exists():
        raise FileNotFoundError(f"{zip_path} does not contain index.html at the zip root")
    return target


def start_docs_server(root: Path) -> DocsServer:
    port = _free_port()
    handler = partial(QuietStaticHandler, directory=str(root))
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return DocsServer(
        base_url=f"http://127.0.0.1:{port}",
        root=root,
        server=server,
        thread=thread,
    )


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _file_digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()[:16]


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False
