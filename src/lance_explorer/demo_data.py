from __future__ import annotations

import random
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import lancedb
import pyarrow as pa
from faker import Faker
from lance import blob_array, blob_field
from lancedb.index import FTS, IvfFlat

from lance_explorer.config import lancedb_storage_options_from_env
from lance_explorer.index_registry import fts_options_for_preset
from lance_explorer.paths import has_uri_scheme, split_table_uri

FAKER_LOCALE_ALIASES = {
    "usa": "en_US",
    "us": "en_US",
    "english": "en_US",
    "uk": "en_GB",
    "spanish": "es_ES",
    "spain": "es_ES",
    "mexico": "es_MX",
    "chinese": "zh_CN",
    "china": "zh_CN",
    "taiwan": "zh_TW",
    "japanese": "ja_JP",
    "french": "fr_FR",
    "german": "de_DE",
    "italian": "it_IT",
    "portuguese": "pt_BR",
    "brazil": "pt_BR",
    "korean": "ko_KR",
    "india": "en_IN",
}

DEMO_EMBEDDING_DIM = 64
DEMO_VECTOR_INDEX_NAME = "embedding_vector_idx"
DEMO_FTS_INDEX_NAME = "bio_multilingual_fts_idx"
DEMO_HEADSHOT_MIME = "image/png"
DEMO_HEADSHOT_ASSET_DIR = Path(__file__).with_name("demo_assets") / "headshots"
DEMO_HEADSHOT_FILENAMES = (
    "woman_01.png",
    "woman_02.png",
    "woman_03.png",
    "woman_04.png",
    "woman_05.png",
    "man_01.png",
    "man_02.png",
    "man_03.png",
    "man_04.png",
    "man_05.png",
)
DEMO_BINARY_COLUMNS = (
    "headshot_thumbnail_bytes",
    "headshot_full_bytes",
)

DEMO_SCHEMA = pa.schema(
    [
        pa.field("id", pa.int64()),
        pa.field("legal_name", pa.string()),
        pa.field("stage_name", pa.string()),
        pa.field("locale", pa.string()),
        pa.field("bio", pa.string()),
        pa.field("agency_email", pa.string()),
        pa.field("phone_number", pa.string()),
        pa.field("birth_date", pa.date32()),
        pa.field("home_city", pa.string()),
        pa.field("country", pa.string()),
        pa.field("genre", pa.list_(pa.string())),
        pa.field("award_count", pa.int16()),
        pa.field("popularity_score", pa.float32()),
        pa.field("active", pa.bool_()),
        pa.field("embedding", pa.list_(pa.float32(), DEMO_EMBEDDING_DIM)),
        pa.field("headshot_filename", pa.string()),
        pa.field("headshot_mime", pa.string()),
        pa.field("headshot_thumbnail_bytes", pa.binary()),
        blob_field("headshot_full_bytes"),
    ]
)
DEMO_VERSIONED_FIELD = pa.field("publicity_risk", pa.string())
DEMO_VERSIONED_SCHEMA = DEMO_SCHEMA.append(DEMO_VERSIONED_FIELD)

_GENRES = [
    "action",
    "arthouse",
    "comedy",
    "documentary",
    "drama",
    "historical",
    "musical",
    "science fiction",
    "thriller",
]

_BIO_TERMS = [
    "privacy request",
    "contract review",
    "rights management",
    "red carpet",
    "streaming release",
    "charity gala",
    "international press",
    "production dispute",
    "award campaign",
    "location shoot",
]


@dataclass(frozen=True, slots=True)
class DemoTableResult:
    """Summary of a generated demo Lance table."""

    table_uri: str
    database_uri: str
    table_name: str
    row_count: int
    version_count: int
    locale: str


def resolve_faker_locale(value: str) -> str:
    """Resolve a friendly Faker locale alias or pass through a locale code."""

    key = value.strip()
    if not key:
        raise ValueError("Faker locale cannot be empty")
    return FAKER_LOCALE_ALIASES.get(key.lower(), key)


def demo_rows(
    *,
    row_count: int = 100,
    locale: str = "usa",
    seed: int | None = None,
    include_publicity_risk: bool = False,
) -> list[dict[str, Any]]:
    """Generate fictional PII-style movie-star rows for demos."""

    if row_count < 1:
        raise ValueError("Demo row count must be at least 1")

    resolved_locale = resolve_faker_locale(locale)
    fake = Faker(resolved_locale)
    randomizer = random.Random(seed)
    if seed is not None:
        fake.seed_instance(seed)

    rows: list[dict[str, Any]] = []
    for row_id in range(1, row_count + 1):
        profile = fake.profile()
        legal_name = str(profile["name"])
        genres = randomizer.sample(_GENRES, k=randomizer.randint(1, min(5, len(_GENRES))))
        stage_name = f"{fake.first_name()} {fake.word().title()}"
        home_city = fake.city()
        country = fake.country()
        agency_email = str(profile.get("mail") or fake.email())
        phone_number = fake.phone_number()
        award_count = randomizer.randint(0, 18)
        active = randomizer.random() > 0.18
        publicity_risk = _publicity_risk(award_count, active)
        bio_terms = randomizer.sample(_BIO_TERMS, k=3)
        bio = (
            f"{stage_name} is a fictional {', '.join(genres)} movie star from "
            f"{home_city}, {country}. "
            f"The profile mentions {', '.join(bio_terms)} and an agency contact at "
            f"{agency_email}."
        )
        headshot_filename, thumbnail_bytes, full_bytes = _headshot_payload(row_id)
        row = {
            "id": row_id,
            "legal_name": legal_name,
            "stage_name": stage_name,
            "locale": resolved_locale,
            "bio": bio,
            "agency_email": agency_email,
            "phone_number": phone_number,
            "birth_date": profile["birthdate"],
            "home_city": home_city,
            "country": country,
            "genre": genres,
            "award_count": award_count,
            "popularity_score": round(randomizer.uniform(1.0, 100.0), 2),
            "active": active,
            "embedding": [
                round(randomizer.uniform(-1.0, 1.0), 6) for _ in range(DEMO_EMBEDDING_DIM)
            ],
            "headshot_filename": headshot_filename,
            "headshot_mime": DEMO_HEADSHOT_MIME,
            "headshot_thumbnail_bytes": thumbnail_bytes,
            "headshot_full_bytes": full_bytes,
        }
        if include_publicity_risk:
            row["publicity_risk"] = publicity_risk
        rows.append(row)
    return rows


