"use client";

import { useRouter } from "next/navigation";
import WorkoutsTab from "../../components/WorkoutsTab";
import { useShell } from "../shell";

export default function WorkoutsPage() {
  const { apiBase, refreshTrigger, onUnauthorized } = useShell();
  const router = useRouter();
  return (
    <WorkoutsTab
      key={refreshTrigger}
      apiBase={apiBase}
      onOpen={(sessionKey) => router.push(`/workouts/${encodeURIComponent(sessionKey)}`)}
      onUnauthorized={onUnauthorized}
    />
  );
}
