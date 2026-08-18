/**
 * Accessibility violations this build knowingly ships. Currently none.
 *
 * The mechanism exists rather than the backlog. It follows
 * `.agents/scripts/design_tokens_allowlist.json`, and for the same reason: a check
 * that fails on a pre-existing backlog gets switched off within a week, and a check
 * nobody runs protects nothing.
 *
 * It is deliberately **empty**, because the eight violations the suite found on its
 * first run were fixed rather than recorded — five contrast defects and three
 * undersized controls, all of them small edits. An empty allowlist is what makes
 * this a gate instead of a ratchet: the next violation to appear is new by
 * definition, and belongs to whoever just wrote it.
 *
 * Adding an entry is a decision that gets written down (AGENTS.md rule 14), so it
 * comes with the commit that argues for it. Each key names the route, the theme and
 * the axe rule, so removing it later is a one-line change. Deleting entries is the
 * intended direction of travel.
 */

/** `route|theme|axe-rule`. Theme is included because contrast differs per theme. */
export function violationKey(route: string, theme: string, ruleId: string): string {
  return `${route}|${theme}|${ruleId}`;
}

export const KNOWN_VIOLATIONS = new Set<string>();
