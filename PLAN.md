# Lance Explorer — Reference Plan and Implemented MVP

**Status:** Implemented and locally validated MVP  
**Target runtime:** Python 3.12  
**Validated libraries:** LanceDB 0.34.0, Streamlit 1.59.2, Universal Pathlib 0.3.10, s3fs 2026.6.0, PyArrow 21.0.0

## 1. Objective

Build a local-first Streamlit application for navigating LanceDB storage, inspecting and comparing tables, running bounded queries, managing non-vector indexes, and performing table maintenance.

The application is deliberately lightweight:

- no authentication or role system;
- no audit database;
- no background queue;
- no embedded credential store;
- no model downloads, embedding generation, or rerankers;
- no automatic full-table comparison;
- no operation is repeated merely because Streamlit reruns a page.

Local filesystems and S3-compatible object stores are first-class. The app is suitable for an air-gapped network when its Python wheels are staged internally.

## 2. Implemented capabilities

### Explorer

- URI-bar navigation for local and `s3://` paths.
- Back, forward, parent, home, and refresh controls.
- Child path listing with Lance table detection.
- Explicit probing of a URI as a LanceDB database.
- Selection of a table from a complete `.lance` URI.
- Code export for connection and open-table setup.

### Table inspection

- Current URI, row count, version, fragment count, and index count.
- Flattened Arrow schema, including nested fields and field metadata.
- Raw Arrow schema display.
- Table statistics and index statistics.
- Version history.
- Schema comparison between two versions.
- Explicitly loaded, bounded row preview.

### Query workbench

- SQL-style filter expression with projection and hard row limit.
- Full-text search against a selected string column.
- Optional query-plan output.
- Raw pasted-vector search against a list-like column; no embedding generation.
- Results execute only on form submission and remain in session state across harmless reruns.
- Code export for each query form.

### Table comparison

- Two complete `.lance` URI inputs.
- Optional version selection for metadata/schema comparison.
- Row-count, schema, index, and table-statistics comparison.
- Bounded positional sample comparison.
- Bounded unique-key comparison showing left-only, right-only, and changed values.
- Code export for the selected comparison.

### Index management

- Existing index definitions and statistics.
- Runtime discovery of index configuration classes in the installed LanceDB SDK.
- Arrow-type-aware choices for:
  - `BTree`;
  - `Bitmap`;
  - `LabelList`;
  - `Fm`, when present;
  - `FTS`.
- Create, replace, and drop indexes through explicit forms.
- Vector-index creation is intentionally omitted from this version.
- Code export for create/drop operations.

### Maintenance

- Optimize a table.
- Optimize while pruning versions older than a selected retention period.
- Optional deletion of unverified files with an explicit warning and typed confirmation.
- Restore a prior version.
- Drop a table with table-name confirmation.
- Code export for all maintenance operations.

### In-app guidance

- Native Streamlit info tooltips on non-obvious fields, metrics, queries, and actions.
- A compact sidebar explanation of Lance and the workloads it handles well.
- A registry-driven index guide describing each installed non-vector index type.
- Succinct warnings for version cleanup, restoration, index removal, and table deletion.
- Help text is centralized and tested so page copy remains consistent and brief.

LanceDB's unified `Table.optimize(...)` method is used instead of the deprecated compact-only and cleanup-only methods. It performs compaction, version pruning when requested, and index maintenance without introducing the separate `pylance` dependency.

## 3. Architecture

```text
Streamlit application
├── app.py                     Multipage navigation and shared initialization
├── ui/
│   ├── pages/                 Explorer, Table, Query, Compare, Indexes, Maintenance
│   ├── components/            Table selector and code-export/copy component
│   ├── help_text.py            Centralized tooltips and Lance feature guidance
│   ├── cache.py               Short-lived read caches
│   └── state.py               Navigation, selection, generations, submitted results
├── repository.py              LanceDB API boundary
├── paths.py                   UPath navigation and table URI decomposition
├── schema_diff.py             Nested Arrow schema flattening and comparison
├── comparison.py              Bounded metadata and row comparison
├── index_registry.py          Programmatic index discovery and compatibility
├── codegen/
│   └── renderer.py            Manifest-driven, strict Jinja renderer
└── templates/python/          External code templates
```

The repository owns LanceDB calls. Domain modules own path parsing, schema comparison, row comparison, and index compatibility. Page modules coordinate inputs and presentation rather than embedding storage logic. Help copy is centralized in `ui/help_text.py` and index-specific guidance is read from `index_registry.py`, preventing duplicated or contradictory explanations.

