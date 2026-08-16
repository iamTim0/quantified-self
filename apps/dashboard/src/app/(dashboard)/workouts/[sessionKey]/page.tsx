"use client";

import { use } from "react";
import { useRouter } from "next/navigation";
import WorkoutDetail from "../../../components/WorkoutDetail";
import { useShell } from "../../shell";

/**
 * `params` is a Promise in this Next version and is unwrapped with `use()`.
 * See `node_modules/next/dist/docs/` — the app router's dynamic APIs are async.
 */
export default function WorkoutDetailPage({
  params,
}: {
  params: Promise<{ sessionKey: string }>;
}) {
  const { sessionKey } = use(params);
  const { apiBase, onUnauthorized } = useShell();
  const router = useRouter();
  return (
    <WorkoutDetail
      apiBase={apiBase}
      sessionKey={decodeURIComponent(sessionKey)}
      onBack={() => router.push("/workouts")}
      onUnauthorized={onUnauthorized}
    />
  );
}
