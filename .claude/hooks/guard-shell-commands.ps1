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
# auto_boost_promotion.py raises real promoted-listing ad rates through the
# Marketing API - that spends money and is not a preview unless --dry-run is
# passed. scripts/main.py is deliberately NOT matched any more: the boost step
# was removed from the pipeline, so main.py no longer writes to eBay at all.
if ($cmd -match 'scripts[/\\]auto_boost_promotion\.py' -and $cmd -notmatch '--dry-run') {
    Send-Decision 'ask' @'
This changes LIVE promoted-listing ad rates without --dry-run.

auto_boost_promotion.py raises real ad rates via the Marketing API (it spends
money, and the bid changes are not trivially reversible). It is no longer part
of the pipeline - running it is always a deliberate act.

Add --dry-run to preview the changes instead, or approve to apply for real.
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
