param([string] $OutputDir = "docs_mirrors")

$ErrorActionPreference = "Stop"
$WorkDir = Join-Path $OutputDir "_work"
$DocsRoot = Join-Path $WorkDir "lancedb-docs"
$ApiRoot = Join-Path $WorkDir "lancedb-python-api"
$DocsZip = Join-Path $OutputDir "lancedb-docs.zip"
$ApiZip = Join-Path $OutputDir "lancedb-python-api.zip"

New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
Remove-Item -LiteralPath $DocsRoot -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $ApiRoot -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $DocsRoot, $ApiRoot -Force | Out-Null

wget.exe --mirror --page-requisites --convert-links --adjust-extension --no-parent `
    --no-host-directories --restrict-file-names=windows --cut-dirs=0 `
    "--directory-prefix=$DocsRoot" `
    https://docs.lancedb.com/

Compress-Archive -Path (Join-Path $DocsRoot "*") `
    -DestinationPath $DocsZip `
    -Force

wget.exe --mirror --page-requisites --convert-links --adjust-extension --no-parent `
    --no-host-directories --restrict-file-names=windows --cut-dirs=3 `
    "--directory-prefix=$ApiRoot" `
    https://lancedb.github.io/lancedb/python/python/

Compress-Archive -Path (Join-Path $ApiRoot "*") `
    -DestinationPath $ApiZip `
    -Force

Write-Host "Wrote:"
Write-Host "  $DocsZip"
Write-Host "  $ApiZip"
