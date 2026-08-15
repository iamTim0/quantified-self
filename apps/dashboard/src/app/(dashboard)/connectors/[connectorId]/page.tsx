"use client";

import { use } from "react";
import ConnectorsPage from "../../../components/ConnectorsPage";
import { useShell } from "../../shell";

/**
 * One connector instance, in detail.
 *
 * The id arrives as a route parameter rather than being parsed back out of
 * `usePathname()`, which is what this used to do from inside the connector list.
 */
export default function ConnectorDetailRoutePage({
  params,
}: {
  params: Promise<{ connectorId: string }>;
}) {
  const { connectorId } = use(params);
  const { apiBase, tenantId, refreshTrigger, openConfigureModal } = useShell();

  return (
    <ConnectorsPage
      apiBase={apiBase}
      tenantId={tenantId}
      refreshTrigger={refreshTrigger}
      onOpenConfigureModal={openConfigureModal}
      connectorId={decodeURIComponent(connectorId)}
    />
  );
}