Fresh LanceDB table handles are opened for each repository operation. This avoids sharing checked-out versions or mutable table state through Streamlit's resource cache.

## 4. Path and storage model

Use `upath.UPath` as the common Pathlib-style abstraction:

```python
from upath import UPath

path = UPath("s3://bucket/database")
child = path / "events.lance"
parent = path.parent
```

Rules:

1. Bare local paths are expanded and converted to absolute paths.
2. URI schemes are preserved.
3. `UPath` handles joining, parent navigation, names, and child iteration for local and S3 paths.
4. Values are converted to `str` only at LanceDB boundaries or for display.
5. A complete table URI must end in `.lance`.
6. Its parent URI is treated as the LanceDB database URI, and its filename stem is the table name.

For S3 navigation, `UPath` receives `s3fs` options derived at runtime from standard AWS environment variables. LanceDB receives only non-secret storage options such as endpoint, region, and `allow_http`; credentials remain in the normal provider chain.

Supported environment variables:

```bash
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_SESSION_TOKEN=
AWS_REGION=us-east-1
AWS_ENDPOINT=http://localhost:9000
ALLOW_HTTP=true
```

`ALLOW_HTTP=true` is intended for a controlled local S3-compatible endpoint such as MinIO. Generic HTTP directory navigation is not assumed.

## 5. Caching and rerun safety

### Core rule

> Cache bounded read snapshots; never cache mutations; execute queries, comparisons, and actions only from explicit form submissions.

### Read caches

| Data | Streamlit mechanism | TTL | Max entries |
|---|---|---:|---:|
| Local child listing | `st.cache_data` | 5 seconds | 256 |
| S3 child listing | `st.cache_data` | 15 seconds | 256 |
| Database table names | `st.cache_data` | 15 seconds | 256 |
| Table snapshot | `st.cache_data` | 20 seconds | 512 |
| Version list | `st.cache_data` | 20 seconds | 512 |
| Version schema | `st.cache_data` | 20 seconds | 512 |
| Rendered code | `st.cache_data` | content-hash keyed | 512 |
| Template renderer | `st.cache_resource` | process lifetime | by template directory |

Query and comparison output is not placed in a global pickle cache. It is retained in `st.session_state` only after submission.

### Generation invalidation

A per-resource integer generation is included in metadata and directory cache keys. Refreshing or mutating a table increments the relevant generation without clearing every unrelated cache.

After a mutation, the app also clears displayed query, comparison, preview, and schema-diff results so stale output is not presented as current.

### Form behavior

- Query, comparison, index, and maintenance calls are inside `st.form` blocks.
- Rendering, tab changes, code-copy clicks, and navigation reruns do not repeat the submitted operation.
- Re-submitting the form is considered an intentional rerun.
- Service-layer limits cap results even if widget values are manipulated.

## 6. Query design

The filter workbench is intentionally not a general SQL console. It exposes:

- projection;
- a Lance SQL-style filter expression;
- row limit;
- optional execution plan.

FTS exposes:

- query text;
- applicable string column;
- optional metadata filter;
- projection and limit.

Raw-vector search exposes:

- finite numeric JSON array;
- selected list-like vector column;
- optional filter;
- projection and limit.

No model or embedding code is loaded by the application.

## 7. Comparison design

### Metadata comparison

For each table/version, collect:

- row count;
- current/resolved version;
- schema and schema metadata;
- table/fragment statistics;
- index definitions and statistics.

Nested schema comparison reports:

- added and removed fields;
- type changes;
- nullability changes;
- field metadata changes;
- order changes;
- schema metadata changes.

### Bounded row comparison

Without a key, compare bounded results positionally. With a key:

1. include the key plus selected columns;
2. reject missing or duplicate keys within the bounded result;
3. report keys found on only one side;
4. report changed values by key and column.

The MVP does not claim that a bounded comparison proves complete table equality. A future large-scale exact comparison should use partitioned hashes or Lance-native execution rather than loading unrestricted tables into pandas.

## 8. Index registry

Index choices are not hardcoded into page logic. `index_registry.py` declares metadata and dynamically checks whether each class exists in `lancedb.index`.

Compatibility rules are based on Arrow types:

- `BTree`: scalar equality/range-compatible types;
- `Bitmap`: low-cardinality scalar types;
- `LabelList`: list-like types;
- `Fm`: string types;
- `FTS`: string types.

