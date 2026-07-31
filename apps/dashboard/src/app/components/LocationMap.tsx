"use client";

import React, { useEffect, useRef, useState } from "react";
import { MapPin, Navigation, Calendar, ShieldCheck, RefreshCw } from "lucide-react";

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
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapInstanceRef = useRef<any>(null);
  const [points, setPoints] = useState<GpsPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [leafletLoaded, setLeafletLoaded] = useState(false);

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

  // 3. Initialize & render Leaflet Map
  useEffect(() => {
    if (!leafletLoaded || !mapContainerRef.current || points.length === 0) return;
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

      const map = L.map(mapContainerRef.current, {
        center: [centerLat, centerLon],
        zoom: 13,
        zoomControl: true,
      });

      mapInstanceRef.current = map;

      // Tile Layer (OpenStreetMap CartoDB Voyager)
      L.tileLayer("https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png", {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>',
        maxZoom: 19,
      }).addTo(map);

      // Custom Emerald Circle Marker Icon
      const customIcon = L.divIcon({
        className: "custom-leaflet-marker",
        html: `<div style="background-color: #0d5c3a; width: 14px; height: 14px; border-radius: 50%; border: 3px solid white; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.3);"></div>`,
        iconSize: [14, 14],
        iconAnchor: [7, 7],
      });

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

      // Add Markers
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
        L.marker([pt.latitude, pt.longitude], { icon: customIcon })
          .addTo(map)
          .bindPopup(popupContent);
      });

      // Crucial Leaflet resize fix for dynamic container sizing
      setTimeout(() => {
        if (mapInstanceRef.current) {
          mapInstanceRef.current.invalidateSize();
        }
      }, 250);
    } catch (e) {
      console.error("Error initializing Leaflet map:", e);
    }
  }, [leafletLoaded, points]);

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

  return (
    <div className="glass-card p-6 bg-white border border-slate-200/80 rounded-3xl space-y-4 shadow-sm">
      {/* Include Leaflet CSS directly */}
      <link
        rel="stylesheet"
        href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
        integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="
        crossOrigin=""
      />
      <style jsx global>{`
        .leaflet-container {
          width: 100% !important;
          height: 100% !important;
          border-radius: 1rem !important;
          z-index: 1 !important;
        }
      `}</style>

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
      <div className="relative w-full h-[400px] min-h-[400px] rounded-2xl overflow-hidden border border-slate-200 z-0">
        <div ref={mapContainerRef} className="w-full h-full min-h-[400px] z-0" />
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
