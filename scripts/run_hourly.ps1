param()

$ProjectRoot = "C:\Projects\EbayPrice"
$LogDir = "$env:USERPROFILE\ebay_exports"
$LogFile = "$LogDir\run_hourly.log"

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }

# Force UTF-8 encoding so Unicode output from Python doesn't crash
$PSDefaultParameterValues['Out-File:Encoding'] = 'utf8'
$env:PYTHONIOENCODING = 'utf-8'

"[$([DateTime]::Now)] Starting hourly pipeline..." | Out-File -FilePath $LogFile -Append

$Python = "$ProjectRoot\.venv\Scripts\python.exe"
$MainScript = "$ProjectRoot\scripts\main.py"

Set-Location $ProjectRoot

$Output = & $Python $MainScript 2>&1
$ExitCode = $LASTEXITCODE

if ($Output) {
    $Output | Out-File -FilePath $LogFile -Append
}
"[$([DateTime]::Now)] Finished with exit code $ExitCode" | Out-File -FilePath $LogFile -Append

exit $ExitCode
