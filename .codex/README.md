# Codex Project Customization

This repository shares its engineering skills across Gemini/Antigravity, Codex, and Claude Code:

- Skills live in `.agents/skills/` and are discovered directly by Gemini/Antigravity and Codex.
- Claude Code registers the same skills through stubs in `.claude/skills/` that defer to `.agents/skills/`.
- Gemini/Antigravity hooks live in `.agents/hooks.json`.
- Codex hooks are translated into `.codex/hooks.json` and call the shared scripts in `.agents/scripts/`.
- Claude Code hooks are translated into `.claude/settings.json` and call the same shared scripts.
- Codex project hooks require trust approval in `/hooks` the first time they are changed.

No project-scoped MCP servers are currently defined. MCP credentials and user-specific servers stay in the local Codex configuration; this repository must not commit tokens or machine-specific endpoints.
