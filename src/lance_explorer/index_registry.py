from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

import pyarrow as pa
from lancedb.index import (
    FTS,
    Bitmap,
    BTree,
    Fm,
    HnswFlat,
    HnswPq,
    HnswSq,
    IvfFlat,
    IvfHnswFlat,
    IvfHnswPq,
    IvfHnswSq,
    IvfPq,
    IvfRq,
    IvfSq,
    LabelList,
)

from lance_explorer.language_models import (
    configure_packaged_language_model,
    fts_uses_packaged_language_model,
    model_backed_tokenizers,
)

Compatibility = Callable[[pa.DataType], bool]
IndexCategory = Literal["scalar", "text", "vector"]


def _scalar(data_type: pa.DataType) -> bool:
    return any(
        predicate(data_type)
        for predicate in (
            pa.types.is_boolean,
            pa.types.is_integer,
            pa.types.is_floating,
            pa.types.is_decimal,
            pa.types.is_temporal,
            pa.types.is_string,
            pa.types.is_large_string,
        )
    )


def _string(data_type: pa.DataType) -> bool:
    return pa.types.is_string(data_type) or pa.types.is_large_string(data_type)


def _list(data_type: pa.DataType) -> bool:
    return (
        pa.types.is_list(data_type)
        or pa.types.is_large_list(data_type)
        or pa.types.is_fixed_size_list(data_type)
    )


def _float_vector(data_type: pa.DataType) -> bool:
    if not _list(data_type):
        return False
    return pa.types.is_floating(data_type.value_type)


@dataclass(frozen=True, slots=True)
class IndexDefinition:
    """UI and construction metadata for one LanceDB index type."""

    key: str
    config_type: type[Any]
    label: str
    description: str
    compatible: Compatibility
    category: IndexCategory = "scalar"
    template: str = "create_index"

    @property
    def class_name(self) -> str:
        """Return the public class name used by generated Python."""

        return self.config_type.__name__

    def create_config(self, **kwargs: Any) -> Any:
        """Instantiate this index configuration."""

        return self.config_type(**kwargs)


@dataclass(frozen=True, slots=True)
class FtsPreset:
    """Named FTS option bundle shown in the index creation UI."""

    key: str
    label: str
    description: str
    options: dict[str, object]


INDEX_DEFINITIONS: tuple[IndexDefinition, ...] = (
    IndexDefinition(
        "BTREE",
        BTree,
        "B-tree",
        "Best for selective equality and range filters on mostly unique values.",
        _scalar,
    ),
    IndexDefinition(
        "BITMAP",
        Bitmap,
        "Bitmap",
        "Best for low-cardinality columns such as statuses or categories.",
        _scalar,
    ),
    IndexDefinition(
        "LABEL_LIST",
        LabelList,
        "Label list",
        "Best for array membership filters on primitive list columns.",
        _list,
    ),
    IndexDefinition(
        "FM",
        Fm,
        "FM",
        "Best for raw substring searches in paths, URLs, identifiers, or logs.",
        _string,
        "text",
    ),
    IndexDefinition(
        "FTS",
        FTS,
        "Full-text search",
        "Best for BM25-ranked keyword and phrase search over natural language.",
        _string,
        "text",
    ),
    IndexDefinition(
        "IVF_FLAT",
        IvfFlat,
        "IvfFlat - Inverted File Flat, raw vectors",
        "Best for IVF partitioning without vector compression.",
        _float_vector,
        "vector",
    ),
    IndexDefinition(
        "IVF_PQ",
        IvfPq,
        "IvfPq - Inverted File with Product Quantization",
        "Best for smaller indexes with good recall on lower-dimensional vectors.",
        _float_vector,
        "vector",
    ),
    IndexDefinition(
        "IVF_SQ",
        IvfSq,
        "IvfSq - Inverted File with Scalar Quantization",
        "Best for balanced vector compression, latency, and recall.",
        _float_vector,
        "vector",
    ),
    IndexDefinition(
        "IVF_RQ",
        IvfRq,
        "IvfRq - Inverted File with RaBitQ Quantization",
        "Best for high compression on large, high-dimensional vector datasets.",
        _float_vector,
        "vector",
    ),
    IndexDefinition(
        "IVF_HNSW_FLAT",
        IvfHnswFlat,
        "IvfHnswFlat - Inverted File plus Hierarchical Navigable Small World, raw vectors",
        "Best for high recall with IVF partitioning and no compression.",
        _float_vector,
        "vector",
    ),
    IndexDefinition(
        "IVF_HNSW_PQ",
        IvfHnswPq,
        "IvfHnswPq - Inverted File plus Hierarchical Navigable Small World "
        "with Product Quantization",
        "Best for HNSW recall with product-quantized storage.",
        _float_vector,
        "vector",
    ),
    IndexDefinition(
        "IVF_HNSW_SQ",
        IvfHnswSq,
        "IvfHnswSq - Inverted File plus Hierarchical Navigable Small World "
        "with Scalar Quantization",
        "Best for HNSW recall with scalar-quantized storage.",
        _float_vector,
        "vector",
    ),
    IndexDefinition(
        "HNSW_FLAT",
        HnswFlat,
        "HnswFlat - Hierarchical Navigable Small World, raw vectors",
        "Best for high recall graph search without compression.",
        _float_vector,
        "vector",
    ),
    IndexDefinition(
        "HNSW_PQ",
        HnswPq,
        "HnswPq - Hierarchical Navigable Small World with Product Quantization",
        "Best for graph search with product-quantized vectors.",
        _float_vector,
        "vector",
    ),
    IndexDefinition(
        "HNSW_SQ",
        HnswSq,
        "HnswSq - Hierarchical Navigable Small World with Scalar Quantization",
        "Best for graph search with scalar-quantized vectors.",
        _float_vector,
        "vector",
    ),
)

