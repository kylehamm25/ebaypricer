---
name: update-docs
description: Synchronize vault Obsidian notes with current code changes without creating duplicates
---

# Update Docs

Keep `vault/` synchronized with the codebase. Vault-local rules in `vault/AGENTS.md` take precedence.

## Workflow

1. Inspect current changes: `git status`, `git diff`, `git log --oneline -10`.
2. Identify functionality that actually changed (not formatting).
3. Search the vault first for affected concepts: feature names, API routes, components, DB tables, existing ADRs. Prefer `grep`/`glob` over guessing.
4. Update the most relevant **existing** note. Create a new note only when no note fits — and place it in the correct `vault/` section.
5. Add `[[Wiki Links]]` between related notes. No YAML frontmatter — match the existing note style (`###` sections, `___` separators, terse bullets).
6. If the change looks like an architectural/design decision, draft an ADR in `vault/04 - Decisions/` as `proposed` and add it to `[[Decision Log]]` — never silently rewrite an accepted ADR.
7. Summarize doc changes when finished (note + what changed + why).

## Priority (EbayPrice)

- Code is the source of truth for implementation behavior.
- Existing ADRs are the source of truth for design intent.
- Canonical docs (`CLAUDE.md`, `docs/SOFTWARE_PLAN.md`) are the source of truth for architecture — summarize and link, don't copy.
- Pricing logic: the current path is `dashboard/backend/services/price_research.py` + `services/suggested_price.py`. Never document or reintroduce frontend price computation.

## Guardrails

- Never delete documentation. If obsolete, move to `vault/99 - Archive/`.
- Do not rename/move notes unless explicitly requested.
- Do not invent requirements, APIs, or behavior. Only document what the diff and code verify.
- Do not touch `vault/.obsidian/` or `.obsidian/` cache files.
- For large structural changes: report affected notes first, wait for approval.
