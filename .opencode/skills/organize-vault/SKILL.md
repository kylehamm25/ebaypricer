---
name: organize-vault
description: Audit vault health for broken links, duplicates, orphans, and stale content with report-first fixes
---

# Organize Vault

Vault maintenance for `vault/`. Vault-local rules in `vault/AGENTS.md` take precedence. Default is **report-first**: audit, then fix only on approval.

## Audit (default)

Run a health check and report findings grouped by severity. Do not modify anything in audit mode:

1. Broken `[[Wiki Links]]` (target note does not exist).
2. Orphaned notes (no inbound links, excluding Dashboard / Decision Log / Archive).
3. Duplicate or heavily overlapping notes (same concept in two places).
4. Stale references: notes contradicting code or canonical docs (`CLAUDE.md`, `docs/SOFTWARE_PLAN.md`).
5. Inconsistent terminology (e.g. mixed names for the same table, route, or feature).
6. Misplaced notes (wrong `vault/` section) and notes breaking house style (frontmatter added, wrong header level, missing from `Table of Contents.md`).

Report format per finding: severity (high/medium/low) — note — problem — recommended action.

## Fix (only when explicitly asked)

- Fix broken links and terminology inconsistencies.
- Merge duplicates by folding content into the most relevant note and moving the other to `vault/99 - Archive/`.
- Never delete notes. Never rename/move unless explicitly requested in the fix instruction.
- Never touch `.obsidian/` cache files.
- End with `git status` / `git diff --stat` so the user can review.
