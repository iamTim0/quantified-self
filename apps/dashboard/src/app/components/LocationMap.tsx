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
  apiBase: string;
  tenantId: string;
  refreshTrigger: number;
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

const MAX_RENDERED_POINTS = 400;

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

export default function LocationMap({ apiBase, refreshTrigger }: LocationMapProps) {
  const { t, formatDateTime } = useI18n();
  const [mapContainer, setMapContainer] = useState<HTMLDivElement | null>(null);
  const mapInstanceRef = useRef<LeafletMap | null>(null);
  const [points, setPoints] = useState<GpsPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [dateFilter, setDateFilter] = useState<"today" | "7d" | "30d">("today");

  // Vector is the default. Tiles are only ever loaded on an explicit request.
  const [showTiles, setShowTiles] = useState(false);
  const [tileProvider, setTileProvider] = useState<TileProvider>(DEFAULT_PROVIDER);
  const [tileError, setTileError] = useState("");

  const fetchLocationData = useCallback(async () => {
    setLoading(true);
    try {
      const now = new Date();
      const start = new Date(now);
      if (dateFilter === "today") start.setHours(0, 0, 0, 0);
      else start.setDate(start.getDate() - (dateFilter === "7d" ? 7 : 30));

      const query = new URLSearchParams({
        metric_type: "location_point",
        start_time: start.toISOString(),
        end_time: now.toISOString(),
        limit: "1000",
      });
      const res = await apiFetch(`${apiBase}/api/v1/data/metrics?${query}`, {
        cache: "no-store",
      });
      if (!res.ok) return;

      const data = await res.json();
      const parsed: GpsPoint[] = (data.data_points || [])
        .map((dp: { metadata?: Record<string, unknown>; value?: number; timestamp?: string }) => {
          const meta = dp.metadata || {};
          const lat = (meta.latitude as number) ?? dp.value;
          const lon = meta.longitude as number;
          if (lat == null || lon == null || isNaN(Number(lat)) || isNaN(Number(lon))) return null;
          return {
            latitude: Number(lat),
            longitude: Number(lon),
            timestamp: dp.timestamp,
            speed: meta.speed as number | undefined,
            altitude: meta.altitude as number | undefined,
          };
        })
        .filter(Boolean) as GpsPoint[];

      setPoints(parsed);
    } catch (err) {
      console.error("Error fetching GPS points:", err);
    } finally {
      setLoading(false);
    }
  }, [apiBase, dateFilter]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      await Promise.resolve();
      if (!cancelled) await fetchLocationData();
    })();
    return () => {
      cancelled = true;
    };
  }, [fetchLocationData, refreshTrigger]);

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
    () => (dateFilter === "today" ? points.filter((p) => isToday(p.timestamp)) : points),
    [points, dateFilter],
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
        Lade GPS-Daten…
      </div>
    );
  }

  const simplified = filteredPoints.length > renderPoints.length;

  return (
    <div className="glass-card space-y-4 rounded-3xl border border-slate-200/80 bg-white p-6 shadow-sm">
      <div className="flex flex-col items-start justify-between gap-3 border-b border-slate-100 pb-4 sm:flex-row sm:items-center">
        <div>
          <h3 className="flex items-center gap-2 text-base font-extrabold text-slate-900">
            <MapPin className="h-5 w-5 text-[#0d5c3a]" />
            <span>{t("map.headline")}</span>
          </h3>
          <p className="mt-0.5 text-xs text-slate-500">{t("map.privacyLead")}</p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="flex rounded-xl border border-emerald-200/80 bg-emerald-50 p-1 text-xs">
            {(["today", "7d", "30d"] as const).map((f) => (
              <button
                key={f}
                onClick={() => setDateFilter(f)}
                className={`flex items-center gap-1 rounded-lg px-3 py-1 font-semibold transition-all ${
                  dateFilter === f
                    ? "bg-[#0d5c3a] text-white shadow-sm"
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

          <button
            onClick={() => {
              setTileError("");
              setShowTiles((v) => !v);
            }}
            className={`flex items-center gap-1.5 rounded-xl border px-3 py-1.5 text-xs font-semibold transition-colors ${
              showTiles
                ? "border-[#0d5c3a] bg-[#0d5c3a] text-white"
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
              className="rounded-xl border border-slate-200 bg-white px-2.5 py-1.5 text-xs outline-none"
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
          <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#0d5c3a]" />
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
              aria-label="GPS-Route"
            >
              <defs>
                <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
                  <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#e2e8f0" strokeWidth="1" />
                </pattern>
              </defs>
              <rect width="800" height="400" fill="url(#grid)" />
              <path
                d={svg.path}
                fill="none"
                stroke="#0d5c3a"
                strokeWidth="3"
                strokeLinejoin="round"
              />
              {svg.projected.map((p, i) => (
                <circle
                  key={`${p.timestamp}-${i}`}
                  cx={p.x}
                  cy={p.y}
                  r={i === svg.projected.length - 1 ? 6 : 3}
                  fill={i === svg.projected.length - 1 ? "#0d5c3a" : "#10b981"}
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
          <Navigation className="h-3.5 w-3.5 text-[#0d5c3a]" />
          {filteredPoints.length} Punkte
          {simplified && (
            <span className="flex items-center gap-1 text-slate-400">
              <Layers className="h-3 w-3" />
              auf {renderPoints.length} vereinfacht
            </span>
          )}
        </span>
        <span className="flex items-center gap-1.5">
          <RefreshCw className="h-3 w-3" />
          {showTiles ? TILE_PROVIDERS[tileProvider].label : "Vektor-Darstellung"}
        </span>
      </div>
    </div>
  );
}
