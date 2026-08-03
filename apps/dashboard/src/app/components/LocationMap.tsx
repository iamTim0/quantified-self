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
}

export default function LocationMap({ apiBase, token, tenantId }: LocationMapProps) {
  const [mapContainer, setMapContainer] = useState<HTMLDivElement | null>(null);
  const mapInstanceRef = useRef<any>(null);
  const [points, setPoints] = useState<GpsPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [leafletLoaded, setLeafletLoaded] = useState(false);
  const [viewMode, setViewMode] = useState<"leaflet" | "svg">("leaflet");

  // 1. Load Leaflet JS dynamically from CDN
  useEffect(() => {
    if (typeof window === "undefined") return;

    if ((window as any).L) {
      setLeafletLoaded(true);
      return;
    }

    const script = document.createElement("script");
    script.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
    script.async = true;
    script.onload = () => setLeafletLoaded(true);
    document.body.appendChild(script);
  }, []);

  // 2. Fetch Dawarich GPS location points from Core Data Service
  const fetchLocationData = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${apiBase}/api/v1/data/metrics?metric_type=location_point&limit=500`, {
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
  }, [apiBase, token, tenantId]);

  // 3. Initialize & render Leaflet Map (Guaranteed DOM element via mapContainer state)
  useEffect(() => {
    if (!leafletLoaded || !mapContainer || points.length === 0 || viewMode !== "leaflet") return;
    const L = (window as any).L;
    if (!L) return;

    try {
      if (mapInstanceRef.current) {
        mapInstanceRef.current.remove();
        mapInstanceRef.current = null;
      }

      const latLons: [number, number][] = points.map((p) => [p.latitude, p.longitude]);
      const centerLat = latLons.reduce((acc, p) => acc + p[0], 0) / latLons.length;
      const centerLon = latLons.reduce((acc, p) => acc + p[1], 0) / latLons.length;

      const map = L.map(mapContainer, {
        center: [centerLat, centerLon],
        zoom: 13,
        zoomControl: true,
      });

      mapInstanceRef.current = map;

      // Standard OpenStreetMap Tile Layer
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        maxZoom: 19,
      }).addTo(map);

      // Draw Polyline Route
      if (latLons.length > 1) {
        const polyline = L.polyline(latLons, {
          color: "#0d5c3a",
          weight: 4,
          opacity: 0.85,
          dashArray: "6, 8",
        }).addTo(map);
        map.fitBounds(polyline.getBounds(), { padding: [40, 40] });
      }

      // Add Native Circle Markers
      points.forEach((pt, idx) => {
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

      // Recalculate container bounds
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
  }, [leafletLoaded, points, viewMode, mapContainer]);

  if (loading) {
    return (
      <div className="glass-card p-6 bg-white border border-slate-200/80 rounded-3xl h-[420px] flex items-center justify-center text-xs text-slate-400">
        Lade Dawarich GPS Daten...
      </div>
    );
  }

  if (points.length === 0) {
    return null;
  }

  const latestPoint = points[points.length - 1];

  // SVG Path projection calculation for vector view mode
  const minLat = Math.min(...points.map((p) => p.latitude));
  const maxLat = Math.max(...points.map((p) => p.latitude));
  const minLon = Math.min(...points.map((p) => p.longitude));
  const maxLon = Math.max(...points.map((p) => p.longitude));

  const latSpan = maxLat - minLat || 0.01;
  const lonSpan = maxLon - minLon || 0.01;

  const svgPoints = points.map((p) => {
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
            <span>Dawarich GPS Standorte & Bewegungsstrecke</span>
          </h3>
          <p className="text-xs text-slate-500 mt-0.5">
            Interaktive Visualisierung deiner über Dawarich importierten GPS-Punkte.
          </p>
        </div>

        <div className="flex items-center gap-2">
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
            <span>{points.length} GPS Punkte erfasst</span>
          </span>
        </div>
      </div>

      {/* Map Container */}
      <div className="relative w-full h-[400px] min-h-[400px] rounded-2xl overflow-hidden border border-slate-200 bg-slate-100 z-0">
        {viewMode === "leaflet" ? (
          <div ref={setMapContainer} className="w-full h-full min-h-[400px] z-0" />
        ) : (
          /* High-Precision Interactive SVG Vector Map View */
          <div className="w-full h-full p-4 flex flex-col justify-between bg-slate-900 text-white relative">
            <svg className="w-full h-full" viewBox="0 0 800 400">
              {/* Background Grid */}
              <defs>
                <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
                  <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#1e293b" strokeWidth="1" />
                </pattern>
              </defs>
              <rect width="100%" height="100%" fill="url(#grid)" />

              {/* Trajectory Route Path */}
              <path d={polylinePathStr} fill="none" stroke="#10b981" strokeWidth="3" strokeDasharray="6 6" />

              {/* GPS Waypoints */}
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
