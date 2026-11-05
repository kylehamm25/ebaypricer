---
name: project-status
description: Refresh the vault Project Dashboard from actual repo state and recent history
---

# Project Status

Refresh `vault/00 - Dashboard/Project Dashboard.md` from verifiable repo state. Vault-local rules in `vault/AGENTS.md` take precedence.

## Workflow

1. Gather evidence (read-only):
   - `git log --oneline -15`, `git status`, `git diff --stat`
   - `vault/08 - Tasks/`, `vault/05 - Development/` (known issues, changelog)
   - `vault/04 - Decisions/Decision Log.md` (pending `proposed` ADRs)
2. Update only the `Project Dashboard.md` sections that the evidence supports: Status, Current Focus, Recently Completed, In Progress, Known Issues, Recent Changes.
3. Link to notes (`[[Decision Log]]`, `[[System Architecture]]`, task notes) instead of pasting content.
4. Keep the dashboard's existing note style (no frontmatter, `###` sections, `___` separators) — hand-written sections stay human-owned, only update what the evidence supports.
5. Report what changed on the dashboard and which evidence each line came from.

## Guardrails

- Do not invent progress. If git log and task notes disagree, say so and prefer git log for "completed", task notes for "planned".
- Never delete dashboard history to make it look clean — move stale items to `vault/99 - Archive/` only on explicit request.
- Do not edit any other vault note as a side effect. Use `update-docs` for that.
- Do not touch `.obsidian/` cache files.
