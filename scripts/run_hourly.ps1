param()

$ProjectRoot = "C:\Projects\EbayPrice"
$LogDir = "$env:USERPROFILE\ebay_exports"
$LogFile = "$LogDir\run_hourly.log"

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }

"[$([DateTime]::Now)] Starting hourly pipeline..." | Out-File $LogFile -Append

$Python = "$ProjectRoot\.venv\Scripts\python.exe"
$MainScript = "$ProjectRoot\scripts\main.py"

Set-Location $ProjectRoot

$Output = & $Python $MainScript 2>&1
$ExitCode = $LASTEXITCODE

"$Output" | Out-File $LogFile -Append
"[$([DateTime]::Now)] Finished with exit code $ExitCode" | Out-File $LogFile -Append

exit $ExitCode
