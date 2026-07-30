# Lance Explorer Strategic Plan

**Status:** Implemented MVP with focused local validation.  
**Runtime target:** Python 3.12 through 3.13.  
**Primary stack:** Streamlit, LanceDB, PyArrow, pandas, Universal Pathlib, s3fs, Jinja, Faker.

## Purpose

Lance Explorer is a local-first Streamlit application for inspecting and operating on LanceDB tables without building a full administration platform. It is intended for developers, field engineers, and demo environments that need a practical way to browse storage, select `.lance` tables, inspect metadata, run bounded queries, compare versions/tables, manage non-vector indexes, perform maintenance, and view offline documentation.

The app is deliberately lightweight:

- no authentication or role model;
- no audit database;
- no background worker queue;
- no embedded credential store;
- no model download, embedding generation, or reranking pipeline;
- no unbounded query, preview, or comparison workflow;
- no mutation triggered merely by Streamlit rerendering.

## Current Capabilities

### Explorer

- Navigate local paths and S3-style URIs with back, forward, up, home, and refresh controls.
- Detect `.lance` table directories and prioritize them in directory listings.
- Hide non-Lance files by default while keeping folders visible.
- Select tables directly from clickable table names.
- Maintain a deduped selected-table history with copy controls.

### Table

- Show row count, table version, schema, schema metadata, index information, versions, and statistics.
- Open with Sample first and Statistics last, matching the highest-frequency workflow.
- Preview bounded rows on explicit request with all columns selected by default.
- Render known vector columns as JSON strings in result tables so embeddings are copyable.
- Compare schemas between versions with auto-filled first/latest defaults.
- Export labeled code snippets for common table-open operations.

### Query

- Run bounded SQL-style filters with optional projection and plan output.
- Run bounded FTS queries against FTS-indexed string columns only.
- Run bounded hybrid searches with separate raw-vector and FTS text inputs.
- Run bounded raw-vector queries against list-like vector columns.
- Preserve score columns such as `_score` and `_distance` when the user selects return columns.
- Keep results in session state after explicit submission only.

### Compare

- Compare two full `.lance` table URIs, optionally at selected versions.
- Pre-fill left/right URIs from the selected table and deduped table history on every page visit.
- Discover common columns after both bounded-comparison URIs are present.
- Compare metadata, schema, indexes, statistics, bounded positional samples, and bounded key-based samples.
- Avoid claiming whole-table equality from bounded samples.

### Indexes

- Discover supported non-vector index classes from the installed LanceDB SDK.
- Offer compatible B-tree, bitmap, label-list, FM, and FTS options based on Arrow field type.
- Offer FTS presets for English, ICU multilingual, and packaged Jieba tokenization.
- Create, replace, and drop indexes with confirmation and post-mutation refresh.
- Keep vector-index creation out of scope for this MVP.

### Maintenance

- Optimize tables.
- Prune old versions through LanceDB optimization options.
- Restore a selected version after showing nearby version metadata.
- Drop tables with typed confirmation.
- Present empty LanceDB mutation responses as successful no-detail results.

### Docs

- Serve offline documentation zip mirrors from a loopback-only static server.
- Build a grouped offline index from `llms.txt` when present.
- Merge discovered local markdown files into the index so partial `llms.txt` mirrors still expose pages.
- Open selected index entries in the mirrored HTML iframe.
- Keep the mirror process intentionally simple: `wget --mirror` plus zip.

### Demo Data

- `lance-explorer --create-demo-data` creates fictional PII-style movie-star data.
- Faker locale aliases support quick localized demos.
- Demo rows include a 64-dimensional `embedding` vector, `embedding_vector_idx`, and
  `bio_multilingual_fts_idx`.
- Multiple Lance versions are created by default so schema/history/diff features have data to demonstrate.

## Architecture

```text
src/lance_explorer/
  app.py                    Streamlit navigation and shared sidebar state
  cli.py                    Console entry point and demo-data mode
  config.py                 Environment-derived app/storage configuration
  paths.py                  Local/S3 URI normalization and table URI parsing
  repository.py             LanceDB API boundary and query/mutation limits
  comparison.py             Bounded metadata and row comparison
  schema_diff.py            Arrow schema flattening and diffing
  index_registry.py         Non-vector index discovery and compatibility
  demo_data.py              Faker-backed demo table generation
  docs_index.py             llms.txt parsing and grouping
  docs_server.py            Safe zip extraction and loopback static serving
  codegen/renderer.py       Strict Jinja code-export rendering
  ui/
    cache.py                Short-lived read caches keyed by generations
    state.py                Navigation, table selection, and cache generations
    components/             Shared UI controls, browser copy, data display, and code export
    pages/                  Explorer, Table, Query, Compare, Indexes, Maintenance, Docs
  templates/python/         Packaged code-export templates
```

