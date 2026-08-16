# PostToolUse hook: when a pipeline script that writes an Excel sheet is edited,
# remind the agent about the two downstream mappings that fail SILENTLY.
#
# Renaming or adding a column in get_active.py / append_sold_orders.py does not
# error anywhere - the field just never reaches the dashboard unless the column
# maps in excel_sync.py are updated too, and connected users additionally miss it
# unless ebay_data.py's OAuth sync path grows the same field.
#
# Advisory only: injects context, never blocks.

$ErrorActionPreference = 'Stop'

$raw = [Console]::In.ReadToEnd()
try { $payload = $raw | ConvertFrom-Json } catch { exit 0 }

$path = $payload.tool_input.file_path
if (-not $path) { exit 0 }

$name = Split-Path $path -Leaf
if ($name -notin @('get_active.py', 'append_sold_orders.py')) { exit 0 }

$sheet = if ($name -eq 'get_active.py') { '_ACTIVE_COLUMNS' } else { '_SOLD_COLUMNS' }

@{
    hookSpecificOutput = @{
        hookEventName    = 'PostToolUse'
        additionalContext = @"
You just edited $name, which writes an Excel sheet the dashboard reads.

If you renamed, added, or removed a column, two places must change or the field
silently never reaches the dashboard (no error is raised anywhere):

  1. dashboard/backend/services/excel_sync.py -> $sheet
  2. dashboard/backend/services/ebay_data.py  -> the per-user OAuth sync path,
     or users connected via OAuth (rather than the Excel workbook) won't get it.

If this edit did not touch column names, ignore this.
"@
    }
} | ConvertTo-Json -Depth 5 -Compress

exit 0
