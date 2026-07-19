# Lance Explorer

A local Streamlit UI for navigating, inspecting, querying, comparing, indexing, and maintaining LanceDB tables.

## Features

- Local and S3 URI-bar navigation using Pathlib-style `UPath` objects.
- Schema, table metrics, versions, schema history, indexes, and bounded previews.
- SQL-style filters, FTS, and optional pasted-vector search.
- Full-URI comparison of two Lance tables.
- Non-vector index creation/removal.
- Optimize, retention-based version cleanup, restore, and table deletion.
- External Jinja code templates with syntax highlighting and clipboard copy.
- Conservative Streamlit caching and explicit-submit execution.
- Native info tooltips, an index-type guide, and a compact “Why Lance?” introduction.

See [PLAN.md](PLAN.md) for the full design and implementation details.

## Run with Python 3.12

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

## Create demo data

The CLI can also create a local demo Lance table instead of launching Streamlit:

```bash
lance-explorer --create-demo-data ./demo/movie_stars.lance
```

By default this creates 100 fictional movie-star/PII rows across three Lance table
versions. Version 2 adds a `publicity_risk` field so the Table page can demonstrate
schema history and schema diffing.

Useful options:

```bash
lance-explorer --create-demo-data ./demo/movie_stars.lance --faker-locale spanish
lance-explorer --create-demo-data ./demo/movie_stars.lance --faker-locale chinese --demo-rows 250
lance-explorer --create-demo-data ./demo/movie_stars.lance --demo-versions 4 --demo-seed 42
lance-explorer --create-demo-data ./demo/movie_stars.lance --overwrite-demo-data
```

The hard-coded Faker locale aliases live in
`src/lance_explorer/demo_data.py` as `FAKER_LOCALE_ALIASES`. Alias examples include
`usa`, `spanish`, `chinese`, `japanese`, `french`, `german`, `india`, and `brazil`.

## Runtime environment variables

Credentials are resolved from the runtime environment by LanceDB and `s3fs`. Generated code never includes their values.

```bash
export AWS_ACCESS_KEY_ID='...'
export AWS_SECRET_ACCESS_KEY='...'
export AWS_REGION='us-east-1'

# Optional local S3-compatible endpoint
export AWS_ENDPOINT='http://localhost:9000'
export ALLOW_HTTP='true'

# Optional application defaults
export LANCE_EXPLORER_HOME_URI="$HOME"
export LANCE_EXPLORER_TEMPLATE_DIR='/path/to/template/overrides'
export LANCE_EXPLORER_MAX_QUERY_ROWS='10000'
```

## Validate

```bash
ruff check .
pytest
```

## Air-gapped wheelhouse

On a connected build machine matching the target platform:

```bash
./scripts/build_wheelhouse.sh wheelhouse
```

Then install on the isolated host:

```bash
python3.12 -m pip install --no-index --find-links wheelhouse lance-explorer
```
