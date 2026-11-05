# Obsidian Vault Rules (vault/)

This directory is an Obsidian vault for the EbayPrice project.
It is maintained by both humans and OpenCode. Open the `vault/` folder itself as the Obsidian vault.

Canonical code/architecture docs live outside the vault — do not duplicate them here:
- `CLAUDE.md`, `scripts/CLAUDE.md`, `dashboard/frontend/CLAUDE.md` (project conventions)
- `docs/SOFTWARE_PLAN.md` (schema, auth, migration plan — living design doc)

The vault summarizes and links to those; it never replaces them.

## Structure

- `00 - Dashboard/` — high-level project status (maintained via `project-status` skill)
- `01 - Requirements/` — requirements and specifications
- `02 - Architecture/` — architecture summaries, links into `docs/` and code
- `03 - Features/` — feature documentation
- `04 - Decisions/` — ADRs + Decision Log (append-only)
- `05 - Development/` — implementation notes, known issues, changelog
- `06 - Meetings/` — meeting notes
- `07 - Research/` — research and references
- `08 - Tasks/` — project tasks
- `99 - Archive/` — obsolete material (move, don't delete)

## Obsidian Rules

- Use Markdown with `[[Wiki Links]]` for internal references.
- No YAML frontmatter. Status/date lines (e.g. ADR status) go as bullets at the top of the note.
- Prefer descriptive filenames. Never create a duplicate note when an existing note can be updated.
- Do not rename, move, or delete notes unless explicitly requested.
- Do not modify `.obsidian/` unless explicitly requested.
- Keep one concept per note. Link related notes instead of repeating content.
- Keep `Table of Contents.md` (vault root) current: `## Folder` headers with `- [[Note]]` bullets, mirroring the folder structure.

## Writing Style

Match the existing notes:

- Start with a one-sentence definition or a `# Title`, then `###` sections.
- Separate major sections with `___` (or `---`).
- Terse `- ` bullets. Backticks for commands, paths, and code identifiers.
- Fenced code blocks with language tags for longer snippets.
- Document decisions and reasoning, not just implementation details.
- Be concise. Never repeat information across notes.

## Documentation Rules

When code changes introduce or modify functionality:

1. Determine whether existing vault notes are affected (search first).
2. Update the relevant existing note. Create a new note only if none fits.
3. Code is the source of truth for implementation behavior.
4. Existing ADRs are the source of truth for design intent — do not silently change a decision based on implementation. Record a new ADR instead.
5. Do not document behavior that cannot be verified from the code or the canonical docs above.
6. Never invent requirements, APIs, or behavior.

Skills that implement these workflows: `update-docs`, `project-status`, `organize-vault` in `.opencode/skills/`.

## Vault Sync Hook

`.opencode/plugins/vault-sync.js` tracks code edits and nudges the session on idle to run `update-docs`. It never edits vault/ itself.

- Watched: `src/`, `scripts/`, `dashboard/`, `db/migrations/`, `docs/`, `ebay-defaults-extension/`, plus root config files.
- Ignored: `vault/` edits, `.opencode/`, `.claude/`, caches, logs, local data.
- If `vault/` already has uncommitted changes at idle, the queue drops silently (docs handled in the same pass).
- Disable with `VAULT_SYNC=off`. Only fires in long-lived sessions (TUI / serve), not `opencode run`.

## Safety

- Before large structural changes: explain what will change, list affected notes, wait for approval.
- Never delete information because it looks outdated. Move it to `99 - Archive/` instead.
- For vault health checks and audits, prefer report-first (`organize-vault`, `@vault-reviewer`) then fix on approval.
