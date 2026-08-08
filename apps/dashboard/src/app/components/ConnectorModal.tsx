"use client";

import React, { useState, useEffect } from "react";
import { CheckCircle2, Clock, Calendar, Key, Plug, X, ArrowLeft, Activity, Heart, Flame, MapPin, ShieldCheck, Dumbbell, Download, Upload, CloudSun, HousePlug, BookOpen } from "lucide-react";
import ApiKeyManager from "./ApiKeyManager";
import { apiFetch } from "../lib/api";
import { useT, type MessageKey } from "../lib/i18n/provider";

export type ConnectorDirection = "active" | "passive";

export interface ProviderCatalogItem {
  id: string;
  name: string;
  categoryKey: MessageKey;
  descriptionKey: MessageKey;
  icon: React.ElementType;
  iconColor: string;
  status: "available" | "coming_soon";
  supportedMetrics: string[];
  direction: ConnectorDirection;
}

export const PROVIDER_CATALOG: ProviderCatalogItem[] = [
  {
    id: "yazio",
    name: "Yazio Nutrition v15",
    categoryKey: "modal.catNutrition",
    descriptionKey: "modal.desc.yazio",
    icon: Flame,
    iconColor: "text-amber-400",
    status: "available",
    supportedMetrics: ["Kalorien", "Protein", "Kohlenhydrate", "Fett", "Gegessene Produkte"],
    direction: "active",
  },
  {
    id: "whoop",
    name: "Whoop",
    categoryKey: "modal.catRecovery",
    descriptionKey: "modal.desc.whoop",
    icon: Activity,
    iconColor: "text-red-400",
    status: "available",
    supportedMetrics: ["Recovery %", "HRV (ms)", "Ruhepuls", "Daily Strain"],
    direction: "active",
  },
  {
    id: "apple_health",
    name: "Apple Health",
    categoryKey: "modal.catVitals",
    descriptionKey: "modal.desc.apple_health",
    icon: Heart,
    iconColor: "text-rose-400",
    status: "available",
    supportedMetrics: ["Steps", "Heart rate", "Active energy", "Sleep stages", "Workouts"],
    direction: "passive",
  },
  {
    id: "streak",
    name: "Streak - Gym Log",
    categoryKey: "modal.catStrength",
    descriptionKey: "modal.desc.streak",
    icon: Dumbbell,
    iconColor: "text-[#0d5c3a]",
    status: "available",
    supportedMetrics: ["Exercise sets", "Weight (kg)", "Reps", "Max heart rate", "Set volume"],
    direction: "passive",
  },
  {
    id: "dawarich",
    name: "Dawarich Location",
    categoryKey: "modal.catLocation",
    descriptionKey: "modal.desc.dawarich",
    icon: MapPin,
    iconColor: "text-emerald-500",
    status: "available",
    supportedMetrics: ["Location points", "Latitude", "Longitude"],
    direction: "active",
  },
  {
    id: "home_assistant", name: "Home Assistant", categoryKey: "modal.catSmartHome",
    descriptionKey: "modal.desc.home_assistant",
    icon: HousePlug, iconColor: "text-sky-500", status: "available",
    supportedMetrics: ["Temperature", "Humidity", "Light", "Noise"], direction: "active",
  },
  {
    id: "weather", name: "Weather", categoryKey: "modal.catEnvironment",
    descriptionKey: "modal.desc.weather",
    icon: CloudSun, iconColor: "text-amber-500", status: "available",
    supportedMetrics: ["Temperatur", "Luftdruck", "Niederschlag", "UV-Index"], direction: "active",
  },
  {
    id: "calendar", name: "Calendar", categoryKey: "modal.catRoutine",
    descriptionKey: "modal.desc.calendar",
    icon: Calendar, iconColor: "text-violet-500", status: "available",
    supportedMetrics: ["Termine", "Meetingdauer", "Busy Hours"], direction: "active",
  },
];

