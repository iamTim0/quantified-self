"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  BookOpen,
  CalendarX2,
  Lightbulb,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import ImportDialog from "./ImportDialog";

// tenantId is no longer read: Core derives the tenant from the bearer token, so the
// prop is kept only for call-site compatibility with the other tabs.
type Props = { apiBase: string; token: string; tenantId?: string };
type Gap = { metric_type: string; missing_dates: string[] };
type Connector = { source_type: string; lookback_days: number };

/** Contiguous runs of missing days, so "12 Tage" becomes a usable backfill range. */
function toRanges(dates: string[]): { start: string; end: string; days: number }[] {
  const sorted = [...dates].sort();
  const ranges: { start: string; end: string; days: number }[] = [];

  for (const day of sorted) {
    const last = ranges[ranges.length - 1];
    if (last) {
      const nextExpected = new Date(`${last.end}T00:00:00Z`);
      nextExpected.setUTCDate(nextExpected.getUTCDate() + 1);
      if (nextExpected.toISOString().slice(0, 10) === day) {
        last.end = day;
        last.days += 1;
        continue;
      }
    }
    ranges.push({ start: day, end: day, days: 1 });
  }
  return ranges.sort((a, b) => b.days - a.days);
}

const gapRecommendation = (missingDays: number) => {
  if (missingDays === 0) return "Datenbasis wirkt vollständig.";
  if (missingDays <= 3) return "Leichte Lücken: Analyse nutzbar, aber Trends prüfen.";
  return "Connector, Token oder Sync-Frequenz prüfen, bevor Empfehlungen abgeleitet werden.";
};

const formatDay = (iso: string) =>
  new Date(`${iso}T00:00:00Z`).toLocaleDateString("de-DE", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });

