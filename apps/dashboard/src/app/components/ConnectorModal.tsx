"use client";

import React, { useState, useEffect } from "react";
import {
  Activity,
  ArrowLeft,
  BookOpen,
  Calendar,
  CheckCircle2,
  Clock,
  CloudSun,
  Download,
  Dumbbell,
  Flame,
  GitBranch,
  Heart,
  HousePlug,
  Key,
  MapPin,
  Plug,
  ShieldCheck,
  Upload,
  X,
} from "lucide-react";
import ApiKeyManager from "./ApiKeyManager";
import { apiFetch } from "../lib/api";
import { useI18n, type MessageKey } from "../lib/i18n/provider";
import { describeMetric } from "../lib/metrics/catalog";
import { useDialog } from "../lib/useDialog";

export type ConnectorDirection = "active" | "passive";

/**
 * Open-Meteo, which needs no API key. Shown in the form as a prefilled default
 * rather than hidden, so a self-hosted or commercial endpoint can replace it.
 */
export const WEATHER_DEFAULT_BASE_URL = "https://api.open-meteo.com";

/** One place returned by Core's `/api/v1/data/geocode` proxy. */
interface GeocodeResult {
  name: string;
  country: string | null;
  admin1: string | null;
  latitude: number;
  longitude: number;
}

/** "Berlin, Berlin, Germany" from whichever of the three parts came back. */
function placeLabel(place: GeocodeResult): string {
  return [place.name, place.admin1, place.country].filter(Boolean).join(", ");
}

export interface ProviderCatalogItem {
  id: string;
  name: string;
  categoryKey: MessageKey;
  descriptionKey: MessageKey;
  icon: React.ElementType;
  iconColor: string;
  status: "available" | "coming_soon";
  /**
   * Canonical `metric_type` keys from the registry — never display text. The
   * chips read these through `describeMetric()`, which carries the English and
   * German label of every metric, so this list cannot say a provider emits
   * something no transformer writes, and it cannot say it in one language only.
   * Providers whose metric set depends on the user's own installation name
   * examples under their dynamic namespace (see AGENTS.md rule 15).
   */
  supportedMetrics: string[];
  direction: ConnectorDirection;
  /**
   * The provider mails or exports a file its users can upload. Kept here beside
   * `direction` because both answer the same question — how does data get in —
   * and the server states it too (`supports_file_import` on a listed connector),
   * which is what the connectors page reads.
   */
  fileImport?: boolean;
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
    supportedMetrics: [
      "nutrition_energy",
      "nutrition_protein",
      "nutrition_carbohydrates",
      "nutrition_fat",
      "nutrition_item_energy",
    ],
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
    supportedMetrics: ["whoop_recovery_score", "hrv_rmssd", "heart_rate_resting", "whoop_strain"],
    direction: "active",
    fileImport: true,
  },
  {
    id: "apple_health",
    name: "Apple Health",
    categoryKey: "modal.catVitals",
    descriptionKey: "modal.desc.apple_health",
    icon: Heart,
    iconColor: "text-rose-400",
    status: "available",
    supportedMetrics: [
      "steps",
      "heart_rate",
      "energy_active",
      "sleep_duration",
      "workout_duration",
    ],
    direction: "passive",
    fileImport: true,
  },
  {
    id: "streak",
    name: "Streak - Gym Log",
    categoryKey: "modal.catStrength",
    descriptionKey: "modal.desc.streak",
    icon: Dumbbell,
    iconColor: "text-brand",
    status: "available",
    supportedMetrics: [
      "strength_session_sets",
      "strength_set_weight",
      "strength_set_reps",
      "strength_set_heart_rate_max",
      "strength_set_volume",
    ],
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
    supportedMetrics: ["location_point", "location_latitude", "location_longitude"],
    direction: "active",
  },
  {
    id: "home_assistant",
    name: "Home Assistant",
    categoryKey: "modal.catSmartHome",
    descriptionKey: "modal.desc.home_assistant",
    icon: HousePlug,
    iconColor: "text-sky-500",
    status: "available",
    // Every install exposes different entities, so these are examples under the
    // `home_assistant_` namespace rather than catalogued keys. Their label is
    // derived from the suffix and is therefore the same in both languages —
    // which is the honest answer for a name the user's own setup decides.
    supportedMetrics: [
      "home_assistant_temperature",
      "home_assistant_humidity",
      "home_assistant_illuminance",
      "home_assistant_noise",
    ],
    direction: "active",
  },
  {
    id: "weather",
    name: "Weather",
    categoryKey: "modal.catEnvironment",
    descriptionKey: "modal.desc.weather",
    icon: CloudSun,
    iconColor: "text-amber-500",
    status: "available",
    supportedMetrics: [
      "weather_temperature",
      "weather_pressure",
      "weather_precipitation",
      "weather_uv_index",
    ],
    direction: "active",
  },
  {
    id: "calendar",
    name: "Calendar",
    categoryKey: "modal.catRoutine",
    descriptionKey: "modal.desc.calendar",
    icon: Calendar,
    iconColor: "text-violet-500",
    status: "available",
    // `Busy Hours` before this: the unit in the name, which is exactly the
    // duplicate the registry exists to prevent (`calendar_busy_hours` is not
    // even an alias, on purpose).
    supportedMetrics: [
      "calendar_event_count",
      "calendar_meeting_duration",
      "calendar_busy_duration",
    ],
    direction: "active",
  },
  {
    id: "github",
    name: "GitHub",
    categoryKey: "modal.catRoutine",
    descriptionKey: "modal.desc.github",
    icon: GitBranch,
    iconColor: "text-slate-700",
    status: "available",
    supportedMetrics: [
      "code_commits",
      "code_lines_added",
      "code_lines_removed",
      "code_pull_requests_merged",
      "code_reviews_submitted",
    ],
    direction: "active",
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
  /** The connector being edited. Absent means "create a new instance". */
  initialSourceId?: string;
  initialDisplayName?: string;
  initialPollInterval?: number;
  initialLookbackDays?: number;
  initialLookbackHours?: number;
  /** `"file"` when editing a connector that is fed by uploads alone. */
  initialImportMode?: string | null;
  isEditing?: boolean;
}

