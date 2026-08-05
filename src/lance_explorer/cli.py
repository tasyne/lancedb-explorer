from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from lance_explorer.demo_data import (
    DEMO_BINARY_COLUMNS,
    DEMO_FTS_INDEX_NAME,
    DEMO_VECTOR_INDEX_NAME,
    FAKER_LOCALE_ALIASES,
    create_demo_table,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lance-explorer",
        description="Launch Lance Explorer or create a demo Lance table.",
    )
    parser.add_argument(
        "--create-demo-data",
        metavar="TABLE_URI",
        help="Create a random demo Lance table at a full .lance URI, then exit.",
    )
    parser.add_argument(
        "--faker-locale",
        default="usa",
        help=(
            "Faker locale alias or locale code for demo data. "
            f"Built-in aliases: {', '.join(sorted(FAKER_LOCALE_ALIASES))}."
        ),
    )
    parser.add_argument(
        "--demo-rows",
        type=int,
        default=100,
        help="Number of demo rows to create. Defaults to 100.",
    )
    parser.add_argument(
        "--demo-versions",
        type=int,
        default=3,
        help=(
            "Minimum number of Lance table versions to create. Version 2 adds a demo field. "
            "Defaults to 3."
        ),
    )
    parser.add_argument(
        "--demo-seed",
        type=int,
        default=None,
        help="Optional random seed for reproducible demo data.",
    )
    parser.add_argument(
        "--overwrite-demo-data",
        action="store_true",
        help="Overwrite an existing demo table at the target URI.",
    )
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    """Run the CLI: create demo data or launch Streamlit with passthrough args."""

    parser = _build_parser()
    args, streamlit_args = parser.parse_known_args(argv)

    if args.create_demo_data:
        if streamlit_args:
            parser.error("Streamlit arguments cannot be combined with --create-demo-data.")
        try:
            result = create_demo_table(
                args.create_demo_data,
                row_count=args.demo_rows,
                locale=args.faker_locale,
                seed=args.demo_seed,
                version_count=args.demo_versions,
                overwrite=args.overwrite_demo_data,
            )
        except Exception as exc:
            print(f"Unable to create demo data: {exc}", file=sys.stderr)
            return 1
        binary_note = (
            "Full headshots use Lance Blob v2 storage."
            if result.blob_v2_enabled
            else (
                "Full headshots use Arrow binary fallback because Lance Blob v2 is unavailable "
                "in this environment."
            )
        )
        print(
            "Created demo Lance table "
            f"{result.table_uri} with {result.row_count} rows across "
            f"{result.version_count} versions using Faker locale {result.locale}. "
            f"Included image binary/blob columns {', '.join(DEMO_BINARY_COLUMNS)}. "
            f"{binary_note} "
            f"Created indexes {DEMO_VECTOR_INDEX_NAME} on embedding and "
            f"{DEMO_FTS_INDEX_NAME} on bio using the {result.fts_preset} FTS preset "
            f"({result.fts_base_tokenizer} tokenizer). "
            f"Created demo tags: {', '.join(result.tags) if result.tags else 'none'}."
        )
        return 0

    app_path = Path(__file__).with_name("app.py")
    return subprocess.call(
        [sys.executable, "-m", "streamlit", "run", str(app_path), *streamlit_args]
    )


def main() -> None:
    """Console-script entry point."""

    raise SystemExit(run())
