# Lance Explorer

Local Streamlit UI for browsing LanceDB storage, selecting `.lance` tables, inspecting schemas and versions, running bounded queries, comparing tables, managing indexes, maintaining tables, and viewing offline docs.

For design details, see [PLAN.md](PLAN.md).

## Install

Requires Python `>=3.12,<3.14`.
LanceDB `>=0.34.0` is recommended. LanceDB `0.33.x` can run with reduced binary support on
systems that cannot install newer LanceDB wheels.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

## LanceDB Compatibility

Lance Explorer supports LanceDB `0.33.x`, but `0.34.0+` is the preferred target. This matters
because generated code mirrors the installed SDK's public API where possible.

| Area | LanceDB 0.33.x | LanceDB 0.34.0+ |
| --- | --- | --- |
| Index creation API | Uses older public helpers such as `create_scalar_index`, `create_fts_index`, and legacy vector `create_index(...)` arguments. | Supports unified `create_index(column, config=...)` snippets. |
| Vector index choices | Limited to legacy public vector index types exposed by the installed SDK. | Newer config classes can be used directly when available. |
| Binary demo data | Full headshots fall back to Arrow `binary`. | Full headshots use Lance Blob v2 when the `lance` helpers are available. |
| Demo FTS index | Uses the English/simple tokenizer preset. | Uses the multilingual ICU preset. |
| Code exports | Include compatibility fallbacks for index creation and avoid newer-only version arguments where practical. | Prefer the newer config-style API while keeping copied snippets portable. |

The app displays a warning when LanceDB is older than `0.34.0`. Older deployments can still be
useful, but some LanceDB capabilities are genuinely unavailable rather than hidden by the UI.

## Run

After installation:

```bash
lance-explorer
```

Streamlit arguments pass through:

```bash
lance-explorer --server.port 8502
```

During development you can also run:

```bash
streamlit run src/lance_explorer/app.py
```

The app uses browser-side clipboard buttons and runs Streamlit in viewer toolbar mode so normal
`Ctrl+C` copying in tables is not intercepted by Streamlit's cache menu.

## Demo Data

Create a local demo Lance table:

```bash
lance-explorer --create-demo-data ./demo/movie_stars.lance
```

Defaults: 100 fictional movie-star rows, Faker locale `usa`, 3 table versions, a 64-float
`embedding` column, bundled PNG headshots, `embedding_vector_idx` on `embedding`, and
`bio_multilingual_fts_idx` on `bio`. Version 2 adds `publicity_risk` so schema diffing has
something visible.

Useful options:

```bash
lance-explorer --create-demo-data ./demo/movie_stars.lance --faker-locale spanish
lance-explorer --create-demo-data ./demo/movie_stars.lance --demo-rows 250 --demo-versions 4
lance-explorer --create-demo-data ./demo/movie_stars.lance --demo-seed 42
lance-explorer --create-demo-data ./demo/movie_stars.lance --overwrite-demo-data
```

Faker locale aliases live in `src/lance_explorer/demo_data.py` as `FAKER_LOCALE_ALIASES`.

The Indexes page includes English, multilingual ICU, Jieba, and Lindera FTS presets. Packaged
Jieba files live under `src/lance_explorer/language_models` and can be downloaded from Query or
Indexes as a `.tar.gz` archive for offline reproduction. After extraction, set
`LANCE_LANGUAGE_MODEL_HOME` to the extracted `language_models` directory. ICU does not need
external files. Lindera presets cover Japanese IPADIC, Japanese UniDic, and Korean ko-dic, but
those dictionaries are not bundled; supply them externally and configure
`LANCE_LANGUAGE_MODEL_HOME` plus `LINDERA_CONFIG_PATH`.
For multilingual tables, prefer one language-specific text column and FTS index per tokenizer, then
query with `fts_columns` to select the intended index.
It also supports LanceDB vector indexes for float vector fields, including IVF, HNSW, product
quantization, scalar quantization, and RaBitQ options with generated Python snippets.
GPU-accelerated vector indexing uses LanceDB's `pylance` extra, which is installed by this
project's normal package and Conda environment specs.
The vector index UI includes order-of-magnitude storage notes from LanceDB guidance: raw float32
payload is roughly `dimension * 4` bytes per row, `IVF_HNSW_SQ` is typically a little larger than
`1/4` raw vector size, `IVF_RQ` is around `1/32`, and `IVF_PQ` is usually `1/64` to `1/16`
depending on sub-vector settings.

