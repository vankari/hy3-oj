param([string]$Python = 'python')
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot

# Read local credentials at runtime; never store their values in this script.
if (Test-Path "$root\.env") {
    Get-Content "$root\.env" -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith('#') -and $line -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
            $k = $matches[1]
            $v = $matches[2].Trim()
            if ($v.Length -ge 2 -and $v[0] -eq '"' -and $v[-1] -eq '"') { $v = $v.Substring(1, $v.Length - 2) }
            [Environment]::SetEnvironmentVariable($k, $v, 'Process')
        }
    }
}

# This launcher uses a direct API connection, so clear process-local proxies.
'HY3_HTTP_PROXY','HY3_HTTPS_PROXY','HTTP_PROXY','HTTPS_PROXY','http_proxy','https_proxy' | ForEach-Object {
    [Environment]::SetEnvironmentVariable($_, '', 'Process')
}

Set-Location $root
& $Python scripts/run_solve.py `
    --subset runs/subset_mid100_fail_cpp.jsonl `
    --out runs/closed_loop_mid100_fail_cpp.jsonl `
    --lang cpp `
    --concurrency 2
