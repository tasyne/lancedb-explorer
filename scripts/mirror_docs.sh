#!/usr/bin/env bash
set -euo pipefail

OUT="${1:-docs_mirrors}"
WORK="$OUT/_work"
DOCS_SEEDS="$WORK/lancedb-docs-urls.txt"
API_SEEDS="$WORK/lancedb-python-api-urls.txt"

mkdir -p "$OUT"
rm -rf "$WORK/lancedb-docs" "$WORK/lancedb-python-api"
mkdir -p "$WORK/lancedb-docs" "$WORK/lancedb-python-api"

collect_docs_urls() {
  printf '%s\n' "https://docs.lancedb.com/" > "$DOCS_SEEDS"
  wget -q -O "$WORK/lancedb-docs-llms.txt" "https://docs.lancedb.com/llms.txt" || true
  wget -q -O "$WORK/lancedb-docs-sitemap.xml" "https://docs.lancedb.com/sitemap.xml" || true

  if [ -s "$WORK/lancedb-docs-llms.txt" ]; then
    sed -e 's/&quot;/"/g' -e 's/&#34;/"/g' "$WORK/lancedb-docs-llms.txt" \
      | grep -Eo 'https?://[^ &)"'"'"'<>]+' \
      | sed 's/[),.;]*$//' >> "$DOCS_SEEDS" || true
  fi
  if [ -s "$WORK/lancedb-docs-sitemap.xml" ]; then
    sed -e 's/&quot;/"/g' -e 's/&#34;/"/g' "$WORK/lancedb-docs-sitemap.xml" \
      | grep -Eo '<loc>[^<]+' \
      | sed 's#<loc>##' >> "$DOCS_SEEDS" || true
  fi
  sort -u "$DOCS_SEEDS" -o "$DOCS_SEEDS"
}

collect_api_urls() {
  printf '%s\n' "https://lancedb.github.io/lancedb/python/python/" > "$API_SEEDS"
  wget -q -O "$WORK/lancedb-python-api-sitemap.xml" "https://lancedb.github.io/lancedb/sitemap.xml" || true

  if [ -s "$WORK/lancedb-python-api-sitemap.xml" ]; then
    sed -e 's/&quot;/"/g' -e 's/&#34;/"/g' "$WORK/lancedb-python-api-sitemap.xml" \
      | grep -Eo '<loc>[^<]+' \
      | sed 's#<loc>##' \
      | grep '/lancedb/python/python/' >> "$API_SEEDS" || true
  fi
  sort -u "$API_SEEDS" -o "$API_SEEDS"
}

collect_docs_urls
wget --mirror --input-file="$DOCS_SEEDS" --page-requisites --convert-links \
  --adjust-extension --no-parent --span-hosts \
  --domains=docs.lancedb.com,mintcdn.com,fonts.googleapis.com,fonts.gstatic.com,cloudfront.net,d3gk2c5xim1je2.cloudfront.net \
  --reject-regex='.*(&quot;|&#34;|%22).*' \
  --no-host-directories --restrict-file-names=windows --cut-dirs=0 \
  --directory-prefix="$WORK/lancedb-docs"

rm -f "$OUT/lancedb-docs.zip"
(cd "$WORK/lancedb-docs" && zip -qr "../../lancedb-docs.zip" .)

collect_api_urls
wget --mirror --input-file="$API_SEEDS" --page-requisites --convert-links \
  --adjust-extension --no-parent --span-hosts \
  --domains=lancedb.github.io,fonts.googleapis.com,fonts.gstatic.com \
  --reject-regex='.*(&quot;|&#34;|%22).*' \
  --no-host-directories --restrict-file-names=windows --cut-dirs=3 \
  --directory-prefix="$WORK/lancedb-python-api"

rm -f "$OUT/lancedb-python-api.zip"
(cd "$WORK/lancedb-python-api" && zip -qr "../../lancedb-python-api.zip" .)

echo "Wrote:"
echo "  $OUT/lancedb-docs.zip"
echo "  $OUT/lancedb-python-api.zip"
