"use client";

import ConnectorsPage from "../../components/ConnectorsPage";
import { useShell } from "../shell";

export default function ConnectorsRoutePage() {
  const { apiBase, tenantId, userRole, refreshTrigger, openConfigureModal } = useShell();
  return (
    // Refresh connector data through the prop so an open import dialog
    // survives a visibility refresh.
    <ConnectorsPage
      apiBase={apiBase}
      tenantId={tenantId}
      userRole={userRole}
      refreshTrigger={refreshTrigger}
      onOpenConfigureModal={openConfigureModal}
    />
  );
}
