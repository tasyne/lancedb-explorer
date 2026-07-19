from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_TRUE_VALUES = {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class AppConfig:
    home_uri: str
    template_override_dir: Path | None
    max_query_rows: int = 10_000
    default_query_rows: int = 100
    local_listing_ttl: int = 5
    remote_listing_ttl: int = 15
    metadata_ttl: int = 20

    @classmethod
    def from_env(cls) -> AppConfig:
        override = os.getenv("LANCE_EXPLORER_TEMPLATE_DIR")
        return cls(
            home_uri=os.getenv("LANCE_EXPLORER_HOME_URI", str(Path.home())),
            template_override_dir=Path(override).expanduser() if override else None,
            max_query_rows=int(os.getenv("LANCE_EXPLORER_MAX_QUERY_ROWS", "10000")),
            default_query_rows=int(os.getenv("LANCE_EXPLORER_DEFAULT_QUERY_ROWS", "100")),
        )


def lancedb_storage_options_from_env() -> dict[str, str]:
    """Return non-secret LanceDB storage options.

    Credentials are intentionally left to the normal AWS environment/provider chain.
    """

    mapping = {
        "endpoint": os.getenv("AWS_ENDPOINT") or os.getenv("AWS_ENDPOINT_URL"),
        "region": os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION"),
        "allow_http": os.getenv("ALLOW_HTTP"),
    }
    return {key: value for key, value in mapping.items() if value}


def upath_storage_options_from_env(uri: str) -> dict[str, object]:
    """Translate runtime environment settings into s3fs-compatible UPath options."""

    if not uri.lower().startswith(("s3://", "s3a://")):
        return {}

    options: dict[str, object] = {}
    endpoint = os.getenv("AWS_ENDPOINT") or os.getenv("AWS_ENDPOINT_URL")
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")

    client_kwargs: dict[str, str] = {}
    if endpoint:
        client_kwargs["endpoint_url"] = endpoint
    if region:
        client_kwargs["region_name"] = region
    if client_kwargs:
        options["client_kwargs"] = client_kwargs

    # Explicit values are optional. If omitted, s3fs uses the normal AWS provider chain.
    if key := os.getenv("AWS_ACCESS_KEY_ID"):
        options["key"] = key
    if secret := os.getenv("AWS_SECRET_ACCESS_KEY"):
        options["secret"] = secret
    if token := os.getenv("AWS_SESSION_TOKEN"):
        options["token"] = token

    allow_http = os.getenv("ALLOW_HTTP", "false").lower() in _TRUE_VALUES
    if endpoint and endpoint.lower().startswith("http://") and allow_http:
        options["use_ssl"] = False

    return options