Each entry owns:

- stable key;
- LanceDB class name;
- UI label and succinct use-case description shown in the index guide;
- compatibility predicate;
- configuration constructor.

Adding a supported index generally requires one registry entry and, only when specialized options are needed, a small UI configuration block.

## 9. Code export

Code templates are stored outside Python source:

```text
src/lance_explorer/templates/python/
├── manifest.yaml
├── _connection.py.j2
├── connect.py.j2
├── open_table.py.j2
├── filter_query.py.j2
├── fts_query.py.j2
├── vector_query.py.j2
├── compare_tables.py.j2
├── create_index.py.j2
├── drop_index.py.j2
├── optimize.py.j2
├── cleanup_versions.py.j2
├── restore_version.py.j2
└── drop_table.py.j2
```

`manifest.yaml` maps operation IDs to template files, titles, languages, and required context fields. Jinja uses `StrictUndefined` so missing values fail visibly instead of yielding incomplete code.

Runtime template override:

```bash
LANCE_EXPLORER_TEMPLATE_DIR=/opt/lance-explorer/templates
```

Resolution order:

1. override directory;
2. packaged templates.

Generated snippets:

- use `UPath` for local/S3 paths;
- use syntax highlighting through `st.code`;
- provide a local clipboard button through inline Streamlit HTML/JavaScript;
- never include credential values;
- reference endpoint/region/HTTP environment variables when relevant.

The code-render cache includes the template source hash, so modifying an override template invalidates its prior rendered snippet.

## 10. Error handling and destructive operations

- Backend exceptions are rendered as concise page errors.
- Query limits are enforced in `LanceRepository`.
- Vector input must be a non-empty finite numeric JSON list.
- Full table scans are never initiated automatically.
- Cleanup, restore, and table deletion require typed confirmation.
- `delete_unverified=True` is exposed only alongside LanceDB's concurrency/corruption warning.
- Index changes require explicit form submission.
- Dropping an index removes it from table metadata; a later optimize operation handles unreferenced storage and index maintenance.

## 11. Focused tests

The test suite deliberately targets high-risk behavior instead of maximizing line coverage.

Implemented tests cover:

- local and S3-style URI parsing;
- Pathlib-style local child navigation;
- complete `.lance` URI decomposition;
- nested Arrow schema differences;
- numeric-vector validation and hard query limits;
- code-template rendering, override precedence, and secret-key rejection;
- local table inspection, filtering, and version listing;
- B-tree index creation/removal;
- FTS index creation and search;
- bounded keyed table comparison;
- default Streamlit page smoke rendering;
- required help coverage for important operations;
- succinct Lance overview and index guidance constraints.

Validation commands:

```bash
ruff check .
pytest
```

Current result: **24 tests passing** and **Ruff clean**.

## 12. Air-gapped deployment

The application performs no required outbound web calls and uses no CDN assets. For deployment:

1. Build wheels on a connected machine matching the target OS and architecture.
2. Transfer the wheelhouse through the approved process.
3. Install with `--no-index` on the isolated network.
4. Configure local filesystem or internal S3-compatible endpoints through environment variables.

A helper script is included:

```bash
./scripts/build_wheelhouse.sh wheelhouse
```

Offline installation pattern:

```bash
python3.12 -m pip install --no-index --find-links wheelhouse lance-explorer
```

The package targets Python 3.12. Local validation in the build environment also succeeded under Python 3.13, but Python 3.12 remains the intended deployment runtime.

## 13. Running the app

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
streamlit run src/lance_explorer/app.py
```

Or after installation:

```bash
lance-explorer
```

## 14. Deferred enhancements

These are intentionally outside the MVP:

- branch/tag management;
- vector-index creation and tuning;
- exact distributed comparison of very large tables;
- pagination for extremely large table collections;
- background job execution;
- authentication, permissions, and audit history;
- embedding/model management.

## 15. Technical references

Verified July 18, 2026:

- LanceDB Python SDK: <https://lancedb.github.io/lancedb/python/python/>
- LanceDB storage configuration: <https://docs.lancedb.com/storage/configuration>
- Streamlit caching: <https://docs.streamlit.io/develop/concepts/architecture/caching>
- Streamlit navigation: <https://docs.streamlit.io/develop/api-reference/navigation/st.navigation>
- Universal Pathlib: <https://universal-pathlib.readthedocs.io/en/latest/>