export const getConnectorDirection = (sourceType: string): ConnectorDirection =>
  PROVIDER_CATALOG.find((provider) => provider.id === sourceType)?.direction ?? "active";

interface ConnectorModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSaved: () => void;
  tenantId: string;
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
  apiBase = process.env.NEXT_PUBLIC_API_URL || (typeof window !== "undefined" ? window.location.origin : "http://127.0.0.1:8000"),
  initialSourceType,
  initialPollInterval = 6,
  initialLookbackDays = 30,
  isEditing = false,
}: ConnectorModalProps) {
  const t = useT();
  const [step, setStep] = useState<"select_provider" | "configure_provider">("select_provider");
  const [selectedProvider, setSelectedProvider] = useState<ProviderCatalogItem | null>(null);

  const [accessToken, setAccessToken] = useState("");
  const [yazioAuthMode, setYazioAuthMode] = useState<"token" | "login">("token");
  const [yazioEmail, setYazioEmail] = useState("");
  const [yazioPassword, setYazioPassword] = useState("");
  const [dawarichUrl, setDawarichUrl] = useState("http://localhost:3000");
  const [dawarichApiKey, setDawarichApiKey] = useState("");
  const [providerBaseUrl, setProviderBaseUrl] = useState("");

  const [pollIntervalHours, setPollIntervalHours] = useState(initialPollInterval);
  const [lookbackDays, setLookbackDays] = useState(initialLookbackDays);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // The client-side key generator is gone: inbound keys are now minted by Core
  // (cryptographically random, stored only as a hash) and managed in ApiKeyManager.
  // Math.random() was never a suitable source for a credential anyway.

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
              setError(t("modal.needEmailPassword"));
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
          setError(t("modal.needYazioToken"));
          setLoading(false);
          return;
        }
      } else if (selectedProvider.id === "dawarich") {
        finalToken = dawarichApiKey.trim();
        payloadConfig = {
          base_url: dawarichUrl.trim() || "http://localhost:3000",
        };
        if (!finalToken && !isEditing) {
          setError(t("modal.needDawarichKey"));
          setLoading(false);
          return;
        }
      } else if (selectedProvider.id === "calendar") {
        const url = providerBaseUrl.trim();
        if (!url) {
          setError(t("modal.needCalendarUrl"));
          setLoading(false);
          return;
        }
        if (!/^https?:\/\//i.test(url)) {
          setError(t("modal.calendarUrlScheme"));
          setLoading(false);
          return;
        }
        // A public or tokenised .ics URL is complete on its own. Demanding an API
        // key for an Outlook/Office feed was the reported bug, so only ask for one
        // when the URL clearly is not a calendar feed.
        const isIcsUrl = url.split("?")[0].toLowerCase().endsWith(".ics");
        payloadConfig = { ics_url: url, base_url: url };
        if (!isIcsUrl && !finalToken && !isEditing) {
          setError(
            t("modal.calendarUrlSuspect"),
          );
          setLoading(false);
          return;
        }
      } else if (["home_assistant", "weather"].includes(selectedProvider.id)) {
        if (!providerBaseUrl.trim()) {
          setError(t("modal.needBaseUrl"));
          setLoading(false);
          return;
        }
        payloadConfig = { base_url: providerBaseUrl.trim() };
        if (!finalToken && !isEditing) {
          setError(t("modal.needApiKey", { provider: selectedProvider.name }));
          setLoading(false);
          return;
        }
      } else if (isPassive) {
        // Push connectors authenticate with tenant-bound API keys managed separately
        // (see ApiKeyManager), so there is no provider credential to enter here.
        payloadConfig = { ...(payloadConfig || {}), auth_mode: "api_key" };
      } else if (!finalToken && !isEditing) {
        setError(t("modal.needApiKeyOrGenerate", { provider: selectedProvider.name }));
        setLoading(false);
        return;
      }

      const res = await apiFetch(`${apiBase}/api/v1/data/sources/configure`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Tenant-ID": tenantId,
        },
        body: JSON.stringify({
          source_type: selectedProvider.id,
          access_token: finalToken || undefined,
          status: "active",
          // The Core contract requires a positive value; passive importers ignore it and wait for webhook events.
          poll_interval_hours: Number(pollIntervalHours),
          lookback_days: Number(lookbackDays),
          config: payloadConfig,
        }),
      });

      if (res.ok) {
        setMessage(t("modal.saved", { provider: selectedProvider.name }));
        setAccessToken("");
        setYazioEmail("");
        setYazioPassword("");
        onSaved();
        setTimeout(() => {
          onClose();
        }, 1200);
      } else {
        const data = await res.json().catch(() => null);
        setError(data?.detail || t("modal.saveFailed"));
      }
    } catch (err: any) {
      setError(t("modal.networkError", { message: err?.message || t("modal.serverUnreachable") }));
    } finally {
      setLoading(false);
    }
  };

  const isPassive = selectedProvider?.direction === "passive";

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
                title={t("modal.backToChoice")}
              >
                <ArrowLeft className="w-4 h-4" />
              </button>
            )}
            <div className="flex items-center gap-2 text-slate-900">
              <Plug className="w-5 h-5 text-[#0d5c3a]" />
              <h2 className="text-lg font-bold">
                {step === "select_provider"
                  ? t("modal.pickSource")
                  : isEditing
                  ? t("modal.editProvider", { provider: selectedProvider?.name ?? "" })
                  : t("modal.connectProvider", { provider: selectedProvider?.name ?? "" })}
              </h2>
              {selectedProvider && step === "configure_provider" && (
                <a
                  href={`/docs/importers/${selectedProvider.id === "apple_health" ? "apple-health" : selectedProvider.id === "home_assistant" ? "home-assistant" : selectedProvider.id}/`}
                  target="_blank"
                  rel="noreferrer"
                  className="ml-2 inline-flex items-center gap-1 px-2.5 py-1 rounded-xl bg-emerald-50 border border-emerald-200 text-xs font-bold text-emerald-800 hover:bg-emerald-100 transition-colors"
                  title={t("modal.guideFor", { provider: selectedProvider.name })}
                >
                  <BookOpen className="w-3.5 h-3.5 text-[#0d5c3a]" />
                  <span>Anleitung</span>
                </a>
              )}
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
              {t("modal.pickHint")}
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
                          {isAvailable ? t("modal.available") : t("connectors.soon")}
                        </span>
                      </div>
                      <h3 className="text-sm font-bold text-slate-900">{provider.name}</h3>
                      <span className={provider.direction === "active"
                        ? "inline-flex text-[10px] px-2.5 py-0.5 rounded-full font-bold uppercase tracking-wider bg-sky-50 text-sky-800 border border-sky-200"
                        : "inline-flex text-[10px] px-2.5 py-0.5 rounded-full font-bold uppercase tracking-wider bg-violet-50 text-violet-800 border border-violet-200"}>
                        {provider.direction === "active" ? t("modal.activeShort") : t("modal.passiveShort")}
                      </span>
                      <p className="text-[11px] text-slate-500 leading-snug">{t(provider.descriptionKey)}</p>
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
            <div className={isPassive
              ? "p-3.5 rounded-2xl border text-xs flex items-start gap-2.5 bg-violet-50 border-violet-200 text-violet-950"
              : "p-3.5 rounded-2xl border text-xs flex items-start gap-2.5 bg-sky-50 border-sky-200 text-sky-950"}>
              {isPassive ? (
                <Upload className="w-4 h-4 text-violet-600 shrink-0 mt-0.5" />
              ) : (
                <Download className="w-4 h-4 text-sky-600 shrink-0 mt-0.5" />
              )}
              <div>
                <span className="font-bold block">
                  {isPassive ? t("modal.passiveTitle") : t("modal.activeTitle")}
                </span>
                <span className="text-[11px] leading-relaxed block mt-0.5">
                  {isPassive
                    ? t("modal.passiveBody")
                    : t("modal.activeBody")}
                </span>
              </div>
            </div>

            {isEditing && (
              <div className="p-3.5 rounded-2xl bg-emerald-50 border border-emerald-200 text-xs text-emerald-900 flex items-start gap-2.5">
                <ShieldCheck className="w-4 h-4 text-emerald-600 shrink-0 mt-0.5" />
                <div>
                  <span className="font-bold block">{t("modal.credentialsStored")}</span>
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
                        placeholder={isEditing ? t("modal.keepCredentials") : "name@example.com"}
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
                        placeholder={isEditing ? t("modal.keepUnchanged") : "••••••••"}
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
                      placeholder={isEditing ? t("modal.keepCredentialsShort") : t("modal.pasteYazioToken")}
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
                    placeholder={isEditing ? t("modal.keepApiKey") : t("modal.pasteDawarichKey")}
                    value={dawarichApiKey}
                    onChange={(e) => setDawarichApiKey(e.target.value)}
                    required={!isEditing}
                    className="w-full px-4 py-2.5 rounded-2xl bg-white border border-slate-200 text-slate-900 text-sm focus:border-[#0d5c3a] focus:ring-2 focus:ring-[#0d5c3a]/20 outline-none font-mono"
                  />
                </div>
              </div>
            )}

            {selectedProvider?.id === "calendar" && (
              <div className="space-y-3">
                <div>
                  <label className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-1.5">
                    Kalender-Feed URL (.ics)
                  </label>
                  <input
                    type="url"
                    required
                    value={providerBaseUrl}
                    onChange={(event) => setProviderBaseUrl(event.target.value)}
                    placeholder="https://outlook.office365.com/owa/calendar/.../calendar.ics"
                    className="w-full px-4 py-2.5 rounded-2xl bg-white border border-slate-200 text-slate-900 text-sm outline-none"
                  />
                  <p className="mt-1.5 text-[11px] leading-relaxed text-slate-500">
                    {t("modal.icsHint")}
                    ohne API Key. Die URL einer privaten Feed-Adresse ist selbst das Geheimnis und
                    wird verschlüsselt gespeichert sowie nie protokolliert.{" "}
                    <a href="/docs/importers/calendar/" className="text-[#0d5c3a] underline" target="_blank" rel="noreferrer">
                      Einrichtungsanleitung
                    </a>
                  </p>
                </div>
                <div>
                  <label className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-1.5">
                    API Key <span className="text-slate-400 font-normal text-[11px] lowercase">{t("modal.apiKeyOptional")}</span>
                  </label>
                  <input
                    type="password"
                    value={accessToken}
                    onChange={(event) => setAccessToken(event.target.value)}
                    placeholder={t("modal.apiKeyOptionalPlaceholder")}
                    className="w-full px-4 py-2.5 rounded-2xl bg-white border border-slate-200 text-slate-900 text-sm font-mono outline-none"
                  />
                </div>
              </div>
            )}

            {selectedProvider && ["home_assistant", "weather"].includes(selectedProvider.id) && (
              <div className="space-y-3">
                <input type="url" required value={providerBaseUrl} onChange={(event) => setProviderBaseUrl(event.target.value)} placeholder="https://api.example.com" className="w-full px-4 py-2.5 rounded-2xl bg-white border border-slate-200 text-slate-900 text-sm outline-none" />
                <input type="password" required={!isEditing} value={accessToken} onChange={(event) => setAccessToken(event.target.value)} placeholder={isEditing ? "•••••••• (API Key beibehalten)" : "Bearer Token / API Key"} className="w-full px-4 py-2.5 rounded-2xl bg-white border border-slate-200 text-slate-900 text-sm font-mono outline-none" />
              </div>
            )}

            {selectedProvider?.id === "apple_health" && (
              <ApiKeyManager
                apiBase={apiBase}
                sourceType="apple_health"
                ingestPath="/api/v1/ingest/apple-health"
                providerLabel="Health Auto Export"
              />
            )}

            {selectedProvider?.id === "streak" && (
              <ApiKeyManager
                apiBase={apiBase}
                sourceType="streak"
                ingestPath="/api/v1/ingest/streak"
                providerLabel="Streak 2.0 REST Export"
              />
            )}

            {!isPassive && (
            /* Sync Frequency & Period Configuration */
            <div className="pt-3 border-t border-slate-100 space-y-3">
              <h3 className="text-xs font-bold uppercase tracking-wider text-[#0d5c3a] flex items-center gap-1.5">
                <Clock className="w-3.5 h-3.5" /> {t("modal.intervalSection")}
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
                    <option value={1} className="bg-white text-slate-900">{t("modal.everyHour")}</option>
                    <option value={3} className="bg-white text-slate-900">{t("modal.everyNHours", { count: 3 })}</option>
                    <option value={6} className="bg-white text-slate-900">{t("modal.everyNHoursDefault", { count: 6 })}</option>
                    <option value={12} className="bg-white text-slate-900">{t("modal.everyNHours", { count: 12 })}</option>
                    <option value={24} className="bg-white text-slate-900">{t("modal.daily")}</option>
                    <option value={168} className="bg-white text-slate-900">{t("modal.weekly")}</option>
                  </select>
                </div>

                <div>
                  <label className="block text-[11px] text-slate-500 font-bold mb-1 flex items-center gap-1">
                    <Calendar className="w-3 h-3 text-emerald-600" /> {t("modal.importPeriod")}
                  </label>
                  <select
                    value={lookbackDays}
                    onChange={(e) => setLookbackDays(Number(e.target.value))}
                    className="w-full px-3 py-2 rounded-2xl bg-white border border-slate-200 text-slate-900 text-xs focus:border-[#0d5c3a] outline-none font-bold"
                  >
                    <option value={7} className="bg-white text-slate-900">{t("modal.lastNDays", { count: 7 })}</option>
                    <option value={14} className="bg-white text-slate-900">{t("modal.lastNDays", { count: 14 })}</option>
                    <option value={30} className="bg-white text-slate-900">{t("modal.lastNDaysDefault", { count: 30 })}</option>
                    <option value={60} className="bg-white text-slate-900">{t("modal.lastNDays", { count: 60 })}</option>
                    <option value={90} className="bg-white text-slate-900">{t("modal.lastNDays", { count: 90 })}</option>
                  </select>
                </div>
              </div>
            </div>
            )}

            {isPassive && (
              <div className="pt-3 border-t border-slate-100">
                <p className="text-[11px] text-slate-500">
                  <span className="font-bold text-violet-700">{t("modal.passiveFlowLead")}</span> {t("modal.passiveFlowBody")}
                </p>
              </div>
            )}

            {error && <p role="alert" className="rounded-2xl bg-rose-50 border border-rose-200 px-3 py-2 text-xs font-semibold text-rose-700">{error}</p>}
            {message && <p className="rounded-2xl bg-emerald-50 border border-emerald-200 px-3 py-2 text-xs font-semibold text-emerald-800 flex items-center gap-2"><CheckCircle2 className="w-4 h-4 text-emerald-600" />{message}</p>}

            <div className="flex justify-between items-center pt-4 border-t border-slate-100">
              {!isEditing ? (
                <button
                  type="button"
                  onClick={() => setStep("select_provider")}
                  className="px-4 py-2 text-xs font-bold rounded-2xl bg-slate-100 border border-slate-200 hover:bg-slate-200 text-slate-700 transition-colors flex items-center gap-1.5"
                >
                  <ArrowLeft className="w-3.5 h-3.5" /> {t("modal.back")}
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
                {loading ? t("modal.saving") : isEditing ? t("modal.saveSettings") : t("modal.saveConnection")}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
