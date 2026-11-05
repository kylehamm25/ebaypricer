# ADR-001 - Vault Structure

- Status: accepted
- Date: 2026-10-06

___
### Context
- Repo already has canonical docs (`CLAUDE.md`, `docs/SOFTWARE_PLAN.md`) and OpenCode skills in `.claude/skills/`
- Need a human-browsable Obsidian layer that OpenCode can maintain without duplicating those sources

___
### Decision
- Vault lives in `vault/`, open that folder itself as the Obsidian vault
- Vault-local rules in `vault/AGENTS.md`, root `AGENTS.md` only points at it
- New skills in `.opencode/skills/` (`update-docs`, `project-status`, `organize-vault`), names kept unique vs `.claude/skills/`
- Read-only reviewer at `.opencode/agents/vault-reviewer.md`
- Vault summarizes and links, canonical docs stay the source of truth

___
### Alternatives
- Vault as repo root - rejected, `.obsidian/` cache plus hundreds of code files would pollute Obsidian
- Separate vault repo - rejected, OpenCode could not reason over code + docs together
- Copying `.claude/skills/*` under `.opencode/` - rejected, names must stay unique across skill locations

___
### Consequences
- One `git status` / `git diff` reviews code and doc changes together
- Contributors must open `vault/` (not repo root) in Obsidian

___
### Related
- [[Project Dashboard]]
- [[Decision Log]]
- [[System Architecture]]
