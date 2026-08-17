"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Map as LeafletMap } from "leaflet";
import { Calendar, Globe2, Layers, MapPin, Navigation, RefreshCw, ShieldCheck } from "lucide-react";
import { apiFetch } from "../lib/api";

import { useI18n } from "../lib/i18n/provider";

/**
 * GPS route rendering, vector-first.
 *
 * Previously this injected Leaflet from unpkg.com on mount and immediately loaded
 * OpenStreetMap raster tiles. Three problems: the app's own CSP forbids both the
 * third-party script and non-self images, so in any environment where the headers
 * applied the map was a permanently grey box; the `script.onload` had no `onerror`,
 * so that failure was silent; and every visit hit a third-party tile server with
 * the user's location data before they had asked for a map.
 *
 * Now:
 *   * The default view is a pure SVG vector route — no external request of any kind.
 *   * Raster tiles are strictly opt-in, behind a button that states what it does.
 *   * Leaflet is bundled locally, so no third-party script is ever fetched.
 *   * Any failure falls back to the vector view with a visible message.
 *   * Large tracks are simplified before rendering rather than drawing every point.
 */

export interface GpsPoint {
  latitude: number;
  longitude: number;
  timestamp?: string;
  speed?: number;
  altitude?: number;
}

interface LocationMapProps {
  apiBase?: string;
  tenantId?: string;
  refreshTrigger?: number;
  /** A local calendar day to fetch exactly; used by the daily story. */
  day?: string;
  /** Offset, in minutes east of UTC, for the reader's local day window. */
  offsetMinutes?: number;
  /**
   * A track supplied by the caller. When present nothing is fetched and the date
   * filter is hidden: the workout detail already knows which fixes belong to the
   * session, and re-deriving that from a calendar filter would draw a different
   * route from the one the endpoint resolved.
   */
  points?: GpsPoint[];
  /** Heading and privacy note, which a page that has its own heading suppresses. */
  showHeader?: boolean;
}

type TileProvider = "osm" | "carto";

const TILE_PROVIDERS: Record<
  TileProvider,
  { label: string; url: string; attribution: string; subdomains: string }
> = {
  osm: {
    label: "OpenStreetMap",
    url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    subdomains: "abc",
  },
  carto: {
    label: "CARTO Voyager",
    url: "https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png",
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
    subdomains: "abcd",
  },
};

/** Configurable, but never used unless the user explicitly loads the map. */
const DEFAULT_PROVIDER: TileProvider =
  (process.env.NEXT_PUBLIC_MAP_TILE_PROVIDER as TileProvider) in TILE_PROVIDERS
    ? (process.env.NEXT_PUBLIC_MAP_TILE_PROVIDER as TileProvider)
    : "osm";

/**
 * Points drawn into the polyline.
 *
 * Raised from 400 once the fetch stopped clipping the day: 400 was chosen against
 * a track that was already capped at 1,000 fixes, where it cost little. Against a
 * whole day it is the step that throws the shape away — and `simplifyTrack` keeps
 * corners over straight stretches, so the extra points buy detail in exactly the
 * places a route is recognisable by. A few thousand vertices in one Leaflet
 * polyline is well inside what it draws smoothly.
 */
const MAX_RENDERED_POINTS = 2000;

/**
 * Reduce a track to at most `limit` points, keeping the ones that carry the shape.
 *
 * Perpendicular distance to the local segment is a good proxy for "this point is a
 * corner"; straight stretches collapse, turns survive. Endpoints are always kept so
 * the route still starts and ends where it did.
 */
export function simplifyTrack(points: GpsPoint[], limit = MAX_RENDERED_POINTS): GpsPoint[] {
  if (points.length <= limit) return points;

  const significance = points.map((p, i) => {
    if (i === 0 || i === points.length - 1) return Number.POSITIVE_INFINITY;
    const prev = points[i - 1];
    const next = points[i + 1];
    // Twice the triangle area = deviation from the straight line prev→next.
    return Math.abs(
      (next.longitude - prev.longitude) * (prev.latitude - p.latitude) -
        (prev.longitude - p.longitude) * (next.latitude - prev.latitude),
    );
  });

  const threshold = [...significance].filter(Number.isFinite).sort((a, b) => b - a)[limit - 2] ?? 0;

  const kept = points.filter((_, i) => significance[i] >= threshold);
  // Ties at the threshold can overshoot the limit; trim evenly rather than truncating
  // the tail, which would silently drop the most recent positions.
  if (kept.length > limit) {
    const stride = kept.length / limit;
    return Array.from({ length: limit }, (_, i) => kept[Math.floor(i * stride)]);
  }
  return kept;
}

