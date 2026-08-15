"use client";

import AnalysisTab from "../../components/AnalysisTab";
import { useShell } from "../shell";

export default function AnalysisPage() {
  const { apiBase, tenantId, refreshTrigger } = useShell();
  return <AnalysisTab apiBase={apiBase} tenantId={tenantId} refreshTrigger={refreshTrigger} />;
}
