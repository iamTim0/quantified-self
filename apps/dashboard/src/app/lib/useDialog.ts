"use client";

/**
 * The keyboard behaviour a dialog has to have before it may say `aria-modal`.
 *
 * Three dialogs in this app set `role="dialog"`; two of them also set
 * `aria-modal="true"`, which tells assistive technology that everything outside
 * the subtree is inert. Nothing enforced that. Focus was never moved in, Tab
 * walked straight out of the back of the dialog into content a screen reader had
 * just been told did not exist, Escape did nothing, and the page behind kept
 * scrolling.
 *
 * `MobileTabBar` had reached the honest conclusion on its own and dropped
 * `aria-modal`, with a comment saying it would claim less until there was a real
 * focus trap. This is that trap, so all three can claim the same thing and mean
 * it.
 *
 * ## Why not `<dialog>`
 *
 * `HTMLDialogElement.showModal()` gives the trap, Escape and the inert
 * background for free, and it would be the right answer for a new component.
 * Retrofitting it here means changing how three dialogs mount and render — they
 * are conditionally rendered rather than imperatively opened — which is a larger
 * change than the bug warrants. This hook is ~60 lines and leaves the markup
 * alone.
 *
 * ## What it does
 *
 * * Moves focus to the first focusable element inside, on open.
 * * Cycles Tab and Shift+Tab within the dialog.
 * * Closes on Escape.
 * * Returns focus to whatever was focused before it opened — otherwise focus
 *   falls to `<body>` and the next Tab restarts at the top of the document.
 * * Locks scrolling on the page behind.
 */

import { useCallback, useEffect, useRef } from "react";

/** Everything the browser will let a user Tab to, minus the ones it will not. */
const FOCUSABLE = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(", ");

function focusableWithin(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    // `offsetParent` is null for anything `display:none`, which is how a
    // collapsed step's controls would otherwise join the tab cycle.
    (element) => element.offsetParent !== null || element === document.activeElement,
  );
}

export function useDialog<T extends HTMLElement = HTMLDivElement>(
  open: boolean,
  onClose: () => void,
) {
  const ref = useRef<T>(null);
  const opener = useRef<HTMLElement | null>(null);

  // Held in a ref so the effect below does not re-run — and re-take focus —
  // every time the caller passes a new inline closure.
  const close = useRef(onClose);
  close.current = onClose;

  const onKeyDown = useCallback((event: KeyboardEvent) => {
    if (event.key === "Escape") {
      event.stopPropagation();
      close.current();
      return;
    }
    if (event.key !== "Tab" || !ref.current) return;

    const items = focusableWithin(ref.current);
    if (items.length === 0) {
      // Nothing to land on; keep focus in the dialog rather than letting it out.
      event.preventDefault();
      return;
    }
    const first = items[0];
    const last = items[items.length - 1];
    const active = document.activeElement;

    if (event.shiftKey && (active === first || !ref.current.contains(active))) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  }, []);

  useEffect(() => {
    if (!open) return;

    opener.current = document.activeElement as HTMLElement | null;

    // The dialog's own content decides what deserves focus first; falling back
    // to the container means a screen reader still starts inside rather than at
    // the top of the page.
    const target = ref.current ? focusableWithin(ref.current)[0] : null;
    (target ?? ref.current)?.focus();

    document.addEventListener("keydown", onKeyDown, true);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      document.body.style.overflow = previousOverflow;
      opener.current?.focus();
    };
  }, [open, onKeyDown]);

  return ref;
}