export default function LocationMap({
  apiBase,
  refreshTrigger,
  day,
  offsetMinutes,
  points: suppliedPoints,
  showHeader = true,
}: LocationMapProps) {
  const { t, formatDateTime, formatNumber } = useI18n();
  const [mapContainer, setMapContainer] = useState<HTMLDivElement | null>(null);
  const mapInstanceRef = useRef<LeafletMap | null>(null);
  const [fetchedPoints, setFetchedPoints] = useState<GpsPoint[]>([]);
  /**
   * How many fixes the span actually holds, as opposed to how many are drawn.
   *
   * `null` while nothing has been fetched, and for a caller-supplied track, where
   * the points are all there is and the two numbers are the same.
   */
  const [fixCount, setFixCount] = useState<number | null>(null);
  const [dateFilter, setDateFilter] = useState<"today" | "7d" | "30d">("today");
  // A caller-supplied track is ready on the first render, so there is nothing to
  // wait for and the spinner would be a frame of noise.
  const controlled = suppliedPoints !== undefined;
  const [loading, setLoading] = useState(!controlled);
  const points = suppliedPoints ?? fetchedPoints;

  // Vector is the default. Tiles are only ever loaded on an explicit request.
  const [showTiles, setShowTiles] = useState(false);
  const [tileProvider, setTileProvider] = useState<TileProvider>(DEFAULT_PROVIDER);
  const [tileError, setTileError] = useState("");

  const fetchLocationData = useCallback(async () => {
    setLoading(true);
    try {
      const now = new Date();
      const offset = offsetMinutes ?? -now.getTimezoneOffset();
      // The day the span ends on, and how many days back it reaches. The server
      // owns both boundaries through the same `day_window` the day report uses, so
      // the map and the story cannot disagree about where a day starts.
      const lastDay = day ?? new Date(now.getTime() + offset * 60_000).toISOString().slice(0, 10);
      const spanDays = day ? 1 : dateFilter === "today" ? 1 : dateFilter === "7d" ? 7 : 30;

      const query = new URLSearchParams({
        day: lastDay,
        days: String(spanDays),
        offset_minutes: String(offset),
      });
      // The whole span, decimated in the database to fit. Not `/metrics` with
      // `limit=1000`: that endpoint sorts ascending and reports no truncation, so a
      // day with more fixes than the limit returned the *earliest* thousand — a
      // track that stopped mid-morning, with the count of what was returned shown
      // as if it were the day's own. A partial track looks exactly like a short day.
      const res = await apiFetch(`${apiBase}/api/v1/data/day/track?${query}`, {
        cache: "no-store",
      });
      if (!res.ok) return;

      const data = await res.json();
      const parsed: GpsPoint[] = (data.samples || [])
        .map((sample: { lat?: number; lon?: number; t?: string; speed?: number; altitude?: number }) => {
          if (
            sample.lat == null ||
            sample.lon == null ||
            isNaN(Number(sample.lat)) ||
            isNaN(Number(sample.lon))
          ) {
            return null;
          }
          return {
            latitude: Number(sample.lat),
            longitude: Number(sample.lon),
            timestamp: sample.t,
            speed: sample.speed ?? undefined,
            altitude: sample.altitude ?? undefined,
          };
        })
        .filter(Boolean) as GpsPoint[];

      setFetchedPoints(parsed);
      // The real number of fixes behind the drawn line, which is not the number of
      // points drawn. Reporting the latter as the former is how a decimated track
      // passes for a complete one.
      setFixCount(typeof data.fix_count === "number" ? data.fix_count : parsed.length);
    } catch (err) {
      console.error("Error fetching GPS points:", err);
    } finally {
      setLoading(false);
    }
  }, [apiBase, dateFilter, day, offsetMinutes]);

  useEffect(() => {
    if (controlled) return;
    let cancelled = false;
    void (async () => {
      await Promise.resolve();
      if (!cancelled) await fetchLocationData();
    })();
    return () => {
      cancelled = true;
    };
  }, [controlled, fetchLocationData, refreshTrigger]);

  const isToday = (isoString?: string) => {
    if (!isoString) return false;
    const d = new Date(isoString);
    const today = new Date();
    return (
      d.getFullYear() === today.getFullYear() &&
      d.getMonth() === today.getMonth() &&
      d.getDate() === today.getDate()
    );
  };

  const filteredPoints = useMemo(
    () =>
      controlled || day || dateFilter !== "today"
        ? points
        : points.filter((p) => isToday(p.timestamp)),
    [controlled, day, points, dateFilter],
  );

  const renderPoints = useMemo(() => simplifyTrack(filteredPoints), [filteredPoints]);

  // Tiles: bundled Leaflet, loaded on demand only.
  useEffect(() => {
    if (!showTiles || !mapContainer) return;
    let cancelled = false;

    void (async () => {
      try {
        const L = await import("leaflet");
        if (cancelled || !mapContainer) return;

        mapInstanceRef.current?.remove();

        const hasPoints = renderPoints.length > 0;
        const center: [number, number] = hasPoints
          ? [
              renderPoints.reduce((a, p) => a + p.latitude, 0) / renderPoints.length,
              renderPoints.reduce((a, p) => a + p.longitude, 0) / renderPoints.length,
            ]
          : [51.1657, 10.4515];

        const map = L.map(mapContainer, { center, zoom: hasPoints ? 13 : 6 });
        mapInstanceRef.current = map;

        const provider = TILE_PROVIDERS[tileProvider];
        L.tileLayer(provider.url, {
          attribution: provider.attribution,
          maxZoom: 19,
          subdomains: provider.subdomains,
        }).addTo(map);

        if (hasPoints) {
          const latLons: [number, number][] = renderPoints.map((p) => [p.latitude, p.longitude]);
          if (latLons.length > 1) {
            const line = L.polyline(latLons, { color: "#0d5c3a", weight: 4, opacity: 0.85 }).addTo(
              map,
            );
            map.fitBounds(line.getBounds(), { padding: [40, 40] });
          }
          renderPoints.forEach((pt) => {
            L.circleMarker([pt.latitude, pt.longitude], {
              radius: 6,
              fillColor: "#0d5c3a",
              color: "#ffffff",
              weight: 2,
              fillOpacity: 0.95,
            })
              .addTo(map)
              .bindPopup(
                `<div style="font-family:sans-serif;font-size:12px">` +
                  `<strong>${pt.timestamp ? formatDateTime(pt.timestamp) : ""}</strong><br/>` +
                  `<span style="font-family:monospace">${pt.latitude.toFixed(5)}°, ${pt.longitude.toFixed(5)}°</span>` +
                  `</div>`,
              );
          });
        }
        setTimeout(() => mapInstanceRef.current?.invalidateSize(), 120);
      } catch (err) {
        // Never leave a silent grey box: say what happened and go back to vectors.
        console.error("Map failed to load:", err);
        if (!cancelled) {
          setTileError(t("map.tilesFailed"));
          setShowTiles(false);
        }
      }
    })();

    return () => {
      cancelled = true;
      mapInstanceRef.current?.remove();
      mapInstanceRef.current = null;
    };
  }, [showTiles, mapContainer, renderPoints, tileProvider]);

  // Vector projection (equirectangular; adequate at city scale).
  const svg = useMemo(() => {
    if (renderPoints.length === 0) return null;
    const lats = renderPoints.map((p) => p.latitude);
    const lons = renderPoints.map((p) => p.longitude);
    const minLat = Math.min(...lats);
    const maxLat = Math.max(...lats);
    const minLon = Math.min(...lons);
    const maxLon = Math.max(...lons);
    const latSpan = maxLat - minLat || 0.01;
    const lonSpan = maxLon - minLon || 0.01;

    const projected = renderPoints.map((p) => ({
      ...p,
      x: 50 + ((p.longitude - minLon) / lonSpan) * 700,
      y: 350 - ((p.latitude - minLat) / latSpan) * 300,
    }));

    return {
      projected,
      path: projected
        .map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`)
        .join(" "),
    };
  }, [renderPoints]);

  if (loading) {
    return (
      <div className="glass-card flex h-[420px] items-center justify-center rounded-3xl border border-slate-200/80 bg-white p-6 text-xs text-slate-400">
        {t("map.loading")}
      </div>
    );
  }

  // The count the reader is shown is the count of fixes the span holds, which is
  // the server's when it fetched one. Both decimations — the server's, to bound the
  // response, and `simplifyTrack`'s, to bound what Leaflet draws — are reductions of
  // that same number, so "simplified to" is measured against it and not against
  // whatever survived the first step.
  const totalPoints = fixCount ?? filteredPoints.length;
  const simplified = totalPoints > renderPoints.length;

  return (
    <div className="glass-card space-y-4 rounded-3xl border border-slate-200/80 bg-white p-6 shadow-sm">
      <div className="flex flex-col items-start justify-between gap-3 border-b border-slate-100 pb-4 sm:flex-row sm:items-center">
        {showHeader && (
          <div>
            <h3 className="flex items-center gap-2 text-base font-extrabold text-slate-900">
              <MapPin className="h-5 w-5 text-brand" />
              <span>{t("map.headline")}</span>
            </h3>
            <p className="mt-0.5 text-xs text-slate-500">{t("map.privacyLead")}</p>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2">
          {!controlled && !day && (
            <div className="flex rounded-xl border border-emerald-200/80 bg-emerald-50 p-1 text-xs">
              {(["today", "7d", "30d"] as const).map((f) => (
                <button
                  key={f}
                  onClick={() => setDateFilter(f)}
                  className={`flex items-center gap-1 rounded-lg px-3 py-1 font-semibold [transition-property:color,background-color,border-color,text-decoration-color,fill,stroke,box-shadow] ${
                    dateFilter === f
                      ? "bg-brand text-brand-ink shadow-sm"
                      : "text-emerald-800 hover:text-emerald-950"
                  }`}
                >
                  {f === "today" && <Calendar className="h-3 w-3" />}
                  {f === "today"
                    ? t("map.today")
                    : t("quality.windowDays", { count: f === "7d" ? 7 : 30 })}
                </button>
              ))}
            </div>
          )}

          <button
            onClick={() => {
              setTileError("");
              setShowTiles((v) => !v);
            }}
            className={`flex items-center gap-1.5 rounded-xl border px-3 py-1.5 text-xs font-semibold transition-colors ${
              showTiles
                ? "border-brand bg-brand text-brand-ink"
                : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
            }`}
            title={showTiles ? t("map.hideTilesTitle") : t("map.showTilesTitle")}
          >
            <Globe2 className="h-3.5 w-3.5" />
            {showTiles ? t("map.hideTiles") : t("map.showTiles")}
          </button>

          {showTiles && (
            <select
              value={tileProvider}
              onChange={(e) => setTileProvider(e.target.value as TileProvider)}
              className="rounded-xl border border-slate-200 bg-white px-2.5 py-1.5 text-xs outline-none focus-ring"
            >
              {Object.entries(TILE_PROVIDERS).map(([id, p]) => (
                <option key={id} value={id}>
                  {p.label}
                </option>
              ))}
            </select>
          )}
        </div>
      </div>

      {!showTiles && (
        <p className="flex items-start gap-1.5 rounded-2xl bg-slate-50 px-3 py-2 text-[11px] leading-relaxed text-slate-500">
          <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand" />
          <span>{t("map.privacyDetail")}</span>
        </p>
      )}

      {tileError && (
        <p className="rounded-2xl border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] text-amber-900">
          {tileError}
        </p>
      )}

      {showTiles ? (
        <div
          ref={setMapContainer}
          className="h-[380px] w-full overflow-hidden rounded-2xl border border-slate-200"
        />
      ) : (
        <div className="overflow-hidden rounded-2xl border border-slate-200 bg-slate-50">
          {svg ? (
            <svg
              viewBox="0 0 800 400"
              className="h-[380px] w-full"
              role="img"
              aria-label={t("map.routeAria")}
            >
              <defs>
                <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
                  <path d="M 40 0 L 0 0 0 40" fill="none" className="stroke-line" strokeWidth="1" />
                </pattern>
              </defs>
              <rect width="800" height="400" fill="url(#grid)" />
              {/*
                Classes rather than `stroke=` / `fill=` attributes: a presentation
                attribute does not resolve `var()`, so the literals these replace
                stayed the light theme's colours. This panel is the tile-less
                fallback and sits on our own surface, not on map tiles — in dark
                the route was drawn at 2.3:1, making the one thing the view exists
                to show the hardest thing on it to see. The Leaflet track above
                keeps its literal on purpose: it is drawn over third-party tiles,
                which are light in either theme.
              */}
              <path
                d={svg.path}
                fill="none"
                className="stroke-brand"
                strokeWidth="3"
                strokeLinejoin="round"
              />
              {svg.projected.map((p, i) => (
                <circle
                  key={`${p.timestamp}-${i}`}
                  cx={p.x}
                  cy={p.y}
                  r={i === svg.projected.length - 1 ? 6 : 3}
                  className={i === svg.projected.length - 1 ? "fill-brand" : "fill-[#10b981]"}
                  stroke="#ffffff"
                  strokeWidth="1.5"
                >
                  <title>
                    {p.timestamp ? formatDateTime(p.timestamp) : ""} — {p.latitude.toFixed(5)}°,{" "}
                    {p.longitude.toFixed(5)}°
                  </title>
                </circle>
              ))}
            </svg>
          ) : (
            <div className="flex h-[380px] items-center justify-center text-xs text-slate-400">
              {t("map.empty")}
            </div>
          )}
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-slate-500">
        <span className="flex items-center gap-1.5">
          <Navigation className="h-3.5 w-3.5 text-brand" />
          {t("map.pointCount", { count: formatNumber(totalPoints) })}
          {simplified && (
            <span className="flex items-center gap-1 text-slate-400">
              <Layers className="h-3 w-3" />
              {t("map.simplifiedTo", { count: formatNumber(renderPoints.length) })}
            </span>
          )}
        </span>
        <span className="flex items-center gap-1.5">
          <RefreshCw className="h-3 w-3" />
          {showTiles ? TILE_PROVIDERS[tileProvider].label : t("map.vectorMode")}
        </span>
      </div>
    </div>
  );
}
