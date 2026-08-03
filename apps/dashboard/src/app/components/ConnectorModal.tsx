"use client";

import React, { useState, useEffect } from "react";
import { CheckCircle2, Clock, Calendar, Key, Plug, X, ArrowLeft, Activity, Heart, Flame, MapPin, ShieldCheck, Dumbbell } from "lucide-react";

export interface ProviderCatalogItem {
  id: string;
  name: string;
  category: string;
  description: string;
  icon: React.ElementType;
  iconColor: string;
  status: "available" | "coming_soon";
  supportedMetrics: string[];
}

export const PROVIDER_CATALOG: ProviderCatalogItem[] = [
  {
    id: "yazio",
    name: "Yazio Nutrition v15",
    category: "Ernährung & Tagebuch",
    description: "Importiert Mahlzeiten, Lebensmittelnamen, Kalorien, Protein, Kohlenhydrate und Fett aus deinem Yazio-Tagebuch.",
    icon: Flame,
    iconColor: "text-amber-400",
    status: "available",
    supportedMetrics: ["Kalorien", "Protein", "Kohlenhydrate", "Fett", "Gegessene Produkte"],
  },
  {
    id: "whoop",
    name: "Whoop",
    category: "Regeneration & Schlaf",
    description: "Synchronisiert Recovery Score, HRV, Tiefschlaf-Phasen, Ruhepuls und Daily Strain.",
    icon: Activity,
    iconColor: "text-red-400",
    status: "available",
    supportedMetrics: ["Recovery %", "HRV (ms)", "Ruhepuls", "Daily Strain"],
  },
  {
    id: "apple_health",
    name: "Apple Health",
    category: "Fitness & Vitaldaten",
    description: "Importiert Schritte, HF-Verlauf, Aktivitäts-Energie, Schlafphasen & Workouts via Health Auto Export.",
    icon: Heart,
    iconColor: "text-rose-400",
    status: "available",
    supportedMetrics: ["Schritte", "Herzfrequenz", "Aktivitätskalorien", "Schlaf-Phasen", "Workouts"],
  },
  {
    id: "streak",
    name: "Streak - Gym Log",
    category: "Krafttraining & Gym Log",
    description: "Empfängt automatische REST Exports deiner Workouts, Sätze, Reps und Gewichte von der Streak 2.0 App.",
    icon: Dumbbell,
    iconColor: "text-[#0d5c3a]",
    status: "available",
    supportedMetrics: ["Übungssätze", "Gewicht (kg)", "Wiederholungen", "Max Puls", "Set Volumen"],
  },
  {
    id: "dawarich",
    name: "Dawarich Location",
    category: "Location & GPS Tracking",
    description: "Self-hosted Alternative zu Google Location History. Importiert Standorte, GPS-Punkte und Bewegungsstrecken.",
    icon: MapPin,
    iconColor: "text-emerald-500",
    status: "available",
    supportedMetrics: ["Standortpunkte", "Breitengrad", "Längengrad"],
  },
];

interface ConnectorModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSaved: () => void;
  tenantId: string;
  token: string;
  apiBase?: string;
  initialSourceType?: string;
  initialPollInterval?: number;
  initialLookbackDays?: number;
  isEditing?: boolean;
}

