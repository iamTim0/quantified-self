"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import ConnectorModal from "../../../components/ConnectorModal";
import { useShell } from "../../shell";

/**
 * Connecting a new source, as a route.
 *
 * This was a dialog mounted in the dashboard layout, which is where it had to
 * live for the header's "+" to reach it from any tab. A URL does that without
 * any shared state, and gains three things the dialog could not have:
 *
 * - **Back closes it.** On Android the hardware back button used to dismiss the
 *   *page underneath* the open dialog, leaving the dialog floating over
 *   somewhere the reader had not asked to be. In an installed app, where there
 *   is no other back affordance, that was the only one.
 * - **It can be linked.** The documentation can point at the form for a
 *   provider instead of describing how to reach it.
 * - **It can be returned to.** Setup interrupted by fetching an API key from
 *   another app is a reload away from where it was, not a fresh start.
 *
 * The dialog's own presentation is unchanged: it still renders as an overlay
 * over the dashboard shell, because this route is inside that layout. What
 * changed is the address bar and what the browser's controls do.
 */
function NewConnector() {
  const router = useRouter();
  const params = useSearchParams();
  const { apiBase, tenantId, triggerRefresh } = useShell();

  // A provider chosen from the gallery arrives as `?type=`, so the form opens on
  // it directly; without one the dialog shows the gallery, as it always did.
  const sourceType = params.get("type") ?? undefined;

  const close = () => router.push("/connectors");

  return (
    <ConnectorModal
      isOpen
      onClose={close}
      apiBase={apiBase}
      tenantId={tenantId}
      initialSourceType={sourceType}
      isEditing={false}
      onSaved={() => {
        triggerRefresh();
        close();
      }}
    />
  );
}

export default function NewConnectorPage() {
  // `useSearchParams` opts this route into client-side rendering, and Next asks
  // for the boundary explicitly rather than inferring one.
  return (
    <Suspense fallback={null}>
      <NewConnector />
    </Suspense>
  );
}
