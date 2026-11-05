// Vault sync hook: after code edits, nudge the agent to update vault/ docs.
//
// How it works:
// - "tool.execute.after" records every edit/write to a watched code path in a
//   pending queue (.opencode/.vault-sync-state.json, gitignored).
// - On session idle, if the queue is non-empty and vault/ itself was NOT
//   touched, it asks the session (fire-and-forget) to run the update-docs
//   skill against the queued files. The queue is cleared before prompting so
//   the follow-up turn cannot re-trigger itself.
// - If vault/ already has uncommitted changes, the queue is dropped silently:
//   docs were handled in the same pass.
//
// Safety: the hook never edits vault/ itself. It only prompts. The agent
// still decides what is doc-worthy (update-docs skill rules apply).
// Disable: set VAULT_SYNC=off in the environment.
// Note: in `opencode run` the process exits at first idle, so the nudge only
// fires in long-lived sessions (TUI / serve). The pending queue survives, so
// the next interactive idle still picks it up.

export const VaultSyncPlugin = async ({ client, directory, $ }) => {
  const STATE_FILE = `${directory}/.opencode/.vault-sync-state.json`;
  const COOLDOWN_MS = 5 * 60 * 1000;

  const WATCH_PREFIXES = [
    "src/",
    "scripts/",
    "dashboard/",
    "db/migrations/",
    "docs/",
    "ebay-defaults-extension/",
  ];
  const WATCH_FILES = [
    "pyproject.toml",
    "requirements.txt",
    "requirements-dashboard.txt",
    "Dockerfile",
    "opencode.json",
  ];
  const IGNORE_PREFIXES = [
    "vault/",
    ".opencode/",
    ".claude/",
    ".git/",
    ".obsidian/",
    "node_modules/",
    ".venv/",
    "__pycache__/",
    "logs/",
    "data/",
    "dist/",
  ];
  const IGNORE_SUFFIXES = [".gitkeep", ".log", ".pyc", ".xml", ".db"];

  const toRel = (p) => {
    if (!p || typeof p !== "string") return null;
    let rel = p.replace(/\\/g, "/");
    const dir = String(directory).replace(/\\/g, "/").replace(/\/$/, "");
    if (rel.startsWith(dir + "/")) rel = rel.slice(dir.length + 1);
    rel = rel.replace(/^\.\//, "").replace(/^\/+/, "");
    return rel || null;
  };

  const isRelevant = (rel) => {
    if (!rel) return false;
    for (const pre of IGNORE_PREFIXES) if (rel.startsWith(pre)) return false;
    for (const suf of IGNORE_SUFFIXES) if (rel.endsWith(suf)) return false;
    if (WATCH_FILES.includes(rel)) return true;
    for (const pre of WATCH_PREFIXES) if (rel.startsWith(pre)) return true;
    return false;
  };

  const loadState = async () => {
    try {
      const f = Bun.file(STATE_FILE);
      if (await f.exists()) {
        const s = await f.json();
        if (Array.isArray(s.pending)) return { pending: s.pending, lastAttempt: s.lastAttempt || 0 };
      }
    } catch {}
    return { pending: [], lastAttempt: 0 };
  };

  const saveState = async (s) => {
    try {
      await Bun.write(STATE_FILE, JSON.stringify(s));
    } catch {}
  };

  const vaultTouched = async () => {
    try {
      const out = await $`git status --porcelain`.cwd(directory).text();
      return out.split("\n").some((line) => line.slice(3).trimStart().startsWith("vault/"));
    } catch {
      return false;
    }
  };

  const log = async (level, message, extra) => {
    try {
      await client.app.log({ body: { service: "vault-sync", level, message, extra } });
    } catch {}
  };

  return {
    "tool.execute.after": async (input, output) => {
      try {
        const tool = input?.tool;
        if (tool !== "edit" && tool !== "write" && tool !== "apply_patch") return;
        const raw =
          output?.args?.filePath ?? input?.args?.filePath ?? output?.args?.path ?? input?.args?.path;
        const rel = toRel(raw);
        if (!isRelevant(rel)) return;
        const state = await loadState();
        if (!state.pending.includes(rel)) {
          state.pending.push(rel);
          await saveState(state);
          await log("debug", `queued for vault sync: ${rel}`);
        }
      } catch {}
    },

    event: async ({ event }) => {
      try {
        const type = event?.type;
        const props = event?.properties ?? {};
        const status = props.status;
        const isIdle =
          type === "session.idle" ||
          (type === "session.status" && (status?.type === "idle" || status === "idle"));
        if (!isIdle) return;

        const sessionID = props.sessionID;
        if (!sessionID) return;
        if (process.env.VAULT_SYNC === "off") return;

        const state = await loadState();
        if (!state.pending.length) return;

        // Docs already handled in this pass: drop the queue quietly, even on cooldown.
        if (await vaultTouched()) {
          await saveState({ pending: [], lastAttempt: state.lastAttempt || 0 });
          await log("debug", "vault/ touched, dropping sync queue");
          return;
        }

        if (Date.now() - (state.lastAttempt || 0) < COOLDOWN_MS) return;

        const files = [...new Set(state.pending)];
        // Clear BEFORE prompting so the follow-up turn cannot re-arm itself.
        await saveState({ pending: [], lastAttempt: Date.now() });

        const text =
          `Vault sync: these code files were edited since the last docs update:\n` +
          files.map((f) => `- ${f}`).join("\n") +
          `\nFollow the update-docs skill (skill({ name: "update-docs" })): update the affected vault/ notes, or reply that nothing doc-worthy changed. Keep vault style (no frontmatter, ### sections, ___ separators, Table of Contents current). Do not rewrite unrelated notes.`;

        await client.session
          .promptAsync({ path: { id: sessionID }, body: { parts: [{ type: "text", text }] } })
          .catch(() => {});
        await log("info", `vault sync prompted for ${files.length} file(s)`, { sessionID });
      } catch {}
    },
  };
};