@lru_cache(maxsize=1)
def _headshot_assets() -> tuple[tuple[str, bytes, bytes], ...]:
    assets: list[tuple[str, bytes, bytes]] = []
    for filename in DEMO_HEADSHOT_FILENAMES:
        full_path = DEMO_HEADSHOT_ASSET_DIR / filename
        thumbnail_path = DEMO_HEADSHOT_ASSET_DIR / "thumbs" / filename
        assets.append((filename, thumbnail_path.read_bytes(), full_path.read_bytes()))
    return tuple(assets)


def _headshot_payload(row_id: int) -> tuple[str, bytes, bytes]:
    assets = _headshot_assets()
    return assets[(row_id - 1) % len(assets)]


def _publicity_risk(award_count: int, active: bool) -> str:
    if award_count >= 12:
        return "high"
    if not active:
        return "watch"
    return "standard"


def _chunk_sizes(total: int, chunks: int) -> list[int]:
    base, remainder = divmod(total, chunks)
    return [base + (1 if index < remainder else 0) for index in range(chunks)]


def _base_schema_row(row: dict[str, Any]) -> dict[str, Any]:
    return {field.name: row[field.name] for field in DEMO_SCHEMA}


def _arrow_table_from_rows(rows: list[dict[str, Any]], schema: pa.Schema) -> pa.Table:
    arrays = []
    for field in schema:
        values = [row.get(field.name) for row in rows]
        if field.name == "headshot_full_bytes":
            arrays.append(blob_array(values))
        else:
            arrays.append(pa.array(values, type=field.type))
    return pa.Table.from_arrays(arrays, schema=schema)


def _create_demo_vector_index(table: Any, row_count: int) -> None:
    """Create the demo table's default nearest-neighbor index."""

    table.create_index(
        "embedding",
        config=IvfFlat(num_partitions=max(1, min(4, row_count))),
        name=DEMO_VECTOR_INDEX_NAME,
        replace=True,
    )


def _create_demo_fts_index(table: Any) -> None:
    """Create the demo table's multilingual full-text index."""

    table.create_index(
        "bio",
        config=FTS(**fts_options_for_preset("MULTILINGUAL")),
        name=DEMO_FTS_INDEX_NAME,
        replace=True,
    )


def create_demo_table(
    table_uri: str,
    *,
    row_count: int = 100,
    locale: str = "usa",
    seed: int | None = None,
    version_count: int = 3,
    overwrite: bool = False,
) -> DemoTableResult:
    """Create a demo Lance table with multiple versions for diff workflows."""

    if version_count < 2:
        raise ValueError("Demo version count must be at least 2")
    if version_count - 1 > row_count:
        raise ValueError("Demo version count cannot exceed demo row count plus one")

    location = split_table_uri(table_uri)
    if not has_uri_scheme(location.database_uri):
        Path(location.database_uri).mkdir(parents=True, exist_ok=True)

    resolved_locale = resolve_faker_locale(locale)
    rows = demo_rows(
        row_count=row_count,
        locale=resolved_locale,
        seed=seed,
        include_publicity_risk=True,
    )
    row_chunk_count = max(1, version_count - 1)
    chunk_sizes = _chunk_sizes(row_count, row_chunk_count)
    first_chunk_size = chunk_sizes[0]
    data = _arrow_table_from_rows(
        [_base_schema_row(row) for row in rows[:first_chunk_size]],
        DEMO_SCHEMA,
    )
    db = lancedb.connect(
        location.database_uri,
        storage_options=lancedb_storage_options_from_env() or None,
    )
    table = db.create_table(
        location.table_name,
        data=data,
        schema=DEMO_SCHEMA,
        mode="overwrite" if overwrite else "create",
        data_storage_version="2.2",
    )
    # Adding this field as a second write creates an explicit schema change for demos.
    table.add_columns(DEMO_VERSIONED_FIELD)

    offset = first_chunk_size
    for chunk_size in chunk_sizes[1:]:
        table.add(_arrow_table_from_rows(rows[offset : offset + chunk_size], DEMO_VERSIONED_SCHEMA))
        offset += chunk_size

    _create_demo_vector_index(table, row_count)
    _create_demo_fts_index(table)

    return DemoTableResult(
        table_uri=location.table_uri,
        database_uri=location.database_uri,
        table_name=location.table_name,
        row_count=row_count,
        version_count=version_count,
        locale=resolved_locale,
    )
