"use client";

import ExplorerTab from "../../components/ExplorerTab";
import { useShell } from "../shell";

export default function ExplorerPage() {
  const { apiBase, tenantId, refreshTrigger } = useShell();
  return <ExplorerTab key={refreshTrigger} apiBase={apiBase} tenantId={tenantId} />;
}