export default function ConnectorModal({
  isOpen,
  onClose,
  onSaved,
  tenantId,
  apiBase = process.env.NEXT_PUBLIC_API_URL ||
    (typeof window !== "undefined" ? window.location.origin : "http://127.0.0.1:8000"),
  initialSourceType,
  initialSourceId,
  initialDisplayName,
  initialPollInterval = 6,
  initialLookbackDays = 7,
  initialLookbackHours,
  initialImportMode,
  isEditing = false,
}: ConnectorModalProps) {
  const { t, locale } = useI18n();
  // Escape, a focus trap and focus returned to the opener — the behaviour
  // `aria-modal="true"` above has been claiming since this dialog was written.
  const dialogRef = useDialog<HTMLDivElement>(isOpen, onClose);
  const [step, setStep] = useState<"select_provider" | "configure_provider">("select_provider");
  const [selectedProvider, setSelectedProvider] = useState<ProviderCatalogItem | null>(null);

  // What the user calls this instance. Required when creating one: with several
  // connectors of a type, nothing else tells them apart.
  const [displayName, setDisplayName] = useState("");
  const [accessToken, setAccessToken] = useState("");
  const [yazioAuthMode, setYazioAuthMode] = useState<"token" | "login">("token");
  const [yazioEmail, setYazioEmail] = useState("");
  const [yazioPassword, setYazioPassword] = useState("");
  const [dawarichUrl, setDawarichUrl] = useState("http://localhost:3000");
  const [dawarichApiKey, setDawarichApiKey] = useState("");
  const [providerBaseUrl, setProviderBaseUrl] = useState("");

  // Weather is configured by place, not by URL. The coordinates are what actually
  // gets stored -- the search only fills them in, and stays editable afterwards so
  // a location the lookup does not know can still be entered by hand.
  const [weatherBaseUrl, setWeatherBaseUrl] = useState(WEATHER_DEFAULT_BASE_URL);
  const [weatherPlaceQuery, setWeatherPlaceQuery] = useState("");
  const [weatherPlaces, setWeatherPlaces] = useState<GeocodeResult[]>([]);
  const [weatherPlaceLabel, setWeatherPlaceLabel] = useState("");
  const [weatherLatitude, setWeatherLatitude] = useState("");
  const [weatherLongitude, setWeatherLongitude] = useState("");
  const [weatherSearching, setWeatherSearching] = useState(false);
  const [weatherSearchError, setWeatherSearchError] = useState("");
  // "guided" builds the request from a location; "custom" sends the user's own
  // URL verbatim, which is the only way to reach the archive endpoint or ask for
  // variables the guided mode does not offer.
  const [weatherMode, setWeatherMode] = useState<"guided" | "custom">("guided");
  const [weatherRequestUrl, setWeatherRequestUrl] = useState("");

  // "connect" is the ordinary connector; "file" is one fed only by uploaded
  // exports, which needs no credential and is never polled. The choice exists
  // because getting a Whoop or Apple Health archive by email needs no developer
  // account at all, and for a one-off that is the whole difference.
  const [importMode, setImportMode] = useState<"connect" | "file">("connect");

  const [pollIntervalHours, setPollIntervalHours] = useState(initialPollInterval);
  const [lookbackHours, setLookbackHours] = useState(
    initialLookbackHours ?? initialLookbackDays * 24,
  );
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // The client-side key generator is gone: inbound keys are now minted by Core
  // (cryptographically random, stored only as a hash) and managed in ApiKeyManager.
  // Math.random() was never a suitable source for a credential anyway.

  useEffect(() => {
    if (isOpen) {
      setPollIntervalHours(initialPollInterval);
      setLookbackHours(initialLookbackHours ?? initialLookbackDays * 24);
      setImportMode(initialImportMode === "file" ? "file" : "connect");
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
      setDisplayName(initialDisplayName ?? "");
      setAccessToken("");
      setYazioEmail("");
      setYazioPassword("");
      setDawarichUrl("http://localhost:3000");
      setDawarichApiKey("");
      // Was missing, so configuring Home Assistant and then opening Weather showed
      // the Home Assistant URL still sitting in the field.
      setProviderBaseUrl("");
      setWeatherBaseUrl(WEATHER_DEFAULT_BASE_URL);
      setWeatherPlaceQuery("");
      setWeatherPlaces([]);
      setWeatherPlaceLabel("");
      setWeatherLatitude("");
      setWeatherLongitude("");
      setWeatherSearchError("");
      setWeatherMode("guided");
      setWeatherRequestUrl("");
      setMessage(null);
      setError(null);
    }
  }, [
    isOpen,
    initialSourceType,
    initialSourceId,
    initialDisplayName,
    initialPollInterval,
    initialLookbackDays,
    initialLookbackHours,
  ]);

  if (!isOpen) return null;

  const handleSelectProvider = (provider: ProviderCatalogItem) => {
    if (provider.status === "coming_soon") return;
    setSelectedProvider(provider);
    setStep("configure_provider");
  };

  /**
   * Resolve a place name through Core rather than from the browser.
   *
   * The dashboard ships a `connect-src` allowlist, and calling the geocoder
   * directly would both need that widened and hand the user's IP address and home
   * town to a third party.
   */
  const searchWeatherPlace = async () => {
    const query = weatherPlaceQuery.trim();
    if (query.length < 2) return;
    setWeatherSearching(true);
    setWeatherSearchError("");
    try {
      const res = await apiFetch(
        `${apiBase}/api/v1/data/geocode?query=${encodeURIComponent(query)}`,
      );
      if (!res.ok) throw new Error("lookup failed");
      const data = await res.json();
      const results: GeocodeResult[] = data.results || [];
      setWeatherPlaces(results);
      if (results.length === 0) setWeatherSearchError(t("modal.weatherNoPlaces"));
    } catch {
      setWeatherPlaces([]);
      setWeatherSearchError(t("modal.weatherSearchFailed"));
    } finally {
      setWeatherSearching(false);
    }
  };

  const chooseWeatherPlace = (place: GeocodeResult) => {
    setWeatherLatitude(String(place.latitude));
    setWeatherLongitude(String(place.longitude));
    setWeatherPlaceLabel(placeLabel(place));
    setWeatherPlaces([]);
    setWeatherSearchError("");
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedProvider) return;

    setMessage(null);
    setError(null);

    // A name is what tells two connectors of the same type apart, so it is
    // required when creating one. Editing keeps the existing name if left blank.
    if (!isEditing && !displayName.trim()) {
      setError(t("modal.needDisplayName"));
      return;
    }

    setLoading(true);
    try {
      let finalToken = accessToken.trim();
      let payloadConfig: Record<string, any> | undefined = undefined;

      if (fileOnly) {
        // Nothing to authenticate against: the data arrives when the user uploads
        // an export. The connector still exists as a row, because its id is what
        // makes re-uploading the same file a no-op rather than a second copy.
        finalToken = "";
        payloadConfig = { import_mode: "file" };
      } else if (selectedProvider.id === "yazio") {
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
        // The URL is the whole configuration. There is no API mode any more, so
        // there is nothing to demand a credential for -- and a feed whose path
        // does not end in .ics is perfectly normal.
        payloadConfig = { ics_url: url, base_url: url };
        finalToken = "";
      } else if (
        selectedProvider.id === "weather" &&
        isEditing &&
        !weatherRequestUrl.trim() &&
        !weatherLatitude.trim() &&
        !weatherLongitude.trim()
      ) {
        // Editing only the interval or the name. The stored configuration is not
        // handed to this modal, so an empty form means "leave it alone" rather
        // than "clear it" — Core merges, so omitting `config` keeps what is there.
        payloadConfig = undefined;
      } else if (selectedProvider.id === "weather" && weatherMode === "custom") {
        const url = weatherRequestUrl.trim();
        if (!/^https?:\/\//i.test(url)) {
          setError(t("modal.weatherNeedRequestUrl"));
          setLoading(false);
          return;
        }
        // Sent as written. The importer preserves the query instead of replacing
        // it, so everything copied from the provider's own page survives.
        payloadConfig = { request_url: url };
      } else if (selectedProvider.id === "weather") {
        // Coordinates are the whole configuration. The form never collected them
        // before, so every weather connector created here failed in the importer
        // with a message about fields the user had no way to fill in.
        const latitude = Number(weatherLatitude.trim());
        const longitude = Number(weatherLongitude.trim());
        if (
          !weatherLatitude.trim() ||
          !weatherLongitude.trim() ||
          Number.isNaN(latitude) ||
          Number.isNaN(longitude)
        ) {
          setError(t("modal.weatherNeedCoordinates"));
          setLoading(false);
          return;
        }
        if (latitude < -90 || latitude > 90 || longitude < -180 || longitude > 180) {
          setError(t("modal.weatherCoordinatesRange"));
          setLoading(false);
          return;
        }
        payloadConfig = {
          latitude,
          longitude,
          base_url: weatherBaseUrl.trim() || WEATHER_DEFAULT_BASE_URL,
        };
        if (weatherPlaceLabel.trim()) {
          payloadConfig.place_label = weatherPlaceLabel.trim();
        }
        // Deliberately no credential check: Open-Meteo issues no keys, and
        // demanding one is what made this connector impossible to set up.
      } else if (selectedProvider.id === "home_assistant") {
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
        // oxlint calls the `?? {}` redundant here and it is not: `payloadConfig`
        // is `Record<string, any> | undefined`, and TypeScript rejects spreading
        // a union that includes `undefined` (TS2698) even though the runtime
        // would be fine with it. The type check is the stronger of the two.
        payloadConfig = { ...(payloadConfig ?? {}), auth_mode: "api_key" };
      } else if (!finalToken && !isEditing) {
        setError(t("modal.needApiKeyOrGenerate", { provider: selectedProvider.name }));
        setLoading(false);
        return;
      }

      if (supportsFileImport && !fileOnly) {
        payloadConfig = { ...(payloadConfig ?? {}), import_mode: null };
      }

      const res = await apiFetch(`${apiBase}/api/v1/data/sources/configure`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Tenant-ID": tenantId,
        },
        body: JSON.stringify({
          source_type: selectedProvider.id,
          // Present only when editing: Core reads its absence as "create a new
          // instance", which is what makes a second calendar possible.
          source_id: initialSourceId || undefined,
          display_name: displayName.trim() || undefined,
          access_token: finalToken || undefined,
          status: "active",
          // The Core contract requires a positive value; passive importers ignore it and wait for webhook events.
          poll_interval_hours: Number(pollIntervalHours),
          lookback_days: Math.ceil(Number(lookbackHours) / 24),
          lookback_hours: Number(lookbackHours),
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
  const supportsFileImport = Boolean(selectedProvider?.fileImport);
  const fileOnly = supportsFileImport && importMode === "file";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-slate-900/60 backdrop-blur-md p-4 animate-in fade-in duration-200">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={t("modal.pickSource")}
        tabIndex={-1}
        className="my-auto w-full max-w-xl max-h-[calc(100dvh-2rem)] overflow-y-auto overscroll-contain bg-white border border-slate-200/90 rounded-3xl p-6 shadow-2xl space-y-6"
      >
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
              <Plug className="w-5 h-5 text-brand" />
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
                  <BookOpen className="w-3.5 h-3.5 text-brand" />
                  <span>{t("modal.guide")}</span>
                </a>
              )}
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label={t("common.close")}
            className="text-slate-400 hover:text-slate-900 p-1.5 rounded-xl hover:bg-slate-100 transition-colors"
          >
            <X className="w-5 h-5" aria-hidden="true" />
          </button>
        </div>

        {/* Step 1: Provider Selection Gallery */}
        {step === "select_provider" ? (
          <div className="space-y-4">
            <p className="text-xs text-slate-500">{t("modal.pickHint")}</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 max-h-[60vh] overflow-y-auto pr-1">
              {PROVIDER_CATALOG.map((provider) => {
                const Icon = provider.icon;
                const isAvailable = provider.status === "available";
                return (
                  <button
                    key={provider.id}
                    onClick={() => handleSelectProvider(provider)}
                    disabled={!isAvailable}
                    className={`text-left p-4 rounded-2xl border [transition-property:color,background-color,border-color,text-decoration-color,fill,stroke,box-shadow] flex flex-col justify-between space-y-3 ${
                      isAvailable
                        ? "bg-slate-50 border-slate-200 hover:border-brand hover:bg-emerald-50/50 cursor-pointer shadow-xs"
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
                      <span
                        className={
                          provider.direction === "active"
                            ? "inline-flex text-[10px] px-2.5 py-0.5 rounded-full font-bold uppercase tracking-wider bg-sky-50 text-sky-800 border border-sky-200"
                            : "inline-flex text-[10px] px-2.5 py-0.5 rounded-full font-bold uppercase tracking-wider bg-violet-50 text-violet-800 border border-violet-200"
                        }
                      >
                        {provider.direction === "active"
                          ? t("modal.activeShort")
                          : t("modal.passiveShort")}
                      </span>
                      <p className="text-[11px] text-slate-500 leading-snug">
                        {t(provider.descriptionKey)}
                      </p>
                    </div>

                    {/*
                      The chip reads as a name in the reader's language, the
                      tooltip keeps the canonical key — the same arrangement as
                      the explorer, and the reason the list holds slugs: a
                      metric's two labels live in the registry, so a card cannot
                      promise a metric under a name nothing writes.
                    */}
                    <div className="flex flex-wrap gap-1 pt-1 border-t border-slate-200">
                      {provider.supportedMetrics.slice(0, 3).map((m) => (
                        <span
                          key={m}
                          title={m}
                          className="text-[9px] px-1.5 py-0.5 rounded bg-white text-slate-600 border border-slate-200 font-mono"
                        >
                          {describeMetric(m, locale).label}
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
            <div
              className={
                isPassive
                  ? "p-3.5 rounded-2xl border text-xs flex items-start gap-2.5 bg-violet-50 border-violet-200 text-violet-950"
                  : "p-3.5 rounded-2xl border text-xs flex items-start gap-2.5 bg-sky-50 border-sky-200 text-sky-950"
              }
            >
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
                  {isPassive ? t("modal.passiveBody") : t("modal.activeBody")}
                </span>
              </div>
            </div>

            {isEditing && (
              <div className="p-3.5 rounded-2xl bg-emerald-50 border border-emerald-200 text-xs text-emerald-900 flex items-start gap-2.5">
                <ShieldCheck className="w-4 h-4 text-emerald-600 shrink-0 mt-0.5" />
                <div>
                  <span className="font-bold block">{t("modal.credentialsStored")}</span>
                  <span className="text-[11px] text-emerald-700 leading-relaxed block mt-0.5">
                    {t("modal.credentialsStoredBody")}
                  </span>
                </div>
              </div>
            )}

            {/*
              The name comes first and applies to every connector type: it is the
              only thing distinguishing a work calendar from a family one.
            */}
            <div>
              <label className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-1.5">
                {t("modal.displayNameLabel")}
              </label>
              <input
                type="text"
                required={!isEditing}
                maxLength={128}
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                placeholder={t("modal.displayNamePlaceholder")}
                className="w-full px-4 py-2.5 rounded-2xl bg-white border border-slate-200 text-slate-900 text-sm outline-none focus-ring"
              />
              <p className="mt-1.5 text-[11px] leading-relaxed text-slate-500">
                {t("modal.displayNameHint")}
              </p>
            </div>

            {/*
              How this connector is fed. Whoop and Apple Health both hand a user
              their whole history as a file, which needs no developer account and
              no OAuth application — for somebody who wants their data once, that
              is the difference between having it and not. A file connector is a
              real connector all the same: its id is what makes uploading the same
              export twice a no-op instead of a second copy of a year.
            */}
            {supportsFileImport && (
              <div>
                <div className="flex bg-slate-100 border border-slate-200 rounded-2xl p-1 text-xs">
                  <button
                    type="button"
                    onClick={() => setImportMode("connect")}
                    className={`flex-1 py-2 rounded-xl font-bold [transition-property:color,background-color,border-color,text-decoration-color,fill,stroke,box-shadow] ${
                      importMode === "connect"
                        ? "bg-brand text-brand-ink shadow-sm"
                        : "text-slate-600 hover:text-slate-900"
                    }`}
                  >
                    {t("modal.modeConnect")}
                  </button>
                  <button
                    type="button"
                    onClick={() => setImportMode("file")}
                    className={`flex-1 py-2 rounded-xl font-bold [transition-property:color,background-color,border-color,text-decoration-color,fill,stroke,box-shadow] ${
                      importMode === "file"
                        ? "bg-brand text-brand-ink shadow-sm"
                        : "text-slate-600 hover:text-slate-900"
                    }`}
                  >
                    {t("modal.modeFile")}
                  </button>
                </div>
                <p className="mt-1.5 text-[11px] leading-relaxed text-slate-500">
                  {t(fileOnly ? "modal.modeFileHint" : "modal.modeConnectHint")}
                </p>
              </div>
            )}

            {selectedProvider?.id === "yazio" && (
              <>
                <div className="flex bg-slate-100 border border-slate-200 rounded-2xl p-1 mb-3 text-xs">
                  <button
                    type="button"
                    onClick={() => setYazioAuthMode("token")}
                    className={`flex-1 py-2 rounded-xl font-bold [transition-property:color,background-color,border-color,text-decoration-color,fill,stroke,box-shadow] ${
                      yazioAuthMode === "token"
                        ? "bg-brand text-brand-ink shadow-sm"
                        : "text-slate-600 hover:text-slate-900"
                    }`}
                  >
                    {isEditing ? t("modal.yazioTokenOptional") : t("modal.yazioTokenMode")}
                  </button>
                  <button
                    type="button"
                    onClick={() => setYazioAuthMode("login")}
                    className={`flex-1 py-2 rounded-xl font-bold [transition-property:color,background-color,border-color,text-decoration-color,fill,stroke,box-shadow] ${
                      yazioAuthMode === "login"
                        ? "bg-brand text-brand-ink shadow-sm"
                        : "text-slate-600 hover:text-slate-900"
                    }`}
                  >
                    {isEditing ? t("modal.yazioLoginOptional") : t("modal.yazioLoginMode")}
                  </button>
                </div>

                {yazioAuthMode === "login" ? (
                  <div className="space-y-3">
                    <div>
                      <label className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-1">
                        Yazio {t("auth.email")}{" "}
                        {isEditing && (
                          <span className="text-slate-400 font-normal lowercase">(optional)</span>
                        )}
                      </label>
                      <input
                        type="email"
                        placeholder={isEditing ? t("modal.keepCredentials") : "name@example.com"}
                        value={yazioEmail}
                        onChange={(e) => setYazioEmail(e.target.value)}
                        className="w-full px-4 py-2.5 rounded-2xl bg-white border border-slate-200 text-slate-900 text-sm focus-visible:border-brand focus-visible:ring-2 focus-visible:ring-brand/20 outline-none"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-1">
                        Yazio {t("auth.password")}{" "}
                        {isEditing && (
                          <span className="text-slate-400 font-normal lowercase">(optional)</span>
                        )}
                      </label>
                      <input
                        type="password"
                        placeholder={isEditing ? t("modal.keepUnchanged") : "••••••••"}
                        value={yazioPassword}
                        onChange={(e) => setYazioPassword(e.target.value)}
                        className="w-full px-4 py-2.5 rounded-2xl bg-white border border-slate-200 text-slate-900 text-sm focus-visible:border-brand focus-visible:ring-2 focus-visible:ring-brand/20 outline-none"
                      />
                    </div>
                  </div>
                ) : (
                  <div>
                    <label className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-1.5 flex items-center gap-1.5">
                      <Key className="w-3.5 h-3.5 text-brand" />
                      <span>Yazio Bearer Access Token</span>
                      {isEditing && (
                        <span className="text-slate-400 font-normal text-[11px] lowercase">
                          (optional)
                        </span>
                      )}
                    </label>
                    <input
                      type="password"
                      placeholder={
                        isEditing ? t("modal.keepCredentialsShort") : t("modal.pasteYazioToken")
                      }
                      value={accessToken}
                      onChange={(e) => setAccessToken(e.target.value)}
                      className="w-full px-4 py-2.5 rounded-2xl bg-white border border-slate-200 text-slate-900 text-sm focus-visible:border-brand focus-visible:ring-2 focus-visible:ring-brand/20 outline-none font-mono"
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
                    className="w-full px-4 py-2.5 rounded-2xl bg-white border border-slate-200 text-slate-900 text-sm focus-visible:border-brand focus-visible:ring-2 focus-visible:ring-brand/20 outline-none"
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-1.5 flex items-center gap-1.5">
                    <Key className="w-3.5 h-3.5 text-brand" />
                    <span>Dawarich API Key</span>
                    {isEditing && (
                      <span className="text-slate-400 font-normal text-[11px] lowercase">
                        (optional)
                      </span>
                    )}
                  </label>
                  <input
                    type="password"
                    placeholder={isEditing ? t("modal.keepApiKey") : t("modal.pasteDawarichKey")}
                    value={dawarichApiKey}
                    onChange={(e) => setDawarichApiKey(e.target.value)}
                    required={!isEditing}
                    className="w-full px-4 py-2.5 rounded-2xl bg-white border border-slate-200 text-slate-900 text-sm focus-visible:border-brand focus-visible:ring-2 focus-visible:ring-brand/20 outline-none font-mono"
                  />
                </div>
              </div>
            )}

            {selectedProvider?.id === "calendar" && (
              <div className="space-y-3">
                <div>
                  <label className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-1.5">
                    {t("modal.calendarUrlLabel")}
                  </label>
                  <input
                    type="url"
                    required
                    value={providerBaseUrl}
                    onChange={(event) => setProviderBaseUrl(event.target.value)}
                    placeholder="https://outlook.office365.com/owa/calendar/.../calendar.ics"
                    className="w-full px-4 py-2.5 rounded-2xl bg-white border border-slate-200 text-slate-900 text-sm outline-none focus-ring"
                  />
                  <p className="mt-1.5 text-[11px] leading-relaxed text-slate-500">
                    {t("modal.icsHint")}{" "}
                    <a
                      href="/docs/importers/calendar/"
                      className="text-brand underline"
                      target="_blank"
                      rel="noreferrer"
                    >
                      {t("modal.setupGuide")}
                    </a>
                  </p>
                </div>
              </div>
            )}

            {selectedProvider?.id === "weather" && (
              <div className="space-y-3">
                <div className="flex bg-slate-100 border border-slate-200 rounded-2xl p-1 text-xs">
                  <button
                    type="button"
                    onClick={() => setWeatherMode("guided")}
                    className={`flex-1 py-2 rounded-xl font-bold transition-colors ${
                      weatherMode === "guided"
                        ? "bg-white text-slate-900 shadow-sm"
                        : "text-slate-500"
                    }`}
                  >
                    {t("modal.weatherModeGuided")}
                  </button>
                  <button
                    type="button"
                    onClick={() => setWeatherMode("custom")}
                    className={`flex-1 py-2 rounded-xl font-bold transition-colors ${
                      weatherMode === "custom"
                        ? "bg-white text-slate-900 shadow-sm"
                        : "text-slate-500"
                    }`}
                  >
                    {t("modal.weatherModeCustom")}
                  </button>
                </div>

                {weatherMode === "custom" && (
                  <div>
                    <label className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-1.5">
                      {t("modal.weatherRequestUrlLabel")}
                    </label>
                    <input
                      type="url"
                      required={!isEditing}
                      value={weatherRequestUrl}
                      onChange={(event) => setWeatherRequestUrl(event.target.value)}
                      placeholder="https://archive-api.open-meteo.com/v1/archive?latitude=52.52&longitude=13.41&hourly=temperature_2m"
                      className="w-full px-4 py-2.5 rounded-2xl bg-white border border-slate-200 text-slate-900 text-xs font-mono outline-none focus-ring"
                    />
                    <p className="mt-1.5 text-[11px] leading-relaxed text-slate-500">
                      {t("modal.weatherRequestUrlHint")}
                    </p>
                  </div>
                )}

                {weatherMode === "guided" && (
                  <>
                    <div>
                      <label className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-1.5">
                        {t("modal.weatherPlaceLabel")}
                      </label>
                      <div className="flex gap-2">
                        <input
                          type="text"
                          value={weatherPlaceQuery}
                          onChange={(event) => setWeatherPlaceQuery(event.target.value)}
                          onKeyDown={(event) => {
                            if (event.key === "Enter") {
                              // The modal is a form; Enter here means "search", not "save".
                              event.preventDefault();
                              void searchWeatherPlace();
                            }
                          }}
                          placeholder={t("modal.weatherPlacePlaceholder")}
                          className="flex-1 px-4 py-2.5 rounded-2xl bg-white border border-slate-200 text-slate-900 text-sm outline-none focus-ring"
                        />
                        <button
                          type="button"
                          onClick={() => void searchWeatherPlace()}
                          disabled={weatherSearching || weatherPlaceQuery.trim().length < 2}
                          className="px-4 py-2.5 rounded-2xl bg-slate-100 border border-slate-200 text-slate-700 text-sm font-semibold hover:bg-slate-200 disabled:opacity-50 whitespace-nowrap"
                        >
                          {weatherSearching
                            ? t("modal.weatherSearching")
                            : t("modal.weatherSearch")}
                        </button>
                      </div>
                      {weatherSearchError && (
                        <p className="mt-1.5 text-[11px] text-rose-600">{weatherSearchError}</p>
                      )}
                      {weatherPlaces.length > 0 && (
                        <ul className="mt-2 space-y-1">
                          {weatherPlaces.map((place) => (
                            <li key={`${place.latitude},${place.longitude}`}>
                              <button
                                type="button"
                                onClick={() => chooseWeatherPlace(place)}
                                className="w-full text-left px-3 py-2 rounded-xl bg-white border border-slate-200 hover:border-brand text-xs text-slate-700"
                              >
                                <MapPin className="inline w-3 h-3 mr-1.5 text-brand" />
                                {placeLabel(place)}
                              </button>
                            </li>
                          ))}
                        </ul>
                      )}
                      {weatherPlaceLabel && (
                        <p className="mt-1.5 text-[11px] text-slate-500">
                          {t("modal.weatherChosenPlace", { place: weatherPlaceLabel })}
                        </p>
                      )}
                    </div>

                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                      <div>
                        <label className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-1.5">
                          {t("modal.weatherLatitude")}
                        </label>
                        <input
                          type="text"
                          inputMode="decimal"
                          required={!isEditing}
                          value={weatherLatitude}
                          onChange={(event) => setWeatherLatitude(event.target.value)}
                          placeholder="52.52"
                          className="w-full px-4 py-2.5 rounded-2xl bg-white border border-slate-200 text-slate-900 text-sm font-mono outline-none focus-ring"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-1.5">
                          {t("modal.weatherLongitude")}
                        </label>
                        <input
                          type="text"
                          inputMode="decimal"
                          required={!isEditing}
                          value={weatherLongitude}
                          onChange={(event) => setWeatherLongitude(event.target.value)}
                          placeholder="13.41"
                          className="w-full px-4 py-2.5 rounded-2xl bg-white border border-slate-200 text-slate-900 text-sm font-mono outline-none focus-ring"
                        />
                      </div>
                    </div>

                    <div>
                      <label className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-1.5">
                        {t("modal.weatherBaseUrl")}
                      </label>
                      <input
                        type="url"
                        value={weatherBaseUrl}
                        onChange={(event) => setWeatherBaseUrl(event.target.value)}
                        placeholder={WEATHER_DEFAULT_BASE_URL}
                        className="w-full px-4 py-2.5 rounded-2xl bg-white border border-slate-200 text-slate-900 text-sm outline-none focus-ring"
                      />
                      <p className="mt-1.5 text-[11px] leading-relaxed text-slate-500">
                        {t("modal.weatherBaseUrlHint")}{" "}
                        <a
                          href="/docs/importers/weather/"
                          className="text-brand underline"
                          target="_blank"
                          rel="noreferrer"
                        >
                          {t("modal.setupGuide")}
                        </a>
                      </p>
                    </div>
                  </>
                )}
              </div>
            )}

            {selectedProvider?.id === "home_assistant" && (
              <div className="space-y-3">
                <div>
                  <label className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-1.5">
                    {t("modal.baseUrlLabel")}
                  </label>
                  <input
                    type="url"
                    required
                    value={providerBaseUrl}
                    onChange={(event) => setProviderBaseUrl(event.target.value)}
                    placeholder="https://homeassistant.local:8123"
                    className="w-full px-4 py-2.5 rounded-2xl bg-white border border-slate-200 text-slate-900 text-sm outline-none focus-ring"
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-1.5">
                    {t("modal.tokenLabel")}
                  </label>
                  <input
                    type="password"
                    required={!isEditing}
                    value={accessToken}
                    onChange={(event) => setAccessToken(event.target.value)}
                    placeholder={
                      isEditing ? t("modal.keepTokenPlaceholder") : t("modal.tokenPlaceholder")
                    }
                    className="w-full px-4 py-2.5 rounded-2xl bg-white border border-slate-200 text-slate-900 text-sm font-mono outline-none focus-ring"
                  />
                </div>
              </div>
            )}

            {selectedProvider?.id === "apple_health" && !fileOnly && (
              <ApiKeyManager
                apiBase={apiBase}
                sourceType="apple_health"
                sourceId={initialSourceId}
                ingestPath="/api/v1/ingest/apple-health"
                providerLabel="Health Auto Export"
              />
            )}

            {selectedProvider?.id === "streak" && (
              <ApiKeyManager
                apiBase={apiBase}
                sourceType="streak"
                sourceId={initialSourceId}
                ingestPath="/api/v1/ingest/streak"
                providerLabel="Streak 2.0 REST Export"
              />
            )}

            {!isPassive && !fileOnly && (
              /* Sync Frequency & Period Configuration */
              <div className="pt-3 border-t border-slate-100 space-y-3">
                <h3 className="text-xs font-bold uppercase tracking-wider text-brand flex items-center gap-1.5">
                  <Clock className="w-3.5 h-3.5" /> {t("modal.intervalSection")}
                </h3>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div>
                    <label className="block text-[11px] text-slate-500 font-bold mb-1 flex items-center gap-1">
                      <Clock className="w-3 h-3 text-brand" /> {t("modal.syncFrequency")}
                    </label>
                    <select
                      value={pollIntervalHours}
                      onChange={(e) => setPollIntervalHours(Number(e.target.value))}
                      className="w-full px-3 py-2 rounded-2xl bg-white border border-slate-200 text-slate-900 text-xs focus-visible:border-brand outline-none font-bold"
                    >
                      <option value={1} className="bg-white text-slate-900">
                        {t("modal.everyHour")}
                      </option>
                      <option value={3} className="bg-white text-slate-900">
                        {t("modal.everyNHours", { count: 3 })}
                      </option>
                      <option value={6} className="bg-white text-slate-900">
                        {t("modal.everyNHoursDefault", { count: 6 })}
                      </option>
                      <option value={12} className="bg-white text-slate-900">
                        {t("modal.everyNHours", { count: 12 })}
                      </option>
                      <option value={24} className="bg-white text-slate-900">
                        {t("modal.daily")}
                      </option>
                      <option value={168} className="bg-white text-slate-900">
                        {t("modal.weekly")}
                      </option>
                    </select>
                  </div>

                  <div>
                    <label className="block text-[11px] text-slate-500 font-bold mb-1 flex items-center gap-1">
                      <Calendar className="w-3 h-3 text-emerald-600" /> {t("modal.importPeriod")}
                    </label>
                    <select
                      value={lookbackHours}
                      onChange={(e) => setLookbackHours(Number(e.target.value))}
                      className="w-full px-3 py-2 rounded-2xl bg-white border border-slate-200 text-slate-900 text-xs focus-visible:border-brand outline-none font-bold"
                    >
                      <option value={6} className="bg-white text-slate-900">
                        {t("modal.lastNHours", { count: 6 })}
                      </option>
                      <option value={12} className="bg-white text-slate-900">
                        {t("modal.lastNHours", { count: 12 })}
                      </option>
                      <option value={24} className="bg-white text-slate-900">
                        {t("modal.lastNHours", { count: 24 })}
                      </option>
                      <option value={168} className="bg-white text-slate-900">
                        {t("modal.lastNHoursDefault", { count: 168 })}
                      </option>
                      <option value={336} className="bg-white text-slate-900">
                        {t("modal.lastNHours", { count: 336 })}
                      </option>
                      <option value={720} className="bg-white text-slate-900">
                        {t("modal.lastNHours", { count: 720 })}
                      </option>
                    </select>
                  </div>
                </div>
              </div>
            )}

            {isPassive && !fileOnly && (
              <div className="pt-3 border-t border-slate-100">
                <p className="text-[11px] text-slate-500">
                  <span className="font-bold text-violet-700">{t("modal.passiveFlowLead")}</span>{" "}
                  {t("modal.passiveFlowBody")}
                </p>
              </div>
            )}

            {fileOnly && (
              <div className="pt-3 border-t border-slate-100">
                <p className="text-[11px] text-slate-500">
                  <span className="font-bold text-sky-700">{t("modal.fileFlowLead")}</span>{" "}
                  {t("modal.fileFlowBody")}
                </p>
              </div>
            )}

            {error && (
              <p
                role="alert"
                className="rounded-2xl bg-rose-50 border border-rose-200 px-3 py-2 text-xs font-semibold text-rose-700"
              >
                {error}
              </p>
            )}
            {message && (
              <p className="rounded-2xl bg-emerald-50 border border-emerald-200 px-3 py-2 text-xs font-semibold text-emerald-800 flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                {message}
              </p>
            )}

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
                  {t("common.cancel")}
                </button>
              )}
              <button
                type="submit"
                disabled={loading}
                className="px-5 py-2.5 text-xs font-bold rounded-2xl bg-brand hover:bg-brand-hover text-brand-ink [transition-property:color,background-color,border-color,text-decoration-color,fill,stroke,box-shadow] disabled:opacity-50 shadow-md shadow-brand/20"
              >
                {loading
                  ? t("modal.saving")
                  : isEditing
                    ? t("modal.saveSettings")
                    : t("modal.saveConnection")}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
