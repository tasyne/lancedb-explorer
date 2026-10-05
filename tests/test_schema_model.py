import ast
from decimal import Decimal

import pyarrow as pa
from lance import blob_field

from lance_explorer.schema_model import generate_lance_model


def _load_generated_model(source: str, model_name: str):
    namespace: dict[str, object] = {}
    exec(source, namespace)
    return namespace[model_name], namespace


def test_generated_lance_model_preserves_complex_arrow_schema() -> None:
    schema = pa.schema(
        [
            pa.field("id", pa.int16(), nullable=False),
            pa.field("created_at", pa.timestamp("ns", tz="UTC"), nullable=False),
            pa.field("price", pa.decimal128(10, 2)),
            pa.field(
                "embedding",
                pa.list_(pa.field("value", pa.float64(), nullable=False), 3),
                nullable=False,
            ),
            pa.field(
                "profile",
                pa.struct(
                    [
                        pa.field("full-name", pa.string(), nullable=False),
                        pa.field("rank", pa.uint8()),
                    ]
                ),
                nullable=False,
            ),
            pa.field("attributes", pa.map_(pa.int32(), pa.string())),
            blob_field("payload"),
        ],
        metadata={b"owner": b"search-team"},
    )

    export = generate_lance_model(schema, "search-items", version=9)

    ast.parse(export.source)
    model, namespace = _load_generated_model(export.source, export.model_name)

    assert export.model_name == "SearchItemsModel"
    assert "Vector(3, value_type=pa.float64(), nullable=False)" in export.source
    assert "blob_field('payload', nullable=True)" in export.source
    assert model.to_arrow_schema().equals(schema, check_metadata=True)

    row = model(
        id=1,
        created_at="2026-01-02T03:04:05Z",
        price=Decimal("12.50"),
        embedding=[0.1, 0.2, 0.3],
        profile={"full-name": "Ada", "rank": 4},
        attributes={1: "featured"},
        payload=b"data",
    )
    assert row.model_dump()["profile"]["full-name"] == "Ada"
    assert "SearchItemsProfileModel" in namespace


def test_generated_lance_model_aliases_invalid_python_field_names() -> None:
    schema = pa.schema(
        [
            pa.field("class", pa.string(), nullable=False),
            pa.field("release-year", pa.int64()),
        ]
    )

    export = generate_lance_model(schema, "123 titles")
    model, _ = _load_generated_model(export.source, export.model_name)
    row = model(**{"class": "classic", "release-year": 1968})

    assert export.model_name == "Table123TitlesModel"
    assert "class_: str = Field(alias='class')" in export.source
    assert row.model_dump() == {"class": "classic", "release-year": 1968}
    assert model.to_arrow_schema().equals(schema, check_metadata=True)


def test_generated_lance_model_uses_multivector_for_nested_fixed_vectors() -> None:
    schema = pa.schema(
        [
            pa.field(
                "embeddings",
                pa.list_(pa.list_(pa.float32(), 4)),
                nullable=False,
            )
        ]
    )

    export = generate_lance_model(schema, "documents")
    model, _ = _load_generated_model(export.source, export.model_name)

    assert "MultiVector(4, nullable=False)" in export.source
    assert model.to_arrow_schema().equals(schema, check_metadata=True)
