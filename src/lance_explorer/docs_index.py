from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlparse

_LLMS_ENTRY_RE = re.compile(r"^[*-]\s+\[([^\]]+)]\(([^)]+)\)(?::\s*(.*))?$")


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
        heading = _markdown_heading(line)
        if heading:
            section = heading
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
    """Load `llms.txt` and merge in any mirrored markdown pages it omitted."""

    llms_path = root / "llms.txt"
    entries = (
        parse_llms_index(llms_path.read_text(encoding="utf-8", errors="replace"))
        if llms_path.exists()
        else []
    )
    return _merge_entries(entries, discover_markdown_entries(root))


def discover_markdown_entries(root: Path) -> list[DocsIndexEntry]:
    """Discover local markdown files so the docs index survives partial `llms.txt` data."""

    entries: list[DocsIndexEntry] = []
    for path in sorted(root.rglob("*.md")):
        if not path.is_file():
            continue
        markdown_path = path.relative_to(root).as_posix()
        group_path = group_path_for_markdown_path(markdown_path)
        entries.append(
            DocsIndexEntry(
                llms_section=group_path[0] if group_path else "Docs",
                title=_title_for_markdown_path(markdown_path),
                url=markdown_path,
                description="",
                markdown_path=markdown_path,
                group_path=group_path,
            )
        )
    return entries


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

    path = root.joinpath(*PurePosixPath(markdown_path).parts)
    if path.exists():
        return path

    current = root
    for part in PurePosixPath(markdown_path).parts:
        if not current.exists() or not current.is_dir():
            return path
        matches = [child for child in current.iterdir() if child.name.casefold() == part.casefold()]
        if not matches:
            return path
        current = matches[0]
    return current


def _markdown_heading(line: str) -> str | None:
    if not line.startswith("#"):
        return None
    marker, _, title = line.partition(" ")
    if not marker or any(character != "#" for character in marker):
        return None
    title = title.strip()
    return title or None


def _merge_entries(
    primary: list[DocsIndexEntry],
    fallback: list[DocsIndexEntry],
) -> list[DocsIndexEntry]:
    output = list(primary)
    known_paths = {entry.markdown_path for entry in output if entry.markdown_path}
    for entry in fallback:
        if entry.markdown_path and entry.markdown_path not in known_paths:
            output.append(entry)
            known_paths.add(entry.markdown_path)
    return output


def _title_for_markdown_path(markdown_path: str) -> str:
    path = PurePosixPath(markdown_path)
    if path.name == "index.md" and path.parent.parts:
        return _humanize_path_part(path.parent.parts[-1])
    return _humanize_path_part(path.stem)


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