The repository layer owns LanceDB calls. Pages coordinate inputs and presentation. Domain modules own path parsing, schema comparison, row comparison, index compatibility, docs indexing, and code rendering. This keeps storage behavior testable outside Streamlit.

Fresh LanceDB table handles are opened per repository operation. This prevents checked-out versions or mutable table state from leaking through Streamlit's resource cache.

Browser-specific behavior stays inside UI components. Clipboard support uses a browser-side iframe button and never invokes OS clipboard subprocesses, which keeps Linux and remote Streamlit deployments portable. Display normalization for code and query text disables font ligatures so examples such as `>=` remain visually copyable ASCII.

## Storage and Configuration Strategy

- Treat complete table URIs ending in `.lance` as the user-facing selection unit.
- Treat the table URI parent as the LanceDB database URI and the filename stem as the table name.
- Use `UPath` for path navigation so local and S3-style storage share one mental model.
- Pass non-secret endpoint/region/HTTP options explicitly to LanceDB.
- Let LanceDB and `s3fs` resolve credentials from the normal provider chain.
- Keep generated code free of secret-bearing values.

## Caching and Rerun Safety

Core rule: cache bounded read snapshots; never cache mutations.

- Directory listings, table names, snapshots, versions, and schema rows have short TTLs.
- Per-resource generation counters invalidate targeted caches after refreshes or mutations.
- Query, comparison, preview, and mutation outputs are kept in session state, not global pickle caches.
- Page defaults may rehydrate from selected-table state, but explicit user-edited inputs are not overwritten unless the underlying table selection changes.
- Mutating actions require explicit UI confirmation; deletes require typed name confirmation.
- Post-mutation paths refresh relevant metadata and clear stale displayed results.

## Code Export Strategy

- Templates are outside Python source under `src/lance_explorer/templates/python/`.
- `manifest.yaml` declares template IDs, titles, files, languages, and required context keys.
- Jinja runs with `StrictUndefined` so missing context fails visibly.
- Runtime overrides use `LANCE_EXPLORER_TEMPLATE_DIR`.
- Template source hashes participate in the render cache key.
- Context keys that look secret-bearing are rejected before rendering.
- Streamlit code blocks are labeled and rendered with ligatures disabled so generated SQL/Python remains copy-paste friendly.

## Offline Documentation Strategy

The docs mirror contract is intentionally minimal:

- `docs_mirrors/lancedb-docs.zip`
- `docs_mirrors/lancedb-python-api.zip`
- each archive unpacks to a static root with `index.html` at the zip root.

The app extracts zips to content-addressed temp directories, rejects unsafe archive paths, and serves the result on `127.0.0.1`. If `llms.txt` is available, it becomes a reliable left-side index even when the mirrored site's JavaScript navigation is incomplete.

## Validation Strategy

Tests focus on behavior with high regression risk:

- URI normalization and `.lance` table splitting;
- schema flattening and diffing;
- query limit and vector parsing;
- repository integration against local Lance tables;
- FTS and B-tree index workflows;
- bounded table comparison;
- Compare-page default URI restoration and common-column discovery;
- code-template rendering and override behavior;
- demo-data generation and CLI routing;
- docs zip extraction, MIME handling, and `llms.txt` indexing;
- vector-column display serialization for copyable embeddings;
- Streamlit smoke rendering.

Validation commands:

```bash
ruff check .
pytest
```

## Deferred Work

Prioritize only when the workflows justify the complexity:

- branch and tag management;
- general vector-index creation and tuning outside demo-data generation;
- exact large-table comparison using partitioned hashes or Lance-native execution;
- stronger pagination for very large table collections;
- background jobs for long-running mutations;
- authentication, permissions, and audit history;
- richer offline docs search beyond the `llms.txt` index;
- optional generated documentation bundles when simple mirroring is insufficient.

## Engineering Guardrails

- Keep LanceDB SDK compatibility logic in `repository.py` and `index_registry.py`, not spread across pages.
- Keep Streamlit pages thin: gather inputs, call domain/repository helpers, and render results.
- Prefer small shared UI components for repeated browser or dataframe behavior.
- Use concise docstrings on public functions/classes; reserve comments for SDK quirks, security checks, or rerun-sensitive state handling.
- Add tests when behavior crosses module boundaries, depends on LanceDB version quirks, or protects copy/paste/demo workflows.
