from __future__ import annotations

LANCE_OVERVIEW = (
    "Lance is an Arrow-native, versioned columnar format for tabular and multimodal data. "
    "It excels at fast scans and random access, flexible schema evolution, object-store data, "
    "and combining structured filters with full-text or vector search."
)

LANCE_STRENGTHS: tuple[str, ...] = (
    "One versioned table can hold structured data, text, embeddings, and large media.",
    "Fast column scans and row-level random access support both analytics and retrieval.",
    "Schema changes and derived columns often avoid rewriting existing large data files.",
    "Tables work locally or directly on object storage without a separate database server.",
)

HELP: dict[str, str] = {
    "uri_bar": (
        "Open a local path, file:// URI, s3:// prefix, or configured S3-compatible location. "
        "Navigation is read-only until you explicitly run an action."
    ),
    "database": (
        "A LanceDB database is a directory or object-store prefix containing one or more "
        ".lance tables. Listing tables opens that location as a LanceDB catalog."
    ),
    "table_uri": (
        "A full .lance URI identifies one Lance table. Local paths and s3:// URIs are supported."
    ),
    "rows": "Current logical row count for the selected table version.",
    "version": (
        "Lance creates a new table version for each committed write. Versions share unchanged "
        "data files; they are not full copies of the table."
    ),
    "fragments": (
        "Fragments are groups of data files written by table operations. Too many small "
        "fragments can slow reads; Optimize compacts them."
    ),
    "indexes": (
        "Secondary indexes accelerate repeated filters or searches. Newly written rows may be "
        "searched by a slower fallback until Optimize updates the index."
    ),
    "schema": (
        "The Arrow schema defines column names, types, nullability, and nested fields stored in "
        "this table version."
    ),
    "statistics": (
        "Physical table statistics help diagnose fragmentation and storage layout. Values depend "
        "on the installed LanceDB version and table format."
    ),
    "versions": (
        "Versions make reads reproducible and allow restoration. Retain versions while other "
        "processes may still need them."
    ),
    "schema_changes": (
        "Compare two historical versions to find added, removed, reordered, or type-changed fields."
    ),
    "sample": (
        "Loads only the selected columns and row limit. Sampling is explicit so Streamlit reruns "
        "do not repeat the read."
    ),
    "insert_data": (
        "Read-only guidance for add, merge/upsert, pandas, Pydantic validation, and binary/blob "
        "write patterns. No data is changed from this page."
    ),
    "filter_query": (
        "SQL WHERE only. Examples: `birth_date >= DATE '1985-04-02'`; `active = true`; "
        "`award_count BETWEEN 3 AND 10`; `array_has(tags, 'vip')`; `stage_name LIKE 'Ann%'`."
    ),
    "query_plan": (
        "Shows the physical execution plan. Use it to see whether Lance uses an index or performs "
        "a scan."
    ),
    "fts_query": (
        "BM25-ranked keyword search over an FTS-indexed string column. Example: words to search "
        "across full-text index."
    ),
    "hybrid_query": (
        "Combines raw-vector nearest-neighbor search with FTS text search. RRF reranking is "
        "model-free and is LanceDB's basic hybrid fusion."
    ),
    "raw_vector": (
        "Paste a JSON vector such as [0.1, -0.2, 0.3, 0.5]. No embedding model runs here."
    ),
    "metadata_compare": (
        "Read-only comparison of schemas, row counts, versions, fragment metrics, and index "
        "definitions for two full table URIs."
    ),
    "bounded_compare": (
        "Reads no more than the selected limit from either table. Provide a unique key to align "
        "rows reliably; without one, rows are compared by position."
    ),
    "comparison_key": (
        "A column whose values uniquely identify rows in both tables, such as an ID. Duplicate "
        "keys make row-level differences ambiguous."
    ),
    "existing_indexes": (
        "An index can cover only part of a recently updated table. Index statistics show whether "
        "new rows still require fallback scanning."
    ),
    "create_index": (
        "Create an index for a repeated query pattern. Indexes improve reads but consume storage "
        "and must be updated after writes."
    ),
    "replace_index": (
        "Rebuild an index using the selected name. Use this when changing index settings or "
        "intentionally replacing an existing definition."
    ),
    "fts_positions": (
        "Stores token positions so phrase queries can preserve word order. "
        "This increases index size."
    ),
    "fts_tokenizer": (
        "Controls how text becomes search terms. ICU is built in; Jieba and Lindera use packaged "
        "model files under LANCE_LANGUAGE_MODEL_HOME."
    ),
    "fts_language": (
        "Language affects stemming and stop-word removal. It is separate from CJK tokenization."
    ),
    "drop_index": (
        "Removes the index from table metadata. Run Optimize later to reclaim "
        "unreferenced index files."
    ),
    "optimize": (
        "Compacts small fragments, updates existing indexes with newly written rows, and can prune "
        "versions beyond a retention window."
    ),
    "cleanup_versions": (
        "Permanently removes files used only by versions older than the retention cutoff. Keep any "
        "version that readers or reproducible workflows still require."
    ),
    "delete_unverified": (
        "Also remove files that are not referenced by verified manifests. Use only when no other "
        "writer or recovery process may still need them."
    ),
    "restore_version": (
        "Creates a new latest version whose contents match the selected historical "
        "version. It does "
        "not erase the intervening version history."
    ),
    "drop_table": (
        "Permanently removes the table from its LanceDB database. This cannot be "
        "undone through the UI."
    ),
    "code_export": (
        "Shows equivalent Python for the current operation. It is generated from "
        "external templates "
        "and never includes runtime credential values."
    ),
}


def help_text(key: str) -> str:
    """Return registered help text and fail fast for missing UI documentation."""
    return HELP[key]
