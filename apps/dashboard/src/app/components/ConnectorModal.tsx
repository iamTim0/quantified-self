"use client";

import React, { useState, useEffect } from "react";
import { CheckCircle2, Clock, Calendar, Key, Plug, X, ArrowLeft, Activity, Heart, Flame, MapPin, ShieldCheck } from "lucide-react";

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
    status: "coming_soon",
    supportedMetrics: ["Recovery %", "HRV (ms)", "Ruhepuls", "Daily Strain"],
  },
  {
    id: "apple_health",
    name: "Apple Health",
    category: "Fitness & Vitaldaten",
    description: "Importiert Schritte, HF-Verlauf, Aktivitäts-Energie und VO2 Max direkt vom iPhone / Apple Watch.",
    icon: Heart,
    iconColor: "text-rose-400",
    status: "coming_soon",
    supportedMetrics: ["Schritte", "Herzfrequenz", "Aktivitätskalorien"],
  },
  {
    id: "dawarich",
    name: "Dawarich",
    category: "Location & GPS Tracking",
    description: "Self-hosted Alternative zu Google Location History. Importiert Standorte, Besuchsorte und Bewegungsstrecken.",
    icon: MapPin,
    iconColor: "text-emerald-400",
    status: "coming_soon",
    supportedMetrics: ["Standorte", "Besuchte Orte", "GPS-Tracks"],
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
  const [pollIntervalHours, setPollIntervalHours] = useState(initialPollInterval);
  const [lookbackDays, setLookbackDays] = useState(initialLookbackDays);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

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
      } else if (!finalToken && !isEditing) {
        setError("Bitte gib den API Access Token ein.");
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-md p-4 animate-in fade-in duration-200">
      <div className="w-full max-w-xl bg-neutral-950 border border-neutral-800 rounded-3xl p-6 shadow-2xl space-y-6">
        {/* Header */}
        <div className="flex justify-between items-center pb-4 border-b border-neutral-800">
          <div className="flex items-center gap-3">
            {step === "configure_provider" && !isEditing && (
              <button
                onClick={() => setStep("select_provider")}
                className="p-1.5 rounded-lg bg-neutral-900 border border-neutral-800 text-neutral-400 hover:text-white transition-colors"
                title="Zurück zur Auswahl"
              >
                <ArrowLeft className="w-4 h-4" />
              </button>
            )}
            <div className="flex items-center gap-2 text-white">
              <Plug className="w-5 h-5 text-blue-400" />
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
            className="text-neutral-400 hover:text-white p-1 rounded-lg hover:bg-neutral-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Step 1: Provider Selection Gallery */}
        {step === "select_provider" ? (
          <div className="space-y-4">
            <p className="text-xs text-neutral-400">
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
                        ? "bg-neutral-900/80 border-neutral-800 hover:border-blue-500/50 hover:bg-neutral-900 cursor-pointer shadow-lg hover:shadow-blue-500/10"
                        : "bg-neutral-950/40 border-neutral-900 opacity-60 cursor-not-allowed"
                    }`}
                  >
                    <div className="space-y-1.5">
                      <div className="flex justify-between items-center">
                        <Icon className={`w-5 h-5 ${provider.iconColor}`} />
                        <span
                          className={`text-[10px] px-2 py-0.5 rounded-full font-bold uppercase tracking-wider ${
                            isAvailable
                              ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                              : "bg-neutral-800 text-neutral-400 border border-neutral-700"
                          }`}
                        >
                          {isAvailable ? "Verfügbar" : "Demnächst"}
                        </span>
                      </div>
                      <h3 className="text-sm font-bold text-white">{provider.name}</h3>
                      <p className="text-[11px] text-neutral-400 leading-snug">{provider.description}</p>
                    </div>

                    <div className="flex flex-wrap gap-1 pt-1 border-t border-neutral-800/60">
                      {provider.supportedMetrics.slice(0, 3).map((m) => (
                        <span key={m} className="text-[9px] px-1.5 py-0.5 rounded bg-neutral-800 text-neutral-300 font-mono">
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
              <div className="p-3 rounded-2xl bg-emerald-500/10 border border-emerald-500/20 text-xs text-emerald-300 flex items-start gap-2.5">
                <ShieldCheck className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                <div>
                  <span className="font-bold block">Zugangsdaten sind hinterlegt (Fernet AES-256)</span>
                  <span className="text-[11px] text-emerald-400/80 leading-relaxed block mt-0.5">
                    Du kannst Abfrage-Frequenz und Zeitraum anpassen, ohne das Passwort oder den Bearer Token neu einzugeben.
                  </span>
                </div>
              </div>
            )}

            {selectedProvider?.id === "yazio" && (
              <>
                <div className="flex bg-neutral-900 border border-neutral-800 rounded-xl p-1 mb-3 text-xs">
                  <button
                    type="button"
                    onClick={() => setYazioAuthMode("token")}
                    className={`flex-1 py-1.5 rounded-lg font-medium transition-colors ${
                      yazioAuthMode === "token" ? "bg-purple-600 text-white" : "text-neutral-400 hover:text-white"
                    }`}
                  >
                    Bearer Token {isEditing ? "(optional)" : "direkt eingeben"}
                  </button>
                  <button
                    type="button"
                    onClick={() => setYazioAuthMode("login")}
                    className={`flex-1 py-1.5 rounded-lg font-medium transition-colors ${
                      yazioAuthMode === "login" ? "bg-purple-600 text-white" : "text-neutral-400 hover:text-white"
                    }`}
                  >
                    Yazio Login {isEditing ? "(optional)" : ""}
                  </button>
                </div>

                {yazioAuthMode === "login" ? (
                  <div className="space-y-3">
                    <div>
                      <label className="block text-xs font-semibold uppercase tracking-wider text-gray-400 mb-1">
                        Yazio E-Mail {isEditing && <span className="text-neutral-500 font-normal lowercase">(nur ändern bei neuem Login)</span>}
                      </label>
                      <input
                        type="email"
                        placeholder={isEditing ? "Bestehende Zugangsdaten beibehalten..." : "name@example.com"}
                        value={yazioEmail}
                        onChange={(e) => setYazioEmail(e.target.value)}
                        className="w-full px-4 py-2.5 rounded-xl bg-white/5 border border-white/10 text-white text-sm focus:border-blue-500 outline-none"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-semibold uppercase tracking-wider text-gray-400 mb-1">
                        Yazio Passwort {isEditing && <span className="text-neutral-500 font-normal lowercase">(nur ändern bei neuem Login)</span>}
                      </label>
                      <input
                        type="password"
                        placeholder={isEditing ? "•••••••• (unverändert lassen)" : "••••••••"}
                        value={yazioPassword}
                        onChange={(e) => setYazioPassword(e.target.value)}
                        className="w-full px-4 py-2.5 rounded-xl bg-white/5 border border-white/10 text-white text-sm focus:border-blue-500 outline-none"
                      />
                    </div>
                  </div>
                ) : (
                  <div>
                    <label className="block text-xs font-semibold uppercase tracking-wider text-gray-400 mb-1.5 flex items-center gap-1.5">
                      <Key className="w-3.5 h-3.5 text-purple-400" />
                      <span>Yazio Bearer Access Token</span>
                      {isEditing && <span className="text-neutral-500 font-normal text-[11px] lowercase">(optional)</span>}
                    </label>
                    <input
                      type="password"
                      placeholder={isEditing ? "•••••••• (Zugangsdaten beibehalten)" : "Füge deinen Yazio Bearer Token hier ein"}
                      value={accessToken}
                      onChange={(e) => setAccessToken(e.target.value)}
                      className="w-full px-4 py-2.5 rounded-xl bg-white/5 border border-white/10 text-white text-sm focus:border-blue-500 outline-none font-mono"
                    />
                  </div>
                )}
              </>
            )}

            {/* Sync Frequency & Period Configuration */}
            <div className="pt-3 border-t border-neutral-800 space-y-3">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-blue-400 flex items-center gap-1.5">
                <Clock className="w-3.5 h-3.5" /> Abfrage-Intervall & Zeitraum bearbeiten
              </h3>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[11px] text-neutral-400 mb-1 flex items-center gap-1">
                    <Clock className="w-3 h-3 text-purple-400" /> Sync-Frequenz
                  </label>
                  <select
                    value={pollIntervalHours}
                    onChange={(e) => setPollIntervalHours(Number(e.target.value))}
                    className="w-full px-3 py-2 rounded-xl bg-white/5 border border-white/10 text-white text-xs focus:border-blue-500 outline-none font-semibold"
                  >
                    <option value={1} className="bg-neutral-900">Jede Stunde (1 Std)</option>
                    <option value={3} className="bg-neutral-900">Alle 3 Stunden</option>
                    <option value={6} className="bg-neutral-900">Alle 6 Stunden (Standard)</option>
                    <option value={12} className="bg-neutral-900">Alle 12 Stunden</option>
                    <option value={24} className="bg-neutral-900">Täglich (24 Std)</option>
                    <option value={168} className="bg-neutral-900">Wöchentlich (168 Std)</option>
                  </select>
                </div>

                <div>
                  <label className="block text-[11px] text-neutral-400 mb-1 flex items-center gap-1">
                    <Calendar className="w-3 h-3 text-emerald-400" /> Import-Zeitraum
                  </label>
                  <select
                    value={lookbackDays}
                    onChange={(e) => setLookbackDays(Number(e.target.value))}
                    className="w-full px-3 py-2 rounded-xl bg-white/5 border border-white/10 text-white text-xs focus:border-blue-500 outline-none font-semibold"
                  >
                    <option value={7} className="bg-neutral-900">Letzte 7 Tage</option>
                    <option value={14} className="bg-neutral-900">Letzte 14 Tage</option>
                    <option value={30} className="bg-neutral-900">Letzte 30 Tage (Standard)</option>
                    <option value={60} className="bg-neutral-900">Letzte 60 Tage</option>
                    <option value={90} className="bg-neutral-900">Letzte 90 Tage</option>
                  </select>
                </div>
              </div>
            </div>

            {error && <p role="alert" className="rounded-xl bg-red-500/10 px-3 py-2 text-sm text-red-300">{error}</p>}
            {message && <p className="rounded-xl bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300 flex items-center gap-2"><CheckCircle2 className="w-4 h-4" />{message}</p>}

            <div className="flex justify-between items-center pt-4">
              {!isEditing ? (
                <button
                  type="button"
                  onClick={() => setStep("select_provider")}
                  className="px-4 py-2 text-xs font-semibold rounded-xl bg-white/5 border border-white/10 hover:bg-white/10 text-gray-300 transition-colors flex items-center gap-1.5"
                >
                  <ArrowLeft className="w-3.5 h-3.5" /> Zurück
                </button>
              ) : (
                <button
                  type="button"
                  onClick={onClose}
                  className="px-4 py-2 text-xs font-semibold rounded-xl bg-white/5 border border-white/10 hover:bg-white/10 text-gray-300 transition-colors"
                >
                  Abbrechen
                </button>
              )}
              <button
                type="submit"
                disabled={loading}
                className="px-5 py-2 text-xs font-semibold rounded-xl bg-blue-600 hover:bg-blue-500 text-white transition-colors disabled:opacity-50 shadow-lg shadow-blue-600/20"
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
