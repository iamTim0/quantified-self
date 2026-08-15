export const dynamic = "force-dynamic";

export function GET() {
  return Response.json(
    {
      status: "ok",
      service: "qs-dashboard",
      version: process.env.QS_SERVICE_VERSION || "dev",
      commit: process.env.QS_SOURCE_COMMIT || "unknown",
    },
    { headers: { "Cache-Control": "no-store" } },
  );
}
