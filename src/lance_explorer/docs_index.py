from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlparse

_LLMS_ENTRY_RE = re.compile(r"^- \[([^\]]+)]\(([^)]+)\)(?::\s*(.*))?$")


@dataclass(frozen=True, slots=True)
class DocsIndexEntry:
    """One link parsed from an offline docs `llms.txt` index."""

    llms_section: str
    title: str
    url: str
    description: str
    markdown_path: str | None
    group_path: tuple[str, ...]


def parse_llms_index(text: str) -> list[DocsIndexEntry]:
    """Parse Mintlify-style `llms.txt` links while preserving section headings."""

    section = "Docs"
    entries: list[DocsIndexEntry] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            section = line.removeprefix("## ").strip()
            continue

        match = _LLMS_ENTRY_RE.match(line)
        if not match:
            continue

        title, url, description = match.groups()
        markdown_path = markdown_path_from_url(url)
        entries.append(
            DocsIndexEntry(
                llms_section=section,
                title=title.strip(),
                url=url.strip(),
                description=(description or "").strip(),
                markdown_path=markdown_path,
                group_path=group_path_for_markdown_path(markdown_path),
            )
        )

    return entries


def load_llms_index(root: Path) -> list[DocsIndexEntry]:
    """Load `llms.txt` from an extracted docs mirror, if present."""

    llms_path = root / "llms.txt"
    if not llms_path.exists():
        return []
    return parse_llms_index(llms_path.read_text(encoding="utf-8"))


def markdown_path_from_url(url: str) -> str | None:
    """Return a local markdown path for docs links, ignoring non-markdown assets."""

    parsed = urlparse(url)
    path = unquote(parsed.path).lstrip("/")
    if not path.endswith(".md"):
        return None
    return PurePosixPath(path).as_posix()


def group_path_for_markdown_path(markdown_path: str | None) -> tuple[str, ...]:
    """Infer a display group from a markdown path when `llms.txt` is flat."""

    if not markdown_path:
        return ()

    path = PurePosixPath(markdown_path)
    parts = list(path.parts[:-1])
    if path.name != "index.md":
        return tuple(_humanize_path_part(part) for part in parts)
    return tuple(_humanize_path_part(part) for part in parts)


def local_markdown_path(root: Path, markdown_path: str) -> Path:
    """Resolve an index markdown path under an extracted mirror root."""

    return root.joinpath(*PurePosixPath(markdown_path).parts)


def _humanize_path_part(part: str) -> str:
    replacements = {
        "ai": "AI",
        "api": "API",
        "api-reference": "API Reference",
        "aws": "AWS",
        "faq": "FAQ",
        "fts": "FTS",
        "llm": "LLM",
        "llms": "LLMs",
        "rest": "REST",
        "sdk": "SDK",
        "sql": "SQL",
        "udf": "UDF",
        "udfs": "UDFs",
        "udtf": "UDTF",
        "udtfs": "UDTFs",
    }
    if part.lower() in replacements:
        return replacements[part.lower()]
    return " ".join(
        replacements.get(piece.lower(), piece.capitalize())
        for piece in part.replace("_", "-").split("-")
    )
