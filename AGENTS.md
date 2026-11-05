# AGENTS.md (OpenCode)

Canonical project docs live in the Claude files — read them there, don't duplicate them here:

- `CLAUDE.md` — what the project is, commands, architecture, pipeline/dashboard boundary.
- `scripts/CLAUDE.md` — hand-run tools detail (the legacy Excel chain was retired Oct 2026; read when working in `scripts/`).
- `dashboard/frontend/CLAUDE.md` — frontend routes, components, never-compute-a-price rule (read when working in `dashboard/frontend/`).
- `docs/SOFTWARE_PLAN.md` — schema, auth, and migration plan (living design doc).

The three `CLAUDE.md` files are also wired via `instructions` in `opencode.json`, so they load in OpenCode even though this file takes precedence over the `CLAUDE.md` fallback.

Skills in `.claude/skills/` (`ebay-pricing-rules`, `ebay-api-rate-limits`, `ebay-listing-dry-run`, `listing-defaults-audit`) are auto-discovered by OpenCode — keep them there, don't copy them under `.opencode/` (names must stay unique across all skill locations).

`.claude/hooks/`, `.claude/settings.json` and `.claude/settings.local.json` are Claude Code-only and have no OpenCode equivalent here — safe to ignore.

## Obsidian vault (`vault/`)

Open `vault/` itself as the Obsidian vault. Vault-local rules live in `vault/AGENTS.md` — read it when working in `vault/`.
Project skills in `.opencode/skills/` (`update-docs`, `project-status`, `organize-vault`) and reviewer agent `.opencode/agents/vault-reviewer.md` implement the repeatable vault workflows. Invoke with e.g. `skill({ name: "update-docs" })` or `@vault-reviewer`.
Plugin `.opencode/plugins/vault-sync.js` queues code edits and prompts an `update-docs` pass on session idle (never edits vault/ itself; `VAULT_SYNC=off` disables).