export default function ConnectorModal({
  isOpen,
  onClose,
  onSaved,
  tenantId,
  token,
  apiBase = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000",
  initialSourceType,
  initialPollInterval = 6,
  initialLookbackDays = 30,
  isEditing = false,
}: ConnectorModalProps) {
  const [step, setStep] = useState<"select_provider" | "configure_provider">("select_provider");
  const [selectedProvider, setSelectedProvider] = useState<ProviderCatalogItem | null>(null);

  const [accessToken, setAccessToken] = useState("");
  const [yazioAuthMode, setYazioAuthMode] = useState<"token" | "login">("token");
  const [yazioEmail, setYazioEmail] = useState("");
  const [yazioPassword, setYazioPassword] = useState("");
  const [dawarichUrl, setDawarichUrl] = useState("http://localhost:3000");
  const [dawarichApiKey, setDawarichApiKey] = useState("");

  const [pollIntervalHours, setPollIntervalHours] = useState(initialPollInterval);
  const [lookbackDays, setLookbackDays] = useState(initialLookbackDays);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const generateRandomApiKey = () => {
    const chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
    let key = "qs_sec_";
    for (let i = 0; i < 32; i++) {
      key += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    setAccessToken(key);
  };

  useEffect(() => {
    if (isOpen) {
      setPollIntervalHours(initialPollInterval);
      setLookbackDays(initialLookbackDays);
      if (initialSourceType) {
        const item = PROVIDER_CATALOG.find((p) => p.id === initialSourceType);
        if (item) {
          setSelectedProvider(item);
          setStep("configure_provider");
        } else {
          setStep("select_provider");
        }
      } else {
        setStep("select_provider");
        setSelectedProvider(null);
      }
      setAccessToken("");
      setYazioEmail("");
      setYazioPassword("");
      setDawarichUrl("http://localhost:3000");
      setDawarichApiKey("");
      setMessage(null);
      setError(null);
    }
  }, [isOpen, initialSourceType, initialPollInterval, initialLookbackDays]);

  if (!isOpen) return null;

  const handleSelectProvider = (provider: ProviderCatalogItem) => {
    if (provider.status === "coming_soon") return;
    setSelectedProvider(provider);
    setStep("configure_provider");
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedProvider) return;

    setMessage(null);
    setError(null);

    setLoading(true);
    try {
      let finalToken = accessToken.trim();
      let payloadConfig: Record<string, any> | undefined = undefined;

      if (selectedProvider.id === "yazio") {
        if (yazioAuthMode === "login") {
          if (yazioEmail.trim() || yazioPassword.trim()) {
            if (!yazioEmail.trim() || !yazioPassword.trim()) {
              setError("Bitte gib sowohl E-Mail als auch Passwort ein.");
              setLoading(false);
              return;
            }
            finalToken = "SERVER_OAUTH_LOGIN";
            payloadConfig = {
              yazio_email: yazioEmail.trim(),
              yazio_password: yazioPassword.trim(),
            };
          }
        } else if (!finalToken && !isEditing) {
          setError("Bitte gib einen Yazio Bearer Access Token ein.");
          setLoading(false);
          return;
        }
      } else if (selectedProvider.id === "dawarich") {
        finalToken = dawarichApiKey.trim();
        payloadConfig = {
          base_url: dawarichUrl.trim() || "http://localhost:3000",
        };
        if (!finalToken && !isEditing) {
          setError("Bitte gib den Dawarich API Key ein.");
          setLoading(false);
          return;
        }
      } else if (!finalToken && !isEditing) {
        setError(`Bitte gib einen gültigen API Key für ${selectedProvider.name} ein oder generiere einen.`);
        setLoading(false);
        return;
      }

      const res = await fetch(`${apiBase}/api/v1/data/sources/configure`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Tenant-ID": tenantId,
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          source_type: selectedProvider.id,
          access_token: finalToken || undefined,
          status: "active",
          poll_interval_hours: Number(pollIntervalHours),
          lookback_days: Number(lookbackDays),
          config: payloadConfig,
        }),
      });

      if (res.ok) {
        setMessage(`${selectedProvider.name} Einstellungen erfolgreich gespeichert!`);
        setAccessToken("");
        setYazioEmail("");
        setYazioPassword("");
        onSaved();
        setTimeout(() => {
          onClose();
        }, 1200);
      } else {
        const data = await res.json().catch(() => null);
        setError(data?.detail || "Konfiguration konnte nicht gespeichert werden.");
      }
    } catch (err: any) {
      setError(`Netzwerkfehler: ${err?.message || "Server nicht erreichbar"}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-md p-4 animate-in fade-in duration-200">
      <div className="w-full max-w-xl bg-white border border-slate-200/90 rounded-3xl p-6 shadow-2xl space-y-6">
        {/* Header */}
        <div className="flex justify-between items-center pb-4 border-b border-slate-100">
          <div className="flex items-center gap-3">
            {step === "configure_provider" && !isEditing && (
              <button
                onClick={() => setStep("select_provider")}
                className="p-2 rounded-xl bg-slate-100 border border-slate-200 text-slate-600 hover:text-slate-900 transition-colors"
                title="Zurück zur Auswahl"
              >
                <ArrowLeft className="w-4 h-4" />
              </button>
            )}
            <div className="flex items-center gap-2 text-slate-900">
              <Plug className="w-5 h-5 text-[#0d5c3a]" />
              <h2 className="text-lg font-bold">
                {step === "select_provider"
                  ? "Datenquelle auswählen"
                  : isEditing
                  ? `${selectedProvider?.name} bearbeiten`
                  : `${selectedProvider?.name} verbinden`}
              </h2>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-900 p-1.5 rounded-xl hover:bg-slate-100 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Step 1: Provider Selection Gallery */}
        {step === "select_provider" ? (
          <div className="space-y-4">
            <p className="text-xs text-slate-500">
              Wähle einen Connector aus dem Katalog, um dein Konto zu verknüpfen und automatisches Syncing einzurichten:
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 max-h-[60vh] overflow-y-auto pr-1">
              {PROVIDER_CATALOG.map((provider) => {
                const Icon = provider.icon;
                const isAvailable = provider.status === "available";
                return (
                  <button
                    key={provider.id}
                    onClick={() => handleSelectProvider(provider)}
                    disabled={!isAvailable}
                    className={`text-left p-4 rounded-2xl border transition-all flex flex-col justify-between space-y-3 ${
                      isAvailable
                        ? "bg-slate-50 border-slate-200 hover:border-[#0d5c3a] hover:bg-emerald-50/50 cursor-pointer shadow-xs"
                        : "bg-slate-100/50 border-slate-200 opacity-60 cursor-not-allowed"
                    }`}
                  >
                    <div className="space-y-1.5">
                      <div className="flex justify-between items-center">
                        <Icon className={`w-5 h-5 ${provider.iconColor}`} />
                        <span
                          className={`text-[10px] px-2.5 py-0.5 rounded-full font-bold uppercase tracking-wider ${
                            isAvailable
                              ? "bg-emerald-50 text-emerald-800 border border-emerald-200"
                              : "bg-slate-200 text-slate-500 border border-slate-300"
                          }`}
                        >
                          {isAvailable ? "Verfügbar" : "Demnächst"}
                        </span>
                      </div>
                      <h3 className="text-sm font-bold text-slate-900">{provider.name}</h3>
                      <p className="text-[11px] text-slate-500 leading-snug">{provider.description}</p>
                    </div>

                    <div className="flex flex-wrap gap-1 pt-1 border-t border-slate-200">
                      {provider.supportedMetrics.slice(0, 3).map((m) => (
                        <span key={m} className="text-[9px] px-1.5 py-0.5 rounded bg-white text-slate-600 border border-slate-200 font-mono">
                          {m}
                        </span>
                      ))}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        ) : (
          /* Step 2: Configuration Form for Selected Provider */
          <form onSubmit={handleSubmit} className="space-y-4">
            {isEditing && (
              <div className="p-3.5 rounded-2xl bg-emerald-50 border border-emerald-200 text-xs text-emerald-900 flex items-start gap-2.5">
                <ShieldCheck className="w-4 h-4 text-emerald-600 shrink-0 mt-0.5" />
                <div>
                  <span className="font-bold block">Zugangsdaten sind hinterlegt (Fernet AES-256)</span>
                  <span className="text-[11px] text-emerald-700 leading-relaxed block mt-0.5">
                    Du kannst Abfrage-Frequenz und Zeitraum anpassen, ohne das Passwort neu einzugeben.
                  </span>
                </div>
              </div>
            )}

            {selectedProvider?.id === "yazio" && (
              <>
                <div className="flex bg-slate-100 border border-slate-200 rounded-2xl p-1 mb-3 text-xs">
                  <button
                    type="button"
                    onClick={() => setYazioAuthMode("token")}
                    className={`flex-1 py-2 rounded-xl font-bold transition-all ${
                      yazioAuthMode === "token" ? "bg-[#0d5c3a] text-white shadow-sm" : "text-slate-600 hover:text-slate-900"
                    }`}
                  >
                    Bearer Token {isEditing ? "(optional)" : "direkt eingeben"}
                  </button>
                  <button
                    type="button"
                    onClick={() => setYazioAuthMode("login")}
                    className={`flex-1 py-2 rounded-xl font-bold transition-all ${
                      yazioAuthMode === "login" ? "bg-[#0d5c3a] text-white shadow-sm" : "text-slate-600 hover:text-slate-900"
                    }`}
                  >
                    Yazio Login {isEditing ? "(optional)" : ""}
                  </button>
                </div>

                {yazioAuthMode === "login" ? (
                  <div className="space-y-3">
                    <div>
                      <label className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-1">
                        Yazio E-Mail {isEditing && <span className="text-slate-400 font-normal lowercase">(optional)</span>}
                      </label>
                      <input
                        type="email"
                        placeholder={isEditing ? "Bestehende Zugangsdaten beibehalten..." : "name@example.com"}
                        value={yazioEmail}
                        onChange={(e) => setYazioEmail(e.target.value)}
                        className="w-full px-4 py-2.5 rounded-2xl bg-white border border-slate-200 text-slate-900 text-sm focus:border-[#0d5c3a] focus:ring-2 focus:ring-[#0d5c3a]/20 outline-none"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-1">
                        Yazio Passwort {isEditing && <span className="text-slate-400 font-normal lowercase">(optional)</span>}
                      </label>
                      <input
                        type="password"
                        placeholder={isEditing ? "•••••••• (unverändert lassen)" : "••••••••"}
                        value={yazioPassword}
                        onChange={(e) => setYazioPassword(e.target.value)}
                        className="w-full px-4 py-2.5 rounded-2xl bg-white border border-slate-200 text-slate-900 text-sm focus:border-[#0d5c3a] focus:ring-2 focus:ring-[#0d5c3a]/20 outline-none"
                      />
                    </div>
                  </div>
                ) : (
                  <div>
                    <label className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-1.5 flex items-center gap-1.5">
                      <Key className="w-3.5 h-3.5 text-[#0d5c3a]" />
                      <span>Yazio Bearer Access Token</span>
                      {isEditing && <span className="text-slate-400 font-normal text-[11px] lowercase">(optional)</span>}
                    </label>
                    <input
                      type="password"
                      placeholder={isEditing ? "•••••••• (Zugangsdaten beibehalten)" : "Füge deinen Yazio Bearer Token hier ein"}
                      value={accessToken}
                      onChange={(e) => setAccessToken(e.target.value)}
                      className="w-full px-4 py-2.5 rounded-2xl bg-white border border-slate-200 text-slate-900 text-sm focus:border-[#0d5c3a] focus:ring-2 focus:ring-[#0d5c3a]/20 outline-none font-mono"
                    />
                  </div>
                )}
              </>
            )}

            {selectedProvider?.id === "dawarich" && (
              <div className="space-y-3">
                <div>
                  <label className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-1">
                    Dawarich Server URL (Base URL)
                  </label>
                  <input
                    type="url"
                    placeholder="https://dawarich.example.com"
                    value={dawarichUrl}
                    onChange={(e) => setDawarichUrl(e.target.value)}
                    required
                    className="w-full px-4 py-2.5 rounded-2xl bg-white border border-slate-200 text-slate-900 text-sm focus:border-[#0d5c3a] focus:ring-2 focus:ring-[#0d5c3a]/20 outline-none"
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-1.5 flex items-center gap-1.5">
                    <Key className="w-3.5 h-3.5 text-[#0d5c3a]" />
                    <span>Dawarich API Key</span>
                    {isEditing && <span className="text-slate-400 font-normal text-[11px] lowercase">(optional)</span>}
                  </label>
                  <input
                    type="password"
                    placeholder={isEditing ? "•••••••• (API Key beibehalten)" : "Füge deinen Dawarich API Key hier ein"}
                    value={dawarichApiKey}
                    onChange={(e) => setDawarichApiKey(e.target.value)}
                    required={!isEditing}
                    className="w-full px-4 py-2.5 rounded-2xl bg-white border border-slate-200 text-slate-900 text-sm focus:border-[#0d5c3a] focus:ring-2 focus:ring-[#0d5c3a]/20 outline-none font-mono"
                  />
                </div>
              </div>
            )}

            {selectedProvider?.id === "apple_health" && (
              <div className="space-y-3">
                <div className="p-4 bg-emerald-50/80 border border-emerald-200/80 rounded-2xl space-y-2">
                  <div className="text-xs font-bold text-slate-900 flex items-center gap-1.5">
                    <Plug className="w-4 h-4 text-[#0d5c3a]" />
                    <span>Health Auto Export Webhook Endpoint</span>
                  </div>
                  <p className="text-xs text-slate-600">
                    Trage in der <strong>Health Auto Export App</strong> (iOS/macOS) folgenden Webhook URL ein:
                  </p>
                  <div className="p-2.5 bg-white border border-slate-200 rounded-xl font-mono text-[11px] text-[#0d5c3a] font-bold select-all break-all shadow-sm">
                    {apiBase}/api/v1/ingest/apple-health
                  </div>
                </div>
                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <label className="text-xs font-bold uppercase tracking-wider text-slate-500 flex items-center gap-1.5">
                      <Key className="w-3.5 h-3.5 text-[#0d5c3a]" />
                      <span>Erforderlicher Webhook API Key (X-Api-Key)</span>
                    </label>
                    <button
                      type="button"
                      onClick={generateRandomApiKey}
                      className="text-[11px] font-semibold text-[#0d5c3a] hover:underline"
                    >
                      🔐 Key Generieren
                    </button>
                  </div>
                  <input
                    type="text"
                    placeholder="Generiere oder gib einen API Token zur Webhook-Absicherung ein"
                    value={accessToken}
                    onChange={(e) => setAccessToken(e.target.value)}
                    required={!isEditing}
                    className="w-full px-4 py-2.5 rounded-2xl bg-white border border-slate-200 text-slate-900 text-sm focus:border-[#0d5c3a] focus:ring-2 focus:ring-[#0d5c3a]/20 outline-none font-mono"
                  />
                  <p className="text-[11px] text-slate-500 mt-1">
                    Trage diesen API Key in der Health Auto Export App unter Header <code>X-Api-Key</code> ein.
                  </p>
                </div>
              </div>
            )}

            {selectedProvider?.id === "streak" && (
              <div className="space-y-3">
                <div className="p-4 bg-emerald-50/80 border border-emerald-200/80 rounded-2xl space-y-2">
                  <div className="text-xs font-bold text-slate-900 flex items-center gap-1.5">
                    <Plug className="w-4 h-4 text-[#0d5c3a]" />
                    <span>Streak - Gym Log REST Export Endpoint</span>
                  </div>
                  <p className="text-xs text-slate-600">
                    Trage in der <strong>Streak 2.0 App</strong> (REST Export Kachel) diesen Endpoint URL ein:
                  </p>
                  <div className="p-2.5 bg-white border border-slate-200 rounded-xl font-mono text-[11px] text-[#0d5c3a] font-bold select-all break-all shadow-sm">
                    {apiBase}/api/v1/ingest/streak
                  </div>
                </div>
                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <label className="text-xs font-bold uppercase tracking-wider text-slate-500 flex items-center gap-1.5">
                      <Key className="w-3.5 h-3.5 text-[#0d5c3a]" />
                      <span>Erforderlicher API Key (X-Api-Key)</span>
                    </label>
                    <button
                      type="button"
                      onClick={generateRandomApiKey}
                      className="text-[11px] font-semibold text-[#0d5c3a] hover:underline"
                    >
                      🔐 Key Generieren
                    </button>
                  </div>
                  <input
                    type="text"
                    placeholder="Generiere oder gib einen API Token für Streak REST Export ein"
                    value={accessToken}
                    onChange={(e) => setAccessToken(e.target.value)}
                    required={!isEditing}
                    className="w-full px-4 py-2.5 rounded-2xl bg-white border border-slate-200 text-slate-900 text-sm focus:border-[#0d5c3a] focus:ring-2 focus:ring-[#0d5c3a]/20 outline-none font-mono"
                  />
                  <p className="text-[11px] text-slate-500 mt-1">
                    Trage diesen API Key in Streak 2.0 unter Header <code>X-Api-Key</code> ein.
                  </p>
                </div>
              </div>
            )}

            {/* Sync Frequency & Period Configuration */}
            <div className="pt-3 border-t border-slate-100 space-y-3">
              <h3 className="text-xs font-bold uppercase tracking-wider text-[#0d5c3a] flex items-center gap-1.5">
                <Clock className="w-3.5 h-3.5" /> Abfrage-Intervall & Zeitraum bearbeiten
              </h3>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[11px] text-slate-500 font-bold mb-1 flex items-center gap-1">
                    <Clock className="w-3 h-3 text-[#0d5c3a]" /> Sync-Frequenz
                  </label>
                  <select
                    value={pollIntervalHours}
                    onChange={(e) => setPollIntervalHours(Number(e.target.value))}
                    className="w-full px-3 py-2 rounded-2xl bg-white border border-slate-200 text-slate-900 text-xs focus:border-[#0d5c3a] outline-none font-bold"
                  >
                    <option value={1} className="bg-white text-slate-900">Jede Stunde (1 Std)</option>
                    <option value={3} className="bg-white text-slate-900">Alle 3 Stunden</option>
                    <option value={6} className="bg-white text-slate-900">Alle 6 Stunden (Standard)</option>
                    <option value={12} className="bg-white text-slate-900">Alle 12 Stunden</option>
                    <option value={24} className="bg-white text-slate-900">Täglich (24 Std)</option>
                    <option value={168} className="bg-white text-slate-900">Wöchentlich (168 Std)</option>
                  </select>
                </div>

                <div>
                  <label className="block text-[11px] text-slate-500 font-bold mb-1 flex items-center gap-1">
                    <Calendar className="w-3 h-3 text-emerald-600" /> Import-Zeitraum
                  </label>
                  <select
                    value={lookbackDays}
                    onChange={(e) => setLookbackDays(Number(e.target.value))}
                    className="w-full px-3 py-2 rounded-2xl bg-white border border-slate-200 text-slate-900 text-xs focus:border-[#0d5c3a] outline-none font-bold"
                  >
                    <option value={7} className="bg-white text-slate-900">Letzte 7 Tage</option>
                    <option value={14} className="bg-white text-slate-900">Letzte 14 Tage</option>
                    <option value={30} className="bg-white text-slate-900">Letzte 30 Tage (Standard)</option>
                    <option value={60} className="bg-white text-slate-900">Letzte 60 Tage</option>
                    <option value={90} className="bg-white text-slate-900">Letzte 90 Tage</option>
                  </select>
                </div>
              </div>
            </div>

            {error && <p role="alert" className="rounded-2xl bg-rose-50 border border-rose-200 px-3 py-2 text-xs font-semibold text-rose-700">{error}</p>}
            {message && <p className="rounded-2xl bg-emerald-50 border border-emerald-200 px-3 py-2 text-xs font-semibold text-emerald-800 flex items-center gap-2"><CheckCircle2 className="w-4 h-4 text-emerald-600" />{message}</p>}

            <div className="flex justify-between items-center pt-4 border-t border-slate-100">
              {!isEditing ? (
                <button
                  type="button"
                  onClick={() => setStep("select_provider")}
                  className="px-4 py-2 text-xs font-bold rounded-2xl bg-slate-100 border border-slate-200 hover:bg-slate-200 text-slate-700 transition-colors flex items-center gap-1.5"
                >
                  <ArrowLeft className="w-3.5 h-3.5" /> Zurück
                </button>
              ) : (
                <button
                  type="button"
                  onClick={onClose}
                  className="px-4 py-2 text-xs font-bold rounded-2xl bg-slate-100 border border-slate-200 hover:bg-slate-200 text-slate-700 transition-colors"
                >
                  Abbrechen
                </button>
              )}
              <button
                type="submit"
                disabled={loading}
                className="px-5 py-2.5 text-xs font-bold rounded-2xl bg-[#0d5c3a] hover:bg-[#08432a] text-white transition-all disabled:opacity-50 shadow-md shadow-[#0d5c3a]/20"
              >
                {loading ? "Speichere..." : isEditing ? "Einstellungen Speichern" : "Verbindung Speichern"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
