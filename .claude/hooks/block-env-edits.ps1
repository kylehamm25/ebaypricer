# PreToolUse hook: refuse Edit/Write against .env files.
#
# .env holds live eBay OAuth refresh tokens, the Supabase service key, and
# EBAY_TOKEN_ENCRYPTION_KEY. auth.py rewrites it at runtime on every token
# refresh, so an edit here can also race the pipeline and clobber a fresh token.
# Templates (.env.example and friends) are tracked in git and stay editable.
#
# Reads the PreToolUse payload on stdin; emits a deny decision as JSON.
# Written in PowerShell deliberately: this machine has no jq, and `bash`
# resolves to WSL bash, which sees a different filesystem.

$ErrorActionPreference = 'Stop'

$raw = [Console]::In.ReadToEnd()
try { $payload = $raw | ConvertFrom-Json } catch { exit 0 }

$path = $payload.tool_input.file_path
if (-not $path) { exit 0 }

$name = Split-Path $path -Leaf

# Tracked templates carry no secrets - leave them editable.
if ($name -match '^\.env\.(example|sample|template)$') { exit 0 }

if ($name -eq '.env' -or $name -like '.env.*') {
    @{
        hookSpecificOutput = @{
            hookEventName            = 'PreToolUse'
            permissionDecision       = 'deny'
            permissionDecisionReason = "Blocked by the block-env-edits hook: $name holds live secrets (eBay OAuth tokens, Supabase keys) and is rewritten at runtime by auth.py. Edit it by hand, or add the key to .env.example if this is new config."
        }
    } | ConvertTo-Json -Depth 5 -Compress
}

exit 0
