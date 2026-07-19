#!/usr/bin/env bash
set -euo pipefail

OUT="${1:-docs_mirrors}"
WORK="$OUT/_work"

mkdir -p "$OUT"
rm -rf "$WORK/lancedb-docs" "$WORK/lancedb-python-api"
mkdir -p "$WORK/lancedb-docs" "$WORK/lancedb-python-api"

wget --mirror --page-requisites --convert-links --adjust-extension --no-parent \
  --no-host-directories --restrict-file-names=windows --cut-dirs=0 \
  --directory-prefix="$WORK/lancedb-docs" \
  https://docs.lancedb.com/

rm -f "$OUT/lancedb-docs.zip"
(cd "$WORK/lancedb-docs" && zip -qr "../../lancedb-docs.zip" .)

wget --mirror --page-requisites --convert-links --adjust-extension --no-parent \
  --no-host-directories --restrict-file-names=windows --cut-dirs=3 \
  --directory-prefix="$WORK/lancedb-python-api" \
  https://lancedb.github.io/lancedb/python/python/

rm -f "$OUT/lancedb-python-api.zip"
(cd "$WORK/lancedb-python-api" && zip -qr "../../lancedb-python-api.zip" .)

echo "Wrote:"
echo "  $OUT/lancedb-docs.zip"
echo "  $OUT/lancedb-python-api.zip"
