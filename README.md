# Lance Explorer

Local Streamlit UI for browsing LanceDB storage, selecting `.lance` tables, inspecting schemas and versions, running bounded queries, comparing tables, managing indexes, maintaining tables, and viewing offline docs.

For design details, see [PLAN.md](PLAN.md).

## Install

Requires Python `>=3.12,<3.14`.

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

## Demo Data

Create a local demo Lance table:

```bash
lance-explorer --create-demo-data ./demo/movie_stars.lance
```

Defaults: 100 fictional movie-star rows, Faker locale `usa`, and 3 table versions. Version 2 adds `publicity_risk` so schema diffing has something visible.

Useful options:

```bash
lance-explorer --create-demo-data ./demo/movie_stars.lance --faker-locale spanish
lance-explorer --create-demo-data ./demo/movie_stars.lance --demo-rows 250 --demo-versions 4
lance-explorer --create-demo-data ./demo/movie_stars.lance --demo-seed 42
lance-explorer --create-demo-data ./demo/movie_stars.lance --overwrite-demo-data
```

Faker locale aliases live in `src/lance_explorer/demo_data.py` as `FAKER_LOCALE_ALIASES`.

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

Requirements: GNU `wget`; the shell script also needs `zip`. The scripts are intentionally simple `wget --mirror` plus zip wrappers.

To store the zips elsewhere:

```bash
export LANCE_EXPLORER_DOCS_MIRROR_DIR="/path/to/docs_mirrors"
```

If links inside the mirrored docs fail, use the `Offline Index`. Maximizing the browser window can also help because the embedded docs hide navigation in narrow layouts.

## Configuration

LanceDB and `s3fs` read credentials from the normal environment/provider chain. The app does not store or render secret values in generated code.

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

## Air-Gapped Install

On a connected build machine matching the target platform:

```bash
./scripts/build_wheelhouse.sh wheelhouse
```

Then copy `wheelhouse/` to the isolated host and install:

```bash
python3.12 -m pip install --no-index --find-links wheelhouse lance-explorer
```
