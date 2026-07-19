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
