"use client";

import { useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";

/**
 * One collapsible section, and the only one this app should have.
 *
 * There were three patterns doing this before: `DataQualityTab` used a native
 * `<details>` with a rotating glyph, `ImportDialog` used one without, and
 * `AnalysisTab` hand-rolled `useState` plus `aria-expanded` on a button. Three
 * spellings of one idea is how a phone ends up with a section that opens by
 * keyboard on one screen and not on the next.
 *
 * **Native `<details>`, deliberately.** Keyboard operation, the open/closed state
 * exposed to assistive technology, and Chrome's find-in-page reaching collapsed
 * text all come free. Nothing here sets `aria-expanded`: `<summary>` already
 * publishes that state, and a second attribute beside it is a duplicate
 * announcement rather than extra help.
 *
 * **`meta` is not decoration.** A column of closed sections is only navigable if
 * each says what is inside it — "4 values", "12 entries", "1,830 kcal". A
 * disclosure whose summary is a bare noun makes the reader open every one, which
 * is worse than the wall of content it replaced.
 *
 * **`note` lives inside `<summary>`.** Everything else in a `<details>` is hidden
 * while it is closed, and a note is precisely the line that has to survive being
 * closed — a lane whose connector last ran at 06:00 must say so without being
 * opened. It costs nothing: a `<summary>` may contain flow content, and the
 * larger target is easier to hit.
 */
export default function Disclosure({
  title,
  meta,
  children,
  defaultOpen = false,
  mountOnOpen = false,
  className = "",
  contentClassName = "",
  note,
  titleAs,
  id,
}: {
  title: ReactNode;
  /** Short right-aligned summary of what is inside — a count, a total, a state. */
  meta?: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  /**
   * Render `children` only while open.
   *
   * Required for anything that measures itself: Chart.js reads a canvas of 0×0
   * inside a `display:none` subtree, and Leaflet needs `invalidateSize()` after
   * one appears. It is also the better deferral for expensive content — a reader
   * asking for it is a more precise signal than proximity to the viewport.
   */
  mountOnOpen?: boolean;
  className?: string;
  contentClassName?: string;
  /** A line that must stay legible while collapsed, such as a freshness warning. */
  note?: ReactNode;
  /**
   * Render the title as a real heading.
   *
   * Collapsing a screen into disclosures otherwise deletes its outline: a reader
   * navigating by heading loses every section at once, which is a worse trade
   * than the density it bought. `<summary>` takes flow content, so a heading
   * inside it is valid and keeps the document structure the cards used to carry.
   */
  titleAs?: "h2" | "h3" | "h4";
  /**
   * A DOM id, so something elsewhere on the page can open this one.
   *
   * Used by the correlation matrix: a cell is a shortcut to the card for that
   * pair, and with a native `<details>` "open it" is `element.open = true`
   * followed by `scrollIntoView()`. The `scroll-padding` declared on `html`
   * keeps the result clear of the sticky header and the tab bar.
   */
  id?: string;
}) {
  const TitleTag = titleAs ?? "span";
  // Controlled rather than `defaultOpen` on the element: React re-applies its
  // props on every render, so an uncontrolled `open` would snap back shut the
  // next time the parent re-rendered for an unrelated reason.
  const [open, setOpen] = useState(defaultOpen);

  return (
    <details
      id={id}
      open={open}
      onToggle={(event) => setOpen((event.currentTarget as HTMLDetailsElement).open)}
      className={`group rounded-2xl border border-line bg-surface ${className}`}
    >
      {/*
        `min-h-11` is the 44px target a thumb needs; `touch-action: manipulation`
        removes the 300ms the browser otherwise waits to see whether a tap was
        the first half of a double-tap zoom. `list-none` plus `marker:hidden`
        covers both the WebKit and the Blink spellings of the default triangle.
      */}
      <summary className="cursor-pointer list-none touch-manipulation px-4 py-2.5 marker:hidden">
        <div className="flex min-h-11 items-center gap-3">
          <ChevronDown
            className="h-4 w-4 shrink-0 text-ink-faint transition-transform group-open:rotate-180"
            aria-hidden="true"
          />
          <TitleTag className="min-w-0 flex-1 text-body font-semibold text-ink">{title}</TitleTag>
          {meta !== undefined && meta !== null && (
            <span className="shrink-0 text-meta tabular-nums text-ink-muted">{meta}</span>
          )}
        </div>
        {note !== undefined && note !== null && (
          <div className="pl-7 text-meta text-ink-muted">{note}</div>
        )}
      </summary>

      <div className={`border-t border-line px-4 py-3 ${contentClassName}`}>
        {mountOnOpen && !open ? null : children}
      </div>
    </details>
  );
}
