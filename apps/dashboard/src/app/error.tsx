"use client";

import CrashScreen from "./components/CrashScreen";

/**
 * The boundary for everything outside the dashboard shell — sign-in, the OIDC
 * callback, the legal pages — and for a throw in the dashboard layout itself, which
 * the boundary inside that group cannot catch.
 *
 * Still inside the root layout, so `LocaleProvider` is mounted and this is
 * translated. Only `global-error.tsx` sits outside it, and only that file has to
 * solve the language problem the hard way.
 */
export default function AppError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return <CrashScreen error={error} reset={reset} />;
}
