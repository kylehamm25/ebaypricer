# PreToolUse hook for Bash/PowerShell. Two checks, deliberately in one script:
# both only need the command string, and a second hook would mean a second pwsh
# spawn on every shell command the agent runs.
#
#   1. ASK before a pipeline run that mutates live eBay state.
#   2. DENY a git commit carrying AI attribution (CLAUDE.md forbids it).
#
# Reads the PreToolUse payload on stdin; emits a decision as JSON.

$ErrorActionPreference = 'Stop'

$raw = [Console]::In.ReadToEnd()
try { $payload = $raw | ConvertFrom-Json } catch { exit 0 }

$cmd = $payload.tool_input.command
if (-not $cmd) { exit 0 }

function Send-Decision {
    param([string]$Decision, [string]$Reason)
    @{
        hookSpecificOutput = @{
            hookEventName            = 'PreToolUse'
            permissionDecision       = $Decision
            permissionDecisionReason = $Reason
        }
    } | ConvertTo-Json -Depth 5 -Compress
    exit 0
}

# --- 1. Live eBay writes ------------------------------------------------------
# scripts/main.py ends with auto_boost_promotion.py, which raises real promoted-
# listing ad rates through the Marketing API - that spends money and is not a
# preview unless --dry-run is passed. Scoped to scripts/ so it never catches
# `python -m uvicorn dashboard.backend.main:app` or dashboard/backend/main.py.
if ($cmd -match 'scripts[/\\](main|auto_boost_promotion)\.py' -and $cmd -notmatch '--dry-run') {
    Send-Decision 'ask' @'
This runs the pipeline against LIVE eBay data without --dry-run.

auto_boost_promotion.py raises real promoted-listing ad rates via the Marketing
API (it spends money, and the bid changes are not trivially reversible).

Add --dry-run to preview promotion changes instead, or approve to apply for real.
'@
}

# --- 2. AI attribution in commits --------------------------------------------
# CLAUDE.md: never put Claude/AI attribution or Co-Authored-By in anything
# pushed to GitHub. CLAUDE.md is scrubbed from the text first so an ordinary
# `git commit -m "Update CLAUDE.md"` is not a false positive.
if ($cmd -match 'git\s+commit') {
    $scrubbed = $cmd -replace '(?i)CLAUDE\.md', ''
    $found = @()
    if ($scrubbed -match '(?i)co-authored-by') { $found += 'Co-Authored-By' }
    if ($scrubbed -match '(?i)generated with')  { $found += 'Generated with' }
    if ($scrubbed -match '(?i)claude')          { $found += 'Claude' }
    if ($scrubbed -match '(?i)anthropic')       { $found += 'Anthropic' }

    if ($found.Count -gt 0) {
        Send-Decision 'deny' ("Blocked by the commit-attribution hook: the commit message contains " +
            ($found -join ', ') + ". CLAUDE.md forbids Claude/AI attribution, signatures, and " +
            "Co-Authored-By lines in anything pushed to GitHub. Rewrite the message without them.")
    }
}

exit 0
