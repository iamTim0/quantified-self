"use client";

import DataQualityTab from "../../components/DataQualityTab";
import { useShell } from "../shell";

export default function QualityPage() {
  const { apiBase, tenantId } = useShell();
  return <DataQualityTab apiBase={apiBase} tenantId={tenantId} />;
}