Demo headshots are PNG fixtures derived from Random User Generator portrait URLs and bundled under
`src/lance_explorer/demo_assets/headshots`. The demo stores thumbnails as inline Arrow `binary`
values. With LanceDB `>=0.34.0`, full images use Lance Blob v2 values so the UI can show the
difference between small row-local binary payloads and larger blob-backed payloads. With LanceDB
`0.33.x`, full images fall back to Arrow `binary` so demo creation can still proceed.

## Using the App

- Explorer selects `.lance` tables directly from clickable directory rows and keeps a deduped table history.
- Table opens on the Sample tab; vector columns display as JSON arrays so embeddings can be copied.
- Table includes read-only insert/update guidance with code exports for Arrow blobs, pandas, Pydantic, merge/upsert, and direct update workflows.
- Query supports bounded filters, full-text search, hybrid search, and raw-vector search. FTS selectors show only indexed string columns.
- Compare pre-fills from the selected table and table history. Bounded row comparison lists only columns common to both table URIs.
- Code export expanders show copyable Python for the current operation.

## Offline Docs

The Docs page can serve two local documentation mirrors:

- `docs_mirrors/lancedb-docs.zip`
- `docs_mirrors/lancedb-python-api.zip`

Each zip must unpack to a static site root with `index.html` at the zip root. If `llms.txt` is present, the app builds the left-side `Offline Index` from it and opens selected pages in the mirrored HTML iframe.

Create the archives on an internet-connected machine:

```bash
./scripts/mirror_docs.sh
```

Windows PowerShell:

```powershell
.\scripts\mirror_docs.ps1
```

Requirements: GNU `wget`; the shell script also needs `zip`. The scripts seed `wget` from
`llms.txt` and sitemap URLs, then mirror page requisites across an explicit allowlist that includes
the docs host plus CDN assets such as `mintcdn.com`, `fonts.googleapis.com`, and
`fonts.gstatic.com`, plus CloudFront-hosted Font Awesome assets used by the docs site.

To store the zips elsewhere:

```bash
export LANCE_EXPLORER_DOCS_MIRROR_DIR="/path/to/docs_mirrors"
```

If links inside the mirrored docs fail, use the `Offline Index`. Maximizing the browser window can also help because the embedded docs hide navigation in narrow layouts.

## Configuration

LanceDB and `s3fs` read credentials from the normal environment/provider chain. The app does not store or render secret values in generated code.
Generated code does include non-secret storage settings from the running environment:
`AWS_ENDPOINT`, `AWS_DEFAULT_REGION`, and `ALLOW_HTTP`.

Common environment variables:

```bash
export AWS_ACCESS_KEY_ID="..."
export AWS_SECRET_ACCESS_KEY="..."
export AWS_SESSION_TOKEN="..."
export AWS_REGION="us-east-1"

# Optional S3-compatible endpoint
export AWS_ENDPOINT="http://localhost:9000"
export ALLOW_HTTP="true"

# Optional app defaults
export LANCE_EXPLORER_HOME_URI="$HOME"
export LANCE_EXPLORER_TEMPLATE_DIR="/path/to/template/overrides"
export LANCE_EXPLORER_MAX_QUERY_ROWS="10000"
export LANCE_EXPLORER_DEFAULT_QUERY_ROWS="100"
export LANCE_EXPLORER_DOCS_MIRROR_DIR="/path/to/docs_mirrors"
```

## Validate

Run the test suite from the project root after installing the dev dependencies:

```bash
ruff check .
pytest
```

Build a wheel with Hatchling:

```bash
python -m pip install hatchling
python -m hatchling build -t wheel
```

## Air-Gapped Install

On a connected build machine matching the target platform:

```bash
./scripts/build_wheelhouse.sh wheelhouse
```

Then copy `wheelhouse/` to the isolated host and install:

```bash
python3.12 -m pip install --no-index --find-links wheelhouse lance-explorer
```
