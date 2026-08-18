"use client";

import { useRouter } from "next/navigation";
import { use, useCallback, useEffect, useState } from "react";

import ConnectorModal from "../../../../components/ConnectorModal";
import type { ConnectorItem } from "../../../../components/ConnectorsPage";
import { apiFetch } from "../../../../lib/api";
import { useShell } from "../../../shell";

/**
 * Editing one connector, as a route rather than a dialog.
 *
 * Same reasoning as `/connectors/new`: back closes it, the URL can be linked,
 * and the layout no longer carries state for a screen most sessions never open.
 *
 * The connector is fetched here rather than handed over in memory. That is the
 * point of a route — arriving by link, by reload or by back button all have to
 * work, and none of them can bring a JavaScript object with them.
 */
export default function EditConnectorPage({
  params,
}: {
  params: Promise<{ connectorId: string }>;
}) {
  const { connectorId } = use(params);
  const id = decodeURIComponent(connectorId);
  const router = useRouter();
  const { apiBase, tenantId, triggerRefresh } = useShell();
  const [connector, setConnector] = useState<ConnectorItem | null>(null);
  const [missing, setMissing] = useState(false);

  const close = useCallback(() => router.push(`/connectors/${encodeURIComponent(id)}`), [id, router]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const response = await apiFetch(`${apiBase}/api/v1/data/sources`);
      if (cancelled || !response.ok) return;
      const body = (await response.json()) as { connectors?: ConnectorItem[] };
      const found = (body.connectors ?? []).find((entry) => entry.id === id);
      if (cancelled) return;
      if (found) setConnector(found);
      else setMissing(true);
    })();
    return () => {
      cancelled = true;
    };
  }, [apiBase, id]);

  // A connector that is not there any more sends the reader back to the list
  // rather than showing an empty form that would create a second one on save.
  useEffect(() => {
    if (missing) router.replace("/connectors");
  }, [missing, router]);

  if (!connector) return null;

  return (
    <ConnectorModal
      isOpen
      onClose={close}
      apiBase={apiBase}
      tenantId={tenantId}
      initialSourceType={connector.source_type}
      // Which instance is being edited. Without it the dialog would create a new
      // connector every time instead of updating the one that was opened.
      initialSourceId={connector.id}
      initialDisplayName={connector.display_name}
      initialPollInterval={connector.poll_interval_hours || 6}
      initialLookbackDays={connector.lookback_days || 7}
      initialLookbackHours={
        connector.lookback_hours || (connector.lookback_days ? connector.lookback_days * 24 : 168)
      }
      // Which kind of connector this is, so editing one fed by uploads does not
      // silently turn it back into a polled one.
      initialImportMode={connector.import_mode}
      isEditing
      onSaved={() => {
        triggerRefresh();
        close();
      }}
    />
  );
}
