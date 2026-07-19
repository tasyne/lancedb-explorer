from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from lance_explorer.demo_data import FAKER_LOCALE_ALIASES, create_demo_table


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
        print(
            "Created demo Lance table "
            f"{result.table_uri} with {result.row_count} rows across "
            f"{result.version_count} versions using Faker locale {result.locale}."
        )
        return 0

    app_path = Path(__file__).with_name("app.py")
    return subprocess.call(
        [sys.executable, "-m", "streamlit", "run", str(app_path), *streamlit_args]
    )


def main() -> None:
    raise SystemExit(run())