FTS_BASE_TOKENIZERS = (
    "simple",
    "whitespace",
    "raw",
    "ngram",
    "icu",
    "icu/split",
    *model_backed_tokenizers(),
)
FTS_LANGUAGES = (
    "Arabic",
    "Danish",
    "Dutch",
    "English",
    "Finnish",
    "French",
    "German",
    "Greek",
    "Hungarian",
    "Italian",
    "Norwegian",
    "Portuguese",
    "Romanian",
    "Russian",
    "Spanish",
    "Swedish",
    "Tamil",
    "Turkish",
)
FTS_PRESETS: dict[str, FtsPreset] = {
    "ENGLISH": FtsPreset(
        "ENGLISH",
        "English",
        "Simple tokenizer with English stemming, stop words, and ASCII folding.",
        {
            "with_position": True,
            "base_tokenizer": "simple",
            "language": "English",
            "max_token_length": 40,
            "lower_case": True,
            "stem": True,
            "remove_stop_words": True,
            "ascii_folding": True,
            "ngram_min_length": 3,
            "ngram_max_length": 3,
            "prefix_only": False,
        },
    ),
    "MULTILINGUAL": FtsPreset(
        "MULTILINGUAL",
        "Multilingual",
        "ICU tokenizer for mixed-language text; no language-specific stemming.",
        {
            "with_position": True,
            "base_tokenizer": "icu",
            "language": "English",
            "max_token_length": 40,
            "lower_case": True,
            "stem": False,
            "remove_stop_words": False,
            "ascii_folding": True,
            "ngram_min_length": 3,
            "ngram_max_length": 3,
            "prefix_only": False,
        },
    ),
    "JIEBA": FtsPreset(
        "JIEBA",
        "Jieba",
        "Mandarin-oriented tokenizer using packaged Jieba dictionary files.",
        {
            "with_position": True,
            "base_tokenizer": "jieba/default",
            "max_token_length": 40,
            "lower_case": True,
            "stem": False,
            "remove_stop_words": False,
            "ascii_folding": False,
            "ngram_min_length": 3,
            "ngram_max_length": 3,
            "prefix_only": False,
        },
    ),
    "LINDERA_IPADIC": FtsPreset(
        "LINDERA_IPADIC",
        "Japanese - Lindera IPADIC",
        "Japanese morphological tokenization with an externally supplied Lindera IPADIC model.",
        {
            "with_position": True,
            "base_tokenizer": "lindera/ipadic",
            "max_token_length": 40,
            "lower_case": True,
            "stem": False,
            "remove_stop_words": False,
            "ascii_folding": False,
            "ngram_min_length": 3,
            "ngram_max_length": 3,
            "prefix_only": False,
        },
    ),
    "LINDERA_UNIDIC": FtsPreset(
        "LINDERA_UNIDIC",
        "Japanese - Lindera UniDic",
        "Japanese morphological tokenization with an externally supplied Lindera UniDic model.",
        {
            "with_position": True,
            "base_tokenizer": "lindera/unidic",
            "max_token_length": 40,
            "lower_case": True,
            "stem": False,
            "remove_stop_words": False,
            "ascii_folding": False,
            "ngram_min_length": 3,
            "ngram_max_length": 3,
            "prefix_only": False,
        },
    ),
    "LINDERA_KO_DIC": FtsPreset(
        "LINDERA_KO_DIC",
        "Korean - Lindera ko-dic",
        "Korean morphological tokenization with an externally supplied Lindera ko-dic model.",
        {
            "with_position": True,
            "base_tokenizer": "lindera/ko-dic",
            "max_token_length": 40,
            "lower_case": True,
            "stem": False,
            "remove_stop_words": False,
            "ascii_folding": False,
            "ngram_min_length": 3,
            "ngram_max_length": 3,
            "prefix_only": False,
        },
    ),
}


def compatible_index_definitions(data_type: pa.DataType) -> list[IndexDefinition]:
    """Return index definitions compatible with an Arrow data type."""

    return [
        definition
        for definition in INDEX_DEFINITIONS
        if definition.compatible(data_type)
    ]


def get_index_definition(key: str) -> IndexDefinition:
    """Return an index definition by stable registry key."""

    for definition in INDEX_DEFINITIONS:
        if definition.key == key:
            return definition
    raise KeyError(f"Unknown index type: {key}")


def create_table_index(
    table: Any,
    *,
    column: str,
    index_type: str,
    config_options: dict[str, Any] | None = None,
    name: str | None = None,
    replace: bool = False,
) -> None:
    """Create an index with LanceDB's unified configuration API."""

    options = dict(config_options or {})
    if index_type == "FTS" and fts_uses_packaged_model(options):
        configure_packaged_language_model(str(options["base_tokenizer"]))
    config = get_index_definition(index_type).create_config(**options)
    table.create_index(column, config=config, name=name, replace=replace)


def fts_options_for_preset(key: str) -> dict[str, object]:
    """Return a mutable copy of a built-in FTS preset's options."""

    return dict(FTS_PRESETS[key].options)


def fts_uses_packaged_jieba(config_options: dict[str, Any]) -> bool:
    """Return whether FTS options need the bundled Jieba language model files."""

    return str(config_options.get("base_tokenizer", "")).startswith("jieba/")


def fts_uses_packaged_model(config_options: dict[str, Any]) -> bool:
    """Return whether FTS options need any bundled tokenizer model files."""

    return fts_uses_packaged_language_model(config_options)
