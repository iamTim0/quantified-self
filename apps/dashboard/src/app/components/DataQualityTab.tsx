"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, CalendarX2, RefreshCw, Lightbulb, ShieldCheck } from "lucide-react";

type Props = { apiBase: string; token: string; tenantId: string };
type Gap = { metric_type: string; missing_dates: string[] };

const gapRecommendation = (missingDays: number) => {
  if (missingDays === 0) return "Datenbasis wirkt vollständig.";
  if (missingDays <= 3) return "Leichte Lücken: Analyse nutzbar, aber Trends prüfen.";
  return "Connector, Token oder Sync-Frequenz prüfen, bevor Empfehlungen abgeleitet werden.";
};

export default function DataQualityTab({ apiBase, token, tenantId }: Props) {
  const [gaps, setGaps] = useState<Gap[]>([]);
  const [conflicts, setConflicts] = useState<number>(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const end = new Date();
    const start = new Date(end);
    start.setDate(end.getDate() - 29);
    const headers = { Authorization: `Bearer ${token}`, "X-Tenant-ID": tenantId };
    Promise.all([
      fetch(`${apiBase}/api/v1/data/quality/gaps?start_date=${start.toISOString().slice(0, 10)}&end_date=${end.toISOString().slice(0, 10)}`, { headers }),
      fetch(`${apiBase}/api/v1/data/quality/conflicts`, { headers }),
    ]).then(async ([gapResponse, conflictResponse]) => {
      if (gapResponse.ok) setGaps((await gapResponse.json()).gaps ?? []);
      if (conflictResponse.ok) setConflicts(((await conflictResponse.json()).conflicts ?? []).length);
    }).finally(() => setLoading(false));
  }, [apiBase, tenantId, token]);

  const missingTotal = gaps.reduce((sum, gap) => sum + gap.missing_dates.length, 0);
  const cards = [
    { title: "Datenlücken", value: missingTotal, icon: CalendarX2, detail: `${gaps.length} Metriken im 30-Tage-Fenster`, help: gapRecommendation(missingTotal) },
    { title: "Quellenkonflikte", value: conflicts, icon: AlertTriangle, detail: "Abweichungen über 5 %", help: conflicts === 0 ? "Keine auffälligen konkurrierenden Quellen." : "Einheiten und bevorzugte Primärquelle prüfen." },
  ];

  return <section className="space-y-6">
    <div className="flex items-end justify-between">
      <div><p className="text-xs font-bold uppercase tracking-widest text-emerald-700">Data Quality Center</p><h1 className="text-3xl font-extrabold text-slate-900">Datenqualität</h1><p className="mt-2 text-sm text-slate-500">Finde Lücken, Quellenkonflikte und konkrete nächste Schritte für belastbare Analysen.</p></div>
      {loading && <RefreshCw className="h-5 w-5 animate-spin text-emerald-700" />}
    </div>
    <div className="grid gap-4 md:grid-cols-2">{cards.map(({ title, value, icon: Icon, detail, help }) => <article key={title} className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm"><Icon className="mb-5 h-6 w-6 text-emerald-700"/><p className="text-sm font-semibold text-slate-500">{title}</p><p className="text-4xl font-black text-slate-900">{value}</p><p className="mt-2 text-xs text-slate-400">{detail}</p><p className="mt-3 rounded-2xl bg-emerald-50 p-3 text-xs font-semibold text-emerald-800">{help}</p></article>)}</div>
    <article className="rounded-3xl border border-amber-200 bg-amber-50 p-5"><div className="flex gap-3"><Lightbulb className="h-5 w-5 text-amber-700"/><div><h2 className="font-bold text-slate-900">Was bedeuten diese Werte?</h2><p className="mt-1 text-sm text-slate-600">Lücken reduzieren die Aussagekraft von Trends und Korrelationen. Quellenkonflikte zeigen, dass zwei Integrationen für denselben Zeitraum unterschiedliche Werte liefern. Empfehlung: zuerst Datenqualität stabilisieren, dann Korrelationen interpretieren.</p></div></div></article>
    <div className="grid gap-5 lg:grid-cols-2">
      <article className="rounded-3xl border border-slate-200 bg-white p-6"><h2 className="mb-4 font-bold text-slate-900">Größte Datenlücken</h2>{gaps.length === 0 ? <p className="text-sm text-slate-400">Keine Datenlücken im 30-Tage-Fenster gefunden.</p> : gaps.slice(0, 6).map(gap => <div key={gap.metric_type} className="border-b border-slate-100 py-3 text-sm"><div className="flex justify-between"><span className="font-medium text-slate-700">{gap.metric_type}</span><span className="font-bold text-amber-600">{gap.missing_dates.length} Tage</span></div><p className="mt-1 text-xs text-slate-500">{gapRecommendation(gap.missing_dates.length)}</p></div>)}</article>
      <article className="rounded-3xl border border-slate-200 bg-white p-6"><ShieldCheck className="mb-4 h-6 w-6 text-emerald-700"/><h2 className="mb-2 font-bold text-slate-900">Quellenkonflikte</h2><p className="text-sm text-slate-500">{conflicts === 0 ? "Keine widersprüchlichen Messwerte gefunden." : `${conflicts} Messwerte weichen zwischen Quellen deutlich voneinander ab.`}</p><p className="mt-3 text-xs text-slate-500">Bei Konflikten sollte die zuverlässigste Quelle pro Metrik priorisiert und die Einheit im Importer-Transformer geprüft werden.</p></article>
    </div>
  </section>;
}
