# Codex Project Customization

This repository shares its engineering skills across Gemini/Antigravity and Codex:

- Skills live in `.agents/skills/` and are discovered by both clients.
- Gemini/Antigravity hooks live in `.agents/hooks.json`.
- Codex hooks are translated into `.codex/hooks.json` and call the shared scripts in `.agents/scripts/`.
- Codex project hooks require trust approval in `/hooks` the first time they are changed.

No project-scoped MCP servers are currently defined. MCP credentials and user-specific servers stay in the local Codex configuration; this repository must not commit tokens or machine-specific endpoints.
