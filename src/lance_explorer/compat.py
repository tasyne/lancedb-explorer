from __future__ import annotations

import re
from importlib.metadata import PackageNotFoundError, version
from typing import Any

MIN_RECOMMENDED_LANCEDB_VERSION = (0, 34, 0)


def lancedb_version_text() -> str:
    """Return the installed LanceDB package version, or an unknown marker."""

    try:
        return version("lancedb")
    except PackageNotFoundError:
        return "unknown"


def lancedb_version_tuple(version_text: str | None = None) -> tuple[int, int, int] | None:
    """Parse a semantic LanceDB version into a comparable tuple."""

    text = version_text or lancedb_version_text()
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", text)
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def is_lancedb_below_recommended(version_text: str | None = None) -> bool:
    """Return whether LanceDB is older than the app's full-feature target."""

    parsed = lancedb_version_tuple(version_text)
    return parsed is not None and parsed < MIN_RECOMMENDED_LANCEDB_VERSION


def lance_blob_v2_available(version_text: str | None = None) -> bool:
    """Return whether this environment can use Lance Blob v2 helper APIs."""

    parsed = lancedb_version_tuple(version_text)
    if parsed is None or parsed < MIN_RECOMMENDED_LANCEDB_VERSION:
        return False
    try:
        from lance import blob_array, blob_field  # noqa: F401
    except Exception:
        return False
    return True


def lancedb_supports_fts_icu(version_text: str | None = None) -> bool:
    """Return whether LanceDB should support ICU full-text tokenizers."""

    parsed = lancedb_version_tuple(version_text)
    return parsed is None or parsed >= MIN_RECOMMENDED_LANCEDB_VERSION


def lancedb_compatibility_warning(version_text: str | None = None) -> str | None:
    """Return a user-facing warning for reduced LanceDB compatibility."""

    text = version_text or lancedb_version_text()
    if not is_lancedb_below_recommended(text):
        return None
    return (
        f"LanceDB {text} is installed. Lance Explorer works best with LanceDB 0.34.0 or "
        "newer, but that package may not be installable on some older operating systems, "
        "where 0.33.x may be the newest usable release. The app will continue with reduced "
        "binary support: newer Lance table formats allow Blob v2 columns, which store larger "
        "binary payloads as file-like blob data with browser-displayable handles and avoid "
        "keeping full media bytes directly in row-local Arrow binary columns."
    )


def public_compatibility_status() -> dict[str, Any]:
    """Return JSON-safe runtime compatibility details for diagnostics."""

    text = lancedb_version_text()
    return {
        "lancedb_version": text,
        "recommended_minimum": ".".join(str(part) for part in MIN_RECOMMENDED_LANCEDB_VERSION),
        "blob_v2_available": lance_blob_v2_available(text),
        "warning": lancedb_compatibility_warning(text),
    }
