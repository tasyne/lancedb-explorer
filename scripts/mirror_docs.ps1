param([string] $OutputDir = "docs_mirrors")

$ErrorActionPreference = "Stop"
$WorkDir = Join-Path $OutputDir "_work"
$DocsRoot = Join-Path $WorkDir "lancedb-docs"
$ApiRoot = Join-Path $WorkDir "lancedb-python-api"
$DocsSeeds = Join-Path $WorkDir "lancedb-docs-urls.txt"
$ApiSeeds = Join-Path $WorkDir "lancedb-python-api-urls.txt"
$DocsZip = Join-Path $OutputDir "lancedb-docs.zip"
$ApiZip = Join-Path $OutputDir "lancedb-python-api.zip"

New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
Remove-Item -LiteralPath $DocsRoot -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $ApiRoot -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $DocsRoot, $ApiRoot -Force | Out-Null

function Invoke-WgetOptional {
    param(
        [string] $Url,
        [string] $OutputPath
    )

    try {
        & wget.exe -q -O $OutputPath $Url
        if ($LASTEXITCODE -ne 0) {
            Remove-Item -LiteralPath $OutputPath -Force -ErrorAction SilentlyContinue
        }
    }
    catch {
        Remove-Item -LiteralPath $OutputPath -Force -ErrorAction SilentlyContinue
    }
}

function Add-UrlsFromText {
    param(
        [System.Collections.Generic.HashSet[string]] $Urls,
        [string] $Path,
        [string] $Prefix = ""
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }
    $Text = [System.Net.WebUtility]::HtmlDecode((Get-Content -LiteralPath $Path -Raw))
    foreach ($Match in [regex]::Matches($Text, 'https?://[^\s\)\]"''<>]+')) {
        $Url = Get-CleanUrl $Match.Value
        if ($Url -and (-not $Prefix -or $Url.StartsWith($Prefix))) {
            [void] $Urls.Add($Url)
        }
    }
}

function Add-UrlsFromSitemap {
    param(
        [System.Collections.Generic.HashSet[string]] $Urls,
        [string] $Path,
        [string] $Prefix = ""
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }
    $Text = [System.Net.WebUtility]::HtmlDecode((Get-Content -LiteralPath $Path -Raw))
    foreach ($Match in [regex]::Matches($Text, '<loc>([^<]+)</loc>')) {
        $Url = Get-CleanUrl $Match.Groups[1].Value
        if ($Url -and (-not $Prefix -or $Url.StartsWith($Prefix))) {
            [void] $Urls.Add($Url)
        }
    }
}

function Get-CleanUrl {
    param([string] $Url)

    $Clean = [System.Net.WebUtility]::HtmlDecode($Url).Trim().Trim('"', "'")
    $Clean = $Clean.TrimEnd(".", ",", ";", ")")
    if ($Clean -match '"https?://' -or $Clean -match "'https?://") {
        return ""
    }
    if ($Clean -notmatch '^https?://') {
        return ""
    }
    return $Clean
}

function Write-SeedFile {
    param(
        [System.Collections.Generic.HashSet[string]] $Urls,
        [string] $Path
    )

    $Urls | Sort-Object | Set-Content -LiteralPath $Path -Encoding ascii
}

$DocsUrls = [System.Collections.Generic.HashSet[string]]::new()
[void] $DocsUrls.Add("https://docs.lancedb.com/")
Invoke-WgetOptional "https://docs.lancedb.com/llms.txt" (Join-Path $WorkDir "lancedb-docs-llms.txt")
Invoke-WgetOptional "https://docs.lancedb.com/sitemap.xml" (Join-Path $WorkDir "lancedb-docs-sitemap.xml")
Add-UrlsFromText $DocsUrls (Join-Path $WorkDir "lancedb-docs-llms.txt")
Add-UrlsFromSitemap $DocsUrls (Join-Path $WorkDir "lancedb-docs-sitemap.xml")
Write-SeedFile $DocsUrls $DocsSeeds

wget.exe --mirror "--input-file=$DocsSeeds" --page-requisites --convert-links `
    --adjust-extension --no-parent --span-hosts `
    "--domains=docs.lancedb.com,mintcdn.com,fonts.googleapis.com,fonts.gstatic.com,cloudfront.net,d3gk2c5xim1je2.cloudfront.net" `
    '--reject-regex=.*(&quot;|&#34;|%22).*' `
    --no-host-directories --restrict-file-names=windows --cut-dirs=0 `
    "--directory-prefix=$DocsRoot"

Compress-Archive -Path (Join-Path $DocsRoot "*") `
    -DestinationPath $DocsZip `
    -Force

$ApiUrls = [System.Collections.Generic.HashSet[string]]::new()
[void] $ApiUrls.Add("https://lancedb.github.io/lancedb/python/python/")
Invoke-WgetOptional "https://lancedb.github.io/lancedb/sitemap.xml" (Join-Path $WorkDir "lancedb-python-api-sitemap.xml")
Add-UrlsFromSitemap $ApiUrls (Join-Path $WorkDir "lancedb-python-api-sitemap.xml") "https://lancedb.github.io/lancedb/python/python/"
Write-SeedFile $ApiUrls $ApiSeeds

wget.exe --mirror "--input-file=$ApiSeeds" --page-requisites --convert-links `
    --adjust-extension --no-parent --span-hosts `
    "--domains=lancedb.github.io,fonts.googleapis.com,fonts.gstatic.com" `
    '--reject-regex=.*(&quot;|&#34;|%22).*' `
    --no-host-directories --restrict-file-names=windows --cut-dirs=3 `
    "--directory-prefix=$ApiRoot"

Compress-Archive -Path (Join-Path $ApiRoot "*") `
    -DestinationPath $ApiZip `
    -Force

Write-Host "Wrote:"
Write-Host "  $DocsZip"
Write-Host "  $ApiZip"
