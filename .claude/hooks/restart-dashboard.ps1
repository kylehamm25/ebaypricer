# Restarts the dashboard via start-dashboard.bat after backend changes.
#
# Why two modes rather than one PostToolUse hook: start-dashboard.bat is not cheap
# (it kills and respawns two console windows), so restarting on every file edit
# would fire repeatedly mid-task. Instead -Mark just records that a backend file
# was touched, and -Restart acts on it once when the turn ends.
#
#   -Mark     PostToolUse on Edit|Write. Drops a marker if the edited file is one
#             the uvicorn process actually imports. Never restarts anything.
#   -Restart  Stop hook. If a marker exists, restart, then clear the marker.
#
# The backend runs WITHOUT --reload in start-dashboard.bat (unlike the --reload
# command in CLAUDE.md), so a running server keeps serving stale code until it is
# restarted. That is the whole reason this hook exists.
#
# Deliberately a no-op when the dashboard is not already running: editing a backend
# file should never spontaneously launch servers and steal focus with new windows.

param(
    [switch]$Mark,
    [switch]$Restart
)

$ErrorActionPreference = 'Stop'

$marker = Join-Path $env:TEMP 'ebaypricer-backend-dirty'
$projectDir = if ($env:CLAUDE_PROJECT_DIR) { $env:CLAUDE_PROJECT_DIR } else { '.' }

# Files the backend process loads. Frontend changes are handled by Vite HMR, and
# scripts/ + db/migrations/ are not imported by the running server.
function Test-BackendPath([string]$path) {
    if (-not $path) { return $false }
    $p = $path -replace '\\', '/'
    if ($p -notmatch '\.py$') { return $false }
    return ($p -match '/dashboard/backend/') -or ($p -match '/src/ebaypricer/')
}

if ($Mark) {
    $raw = [Console]::In.ReadToEnd()
    try { $payload = $raw | ConvertFrom-Json } catch { exit 0 }

    $path = $payload.tool_response.filePath
    if (-not $path) { $path = $payload.tool_input.file_path }
    if (-not (Test-BackendPath $path)) { exit 0 }

    (Split-Path $path -Leaf) | Out-File -FilePath $marker -Encoding utf8 -Append
    exit 0
}

if (-not $Restart) { exit 0 }

if (-not (Test-Path $marker)) { exit 0 }
$changed = @(Get-Content $marker -ErrorAction SilentlyContinue | Where-Object { $_ }) |
    Select-Object -Unique
Remove-Item $marker -Force -ErrorAction SilentlyContinue

# Only restart something that is already up.
$listening = @()
try {
    $listening = @(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction Stop)
} catch {}
if ($listening.Count -eq 0) {
    @{ systemMessage = "Backend changed ($($changed -join ', ')) but the dashboard isn't running - not started. Run .\start-dashboard.bat when you want it." } |
        ConvertTo-Json -Compress
    exit 0
}

# Stop both servers before relaunching: start-dashboard.bat starts the backend AND
# the Vite dev server, so leaving :5173 up would make the new Vite silently pick
# 5174 and the user's open tab would keep talking to the old one.
foreach ($port in 8000, 5173) {
    try {
        Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop |
            Select-Object -ExpandProperty OwningProcess -Unique |
            ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
    } catch {}
}

# `< nul` feeds EOF to the batch file's trailing `pause` so the launcher exits
# instead of parking a window awaiting a keypress on every restart. The two server
# windows it spawns are independent and stay up.
$bat = Join-Path $projectDir 'start-dashboard.bat'
Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', "`"$bat`" < nul" `
    -WorkingDirectory $projectDir -WindowStyle Minimized

@{ systemMessage = "Restarted the dashboard (backend changed: $($changed -join ', ')). Backend :8000, frontend :5173 - give them a few seconds." } |
    ConvertTo-Json -Compress

exit 0
