"use client";

import React, { useEffect, useRef, useState } from "react";
import { MapPin, Navigation, Calendar, ShieldCheck, RefreshCw, Layers } from "lucide-react";

export interface GpsPoint {
  latitude: number;
  longitude: number;
  timestamp?: string;
  speed?: number;
  altitude?: number;
}

interface LocationMapProps {
  apiBase: string;
  token: string;
  tenantId: string;
  refreshTrigger: number;
}

export default function LocationMap({ apiBase, token, tenantId, refreshTrigger }: LocationMapProps) {
  const [mapContainer, setMapContainer] = useState<HTMLDivElement | null>(null);
  const mapInstanceRef = useRef<any>(null);
  const [points, setPoints] = useState<GpsPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [leafletLoaded, setLeafletLoaded] = useState(false);
  const [viewMode, setViewMode] = useState<"leaflet" | "svg">("svg");
  const [tileProvider, setTileProvider] = useState<"osm" | "carto">("osm");
  const [dateFilter, setDateFilter] = useState<"today" | "7d" | "30d">("today");

  // 1. Dynamically inject Leaflet CSS & Leaflet JS
  useEffect(() => {
    if (typeof window === "undefined") return;

    // Inject Leaflet CSS if missing
    if (!document.getElementById("leaflet-css")) {
      const link = document.createElement("link");
      link.id = "leaflet-css";
      link.rel = "stylesheet";
      link.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
      document.head.appendChild(link);
    }

    if ((window as any).L) {
      setLeafletLoaded(true);
      return;
    }

    const script = document.createElement("script");
    script.id = "leaflet-js";
    script.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
    script.async = true;
    script.onload = () => setLeafletLoaded(true);
    document.body.appendChild(script);
  }, []);

  // 2. Fetch Dawarich GPS location points from Core Data Service
  const fetchLocationData = async () => {
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
      const res = await fetch(`${apiBase}/api/v1/data/metrics?${query}`, {
        cache: "no-store",
        headers: {
          Authorization: `Bearer ${token}`,
          "X-Tenant-ID": tenantId,
        },
      });
      if (res.ok) {
        const data = await res.json();
        const dps = data.data_points || [];
        const parsedPoints: GpsPoint[] = dps
          .map((dp: any) => {
            const meta = dp.metadata || {};
            const lat = meta.latitude ?? dp.value;
            const lon = meta.longitude;
            if (lat != null && lon != null && !isNaN(Number(lat)) && !isNaN(Number(lon))) {
              return {
                latitude: Number(lat),
                longitude: Number(lon),
                timestamp: dp.timestamp,
                speed: meta.speed,
                altitude: meta.altitude,
              };
            }
            return null;
          })
          .filter(Boolean);

        setPoints(parsedPoints);
      }
    } catch (err) {
      console.error("Error fetching Dawarich GPS points:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (token && tenantId) {
      fetchLocationData();
    }
  }, [apiBase, token, tenantId, dateFilter, refreshTrigger]);

  const isToday = (isoString?: string) => {
    if (!isoString) return false;
    try {
      const ptDate = new Date(isoString);
      const today = new Date();
      return (
        ptDate.getFullYear() === today.getFullYear() &&
        ptDate.getMonth() === today.getMonth() &&
        ptDate.getDate() === today.getDate()
      );
    } catch {
      return false;
    }
  };

  const filteredPoints = dateFilter === "today" ? points.filter((p) => isToday(p.timestamp)) : points;

  // 3. Initialize & render OpenStreetMap Leaflet Map
  useEffect(() => {
    if (!leafletLoaded || !mapContainer || viewMode !== "leaflet") return;
    const L = (window as any).L;
    if (!L) return;

    try {
      if (mapInstanceRef.current) {
        mapInstanceRef.current.remove();
        mapInstanceRef.current = null;
      }

      const hasPoints = filteredPoints.length > 0;
      const defaultCenter: [number, number] = [51.1657, 10.4515]; // Central Europe fallback
      const defaultZoom = 6;

      let centerLat = defaultCenter[0];
      let centerLon = defaultCenter[1];

      if (hasPoints) {
        const latLons: [number, number][] = filteredPoints.map((p) => [p.latitude, p.longitude]);
        centerLat = latLons.reduce((acc, p) => acc + p[0], 0) / latLons.length;
        centerLon = latLons.reduce((acc, p) => acc + p[1], 0) / latLons.length;
      }

      const map = L.map(mapContainer, {
        center: [centerLat, centerLon],
        zoom: hasPoints ? 13 : defaultZoom,
        zoomControl: true,
      });

      mapInstanceRef.current = map;

      // Select Tile Layer
      const tileUrl =
        tileProvider === "carto"
          ? "https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png"
          : "https://tile.openstreetmap.org/{z}/{x}/{y}.png";

      const attribution =
        tileProvider === "carto"
          ? '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
          : '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

      L.tileLayer(tileUrl, {
        attribution,
        maxZoom: 19,
        subdomains: tileProvider === "carto" ? "abcd" : "abc",
      }).addTo(map);

      // Draw Polyline Route & Markers if points exist
      if (hasPoints) {
        const latLons: [number, number][] = filteredPoints.map((p) => [p.latitude, p.longitude]);
        if (latLons.length > 1) {
          const polyline = L.polyline(latLons, {
            color: "#0d5c3a",
            weight: 4,
            opacity: 0.85,
            dashArray: "6, 8",
          }).addTo(map);
          map.fitBounds(polyline.getBounds(), { padding: [40, 40] });
        }

        filteredPoints.forEach((pt, idx) => {
          const popupContent = `
            <div style="font-family: sans-serif; font-size: 12px; padding: 4px;">
              <div style="font-weight: bold; color: #0f172a; margin-bottom: 2px;">📍 Dawarich GPS Punkt #${idx + 1}</div>
              <div style="color: #64748b; font-size: 11px;">${pt.timestamp ? new Date(pt.timestamp).toLocaleString("de-DE") : "N/A"}</div>
              <div style="margin-top: 4px; font-family: monospace; font-size: 11px; color: #0d5c3a; font-weight: 600;">
                ${pt.latitude.toFixed(5)}°, ${pt.longitude.toFixed(5)}°
              </div>
            </div>
          `;
          L.circleMarker([pt.latitude, pt.longitude], {
            radius: 8,
            fillColor: "#0d5c3a",
            color: "#ffffff",
            weight: 3,
            opacity: 1,
            fillOpacity: 0.95,
          })
            .addTo(map)
            .bindPopup(popupContent);
        });
      }

      // Force size recalculation to prevent gray tiles
      const timer1 = setTimeout(() => {
        if (mapInstanceRef.current) mapInstanceRef.current.invalidateSize();
      }, 100);
      const timer2 = setTimeout(() => {
        if (mapInstanceRef.current) mapInstanceRef.current.invalidateSize();
      }, 500);

      return () => {
        clearTimeout(timer1);
        clearTimeout(timer2);
      };
    } catch (e) {
      console.error("Error initializing Leaflet map:", e);
    }
  }, [leafletLoaded, filteredPoints, viewMode, tileProvider, mapContainer]);

  if (loading) {
    return (
      <div className="glass-card p-6 bg-white border border-slate-200/80 rounded-3xl h-[420px] flex items-center justify-center text-xs text-slate-400">
        Lade Dawarich GPS Daten...
      </div>
    );
  }

  const latestPoint = filteredPoints.length > 0
    ? filteredPoints[filteredPoints.length - 1]
    : points.length > 0
    ? points[points.length - 1]
    : { latitude: 51.1657, longitude: 10.4515 };

  // SVG Path projection calculation for vector view mode
  const targetPoints = filteredPoints.length > 0 ? filteredPoints : points;
  const minLat = targetPoints.length > 0 ? Math.min(...targetPoints.map((p) => p.latitude)) : 50.0;
  const maxLat = targetPoints.length > 0 ? Math.max(...targetPoints.map((p) => p.latitude)) : 52.0;
  const minLon = targetPoints.length > 0 ? Math.min(...targetPoints.map((p) => p.longitude)) : 9.0;
  const maxLon = targetPoints.length > 0 ? Math.max(...targetPoints.map((p) => p.longitude)) : 11.0;

  const latSpan = maxLat - minLat || 0.01;
  const lonSpan = maxLon - minLon || 0.01;

  const svgPoints = targetPoints.map((p) => {
    const x = 50 + ((p.longitude - minLon) / lonSpan) * 700;
    const y = 350 - ((p.latitude - minLat) / latSpan) * 300;
    return { ...p, x, y };
  });

  const polylinePathStr = svgPoints.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`).join(" ");

  return (
    <div className="glass-card p-6 bg-white border border-slate-200/80 rounded-3xl space-y-4 shadow-sm">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3 border-b border-slate-100 pb-4">
        <div>
          <h3 className="text-base font-extrabold text-slate-900 flex items-center gap-2">
            <MapPin className="w-5 h-5 text-[#0d5c3a]" />
            <span>GPS-Standorte & Strecke</span>
          </h3>
          <p className="text-xs text-slate-500 mt-0.5">
            Standardmäßig robuste Vector-Route; OpenStreetMap bleibt optional, falls externe Tiles erreichbar sind.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {/* Date Filter Toggle */}
          <div className="flex bg-emerald-50 border border-emerald-200/80 rounded-xl p-1 text-xs">
            <button
              onClick={() => setDateFilter("today")}
              className={`px-3 py-1 rounded-lg font-semibold transition-all flex items-center gap-1 ${
                dateFilter === "today" ? "bg-[#0d5c3a] text-white shadow-sm" : "text-emerald-800 hover:text-emerald-950"
              }`}
            >
              <Calendar className="w-3 h-3" />
              <span>Heute</span>
            </button>
            <button
              onClick={() => setDateFilter("7d")}
              className={`px-3 py-1 rounded-lg font-semibold transition-all ${
                dateFilter === "7d" ? "bg-[#0d5c3a] text-white shadow-sm" : "text-emerald-800 hover:text-emerald-950"
              }`}
            >
              7 Tage
            </button>
            <button
              onClick={() => setDateFilter("30d")}
              className={`px-3 py-1 rounded-lg font-semibold transition-all ${
                dateFilter === "30d" ? "bg-[#0d5c3a] text-white shadow-sm" : "text-emerald-800 hover:text-emerald-950"
              }`}
            >
              30 Tage
            </button>
          </div>

          {/* Tile Provider Toggle */}
          <div className="flex bg-slate-100 border border-slate-200 rounded-xl p-1 text-xs">
            <button
              onClick={() => setTileProvider("osm")}
              className={`px-3 py-1 rounded-lg font-semibold transition-all flex items-center gap-1 ${
                tileProvider === "osm" ? "bg-[#0d5c3a] text-white shadow-sm" : "text-slate-600 hover:text-slate-900"
              }`}
              title="Standard OpenStreetMap Tiles"
            >
              <Layers className="w-3 h-3" />
              <span>OSM Standard</span>
            </button>
            <button
              onClick={() => setTileProvider("carto")}
              className={`px-3 py-1 rounded-lg font-semibold transition-all ${
                tileProvider === "carto" ? "bg-[#0d5c3a] text-white shadow-sm" : "text-slate-600 hover:text-slate-900"
              }`}
              title="Carto Voyager OSM Tiles"
            >
              OSM Voyager
            </button>
          </div>

          {/* View Mode Toggle */}
          <div className="flex bg-slate-100 border border-slate-200 rounded-xl p-1 text-xs">
            <button
              onClick={() => setViewMode("leaflet")}
              className={`px-3 py-1 rounded-lg font-semibold transition-all ${
                viewMode === "leaflet" ? "bg-[#0d5c3a] text-white shadow-sm" : "text-slate-500 hover:text-slate-900"
              }`}
            >
              OpenStreetMap
            </button>
            <button
              onClick={() => setViewMode("svg")}
              className={`px-3 py-1 rounded-lg font-semibold transition-all ${
                viewMode === "svg" ? "bg-[#0d5c3a] text-white shadow-sm" : "text-slate-500 hover:text-slate-900"
              }`}
            >
              Vector Route
            </button>
          </div>

          <button
            onClick={fetchLocationData}
            className="p-2 text-xs font-semibold rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-700 transition-colors"
            title="Karte aktualisieren"
          >
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
          <span className="text-[10px] font-bold uppercase tracking-wider bg-emerald-50 text-emerald-800 border border-emerald-200 px-3 py-1.5 rounded-full flex items-center gap-1.5">
            <Navigation className="w-3.5 h-3.5 text-emerald-600 animate-pulse" />
            <span>{filteredPoints.length} GPS Punkte</span>
          </span>
        </div>
      </div>

      {/* Map Container */}
      <div className="relative w-full h-[400px] min-h-[400px] rounded-2xl overflow-hidden border border-slate-200 bg-slate-100 z-0">
        {viewMode === "leaflet" ? (
          <>
            <div ref={setMapContainer} className="w-full h-full min-h-[400px] z-0" />
            {filteredPoints.length === 0 && (
              <div className="absolute top-3 left-12 right-12 z-[1000] bg-white/95 backdrop-blur border border-slate-200 p-3 rounded-xl shadow-md flex items-center justify-between gap-3 text-xs">
                <div className="flex items-center gap-2 text-slate-700">
                  <MapPin className="w-4 h-4 text-emerald-600 shrink-0" />
                  <span>Keine GPS-Punkte für den gewählten Zeitraum erfasst. Standard-Kartenansicht aktiv.</span>
                </div>
              </div>
            )}
          </>
        ) : (
          /* High-Precision Interactive SVG Vector Map View */
          <div className="w-full h-full p-4 flex flex-col justify-between bg-slate-900 text-white relative">
            <svg className="w-full h-full" viewBox="0 0 800 400">
              <defs>
                <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
                  <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#1e293b" strokeWidth="1" />
                </pattern>
              </defs>
              <rect width="100%" height="100%" fill="url(#grid)" />

              <path d={polylinePathStr} fill="none" stroke="#10b981" strokeWidth="3" strokeDasharray="6 6" />

              {svgPoints.map((pt, idx) => (
                <g key={idx} className="cursor-pointer group">
                  <circle cx={pt.x} cy={pt.y} r="6" fill="#0d5c3a" stroke="#34d399" strokeWidth="2" />
                  <title>{`📍 Punkt #${idx + 1}: ${pt.latitude.toFixed(5)}°, ${pt.longitude.toFixed(5)}°`}</title>
                </g>
              ))}
            </svg>
            <div className="absolute bottom-3 left-3 bg-slate-800/90 border border-slate-700 px-3 py-1.5 rounded-xl text-[11px] font-mono text-emerald-400">
              Bounding Box: [{minLat.toFixed(3)}°, {minLon.toFixed(3)}°] ➔ [{maxLat.toFixed(3)}°, {maxLon.toFixed(3)}°]
            </div>
          </div>
        )}
      </div>

      {/* Footer Info Details */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-1 text-xs">
        <div className="p-3 bg-slate-50 border border-slate-200/60 rounded-2xl flex items-center gap-2.5">
          <MapPin className="w-4 h-4 text-[#0d5c3a]" />
          <div>
            <div className="text-[10px] text-slate-400 font-bold uppercase">Letzte Koordinaten</div>
            <div className="font-mono font-bold text-slate-800 text-[11px]">
              {latestPoint.latitude.toFixed(4)}°, {latestPoint.longitude.toFixed(4)}°
            </div>
          </div>
        </div>

        <div className="p-3 bg-slate-50 border border-slate-200/60 rounded-2xl flex items-center gap-2.5">
          <Calendar className="w-4 h-4 text-emerald-600" />
          <div>
            <div className="text-[10px] text-slate-400 font-bold uppercase">Letzter GPS Import</div>
            <div className="font-mono text-slate-700 text-[11px]">
              {latestPoint.timestamp ? new Date(latestPoint.timestamp).toLocaleString("de-DE") : "Jetzt"}
            </div>
          </div>
        </div>

        <div className="p-3 bg-slate-50 border border-slate-200/60 rounded-2xl flex items-center gap-2.5">
          <ShieldCheck className="w-4 h-4 text-amber-500" />
          <div>
            <div className="text-[10px] text-slate-400 font-bold uppercase">PostGIS Spatial Index</div>
            <div className="font-semibold text-slate-700 text-[11px]">
              geometry(Point, 4326) Aktiv
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