export default function DataQualityTab({ apiBase, token }: Props) {
  const [gaps, setGaps] = useState<Gap[]>([]);
  const [conflicts, setConflicts] = useState<number>(0);
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [windowDays, setWindowDays] = useState(30);
  const [loading, setLoading] = useState(true);
  const [backfill, setBackfill] = useState<{ sourceType: string } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const end = new Date();
    const start = new Date(end);
    start.setDate(end.getDate() - (windowDays - 1));
    const headers = { Authorization: `Bearer ${token}` };

    try {
      const [gapRes, conflictRes, connectorRes] = await Promise.all([
        fetch(
          `${apiBase}/api/v1/data/quality/gaps?start_date=${start
            .toISOString()
            .slice(0, 10)}&end_date=${end.toISOString().slice(0, 10)}`,
          { headers },
        ),
        fetch(`${apiBase}/api/v1/data/quality/conflicts`, { headers }),
        fetch(`${apiBase}/api/v1/data/sources`, { headers }),
      ]);
      if (gapRes.ok) setGaps((await gapRes.json()).gaps ?? []);
      if (conflictRes.ok)
        setConflicts(((await conflictRes.json()).conflicts ?? []).length);
      if (connectorRes.ok)
        setConnectors((await connectorRes.json()).connectors ?? []);
    } finally {
      setLoading(false);
    }
  }, [apiBase, token, windowDays]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      await Promise.resolve();
      if (!cancelled) await load();
    })();
    return () => {
      cancelled = true;
    };
  }, [load]);

  const missingTotal = gaps.reduce((sum, gap) => sum + gap.missing_dates.length, 0);
  const cards = [
    {
      title: "Datenlücken",
      value: missingTotal,
      icon: CalendarX2,
      detail: `${gaps.length} Metriken im ${windowDays}-Tage-Fenster`,
      help: gapRecommendation(missingTotal),
    },
    {
      title: "Quellenkonflikte",
      value: conflicts,
      icon: AlertTriangle,
      detail: "Abweichungen über 5 %",
      help:
        conflicts === 0
          ? "Keine auffälligen konkurrierenden Quellen."
          : "Einheiten und bevorzugte Primärquelle prüfen.",
    },
  ];

  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-widest text-emerald-700">
            Data Quality Center
          </p>
          <h1 className="text-3xl font-extrabold text-slate-900">Datenqualität</h1>
          <p className="mt-2 text-sm text-slate-500">
            Finde Lücken, Quellenkonflikte und konkrete nächste Schritte für belastbare
            Analysen.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs font-semibold text-slate-500">
            Zeitfenster
            <select
              value={windowDays}
              onChange={(e) => setWindowDays(Number(e.target.value))}
              className="ml-2 rounded-xl border border-slate-200 bg-white px-2.5 py-1.5 text-xs text-slate-800 outline-none"
            >
              <option value={7}>7 Tage</option>
              <option value={30}>30 Tage</option>
              <option value={90}>90 Tage</option>
              <option value={180}>180 Tage</option>
              <option value={365}>365 Tage</option>
            </select>
          </label>
          {loading && <RefreshCw className="h-5 w-5 animate-spin text-emerald-700" />}
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {cards.map(({ title, value, icon: Icon, detail, help }) => (
          <article
            key={title}
            className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm"
          >
            <Icon className="mb-5 h-6 w-6 text-emerald-700" />
            <p className="text-sm font-semibold text-slate-500">{title}</p>
            <p className="text-4xl font-black text-slate-900">{value}</p>
            <p className="mt-2 text-xs text-slate-400">{detail}</p>
            <p className="mt-3 rounded-2xl bg-emerald-50 p-3 text-xs font-semibold text-emerald-800">
              {help}
            </p>
          </article>
        ))}
      </div>

      <article className="rounded-3xl border border-amber-200 bg-amber-50 p-5">
        <div className="flex gap-3">
          <Lightbulb className="h-5 w-5 shrink-0 text-amber-700" />
          <div>
            <h2 className="font-bold text-slate-900">Was bedeuten diese Werte?</h2>
            <p className="mt-1 text-sm text-slate-600">
              Lücken reduzieren die Aussagekraft von Trends und Korrelationen.
              Quellenkonflikte zeigen, dass zwei Integrationen für denselben Zeitraum
              unterschiedliche Werte liefern. Empfehlung: zuerst Datenqualität
              stabilisieren, dann Korrelationen interpretieren.
            </p>
            <a
              href="/docs/features/data-quality/"
              target="_blank"
              rel="noreferrer"
              className="mt-2 inline-flex items-center gap-1.5 text-xs font-semibold text-amber-800 underline"
            >
              <BookOpen className="h-3.5 w-3.5" /> Dokumentation zur Datenqualität
            </a>
          </div>
        </div>
      </article>

      <div className="grid gap-5 lg:grid-cols-2">
        <article className="rounded-3xl border border-slate-200 bg-white p-6">
          <h2 className="mb-1 font-bold text-slate-900">Größte Datenlücken</h2>
          <p className="mb-4 text-xs text-slate-500">
            Zusammenhängende fehlende Tage. Über &bdquo;Nachladen&ldquo; wird der
            Importdialog mit genau diesem Zeitraum vorbelegt.
          </p>

          {gaps.length === 0 ? (
            <p className="text-sm text-slate-400">
              Keine Datenlücken im {windowDays}-Tage-Fenster gefunden.
            </p>
          ) : (
            gaps.slice(0, 6).map((gap) => {
              const ranges = toRanges(gap.missing_dates);
              return (
                <div key={gap.metric_type} className="border-b border-slate-100 py-3">
                  <div className="flex justify-between text-sm">
                    <span className="font-medium text-slate-700">{gap.metric_type}</span>
                    <span className="font-bold text-amber-600">
                      {gap.missing_dates.length} Tage
                    </span>
                  </div>
                  <ul className="mt-1.5 space-y-1">
                    {ranges.slice(0, 3).map((r) => (
                      <li
                        key={`${r.start}-${r.end}`}
                        className="flex items-center justify-between rounded-lg bg-slate-50 px-2.5 py-1.5 text-[11px]"
                      >
                        <span className="font-mono text-slate-600">
                          {r.start === r.end
                            ? formatDay(r.start)
                            : `${formatDay(r.start)} – ${formatDay(r.end)}`}
                        </span>
                        <span className="text-slate-400">
                          {r.days} {r.days === 1 ? "Tag" : "Tage"}
                        </span>
                      </li>
                    ))}
                    {ranges.length > 3 && (
                      <li className="text-[11px] text-slate-400">
                        … und {ranges.length - 3} weitere Bereiche
                      </li>
                    )}
                  </ul>
                  <p className="mt-1.5 text-xs text-slate-500">
                    {gapRecommendation(gap.missing_dates.length)}
                  </p>
                </div>
              );
            })
          )}

          {gaps.length > 0 && connectors.length > 0 && (
            <div className="mt-4 border-t border-slate-100 pt-4">
              <p className="mb-2 text-xs font-semibold text-slate-600">
                Fehlende Daten nachladen
              </p>
              <div className="flex flex-wrap gap-2">
                {connectors.map((c) => (
                  <button
                    key={c.source_type}
                    onClick={() => setBackfill({ sourceType: c.source_type })}
                    className="rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-[11px] font-semibold text-emerald-800 hover:bg-emerald-100"
                  >
                    {c.source_type} nachladen
                  </button>
                ))}
              </div>
              <p className="mt-2 text-[11px] text-slate-400">
                Der Importdialog schlägt den benötigten Zeitraum vor und überspringt
                bereits vorhandene Bereiche.
              </p>
            </div>
          )}
        </article>

        <article className="rounded-3xl border border-slate-200 bg-white p-6">
          <ShieldCheck className="mb-4 h-6 w-6 text-emerald-700" />
          <h2 className="mb-2 font-bold text-slate-900">Quellenkonflikte</h2>
          <p className="text-sm text-slate-500">
            {conflicts === 0
              ? "Keine widersprüchlichen Messwerte gefunden."
              : `${conflicts} Messwerte weichen zwischen Quellen deutlich voneinander ab.`}
          </p>
          <p className="mt-3 text-xs text-slate-500">
            Bei Konflikten sollte die zuverlässigste Quelle pro Metrik priorisiert und die
            Einheit im Importer-Transformer geprüft werden.
          </p>
        </article>
      </div>

      {backfill && (
        <ImportDialog
          key={backfill.sourceType}
          apiBase={apiBase}
          token={token}
          sourceType={backfill.sourceType}
          sourceName={backfill.sourceType}
          isOpen={true}
          onClose={() => setBackfill(null)}
          onQueued={load}
        />
      )}
    </section>
  );
}
