# Claude Code Project Customization

This repository shares its engineering skills across Claude Code, Gemini/Antigravity, and Codex:

- Skills live in `.agents/skills/` and are discovered by Gemini/Antigravity and Codex directly.
- Claude Code requires skills under `.claude/skills/`, so each entry here is a thin stub whose
  frontmatter matches the shared skill and whose body defers to `.agents/skills/<name>/SKILL.md`.
  Edit the shared file, not the stub.
- Gemini/Antigravity hooks live in `.agents/hooks.json`.
- Codex hooks are translated into `.codex/hooks.json`, and Claude Code hooks into
  `.claude/settings.json`; all of them call the shared scripts in `.agents/scripts/`.
- The shared scripts already emit Claude Code's native hook contract
  (`hookSpecificOutput.permissionDecision` for `PreToolUse`, `decision: "block"` for `Stop`),
  so no client-specific wrappers are needed.
- Hook edits are picked up at session start. After changing `.claude/settings.json`, open `/hooks`
  once or restart Claude Code. (Codex likewise requires trust approval via its own `/hooks`.)

Project knowledge for Claude Code lives in [CLAUDE.md](../CLAUDE.md), which imports
[AGENTS.md](../AGENTS.md) so the architectural rules cannot drift between clients.

No project-scoped MCP servers are currently defined. MCP credentials and user-specific servers
stay in the local Claude configuration (`claude mcp add --scope user ...`); this repository must
not commit tokens or machine-specific endpoints.

`settings.local.json` is git-ignored and is the right place for personal overrides.
